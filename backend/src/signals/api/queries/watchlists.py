"""Queries behind `/watchlists` and `/watchlists/{id}/activity`.

Everything is scoped to `user_id` (always 1: the single `users` row the foundation migration
seeds -- there is no login in v1). `activity` reuses `queries.feed`'s sort keys and row mapper
so a watchlist's feed reads exactly like the main feed, just filtered to watched entities.
"""

from fastapi import HTTPException
from sqlalchemy import false, or_, select
from sqlalchemy.orm import Session

from signals.api.pagination import paginate
from signals.api.queries.feed import FEED_KEYS, _feed_item_out
from signals.api.schemas import FeedPage, WatchlistItemOut, WatchlistOut
from signals.db.models import FeedItem, FundManager, Issuer, Owner, Watchlist, WatchlistItem

_ENTITY_MODEL: dict[str, type] = {"insider": Owner, "company": Issuer, "fund": FundManager}


def _item_name(session: Session, kind: str, cik: int) -> str:
    row = session.get(_ENTITY_MODEL[kind], cik)
    return row.name if row is not None else f"CIK {cik}"


def _watchlist_out(session: Session, wl: Watchlist) -> WatchlistOut:
    items = session.execute(
        select(WatchlistItem)
        .where(WatchlistItem.watchlist_id == wl.id)
        .order_by(WatchlistItem.added_at)
    ).scalars()
    return WatchlistOut(
        id=wl.id,
        name=wl.name,
        items=[
            WatchlistItemOut(
                kind=it.kind,  # type: ignore[arg-type]
                cik=it.cik,
                name=_item_name(session, it.kind, it.cik),
                added_at=it.added_at,
            )
            for it in items
        ],
    )


def _get_watchlist(session: Session, user_id: int, watchlist_id: int) -> Watchlist:
    wl = session.get(Watchlist, watchlist_id)
    if wl is None or wl.user_id != user_id:
        raise HTTPException(404, "watchlist not found")
    return wl


def list_watchlists(session: Session, user_id: int) -> list[WatchlistOut]:
    rows = session.execute(
        select(Watchlist).where(Watchlist.user_id == user_id).order_by(Watchlist.id)
    ).scalars()
    return [_watchlist_out(session, wl) for wl in rows]


def create_watchlist(session: Session, user_id: int, name: str) -> WatchlistOut:
    exists = session.execute(
        select(Watchlist).where(Watchlist.user_id == user_id, Watchlist.name == name)
    ).scalar_one_or_none()
    if exists is not None:
        raise HTTPException(409, "a watchlist with this name already exists")
    wl = Watchlist(user_id=user_id, name=name)
    session.add(wl)
    session.flush()
    return _watchlist_out(session, wl)


def get_watchlist(session: Session, user_id: int, watchlist_id: int) -> WatchlistOut:
    return _watchlist_out(session, _get_watchlist(session, user_id, watchlist_id))


def delete_watchlist(session: Session, user_id: int, watchlist_id: int) -> None:
    wl = _get_watchlist(session, user_id, watchlist_id)
    session.delete(wl)
    session.flush()


def add_item(
    session: Session, user_id: int, watchlist_id: int, kind: str, cik: int
) -> WatchlistOut:
    wl = _get_watchlist(session, user_id, watchlist_id)
    if session.get(_ENTITY_MODEL[kind], cik) is None:
        raise HTTPException(404, f"{kind} {cik} not found")
    if session.get(WatchlistItem, (watchlist_id, kind, cik)) is None:
        session.add(WatchlistItem(watchlist_id=watchlist_id, kind=kind, cik=cik))
        session.flush()
    return _watchlist_out(session, wl)


def remove_item(session: Session, user_id: int, watchlist_id: int, kind: str, cik: int) -> None:
    _get_watchlist(session, user_id, watchlist_id)
    item = session.get(WatchlistItem, (watchlist_id, kind, cik))
    if item is not None:
        session.delete(item)
        session.flush()


def activity(
    session: Session, user_id: int, watchlist_id: int, *, cursor: str | None, limit: int
) -> FeedPage:
    wl = _get_watchlist(session, user_id, watchlist_id)
    items = list(
        session.execute(select(WatchlistItem).where(WatchlistItem.watchlist_id == wl.id)).scalars()
    )
    company_ciks = [it.cik for it in items if it.kind == "company"]
    owner_ciks = [it.cik for it in items if it.kind in ("insider", "fund")]

    conditions = []
    if company_ciks:
        conditions.append(FeedItem.issuer_cik.in_(company_ciks))
    if owner_ciks:
        conditions.append(FeedItem.owner_ciks.overlap(owner_ciks))
    stmt = (
        select(FeedItem).where(or_(*conditions)) if conditions else select(FeedItem).where(false())
    )

    rows, next_cursor = paginate(session, stmt, FEED_KEYS, cursor, limit)
    return FeedPage(items=[_feed_item_out(row[0]) for row in rows], next_cursor=next_cursor)
