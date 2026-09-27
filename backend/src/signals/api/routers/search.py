from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.schemas import SearchOut

router = APIRouter(tags=["search"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/search", response_model=SearchOut)
def search(
    db: Db,
    q: Annotated[str, Query(min_length=2)],
    limit: Annotated[int, Query(ge=1, le=50)] = 8,
):
    raise NotImplementedError
