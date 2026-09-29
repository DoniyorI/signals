from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.csv import csv_response
from signals.api.deps import get_db
from signals.api.params import (
    BasisQ,
    Cursor,
    Format,
    Limit,
    OptDate,
    OptFloat,
    OptInt,
    StrList,
    WindowQ,
)
from signals.api.queries import screener as queries
from signals.api.schemas import FundScreenPage, FundScreenRow, InsiderScreenPage, InsiderScreenRow

router = APIRouter(prefix="/screener", tags=["screener"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/insiders", response_model=InsiderScreenPage)
def screen_insiders(
    db: Db,
    roles: StrList = None,
    sectors: StrList = None,
    min_decisions: int = 1,
    last_trade_from: OptDate = None,
    last_trade_to: OptDate = None,
    min_rating: OptInt = None,
    confidence: StrList = None,
    window: WindowQ = "1y",
    min_return: OptFloat = None,
    max_return: OptFloat = None,
    risk: StrList = None,
    basis: BasisQ = "filed",
    include_10b5_1: bool = False,
    sort: str = "rating",
    order: str = "desc",
    cursor: Cursor = None,
    limit: Limit = 50,
    format: Format = "json",
):
    page = queries.screen_insiders(
        db,
        roles=roles,
        sectors=sectors,
        min_decisions=min_decisions,
        last_trade_from=last_trade_from,
        last_trade_to=last_trade_to,
        min_rating=min_rating,
        confidence=confidence,
        window=window,
        min_return=min_return,
        max_return=max_return,
        risk=risk,
        basis=basis,
        include_10b5_1=include_10b5_1,
        sort=sort,
        order=order,
        cursor=cursor,
        limit=limit,
    )
    if format == "csv":
        return csv_response(page.items, "insider_screener.csv", model=InsiderScreenRow)
    return page


@router.get("/funds", response_model=FundScreenPage)
def screen_funds(
    db: Db,
    sectors: StrList = None,
    min_rating: OptInt = None,
    confidence: StrList = None,
    window: WindowQ = "1y",
    min_return: OptFloat = None,
    max_return: OptFloat = None,
    risk: StrList = None,
    basis: BasisQ = "filed",
    tracked_only: bool = True,
    sort: str = "rating",
    order: str = "desc",
    cursor: Cursor = None,
    limit: Limit = 50,
    format: Format = "json",
):
    page = queries.screen_funds(
        db,
        sectors=sectors,
        min_rating=min_rating,
        confidence=confidence,
        window=window,
        min_return=min_return,
        max_return=max_return,
        risk=risk,
        basis=basis,
        tracked_only=tracked_only,
        sort=sort,
        order=order,
        cursor=cursor,
        limit=limit,
    )
    if format == "csv":
        return csv_response(page.items, "fund_screener.csv", model=FundScreenRow)
    return page
