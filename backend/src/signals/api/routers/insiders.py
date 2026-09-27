from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.deps import Curves, get_db
from signals.api.params import BasisQ, Cursor, Format, Limit, OptInt, StrList
from signals.api.schemas import (
    DecisionPage,
    Form144Out,
    HoldingsOut,
    InsiderHeader,
    PerformanceOut,
    TransactionPage,
)

router = APIRouter(prefix="/insiders", tags=["insiders"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/{cik}", response_model=InsiderHeader)
def get_insider(db: Db, cik: int, basis: BasisQ = "filed", include_10b5_1: bool = False):
    raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


@router.get("/{cik}/performance", response_model=PerformanceOut)
def get_performance(
    db: Db,
    curves: Curves,
    cik: int,
    basis: BasisQ = "filed",
    include_10b5_1: bool = False,
):
    raise NotImplementedError


@router.get("/{cik}/holdings", response_model=HoldingsOut)
def get_holdings(db: Db, cik: int):
    raise NotImplementedError


@router.get("/{cik}/form144", response_model=list[Form144Out])
def get_form144(db: Db, cik: int, format: Format = "json"):
    raise NotImplementedError
