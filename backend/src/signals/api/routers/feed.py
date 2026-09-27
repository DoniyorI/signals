from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.params import Cursor, Format, Limit, OptDate, OptFloat, OptInt, StrList
from signals.api.schemas import FeedPage, FeedSummary

router = APIRouter(tags=["feed"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/feed", response_model=FeedPage)
def get_feed(
    db: Db,
    forms: StrList = None,
    direction: StrList = None,
    codes: StrList = None,
    roles: StrList = None,
    sectors: StrList = None,
    badges: StrList = None,
    min_value: OptFloat = None,
    max_value: OptFloat = None,
    min_mcap: OptFloat = None,
    max_mcap: OptFloat = None,
    include_10b5_1: bool = True,
    trade_from: OptDate = None,
    trade_to: OptDate = None,
    filed_from: OptDate = None,
    filed_to: OptDate = None,
    max_lag_days: OptInt = None,
    issuer_cik: OptInt = None,
    owner_cik: OptInt = None,
    cursor: Cursor = None,
    limit: Limit = 50,
    format: Format = "json",
):
    raise NotImplementedError


@router.get("/feed/summary", response_model=FeedSummary)
def get_feed_summary(db: Db, date: OptDate = None):
    raise NotImplementedError
