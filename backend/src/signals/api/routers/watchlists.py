from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.params import Cursor, Limit
from signals.api.queries import watchlists as queries
from signals.api.schemas import FeedPage, WatchlistCreate, WatchlistItemCreate, WatchlistOut

router = APIRouter(prefix="/watchlists", tags=["watchlists"])
Db = Annotated[Session, Depends(get_db)]
USER_ID = 1  # the seeded single user (users.id=1, migration 0001); no login in v1


@router.get("", response_model=list[WatchlistOut])
def list_watchlists(db: Db):
    return queries.list_watchlists(db, USER_ID)


@router.post("", response_model=WatchlistOut, status_code=201)
def create_watchlist(db: Db, body: WatchlistCreate):
    return queries.create_watchlist(db, USER_ID, body.name)


@router.get("/{watchlist_id}", response_model=WatchlistOut)
def get_watchlist(db: Db, watchlist_id: int):
    return queries.get_watchlist(db, USER_ID, watchlist_id)


@router.delete("/{watchlist_id}", status_code=204, response_class=Response)
def delete_watchlist(db: Db, watchlist_id: int):
    queries.delete_watchlist(db, USER_ID, watchlist_id)


@router.post("/{watchlist_id}/items", response_model=WatchlistOut)
def add_item(db: Db, watchlist_id: int, body: WatchlistItemCreate):
    return queries.add_item(db, USER_ID, watchlist_id, body.kind, body.cik)


@router.delete("/{watchlist_id}/items/{kind}/{cik}", status_code=204, response_class=Response)
def remove_item(db: Db, watchlist_id: int, kind: Literal["insider", "company", "fund"], cik: int):
    queries.remove_item(db, USER_ID, watchlist_id, kind, cik)


@router.get("/{watchlist_id}/activity", response_model=FeedPage)
def activity(db: Db, watchlist_id: int, cursor: Cursor = None, limit: Limit = 50):
    return queries.activity(db, USER_ID, watchlist_id, cursor=cursor, limit=limit)
