from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.schemas import Coverage, HealthOut

router = APIRouter(tags=["health"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/health", response_model=HealthOut)
def health(db: Db) -> HealthOut:
    # Foundation stub: workstream E replaces this with the real report.
    return HealthOut(
        status="ok",
        jobs=[],
        feed_delay_p50_s=None,
        feed_delay_p95_s=None,
        last_filing_seen_at=None,
        parse_errors=[],
        backfill=[],
        coverage=Coverage(
            issuers_with_sector_pct=None,
            cusip_value_mapped_pct=None,
            decisions_with_prices_pct=None,
            decisions_last_price_exit_pct=None,
        ),
        sec_blocked_until=None,
    )
