from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.deps import Curves, get_db
from signals.api.params import BasisQ, Cursor, Format, Limit, OptDate
from signals.api.schemas import FundHeader, FundHoldingsOut, PerformanceOut

router = APIRouter(prefix="/funds", tags=["funds"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/{cik}", response_model=FundHeader)
def get_fund(db: Db, cik: int):
    raise NotImplementedError


@router.get("/{cik}/holdings", response_model=FundHoldingsOut)
def get_fund_holdings(
    db: Db,
    cik: int,
    period: OptDate = None,
    cursor: Cursor = None,
    limit: Limit = 50,
    format: Format = "json",
):
    raise NotImplementedError


@router.get("/{cik}/performance", response_model=PerformanceOut)
def get_fund_performance(db: Db, curves: Curves, cik: int, basis: BasisQ = "filed"):
    raise NotImplementedError
