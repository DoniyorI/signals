from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.queries import health as queries
from signals.api.schemas import CompletenessOut, HealthOut
from signals.completeness import completeness_report
from signals.domain.calendars import now_et

router = APIRouter(tags=["health"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/health", response_model=HealthOut)
def health(db: Db) -> HealthOut:
    return queries.get_health(db)


@router.get("/health/completeness", response_model=CompletenessOut)
def completeness(db: Db, as_of: date | None = None) -> CompletenessOut:
    return completeness_report(db, as_of=as_of or now_et().date())
