"""Form type -> handler registry. Workstream modules register themselves at import time."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.models import Filing
from signals.sec.archive import RawArchive
from signals.sec.sgml import SgmlFiling


@dataclass(frozen=True)
class HandlerContext:
    settings: Settings
    archive: RawArchive
    source: str
    now: datetime


Handler = Callable[[Session, SgmlFiling, Filing, HandlerContext], None]

_REGISTRY: dict[str, Handler] = {}


def register_handler(form_types: Iterable[str], handler: Handler) -> None:
    for form_type in form_types:
        _REGISTRY[form_type] = handler


def get_handler(form_type: str) -> Handler | None:
    return _REGISTRY.get(form_type)


def registered_forms() -> frozenset[str]:
    return frozenset(_REGISTRY)


def reset_registry() -> None:
    """Tests only: forget every registered handler."""
    _REGISTRY.clear()
