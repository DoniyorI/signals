from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

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
from signals.api.schemas import FundScreenPage, InsiderScreenPage

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
    raise NotImplementedError


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
    raise NotImplementedError
