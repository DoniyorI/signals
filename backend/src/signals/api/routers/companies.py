from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.params import Cursor, Format, Limit, OptDate
from signals.api.schemas import (
    CompanyHeader,
    Form144Out,
    InsiderRosterRow,
    InstitutionsOut,
    PriceSeriesOut,
    StakeOut,
)

router = APIRouter(prefix="/companies", tags=["companies"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/{ref}", response_model=CompanyHeader)
def get_company(db: Db, ref: str):
    """`ref` is a CIK (all digits) or a ticker (current, else latest holder)."""
    raise NotImplementedError


@router.get("/{cik}/prices", response_model=PriceSeriesOut)
def get_prices(db: Db, cik: int, start: OptDate = None, end: OptDate = None, markers: bool = True):
    raise NotImplementedError


@router.get("/{cik}/insiders", response_model=list[InsiderRosterRow])
def get_company_insiders(db: Db, cik: int, include_10b5_1: bool = False, format: Format = "json"):
    raise NotImplementedError


@router.get("/{cik}/institutions", response_model=InstitutionsOut)
def get_institutions(
    db: Db,
    cik: int,
    period: OptDate = None,
    cursor: Cursor = None,
    limit: Limit = 50,
    format: Format = "json",
):
    raise NotImplementedError


@router.get("/{cik}/stakes", response_model=list[StakeOut])
def get_stakes(db: Db, cik: int, current_only: bool = False, format: Format = "json"):
    raise NotImplementedError


@router.get("/{cik}/form144", response_model=list[Form144Out])
def get_company_form144(db: Db, cik: int, status: str | None = None, format: Format = "json"):
    raise NotImplementedError
