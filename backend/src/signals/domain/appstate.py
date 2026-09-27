"""Tiny key-value store for operational state (last poll, SEC block, loaded datasets)."""

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from signals.db.models import AppState


def get_state(session: Session, key: str) -> dict | None:
    return session.execute(select(AppState.value).where(AppState.key == key)).scalar_one_or_none()


def set_state(session: Session, key: str, value: dict) -> None:
    stmt = insert(AppState).values(key=key, value=value)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["key"], set_={"value": stmt.excluded.value, "updated_at": func.now()}
        )
    )
