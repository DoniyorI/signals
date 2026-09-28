"""Normalize parsed 13F filings into fund_managers, fund_filings, fund_positions, feed_items.

`fund_positions` keeps one row per filing and (CUSIP, put/call). Amendments never delete
rows: `refresh_effective` flips `is_effective` so each (filer, period) exposes exactly the
holdings in force. A RESTATEMENT replaces the filer's holdings for the period and a
NEW HOLDINGS amendment adds to them (spec 7.6).
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import delete, func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signals.db.models import Filing, FundFiling, FundManager, FundPosition
from signals.domain.feed import FeedItemIn, upsert_feed_item
from signals.domain.types import Direction
from signals.ingest.parsers.form13f import F13FCover, F13FHolding, value_to_usd

NOTICE_SUMMARY = "13F notice (holdings reported by another manager)"


def is_notice(form_type: str | None) -> bool:
    """13F-NT (+/A): the holdings are reported in another manager's 13F-HR."""
    return (form_type or "").upper().startswith("13F-NT")


def _short_usd(value: float) -> str:
    if value >= 1e9:
        return f"${value / 1e9:.1f}B"
    if value >= 1e6:
        return f"${value / 1e6:.1f}M"
    if value >= 1e3:
        return f"${value / 1e3:.0f}K"
    return f"${value:.0f}"


def fund_summary(period: date, positions: int, value_usd: float) -> str:
    quarter = (period.month - 1) // 3 + 1
    return f"13F for Q{quarter} {period.year}: {positions} positions, {_short_usd(value_usd)}"


@dataclass
class AggregatedPosition:
    cusip: str
    put_call: str  # '' when the row is not an option
    name_of_issuer: str | None
    title_of_class: str | None
    shares: float
    sh_prn: str
    value_usd: float


def aggregate_holdings(
    holdings: Iterable[F13FHolding], filed_date: date
) -> list[AggregatedPosition]:
    """Sum shares and dollar values per (CUSIP, put/call); keep the first row's labels."""
    merged: dict[tuple[str, str], AggregatedPosition] = {}
    for row in holdings:
        key = (row.cusip, row.put_call or "")
        value = value_to_usd(row.value_reported, filed_date)
        found = merged.get(key)
        if found is None:
            merged[key] = AggregatedPosition(
                cusip=row.cusip,
                put_call=key[1],
                name_of_issuer=row.name_of_issuer or None,
                title_of_class=row.title_of_class,
                shares=row.shares,
                sh_prn=row.sh_prn,
                value_usd=value,
            )
        else:
            found.shares += row.shares
            found.value_usd += value
    return list(merged.values())


def _expire(session: Session, *models: type) -> None:
    """Expire mapped instances that raw SQL may have changed underneath the session."""
    for obj in list(session.identity_map.values()):
        if isinstance(obj, models):
            session.expire(obj)


def _upsert_manager(
    session: Session, cik: int, name: str, filed_date: date, accession_no: str
) -> None:
    """Insert the manager; rename it only from its newest known filing."""
    newest_other = session.scalar(
        select(func.max(FundFiling.filed_date)).where(
            FundFiling.filer_cik == cik, FundFiling.accession_no != accession_no
        )
    )
    stmt = insert(FundManager).values(cik=cik, name=name or f"CIK {cik}")
    if name and (newest_other is None or filed_date >= newest_other):
        stmt = stmt.on_conflict_do_update(
            index_elements=[FundManager.cik],
            set_={"name": stmt.excluded.name, "updated_at": func.now()},
        )
    else:
        stmt = stmt.on_conflict_do_nothing(index_elements=[FundManager.cik])
    session.execute(stmt)


def normalize_13f(
    session: Session, filing: Filing, cover: F13FCover, holdings: list[F13FHolding]
) -> None:
    """Write one parsed 13F filing. Runs inside the caller's transaction; re-runs replace."""
    session.flush()
    acc, filer, period = filing.accession_no, filing.primary_cik, cover.period_of_report
    notice = is_notice(filing.form_type)
    previous = session.execute(
        select(FundFiling.filer_cik, FundFiling.period_of_report).where(
            FundFiling.accession_no == acc
        )
    ).first()

    if filing.period_of_report is None:
        filing.period_of_report = period
    _upsert_manager(session, filer, cover.manager_name, filing.filed_date, acc)

    values = {
        "accession_no": acc,
        "filer_cik": filer,
        "period_of_report": period,
        "filed_date": filing.filed_date,
        "accepted_at": filing.accepted_at,
        "submission_type": filing.form_type,
        "report_type": cover.report_type,
        "amendment_type": cover.amendment_type,
        "amendment_no": cover.amendment_no,
        "value_total_usd": (
            value_to_usd(cover.table_value_total, filing.filed_date)
            if cover.table_value_total is not None
            else None
        ),
        "entry_total": cover.table_entry_total,
    }
    stmt = insert(FundFiling).values(**values)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=[FundFiling.accession_no],
            set_={
                **{k: stmt.excluded[k] for k in values if k != "accession_no"},
                "updated_at": func.now(),
            },
        )
    )

    stale_filers = {filer} | ({previous.filer_cik} if previous else set())
    session.execute(
        delete(FundPosition).where(
            FundPosition.accession_no == acc, FundPosition.filer_cik.in_(stale_filers)
        )
    )
    positions = [] if notice else aggregate_holdings(holdings, filing.filed_date)
    if positions:
        session.execute(
            insert(FundPosition),
            [
                {
                    "period": period,
                    "accession_no": acc,
                    "cusip": p.cusip,
                    "put_call": p.put_call,
                    "filer_cik": filer,
                    "name_of_issuer": p.name_of_issuer,
                    "title_of_class": p.title_of_class,
                    "shares": p.shares,
                    "sh_prn": p.sh_prn,
                    "value_usd": p.value_usd,
                    "is_effective": True,
                }
                for p in positions
            ],
        )

    keys = {(filer, period)}
    if previous is not None:
        keys.add((previous.filer_cik, previous.period_of_report))
    refresh_effective_keys(session, keys)

    summary = (
        NOTICE_SUMMARY
        if notice
        else fund_summary(period, len(positions), sum(p.value_usd for p in positions))
    )
    upsert_feed_item(
        session,
        FeedItemIn(
            accession_no=acc,
            form_type=filing.form_type,
            accepted_at=filing.accepted_at,
            filed_date=filing.filed_date,
            owner_ciks=(filer,),
            owner_names=cover.manager_name or None,
            direction=Direction.OTHER.value,
            codes=(filing.form_type,),
            summary=summary,
        ),
    )
    session.flush()
    _expire(session, FundFiling, FundPosition, FundManager)


# Effective holdings: among a (filer, period)'s non-notice filings in filing order, the base
# is the latest one that is an original or a RESTATEMENT; the effective set is the base plus
# every NEW HOLDINGS amendment after it. Without a base nothing is effective. Filing order is
# (filed_date, accepted_at, accession_no): filed_date is always known, while a bulk-loaded
# original can lack an acceptance time that its XML-parsed amendment has.
_REFRESH_FILINGS = text(
    """
    WITH keys AS (
        SELECT DISTINCT * FROM unnest(CAST(:filers AS bigint[]), CAST(:periods AS date[]))
            AS k(filer_cik, period)
    ),
    ranked AS (
        SELECT f.accession_no, f.filer_cik, f.period_of_report AS period, f.amendment_type,
               row_number() OVER (
                   PARTITION BY f.filer_cik, f.period_of_report
                   ORDER BY f.filed_date, f.accepted_at NULLS LAST, f.accession_no
               ) AS ord
        FROM fund_filings f
        JOIN keys k ON k.filer_cik = f.filer_cik AND k.period = f.period_of_report
        WHERE coalesce(f.submission_type, '') NOT LIKE '13F-NT%'
    ),
    bases AS (
        SELECT filer_cik, period,
               max(ord) FILTER (
                   WHERE amendment_type IS NULL OR amendment_type = 'RESTATEMENT'
               ) AS base_ord
        FROM ranked GROUP BY filer_cik, period
    ),
    flags AS (
        SELECT r.accession_no,
               coalesce(
                   r.ord = b.base_ord
                   OR (r.amendment_type = 'NEW HOLDINGS' AND r.ord > b.base_ord),
                   false
               ) AS effective
        FROM ranked r JOIN bases b ON b.filer_cik = r.filer_cik AND b.period = r.period
    )
    UPDATE fund_filings f
    SET superseded = NOT fl.effective, updated_at = now()
    FROM flags fl
    WHERE f.accession_no = fl.accession_no AND f.superseded IS DISTINCT FROM (NOT fl.effective)
    """
)

_REFRESH_POSITIONS = text(
    """
    WITH keys AS (
        SELECT DISTINCT * FROM unnest(CAST(:filers AS bigint[]), CAST(:periods AS date[]))
            AS k(filer_cik, period)
    )
    UPDATE fund_positions p
    SET is_effective = NOT f.superseded
    FROM fund_filings f
    JOIN keys k ON k.filer_cik = f.filer_cik AND k.period = f.period_of_report
    WHERE p.accession_no = f.accession_no
      AND p.filer_cik = f.filer_cik
      AND p.period = f.period_of_report
      AND p.is_effective IS DISTINCT FROM (NOT f.superseded)
    """
)


def refresh_effective_keys(session: Session, keys: Iterable[tuple[int, date]]) -> None:
    """`refresh_effective` for many (filer, period) keys in two set-based statements."""
    pairs = sorted(set(keys))
    if not pairs:
        return
    session.flush()
    params = {"filers": [p[0] for p in pairs], "periods": [p[1] for p in pairs]}
    session.execute(_REFRESH_FILINGS, params)
    session.execute(_REFRESH_POSITIONS, params)
    _expire(session, FundFiling, FundPosition)


def refresh_effective(session: Session, filer_cik: int, period: date) -> None:
    """Recompute `fund_filings.superseded` and `fund_positions.is_effective` for one key."""
    refresh_effective_keys(session, [(filer_cik, period)])
