from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.csv import csv_response
from signals.api.deps import get_db
from signals.api.params import Cursor, Format, Limit, OptDate, OptFloat, OptInt, StrList
from signals.api.queries import common
from signals.api.queries.feed import feed_summary, list_feed
from signals.api.schemas import FeedItemOut, FeedPage, FeedSummary

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
    page = list_feed(
        db,
        forms=forms,
        direction=direction,
        codes=codes,
        roles=roles,
        sectors=sectors,
        badges=badges,
        min_value=min_value,
        max_value=max_value,
        min_mcap=min_mcap,
        max_mcap=max_mcap,
        include_10b5_1=include_10b5_1,
        trade_from=trade_from,
        trade_to=trade_to,
        filed_from=filed_from,
        filed_to=filed_to,
        max_lag_days=max_lag_days,
        issuer_cik=issuer_cik,
        owner_cik=owner_cik,
        cursor=cursor,
        limit=limit,
    )
    if format == "csv":
        return csv_response(page.items, "feed.csv", model=FeedItemOut)
    return page


@router.get("/feed/summary", response_model=FeedSummary)
def get_feed_summary(db: Db, date: OptDate = None):
    return feed_summary(db, date or common.today())
