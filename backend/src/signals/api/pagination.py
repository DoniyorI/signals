"""Opaque cursors and keyset pagination for list endpoints.

A cursor is URL-safe base64 of a small JSON object holding the sort values of the last row
of the previous page. Pages are cut with a keyset predicate (never OFFSET), so rows inserted
while a user pages never cause repeats or gaps. Every sort key orders NULLS LAST.
"""

import base64
import binascii
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import ColumnElement, Row, Select, and_, false, or_
from sqlalchemy.orm import QueryableAttribute, Session

INVALID_CURSOR = "invalid cursor"

# A sort/filter column as either a bare SQL expression or a mapped ORM attribute (`Model.field`).
# pyright sees these as unrelated types even though both support the same operators at runtime.
SortColumn = ColumnElement[Any] | QueryableAttribute[Any]


def encode_cursor(values: dict) -> str:
    raw = json.dumps(values, separators=(",", ":"), sort_keys=True).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(s: str | None) -> dict | None:
    """The cursor's values, None when there is no cursor; anything malformed is a 400."""
    if not s:
        return None
    try:
        raw = base64.b64decode(s + "=" * (-len(s) % 4), altchars=b"-_", validate=True)
        values = json.loads(raw)
    except (binascii.Error, ValueError) as exc:  # includes JSON and UTF-8 decode errors
        raise HTTPException(400, INVALID_CURSOR) from exc
    if not isinstance(values, dict):
        raise HTTPException(400, INVALID_CURSOR)
    return values


# ----------------------------------------------------------------------------- value parsers
def parse_str(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("expected a string")
    return value


def parse_int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected an integer")
    return value


def parse_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError("expected a number")
    return float(value)


def parse_date(value: Any) -> date:
    return date.fromisoformat(parse_str(value))


def parse_datetime(value: Any) -> datetime:
    return datetime.fromisoformat(parse_str(value))


def _jsonable(value: Any) -> Any:
    return value.isoformat() if isinstance(value, date | datetime) else value


# ----------------------------------------------------------------------------- keyset
@dataclass(frozen=True)
class SortKey:
    """One ORDER BY term. `name` is its field in the cursor; NULLs always sort last."""

    name: str
    column: SortColumn
    desc: bool = True
    nullable: bool = False
    parse: Callable[[Any], Any] = parse_str

    def order(self) -> ColumnElement[Any]:
        term = self.column.desc() if self.desc else self.column.asc()
        return term.nulls_last()


def order_terms(keys: Sequence[SortKey]) -> list[ColumnElement[Any]]:
    return [key.order() for key in keys]


def keyset_filter(keys: Sequence[SortKey], position: dict) -> ColumnElement[bool]:
    """Rows that sort strictly after `position` (a decoded cursor) in the order of `keys`."""
    try:
        values = [_parse(key, position[key.name]) for key in keys]
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(400, INVALID_CURSOR) from exc
    branches = []
    for i, key in enumerate(keys):
        beyond = _beyond(key, values[i])
        if beyond is None:
            continue
        same = [_equal(keys[j], values[j]) for j in range(i)]
        branches.append(and_(*same, beyond))
    return or_(*branches) if branches else false()


def _parse(key: SortKey, value: Any) -> Any:
    if value is None:
        if not key.nullable:
            raise ValueError(f"cursor field {key.name!r} cannot be null")
        return None
    return key.parse(value)


def _equal(key: SortKey, value: Any) -> ColumnElement[bool]:
    return key.column.is_(None) if value is None else key.column == value


def _beyond(key: SortKey, value: Any) -> ColumnElement[bool] | None:
    if value is None:
        return None  # NULLs sort last, so nothing sorts strictly after a NULL on this key
    step = key.column < value if key.desc else key.column > value
    return or_(step, key.column.is_(None)) if key.nullable else step


def paginate(
    session: Session, stmt: Select[Any], keys: Sequence[SortKey], cursor: str | None, limit: int
) -> tuple[list[Row[Any]], str | None]:
    """Run `stmt` (without ORDER BY or LIMIT) for one page. Returns the rows and the next
    cursor, which is None on the last page. Rows carry extra `_cursor_<i>` columns."""
    position = decode_cursor(cursor)
    if position is not None:
        stmt = stmt.where(keyset_filter(keys, position))
    labels = [f"_cursor_{i}" for i in range(len(keys))]
    stmt = (
        stmt.add_columns(
            *(key.column.label(label) for key, label in zip(keys, labels, strict=True))
        )
        .order_by(*order_terms(keys))
        .limit(limit + 1)
    )
    rows = list(session.execute(stmt).all())
    if len(rows) <= limit:
        return rows, None
    rows = rows[:limit]
    last = rows[-1]._mapping
    values = {key.name: _jsonable(last[label]) for key, label in zip(keys, labels, strict=True)}
    return rows, encode_cursor(values)
