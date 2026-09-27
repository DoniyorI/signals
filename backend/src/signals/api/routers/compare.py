from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from signals.api.deps import Curves, get_db
from signals.api.params import BasisQ
from signals.api.schemas import CompareOut

router = APIRouter(tags=["compare"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/compare", response_model=CompareOut)
def compare(
    db: Db,
    curves: Curves,
    ids: str,
    basis: BasisQ = "filed",
    include_10b5_1: bool = False,
):
    """`ids` is a comma-separated list like `insider:123,fund:456` (1 to 4 profiles)."""
    raise NotImplementedError
