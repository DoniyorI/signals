from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from signals.api.csv import csv_response
from signals.api.deps import Curves, get_db
from signals.api.params import BasisQ, Cursor, Format, Limit, OptDate
from signals.api.queries import common
from signals.api.queries import funds as queries
from signals.api.queries.insiders import performance_out
from signals.api.schemas import FundHeader, FundHoldingRow, FundHoldingsOut, PerformanceOut
from signals.db.models import FundManager

router = APIRouter(prefix="/funds", tags=["funds"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/{cik}", response_model=FundHeader)
def get_fund(db: Db, cik: int):
    return queries.get_fund_header(db, cik)


@router.get("/{cik}/holdings", response_model=FundHoldingsOut)
def get_fund_holdings(
    db: Db,
    cik: int,
    period: OptDate = None,
    cursor: Cursor = None,
    limit: Limit = 50,
    format: Format = "json",
):
    result = queries.get_fund_holdings(db, cik, period=period, cursor=cursor, limit=limit)
    if format == "csv":
        return csv_response(result.rows, "fund_holdings.csv", model=FundHoldingRow)
    return result


@router.get("/{cik}/performance", response_model=PerformanceOut)
def get_fund_performance(db: Db, curves: Curves, cik: int, basis: BasisQ = "filed"):
    if db.get(FundManager, cik) is None:
        raise HTTPException(404, "fund not found")
    try:
        curve = curves.fund_curve(db, cik, basis=basis, as_of=common.today())
    except LookupError as exc:
        raise HTTPException(404, "performance is available for tracked funds only") from exc
    return performance_out(curve)
