"""Bulk loader for the SEC Form 13F Data Sets (quarterly and rolling 3-month zips).

The four TSVs that matter (SUBMISSION, COVERPAGE, SUMMARYPAGE, INFOTABLE) land in TEMP tables
via `COPY ... FROM STDIN` (CSV format, tab-delimited, a QUOTE character that never appears in the
data so an embedded double quote in a free-text field passes through literally instead of being
treated as CSV quoting). One set-based pass then turns every accession not already in
`fund_filings` into `filings`, `fund_managers`, `fund_filings` and `fund_positions` rows.
`refresh_effective_keys` (from normalize_funds) settles amendments across every touched
(filer, period) exactly as the single-filing XML path does, and the feed items reuse the same
`fund_summary`/`is_notice`/`NOTICE_SUMMARY` so a bulk-loaded filing reads the same as a live one.
"""

import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import PurePosixPath
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from signals.db.models import Filing, FundFiling, FundManager, FundPosition
from signals.domain.feed import FeedItemIn, upsert_feed_item
from signals.domain.types import Direction
from signals.ingest.normalize_funds import (
    NOTICE_SUMMARY,
    expire_instances,
    fund_summary,
    is_notice,
    refresh_effective_keys,
)

_HREF = re.compile(r'href="([^"]+_form13f\.zip)"')
_QUARTER_NAME = re.compile(r"^(\d{4})q([1-4])_form13f\.zip$")
_RANGE_NAME = re.compile(r"^(\d{2}[a-z]{3}\d{4})-(\d{2}[a-z]{3}\d{4})_form13f\.zip$")
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


@dataclass(frozen=True)
class F13FDatasetLink:
    name: str
    url: str
    start: date
    end: date


@dataclass(frozen=True)
class F13FLoadResult:
    accessions: int
    skipped_existing: int
    positions: int


def _quarter_range(year: int, quarter: int) -> tuple[date, date]:
    start_month = (quarter - 1) * 3 + 1
    end_month, end_day = _QUARTER_END[quarter]
    return date(year, start_month, 1), date(year, end_month, end_day)


def list_13f_datasets(html: str, base_url: str = "https://www.sec.gov") -> list[F13FDatasetLink]:
    """Both naming styles the SEC has used for this data set: `2013q2_form13f.zip` (a calendar
    quarter) and `01jun2026-31aug2026_form13f.zip` (a rolling 3-month window). Sorted by start."""
    found: dict[str, F13FDatasetLink] = {}
    for href in _HREF.findall(html):
        name = href.rsplit("/", 1)[-1]
        quarter_match = _QUARTER_NAME.match(name)
        range_match = _RANGE_NAME.match(name)
        if quarter_match:
            start, end = _quarter_range(int(quarter_match.group(1)), int(quarter_match.group(2)))
        elif range_match:
            start = datetime.strptime(range_match.group(1), "%d%b%Y").date()
            end = datetime.strptime(range_match.group(2), "%d%b%Y").date()
        else:
            continue
        found[name] = F13FDatasetLink(name=name, url=base_url + href, start=start, end=end)
    return sorted(found.values(), key=lambda link: link.start)


# Every column of the source TSV, in file order. COPY needs the temp table's shape to match the
# file's exactly (a named column list still expects every input field, so columns can't be
# skipped); unused columns are simply never read back out.
_SUBMISSION_COLS = ["accession_number", "filing_date", "submissiontype", "cik", "periodofreport"]
_COVERPAGE_COLS = [
    "accession_number",
    "reportcalendarorquarter",
    "isamendment",
    "amendmentno",
    "amendmenttype",
    "confdeniedexpired",
    "datedeniedexpired",
    "datereported",
    "reasonfornonconfidentiality",
    "filingmanager_name",
    "filingmanager_street1",
    "filingmanager_street2",
    "filingmanager_city",
    "filingmanager_stateorcountry",
    "filingmanager_zipcode",
    "reporttype",
    "form13ffilenumber",
    "crdnumber",
    "secfilenumber",
    "provideinfoforinstruction5",
    "additionalinformation",
]
_SUMMARYPAGE_COLS = [
    "accession_number",
    "otherincludedmanagerscount",
    "tableentrytotal",
    "tablevaluetotal",
    "isconfidentialomitted",
]
_INFOTABLE_COLS = [
    "accession_number",
    "infotable_sk",
    "nameofissuer",
    "titleofclass",
    "cusip",
    "figi",
    "value",
    "sshprnamt",
    "sshprnamttype",
    "putcall",
    "investmentdiscretion",
    "othermanager",
    "voting_auth_sole",
    "voting_auth_shared",
    "voting_auth_none",
]
_TABLES: dict[str, tuple[str, list[str]]] = {
    "temp_submission": ("SUBMISSION.tsv", _SUBMISSION_COLS),
    "temp_coverpage": ("COVERPAGE.tsv", _COVERPAGE_COLS),
    "temp_summarypage": ("SUMMARYPAGE.tsv", _SUMMARYPAGE_COLS),
    "temp_infotable": ("INFOTABLE.tsv", _INFOTABLE_COLS),
}
_DATE_FMT = "DD-Mon-YYYY"  # e.g. "31-AUG-2026"; Postgres matches month names case-insensitively


def _raw_connection(session: Session) -> Any:
    """The psycopg3 connection backing this session's current transaction, for COPY."""
    return session.connection().connection.driver_connection


def _load_temp_table(session: Session, table: str, columns: list[str], body: str | None) -> None:
    session.execute(text(f"DROP TABLE IF EXISTS {table}"))
    session.execute(text(f"CREATE TEMP TABLE {table} ({', '.join(f'{c} text' for c in columns)})"))
    if not body:
        return
    raw = _raw_connection(session)
    copy_sql = (
        f"COPY {table} ({', '.join(columns)}) FROM STDIN WITH "
        "(FORMAT csv, DELIMITER E'\\t', QUOTE E'\\x01', HEADER true, NULL '')"
    )
    with raw.cursor() as cur, cur.copy(copy_sql) as copy:
        copy.write(body)


def _tsv_members(archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
    """Resolve exact TSV names at the ZIP root or inside ordinary wrapper directories."""
    targets = {member for member, _columns in _TABLES.values()}
    members: dict[str, zipfile.ZipInfo] = {}
    for info in archive.infolist():
        if info.is_dir():
            continue
        path = PurePosixPath(info.filename)
        if path.name not in targets:
            continue
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise ValueError(f"Unsafe 13F data set member path: {info.filename}")
        if path.name in members:
            raise ValueError(f"Ambiguous 13F data set member: {path.name}")
        members[path.name] = info
    return members


def load_13f_zip(session: Session, zip_bytes: bytes) -> F13FLoadResult:
    """Load one Form 13F Data Set zip. Accessions already in `fund_filings` are skipped, so
    loading the same or an overlapping zip again is a no-op for what it already has."""
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        members = _tsv_members(zf)
        bodies = {
            table: zf.read(members[member]).decode("utf-8", errors="replace")
            if member in members
            else None
            for table, (member, _columns) in _TABLES.items()
        }
    if bodies["temp_submission"] is None:
        raise ValueError("13F data set zip has no SUBMISSION.tsv")

    session.flush()
    for table, (_member, columns) in _TABLES.items():
        _load_temp_table(session, table, columns, bodies[table])

    session.execute(text("DROP TABLE IF EXISTS temp_new_accessions"))
    session.execute(
        text(
            """
            CREATE TEMP TABLE temp_new_accessions AS
            SELECT DISTINCT s.accession_number AS accession_no
            FROM temp_submission s
            LEFT JOIN fund_filings ff ON ff.accession_no = s.accession_number
            WHERE ff.accession_no IS NULL
            """
        )
    )
    total = session.scalar(text("SELECT count(DISTINCT accession_number) FROM temp_submission"))
    new_count = session.scalar(text("SELECT count(*) FROM temp_new_accessions"))
    skipped = int(total or 0) - int(new_count or 0)
    if not new_count:
        expire_instances(session, Filing, FundManager, FundFiling, FundPosition)
        return F13FLoadResult(accessions=0, skipped_existing=skipped, positions=0)

    # The filer's newest known filed_date BEFORE this batch, for the "name only moves forward"
    # rule (matches normalize_13f's _upsert_manager): a backfill of an older quarter must never
    # revert a manager's name that a later filing already established.
    session.execute(text("DROP TABLE IF EXISTS temp_existing_manager_date"))
    session.execute(
        text(
            """
            CREATE TEMP TABLE temp_existing_manager_date AS
            SELECT filer_cik, max(filed_date) AS max_filed_date
            FROM fund_filings
            WHERE filer_cik IN (SELECT DISTINCT cik::bigint FROM temp_submission)
            GROUP BY filer_cik
            """
        )
    )

    session.execute(
        text(
            f"""
            INSERT INTO filings (accession_no, form_type, issuer_cik, primary_cik, filed_date,
                                  accepted_at, accepted_at_source, period_of_report, is_amendment,
                                  source, parse_status, parse_error, first_seen_at, parsed_at)
            SELECT s.accession_number, s.submissiontype, NULL, s.cik::bigint,
                   to_date(trim(s.filing_date), '{_DATE_FMT}'), fa.accepted_at,
                   CASE WHEN fa.accepted_at IS NOT NULL THEN 'submissions' ELSE 'missing' END,
                   to_date(trim(s.periodofreport), '{_DATE_FMT}'),
                   coalesce(c.isamendment, 'N') = 'Y',
                   'bulk_13f', 'parsed', NULL, now(), now()
            FROM temp_submission s
            JOIN temp_new_accessions n ON n.accession_no = s.accession_number
            LEFT JOIN temp_coverpage c ON c.accession_number = s.accession_number
            LEFT JOIN filing_acceptance fa ON fa.accession_no = s.accession_number
            ON CONFLICT (accession_no) DO NOTHING
            """
        )
    )

    session.execute(
        text(
            f"""
            INSERT INTO fund_filings (accession_no, filer_cik, period_of_report, filed_date,
                                       accepted_at, submission_type, report_type, amendment_type,
                                       amendment_no, value_total_usd, entry_total, superseded)
            SELECT s.accession_number, s.cik::bigint,
                   to_date(trim(s.periodofreport), '{_DATE_FMT}'),
                   to_date(trim(s.filing_date), '{_DATE_FMT}'), fa.accepted_at, s.submissiontype,
                   c.reporttype,
                   CASE WHEN upper(trim(c.amendmenttype)) = 'RESTATEMENT' THEN 'RESTATEMENT'
                        WHEN upper(trim(c.amendmenttype)) = 'NEW HOLDINGS' THEN 'NEW HOLDINGS'
                   END,
                   c.amendmentno::integer,
                   sp.tablevaluetotal::double precision *
                       CASE WHEN to_date(trim(s.filing_date), '{_DATE_FMT}') < DATE '2023-01-03'
                            THEN 1000 ELSE 1 END,
                   sp.tableentrytotal::integer,
                   false
            FROM temp_submission s
            JOIN temp_new_accessions n ON n.accession_no = s.accession_number
            LEFT JOIN temp_coverpage c ON c.accession_number = s.accession_number
            LEFT JOIN temp_summarypage sp ON sp.accession_number = s.accession_number
            LEFT JOIN filing_acceptance fa ON fa.accession_no = s.accession_number
            ON CONFLICT (accession_no) DO NOTHING
            """
        )
    )

    session.execute(text("DROP TABLE IF EXISTS temp_manager_names"))
    session.execute(
        text(
            """
            CREATE TEMP TABLE temp_manager_names AS
            SELECT DISTINCT ON (batch.filer_cik)
                   batch.filer_cik, batch.name,
                   (e.max_filed_date IS NULL OR batch.filed_date >= e.max_filed_date)
                       AS should_update
            FROM (
                SELECT s.cik::bigint AS filer_cik,
                       coalesce(nullif(trim(c.filingmanager_name), ''), 'CIK ' || s.cik::bigint)
                           AS name,
                       to_date(trim(s.filing_date), :date_fmt) AS filed_date
                FROM temp_submission s
                JOIN temp_new_accessions n ON n.accession_no = s.accession_number
                LEFT JOIN temp_coverpage c ON c.accession_number = s.accession_number
            ) batch
            LEFT JOIN temp_existing_manager_date e ON e.filer_cik = batch.filer_cik
            ORDER BY batch.filer_cik, batch.filed_date DESC
            """
        ),
        {"date_fmt": _DATE_FMT},
    )
    session.execute(
        text(
            """
            INSERT INTO fund_managers (cik, name)
            SELECT filer_cik, name FROM temp_manager_names
            ON CONFLICT (cik) DO UPDATE SET
                name = CASE
                    WHEN (SELECT t.should_update FROM temp_manager_names t
                          WHERE t.filer_cik = fund_managers.cik)
                    THEN excluded.name ELSE fund_managers.name
                END,
                updated_at = now()
            """
        )
    )

    # Reuse the normalized rows from this INSERT for feed totals. Per-accession scans of
    # the partitioned history table held this quarter's manager locks for hours and
    # blocked live polling; RETURNING bounds the aggregate to the newly loaded batch.
    session.execute(text("DROP TABLE IF EXISTS temp_position_totals"))
    session.execute(
        text(
            f"""
            CREATE TEMP TABLE temp_position_totals AS
            WITH inserted_positions AS (
            INSERT INTO fund_positions (period, accession_no, cusip, put_call, filer_cik,
                                         name_of_issuer, title_of_class, shares, sh_prn, value_usd,
                                         is_effective)
            SELECT to_date(trim(s.periodofreport), '{_DATE_FMT}'), i.accession_number,
                   upper(trim(i.cusip)), coalesce(upper(trim(i.putcall)), ''), s.cik::bigint,
                   (array_agg(i.nameofissuer ORDER BY i.infotable_sk::bigint))[1],
                   (array_agg(i.titleofclass ORDER BY i.infotable_sk::bigint))[1],
                   sum(i.sshprnamt::double precision),
                   coalesce(
                       (array_agg(nullif(upper(trim(i.sshprnamttype)), '')
                                  ORDER BY i.infotable_sk::bigint))[1],
                       'SH'
                   ),
                   sum(i.value::double precision *
                       CASE WHEN to_date(trim(s.filing_date), '{_DATE_FMT}') < DATE '2023-01-03'
                            THEN 1000 ELSE 1 END),
                   true
            FROM temp_infotable i
            JOIN temp_new_accessions n ON n.accession_no = i.accession_number
            JOIN temp_submission s ON s.accession_number = i.accession_number
            WHERE upper(trim(i.cusip)) <> ''
            GROUP BY to_date(trim(s.periodofreport), '{_DATE_FMT}'), i.accession_number,
                     upper(trim(i.cusip)), coalesce(upper(trim(i.putcall)), ''), s.cik::bigint
            RETURNING accession_no, value_usd
            )
            SELECT accession_no, count(*) AS n_positions, sum(value_usd) AS total_value
            FROM inserted_positions
            GROUP BY accession_no
            """
        )
    )
    positions_written = int(
        session.scalar(text("SELECT coalesce(sum(n_positions), 0) FROM temp_position_totals")) or 0
    )

    touched = session.execute(
        text(
            f"""
            SELECT DISTINCT s.cik::bigint, to_date(trim(s.periodofreport), '{_DATE_FMT}')
            FROM temp_submission s
            JOIN temp_new_accessions n ON n.accession_no = s.accession_number
            """
        )
    ).all()
    refresh_effective_keys(session, [(row[0], row[1]) for row in touched])

    feed_rows = session.execute(
        text(
            f"""
            SELECT s.accession_number AS accession_no, s.cik::bigint AS filer_cik,
                   to_date(trim(s.periodofreport), '{_DATE_FMT}') AS period,
                   s.submissiontype AS form_type,
                   to_date(trim(s.filing_date), '{_DATE_FMT}') AS filed_date,
                   fa.accepted_at,
                   coalesce(nullif(trim(c.filingmanager_name), ''), 'CIK ' || s.cik::bigint)
                       AS manager_name,
                   coalesce(t.n_positions, 0) AS n_positions,
                   coalesce(t.total_value, 0) AS total_value
            FROM temp_submission s
            JOIN temp_new_accessions n ON n.accession_no = s.accession_number
            LEFT JOIN temp_coverpage c ON c.accession_number = s.accession_number
            LEFT JOIN filing_acceptance fa ON fa.accession_no = s.accession_number
            LEFT JOIN temp_position_totals t ON t.accession_no = s.accession_number
            """
        )
    ).all()
    for row in feed_rows:
        notice = is_notice(row.form_type)
        summary = (
            NOTICE_SUMMARY if notice else fund_summary(row.period, row.n_positions, row.total_value)
        )
        upsert_feed_item(
            session,
            FeedItemIn(
                accession_no=row.accession_no,
                form_type=row.form_type,
                accepted_at=row.accepted_at,
                filed_date=row.filed_date,
                owner_ciks=(row.filer_cik,),
                owner_names=row.manager_name or None,
                direction=Direction.OTHER.value,
                codes=(row.form_type,),
                summary=summary,
            ),
        )

    session.flush()
    expire_instances(session, Filing, FundManager, FundFiling, FundPosition)
    return F13FLoadResult(
        accessions=int(new_count), skipped_existing=skipped, positions=positions_written
    )
