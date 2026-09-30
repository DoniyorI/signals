from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.csv import csv_response
from signals.api.deps import Curves, get_db
from signals.api.params import BasisQ, Cursor, Format, Limit, OptInt, StrList
from signals.api.queries import common
from signals.api.queries.insiders import (
    get_holdings as query_holdings,
)
from signals.api.queries.insiders import (
    get_insider_header,
    list_decisions,
    list_form144,
    list_transactions,
    performance_out,
)
from signals.api.schemas import (
    DecisionOut,
    DecisionPage,
    Form144Out,
    HoldingsOut,
    InsiderHeader,
    PerformanceOut,
    TransactionOut,
    TransactionPage,
)

router = APIRouter(prefix="/insiders", tags=["insiders"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/{cik}", response_model=InsiderHeader)
def get_insider(db: Db, cik: int, basis: BasisQ = "filed", include_10b5_1: bool = False):
    return get_insider_header(db, cik, basis=basis, include_10b5_1=include_10b5_1)


@router.get("/{cik}/decisions", response_model=DecisionPage)
def get_decisions(
    db: Db,
    cik: int,
    basis: BasisQ = "filed",
    include_10b5_1: bool = False,
    direction: str | None = None,
    cursor: Cursor = None,
    limit: Limit = 50,
    format: Format = "json",
):
    page = list_decisions(
        db,
        cik,
        basis=basis,
        include_10b5_1=include_10b5_1,
        direction=direction,
        cursor=cursor,
        limit=limit,
    )
    if format == "csv":
        return csv_response(page.items, "decisions.csv", model=DecisionOut)
    return page


@router.get("/{cik}/transactions", response_model=TransactionPage)
def get_transactions(
    db: Db,
    cik: int,
    codes: StrList = None,
    issuer_cik: OptInt = None,
    include_superseded: bool = False,
    cursor: Cursor = None,
    limit: Limit = 50,
    format: Format = "json",
):
    page = list_transactions(
        db,
        cik,
        codes=codes,
        issuer_cik=issuer_cik,
        include_superseded=include_superseded,
        cursor=cursor,
        limit=limit,
    )
    if format == "csv":
        return csv_response(page.items, "transactions.csv", model=TransactionOut)
    return page


@router.get("/{cik}/performance", response_model=PerformanceOut)
def get_performance(
    db: Db,
    curves: Curves,
    cik: int,
    basis: BasisQ = "filed",
    include_10b5_1: bool = False,
):
    curve = curves.insider_curve(
        db, cik, basis=basis, include_10b5_1=include_10b5_1, as_of=common.today()
    )
    return performance_out(curve)


@router.get("/{cik}/holdings", response_model=HoldingsOut)
def get_holdings(db: Db, cik: int):
    return query_holdings(db, cik)


@router.get("/{cik}/form144", response_model=list[Form144Out])
def get_form144(db: Db, cik: int, format: Format = "json"):
    items = list_form144(db, cik)
    if format == "csv":
        return csv_response(items, "form144.csv", model=Form144Out)
    return items
