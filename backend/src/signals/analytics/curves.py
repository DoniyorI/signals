"""Performance curves served by the API. Foundation stub; workstream D implements both."""

from datetime import date

from sqlalchemy.orm import Session

from signals.analytics.types import Curve


def insider_curve(
    session: Session, cik: int, *, basis: str, include_10b5_1: bool, as_of: date
) -> Curve:
    raise NotImplementedError


def fund_curve(session: Session, cik: int, *, basis: str, as_of: date) -> Curve:
    raise NotImplementedError
