"""Which fund managers the dashboard tracks: a curated list plus the largest active filers.

"Active" means a manager whose latest 13F has few enough stock positions to be a real
concentrated portfolio, not a index-hugging fund with hundreds of tiny holdings.
"""

import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from signals.db.models import FundManager
from signals.ingest.fund_changes import refresh_fund_manager_stats

DEFAULT_CSV_PATH = Path(__file__).resolve().parent / "tracked_funds.csv"


@dataclass(frozen=True)
class CuratedFund:
    cik: int
    name: str
    reason: str


def load_curated(path: Path = DEFAULT_CSV_PATH) -> list[CuratedFund]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            CuratedFund(cik=int(row["cik"]), name=row["name"], reason=row["reason"])
            for row in csv.DictReader(f)
        ]


def refresh_tracked_funds(
    session: Session, *, curated: list[CuratedFund], top_n: int, max_positions: int
) -> int:
    """Recompute `fund_managers.is_tracked`: every curated CIK that exists, plus the top
    `top_n` of the rest by `latest_value_usd` among those with `latest_positions <=
    max_positions`. Returns the number tracked."""
    refresh_fund_manager_stats(session)
    session.execute(update(FundManager).values(is_tracked=False, tracked_reason=None))

    curated_ciks = [c.cik for c in curated]
    if curated_ciks:
        session.execute(
            update(FundManager)
            .where(FundManager.cik.in_(curated_ciks))
            .values(is_tracked=True, tracked_reason="curated")
        )

    top_active_ciks = session.scalars(
        select(FundManager.cik)
        .where(
            FundManager.cik.notin_(curated_ciks),
            FundManager.latest_positions.is_not(None),
            FundManager.latest_positions <= max_positions,
            FundManager.latest_value_usd.is_not(None),
        )
        .order_by(FundManager.latest_value_usd.desc())
        .limit(top_n)
    ).all()
    if top_active_ciks:
        session.execute(
            update(FundManager)
            .where(FundManager.cik.in_(top_active_ciks))
            .values(is_tracked=True, tracked_reason="top_active")
        )

    session.flush()
    return int(session.scalar(select(func.count()).where(FundManager.is_tracked)) or 0)
