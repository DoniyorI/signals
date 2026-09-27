"""FastAPI dependencies. Tests override get_db and get_curve_service."""

from collections.abc import Generator
from datetime import date
from functools import cache
from types import ModuleType
from typing import Annotated, Protocol

from fastapi import Depends
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from signals.analytics.types import Curve
from signals.config import get_settings
from signals.db.session import make_engine, make_session_factory


class CurveService(Protocol):
    def insider_curve(
        self, session: Session, cik: int, *, basis: str, include_10b5_1: bool, as_of: date
    ) -> Curve: ...

    def fund_curve(self, session: Session, cik: int, *, basis: str, as_of: date) -> Curve: ...


@cache
def _engine() -> Engine:
    return make_engine(get_settings().database_url)


def get_db() -> Generator[Session]:
    session = make_session_factory(_engine())()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def get_curve_service() -> CurveService | ModuleType:
    from signals.analytics import curves

    return curves


Curves = Annotated[CurveService | ModuleType, Depends(get_curve_service)]
Db = Annotated[Session, Depends(get_db)]
