from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.queries import health as queries
from signals.api.schemas import HealthOut

router = APIRouter(tags=["health"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/health", response_model=HealthOut)
def health(db: Db) -> HealthOut:
    return queries.get_health(db)
