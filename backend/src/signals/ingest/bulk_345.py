"""Bulk loader for SEC's quarterly Insider Transactions Data Sets (Forms 3/4/5 TSVs).

Every TSV is staged into an all-TEXT temp table via COPY (fast, and tolerant of SEC's
unquoted, backslash-bearing format), then the rows that matter are read back into Python
and written through the same pure rules and writers as the XML path
(`normalize_insider.build_feed_item`, `upsert_owner`, ...), so a filing normalizes the
same way regardless of how it was ingested. Everything here runs inside the caller's
transaction; the caller commits once per zip.
"""

import io
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import insert, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from signals.db.models import Filing, FilingOwner, InsiderHolding, InsiderTransaction
from signals.domain.feed import upsert_feed_item
from signals.domain.owner_group import owner_group_key
from signals.domain.tickers import (
    canonical_symbol,
    current_symbol,
    rebuild_tickers,
    record_ticker_evidence,
)
from signals.domain.types import PlanFlag
from signals.ingest.amendments import link_amendment, relink_orphans
from signals.ingest.normalize_insider import (
    OwnerLine,
    TradeLine,
    build_feed_item,
    mentions_10b5_1,
    owner_type_for,
    upsert_issuer_name,
    upsert_owner,
    upsert_owner_role,
)
from signals.logging import get_logger

log = get_logger(__name__)

FEED_BATCH_SIZE = 5000

_DATASET_LINK = re.compile(r'href="([^"]*?(\d{4})q([1-4])_form345\.zip)"')

# SEC file name -> our temp table name. Order doesn't matter; all are staged up front.
TSV_TABLES = {
    "SUBMISSION": "tmp_submission",
    "REPORTINGOWNER": "tmp_reportingowner",
    "NONDERIV_TRANS": "tmp_nonderiv_trans",
    "DERIV_TRANS": "tmp_deriv_trans",
    "NONDERIV_HOLDING": "tmp_nonderiv_holding",
    "DERIV_HOLDING": "tmp_deriv_holding",
    "FOOTNOTES": "tmp_footnotes",
}

# *_FN column (lowercased, source table) -> the InsiderTransaction/InsiderHolding field it
# annotates. A few derivative-only fields (TRANS_TOTAL_VALUE, UNDLYNG_SEC_VALUE) have no
# analogous stored column (same gap A1's XML parser leaves, see its ruling), so their
# footnote references are simply not tracked.
_TRANS_FN_FIELDS = {
    "security_title_fn": "security_title",
    "trans_date_fn": "transaction_date",
    "deemed_execution_date_fn": "deemed_execution_date",
    "equity_swap_trans_cd_fn": "equity_swap",
    "trans_timeliness_fn": "timeliness",
    "trans_shares_fn": "shares",
    "trans_pricepershare_fn": "price",
    "trans_acquired_disp_cd_fn": "acquired_disposed",
    "shrs_ownd_folwng_trans_fn": "shares_owned_after",
    "valu_ownd_folwng_trans_fn": "value_owned_after",
    "direct_indirect_ownership_fn": "direct_indirect",
    "nature_of_ownership_fn": "nature_of_ownership",
    "conv_exercise_price_fn": "exercise_price",
    "excercise_date_fn": "exercise_date",  # sic: SEC's own column name is misspelled
    "expiration_date_fn": "expiration_date",
    "undlyng_sec_title_fn": "underlying_title",
    "undlyng_sec_shares_fn": "underlying_shares",
}
_HOLDING_FN_FIELDS = {
    "security_title_fn": "security_title",
    "shrs_ownd_folwng_trans_fn": "shares_owned",
    "valu_ownd_folwng_trans_fn": "value_owned",
    "direct_indirect_ownership_fn": "direct_indirect",
    "nature_of_ownership_fn": "nature_of_ownership",
    "conv_exercise_price_fn": "exercise_price",
    "exercise_date_fn": "exercise_date",
    "expiration_date_fn": "expiration_date",
    "undlyng_sec_title_fn": "underlying_title",
    "undlyng_sec_shares_fn": "underlying_shares",
}


@dataclass(frozen=True)
class DatasetLink:
    name: str
    url: str
    year: int
    quarter: int


@dataclass(frozen=True)
class BulkLoadResult:
    accessions: int
    skipped_existing: int
    transactions: int
    holdings: int


def list_345_datasets(html: str, base_url: str = "https://www.sec.gov") -> list[DatasetLink]:
    links = [
        DatasetLink(
            name=(href := match.group(1)).rsplit("/", 1)[-1],
            url=href if href.startswith("http") else f"{base_url}{href}",
            year=int(match.group(2)),
            quarter=int(match.group(3)),
        )
        for match in _DATASET_LINK.finditer(html)
    ]
    return sorted(links, key=lambda link: (link.year, link.quarter))


# ------------------------------------------------------------------------- text parsing
def _to_float(s: str | None) -> float | None:
    return float(s) if s not in (None, "") else None


def _to_bigint(s: str | None) -> int | None:
    return int(s) if s not in (None, "") else None


def _cik(s: str | None) -> int:
    """ISSUERCIK/RPTOWNERCIK are always present in valid SEC data (unlike the optional
    numeric fields `_to_bigint` covers), so callers get a plain `int` to pass along."""
    if s in (None, ""):
        raise ValueError("missing CIK in bulk 345 data")
    return int(s)


def _to_date(s: str | None) -> date | None:
    return datetime.strptime(s, "%d-%b-%Y").date() if s else None


def _req_date(s: str | None) -> date:
    """FILING_DATE is always present; unlike `_to_date`, which covers optional dates
    (PERIOD_OF_REPORT, DATE_OF_ORIG_SUB, ...)."""
    d = _to_date(s)
    if d is None:
        raise ValueError("missing FILING_DATE in bulk 345 data")
    return d


def _is_true(s: str | None) -> bool:
    return (s or "").strip().lower() in ("1", "true")


def _footnote_ids(s: str | None) -> list[str]:
    return [part.strip() for part in s.split(",") if part.strip()] if s else []


def _relationship_flags(rel: str | None) -> tuple[bool, bool, bool, bool]:
    low = (rel or "").lower()
    is_director = "director" in low
    is_officer = "officer" in low
    is_ten_pct = "tenpercent" in low or "10%" in low
    is_other = "other" in low
    return is_director, is_officer, is_ten_pct, is_other


# ------------------------------------------------------------------------- COPY staging
def _stage_tsv(session: Session, table: str, tsv_text: str) -> list[str]:
    """COPY one decoded TSV into an all-TEXT temp table (dropped and recreated so a
    second load in the same transaction/session doesn't collide). Returns its columns."""
    header_line = tsv_text.split("\n", 1)[0].rstrip("\r")
    columns = [c.strip().lower() for c in header_line.split("\t")]
    conn = session.connection()
    raw = conn.connection.dbapi_connection
    assert raw is not None, "session has no live DBAPI connection"
    cur = raw.cursor()
    cur.execute(f"DROP TABLE IF EXISTS {table}")
    cols_sql = ", ".join(f'"{c}" TEXT' for c in columns)
    cur.execute(f"CREATE TEMP TABLE {table} ({cols_sql}) ON COMMIT DROP")
    with cur.copy(
        f"COPY {table} FROM STDIN (FORMAT csv, DELIMITER E'\\t', QUOTE E'\\x01', HEADER true)"
    ) as copy:
        copy.write(tsv_text)
    return columns


def _rows(session: Session, table: str) -> list[dict]:
    return [dict(r) for r in session.execute(text(f"SELECT * FROM {table}")).mappings()]


def _group_by_accession(rows: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["accession_number"], []).append(row)
    return groups


def _ordered_by_sk(rows: list[dict], sk_col: str) -> list[dict]:
    return sorted(rows, key=lambda r: int(r[sk_col]))


def _field_footnotes(row: dict, fn_map: dict[str, str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for fn_col, field in fn_map.items():
        ids = _footnote_ids(row.get(fn_col))
        if ids:
            result[field] = ids
    return result


def _cited_texts(field_footnotes: dict[str, list[str]], footnotes: dict[str, str]) -> list[str]:
    return [footnotes[fid] for ids in field_footnotes.values() for fid in ids if fid in footnotes]


# ------------------------------------------------------------------------- main entry
def load_345_zip(
    session: Session, zip_bytes: bytes, *, name: str = "bulk_345.zip"
) -> BulkLoadResult:
    columns: dict[str, list[str]] = {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names_by_upper = {n.rsplit("/", 1)[-1].upper(): n for n in zf.namelist()}
        for key, table in TSV_TABLES.items():
            member = names_by_upper.get(f"{key}.TSV")
            tsv_text = (
                zf.read(member).decode("utf-8", errors="replace")
                if member is not None
                else "ACCESSION_NUMBER\n"  # dataset with no rows for this table at all
            )
            columns[key] = _stage_tsv(session, table, tsv_text)

    # 2. Skip accessions already parsed (from the live feed, a reconcile, etc).
    all_accessions = {r["accession_number"] for r in _rows(session, "tmp_submission")}
    already_parsed: set[str] = set()
    if all_accessions:
        already_parsed = {
            row[0]
            for row in session.execute(
                text(
                    "SELECT accession_no FROM filings "
                    "WHERE parse_status = 'parsed' AND accession_no = ANY(:accs)"
                ),
                {"accs": list(all_accessions)},
            )
        }
    if already_parsed:
        for table in TSV_TABLES.values():
            session.execute(
                text(f"DELETE FROM {table} WHERE accession_number = ANY(:accs)"),
                {"accs": list(already_parsed)},
            )
    skipped_existing = len(already_parsed)

    submissions = {r["accession_number"]: r for r in _rows(session, "tmp_submission")}
    if not submissions:
        return BulkLoadResult(0, skipped_existing, 0, 0)

    owners_by_acc = _group_by_accession(_rows(session, "tmp_reportingowner"))
    footnotes_by_acc = _group_by_accession(_rows(session, "tmp_footnotes"))
    footnote_text_by_acc = {
        acc: {r["footnote_id"]: r["footnote_txt"] for r in rows}
        for acc, rows in footnotes_by_acc.items()
    }
    nonderiv_trans_by_acc = _group_by_accession(_rows(session, "tmp_nonderiv_trans"))
    deriv_trans_by_acc = _group_by_accession(_rows(session, "tmp_deriv_trans"))
    nonderiv_holding_by_acc = _group_by_accession(_rows(session, "tmp_nonderiv_holding"))
    deriv_holding_by_acc = _group_by_accession(_rows(session, "tmp_deriv_holding"))

    aff10b5_columns = [c for c in columns["SUBMISSION"] if "10b5" in c]

    accessions = sorted(submissions)
    acceptance: dict[str, datetime] = {}
    if accessions:
        acceptance = dict(
            session.execute(
                text(
                    "SELECT accession_no, accepted_at FROM filing_acceptance "
                    "WHERE accession_no = ANY(:accs)"
                ),
                {"accs": accessions},
            ).all()
        )

    # 3. filings rows (skip any accession with no reporting owner at all: primary_cik has
    # nowhere to come from, and that has not happened in any recorded fixture).
    filing_rows = []
    for acc in accessions:
        owner_ciks = [_cik(o["rptownercik"]) for o in owners_by_acc.get(acc, [])]
        if not owner_ciks:
            log.warning("bulk_345_no_reporting_owner", accession=acc)
            continue
        sub = submissions[acc]
        accepted_at = acceptance.get(acc)
        form_type = sub["document_type"]
        filing_rows.append(
            {
                "accession_no": acc,
                "form_type": form_type,
                "issuer_cik": _cik(sub["issuercik"]),
                "primary_cik": min(owner_ciks),
                "filed_date": _req_date(sub["filing_date"]),
                "accepted_at": accepted_at,
                "accepted_at_source": "submissions" if accepted_at else "missing",
                "period_of_report": _to_date(sub["period_of_report"]),
                "is_amendment": form_type.endswith("/A"),
                "amends_accession": None,
                "original_filed_date": _to_date(sub["date_of_orig_sub"]),
                "source": "bulk_345",
                "raw_path": f"bulk:{name}",
                "parse_status": "parsed",
                "parse_error": None,
            }
        )
    valid_accessions = {row["accession_no"] for row in filing_rows}
    if not valid_accessions:
        return BulkLoadResult(0, skipped_existing, 0, 0)

    stmt = pg_insert(Filing)
    update_cols = [c for c in filing_rows[0] if c not in ("accession_no", "amends_accession")]
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["accession_no"], set_={c: stmt.excluded[c] for c in update_cols}
        ),
        filing_rows,
    )

    # 4. Owners, roles (Python, via normalize_roles inside upsert_owner_role) and issuers.
    seen_issuers: set[int] = set()
    for acc in accessions:
        if acc not in valid_accessions:
            continue
        sub = submissions[acc]
        cik = _cik(sub["issuercik"])
        if cik not in seen_issuers:
            upsert_issuer_name(session, cik, sub["issuername"])
            seen_issuers.add(cik)

    # The newest filing wins (A3's convention): apply owner/role upserts oldest-first.
    owner_events = sorted(
        (
            (submissions[acc]["filing_date"], acc, o)
            for acc in accessions
            if acc in valid_accessions
            for o in owners_by_acc.get(acc, [])
        ),
        key=lambda item: _to_date(item[0]) or date.min,
    )
    for filed_text, acc, o in owner_events:
        cik = _cik(o["rptownercik"])
        name = o["rptownername"] or f"CIK {cik}"
        is_director, is_officer, is_ten_pct, is_other = _relationship_flags(
            o["rptowner_relationship"]
        )
        upsert_owner(
            session, cik, name, owner_type_for(name, is_officer=is_officer, is_director=is_director)
        )
        upsert_owner_role(
            session,
            owner_cik=cik,
            issuer_cik=_cik(submissions[acc]["issuercik"]),
            is_director=is_director,
            is_officer=is_officer,
            officer_title=o["rptowner_title"],
            is_ten_pct_owner=is_ten_pct,
            is_other=is_other,
            other_text=o["rptowner_txt"],
            filed=_req_date(filed_text),
        )

    # filing_owners: delete-then-insert per accession (idempotent, ground rule 2).
    session.execute(
        text("DELETE FROM filing_owners WHERE accession_no = ANY(:accs)"),
        {"accs": list(valid_accessions)},
    )
    filing_owner_rows = []
    for acc in valid_accessions:
        for o in owners_by_acc.get(acc, []):
            is_director, is_officer, is_ten_pct, is_other = _relationship_flags(
                o["rptowner_relationship"]
            )
            filing_owner_rows.append(
                {
                    "accession_no": acc,
                    "owner_cik": _to_bigint(o["rptownercik"]),
                    "is_director": is_director,
                    "is_officer": is_officer,
                    "officer_title": o["rptowner_title"],
                    "is_ten_pct_owner": is_ten_pct,
                    "is_other": is_other,
                }
            )
    if filing_owner_rows:
        session.execute(insert(FilingOwner), filing_owner_rows)

    # 5-7. Transactions and holdings: owner_group, footnotes, 10b5-1 classification.
    session.execute(
        text("DELETE FROM insider_transactions WHERE accession_no = ANY(:accs)"),
        {"accs": list(valid_accessions)},
    )
    session.execute(
        text("DELETE FROM insider_holdings WHERE accession_no = ANY(:accs)"),
        {"accs": list(valid_accessions)},
    )

    transaction_rows: list[dict] = []
    holding_rows: list[dict] = []
    trades_by_acc: dict[str, list[TradeLine]] = {}
    n_holdings_by_acc: dict[str, int] = {}

    for acc in valid_accessions:
        sub = submissions[acc]
        issuer_cik = _cik(sub["issuercik"])
        owner_ciks = [_cik(o["rptownercik"]) for o in owners_by_acc.get(acc, [])]
        group = owner_group_key(owner_ciks)
        footnotes = footnote_text_by_acc.get(acc, {})
        aff = any(_is_true(sub.get(c)) for c in aff10b5_columns)
        trades: list[TradeLine] = []

        for table_kind, rows_by_sk, sk_col in (
            ("nonderiv", nonderiv_trans_by_acc, "nonderiv_trans_sk"),
            ("deriv", deriv_trans_by_acc, "deriv_trans_sk"),
        ):
            for row_no, row in enumerate(_ordered_by_sk(rows_by_sk.get(acc, []), sk_col), start=1):
                field_footnotes = _field_footnotes(row, _TRANS_FN_FIELDS)
                cited = _cited_texts(field_footnotes, footnotes)
                plan = (
                    PlanFlag.FLAG
                    if aff
                    else PlanFlag.FOOTNOTE
                    if mentions_10b5_1([*cited, sub.get("remarks")])
                    else PlanFlag.NONE
                ).value
                shares = _to_float(row.get("trans_shares"))
                price = _to_float(row.get("trans_pricepershare"))
                value = shares * price if shares is not None and price is not None else None
                code = row.get("trans_code")
                transaction_rows.append(
                    {
                        "accession_no": acc,
                        "table_kind": table_kind,
                        "row_no": row_no,
                        "issuer_cik": issuer_cik,
                        "owner_group": group,
                        "security_title": row.get("security_title"),
                        "transaction_date": _to_date(row.get("trans_date")),
                        "deemed_execution_date": _to_date(row.get("deemed_execution_date")),
                        "code": code,
                        "form_type": row.get("trans_form_type"),
                        "equity_swap": (
                            _is_true(row.get("equity_swap_involved"))
                            if row.get("equity_swap_involved")
                            else None
                        ),
                        "timeliness": row.get("trans_timeliness"),
                        "shares": shares,
                        "price": price,
                        "value_usd": value,
                        "acquired_disposed": row.get("trans_acquired_disp_cd"),
                        "shares_owned_after": _to_float(row.get("shrs_ownd_folwng_trans")),
                        "value_owned_after": _to_float(row.get("valu_ownd_folwng_trans")),
                        "direct_indirect": row.get("direct_indirect_ownership"),
                        "nature_of_ownership": row.get("nature_of_ownership"),
                        "plan_10b5_1": plan,
                        "exercise_price": _to_float(row.get("conv_exercise_price")),
                        "exercise_date": _to_date(
                            row.get("excercise_date") or row.get("exercise_date")
                        ),
                        "expiration_date": _to_date(row.get("expiration_date")),
                        "underlying_title": row.get("undlyng_sec_title"),
                        "underlying_shares": _to_float(row.get("undlyng_sec_shares")),
                        "footnotes": {
                            fid: footnotes[fid]
                            for ids in field_footnotes.values()
                            for fid in ids
                            if fid in footnotes
                        },
                        "field_footnotes": field_footnotes,
                        "superseded_by": None,
                        "flags": ["price_missing"] if code in ("P", "S") and price is None else [],
                    }
                )
                trades.append(
                    TradeLine(
                        table_kind,
                        code,
                        _to_date(row.get("trans_date")),
                        shares,
                        price,
                        value,
                        plan,
                    )
                )

        n_holdings = 0
        for table_kind, rows_by_sk, sk_col in (
            ("nonderiv", nonderiv_holding_by_acc, "nonderiv_holding_sk"),
            ("deriv", deriv_holding_by_acc, "deriv_holding_sk"),
        ):
            for row_no, row in enumerate(_ordered_by_sk(rows_by_sk.get(acc, []), sk_col), start=1):
                n_holdings += 1
                field_footnotes = _field_footnotes(row, _HOLDING_FN_FIELDS)
                holding_rows.append(
                    {
                        "accession_no": acc,
                        "table_kind": table_kind,
                        "row_no": row_no,
                        "issuer_cik": issuer_cik,
                        "owner_group": group,
                        "security_title": row.get("security_title"),
                        "shares_owned": _to_float(row.get("shrs_ownd_folwng_trans")),
                        "value_owned": _to_float(row.get("valu_ownd_folwng_trans")),
                        "direct_indirect": row.get("direct_indirect_ownership"),
                        "nature_of_ownership": row.get("nature_of_ownership"),
                        "exercise_price": _to_float(row.get("conv_exercise_price")),
                        "exercise_date": _to_date(row.get("exercise_date")),
                        "expiration_date": _to_date(row.get("expiration_date")),
                        "underlying_title": row.get("undlyng_sec_title"),
                        "underlying_shares": _to_float(row.get("undlyng_sec_shares")),
                        "footnotes": {
                            fid: footnotes[fid]
                            for ids in field_footnotes.values()
                            for fid in ids
                            if fid in footnotes
                        },
                        "superseded_by": None,
                    }
                )
        trades_by_acc[acc] = trades
        n_holdings_by_acc[acc] = n_holdings

    if transaction_rows:
        session.execute(insert(InsiderTransaction), transaction_rows)
    if holding_rows:
        session.execute(insert(InsiderHolding), holding_rows)
    session.flush()

    # 8. Ticker evidence, once per distinct (issuer, symbol, filing date).
    touched_issuers: set[int] = set()
    seen_evidence: set[tuple[int, str | None, str | None]] = set()
    for acc in valid_accessions:
        sub = submissions[acc]
        cik = _cik(sub["issuercik"])
        symbol, filed_text = sub.get("issuertradingsymbol"), sub["filing_date"]
        key = (cik, symbol, filed_text)
        if key in seen_evidence:
            continue
        seen_evidence.add(key)
        if record_ticker_evidence(session, cik, symbol, _req_date(filed_text), "bulk_345"):
            touched_issuers.add(cik)
    if touched_issuers:
        rebuild_tickers(session, touched_issuers)

    # 9. Amendments, then feed items (batched, same rules as A3's build_feed_item).
    for acc in valid_accessions:
        if submissions[acc]["document_type"].endswith("/A"):
            link_amendment(session, acc)
    relink_orphans(session)

    ordered_accessions = sorted(valid_accessions)
    for start in range(0, len(ordered_accessions), FEED_BATCH_SIZE):
        batch = ordered_accessions[start : start + FEED_BATCH_SIZE]
        for acc in batch:
            sub = submissions[acc]
            issuer_cik = _cik(sub["issuercik"])
            owner_lines = [
                OwnerLine(
                    _cik(o["rptownercik"]),
                    o["rptownername"] or f"CIK {o['rptownercik']}",
                    (),
                )
                for o in owners_by_acc.get(acc, [])
            ]
            # Roles for top_role come from what we just upserted (newest-wins already applied).
            owner_lines = [
                OwnerLine(ol.cik, ol.name, _owner_roles(session, ol.cik, issuer_cik))
                for ol in owner_lines
            ]
            filing = session.get(Filing, acc)
            issuer_name = sub.get("issuername")
            upsert_feed_item(
                session,
                build_feed_item(
                    accession_no=acc,
                    form_type=sub["document_type"],
                    accepted_at=filing.accepted_at if filing else None,
                    filed_date=_to_date(sub["filing_date"]),
                    issuer_cik=issuer_cik,
                    issuer_name=issuer_name,
                    ticker=canonical_symbol(sub.get("issuertradingsymbol"))
                    or current_symbol(session, issuer_cik),
                    sector=None,
                    owners=owner_lines,
                    trades=trades_by_acc.get(acc, []),
                    n_holdings=n_holdings_by_acc.get(acc, 0),
                ),
            )
        session.flush()

    return BulkLoadResult(
        accessions=len(valid_accessions),
        skipped_existing=skipped_existing,
        transactions=len(transaction_rows),
        holdings=len(holding_rows),
    )


def _owner_roles(session: Session, owner_cik: int, issuer_cik: int) -> tuple[str, ...]:
    row = session.execute(
        text("SELECT roles FROM owner_roles WHERE owner_cik = :o AND issuer_cik = :i"),
        {"o": owner_cik, "i": issuer_cik},
    ).first()
    return tuple(row[0]) if row and row[0] else ()


def apply_acceptance_times(session: Session) -> int:
    """Fill `accepted_at` for bulk-loaded rows now that `filing_acceptance` has caught up."""
    result = session.execute(
        text(
            """
            UPDATE filings f
            SET accepted_at = fa.accepted_at, accepted_at_source = 'submissions'
            FROM filing_acceptance fa
            WHERE f.accession_no = fa.accession_no AND f.accepted_at IS NULL
            """
        )
    )
    session.execute(
        text(
            """
            UPDATE feed_items fi
            SET accepted_at = fa.accepted_at
            FROM filing_acceptance fa
            WHERE fi.accession_no = fa.accession_no AND fi.accepted_at IS NULL
            """
        )
    )
    session.execute(
        text(
            """
            UPDATE fund_filings ff
            SET accepted_at = fa.accepted_at
            FROM filing_acceptance fa
            WHERE ff.accession_no = fa.accession_no AND ff.accepted_at IS NULL
            """
        )
    )
    return result.rowcount or 0  # pyright: ignore[reportAttributeAccessIssue]
