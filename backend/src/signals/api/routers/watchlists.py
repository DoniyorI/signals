from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.params import Cursor, Limit
from signals.api.schemas import FeedPage, WatchlistCreate, WatchlistItemCreate, WatchlistOut

router = APIRouter(prefix="/watchlists", tags=["watchlists"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[WatchlistOut])
def list_watchlists(db: Db):
    raise NotImplementedError


@router.post("", response_model=WatchlistOut, status_code=201)
def create_watchlist(db: Db, body: WatchlistCreate):
    raise NotImplementedError


@router.get("/{watchlist_id}", response_model=WatchlistOut)
def get_watchlist(db: Db, watchlist_id: int):
    raise NotImplementedError


@router.delete("/{watchlist_id}", status_code=204, response_class=Response)
def delete_watchlist(db: Db, watchlist_id: int):
    raise NotImplementedError


@router.post("/{watchlist_id}/items", response_model=WatchlistOut)
def add_item(db: Db, watchlist_id: int, body: WatchlistItemCreate):
    raise NotImplementedError


@router.delete("/{watchlist_id}/items/{kind}/{cik}", status_code=204, response_class=Response)
def remove_item(db: Db, watchlist_id: int, kind: Literal["insider", "company", "fund"], cik: int):
    raise NotImplementedError


@router.get("/{watchlist_id}/activity", response_model=FeedPage)
def activity(db: Db, watchlist_id: int, cursor: Cursor = None, limit: Limit = 50):
    raise NotImplementedError
