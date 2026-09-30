"""Importing this package registers every form handler with the dispatch registry."""

from signals.domain.types import FORM144_FORMS, FUND_FORMS, INSIDER_FORMS, STAKE_FORMS
from signals.ingest.dispatch import register_handler
from signals.ingest.handlers import funds, insider


def register_all_handlers() -> None:
    """Initialize real handlers on startup, including after a test registry reset."""
    register_handler(INSIDER_FORMS, insider.handle_ownership)
    register_handler(FORM144_FORMS, insider.handle_form144)
    register_handler(FUND_FORMS, funds.handle_13f)
    register_handler(STAKE_FORMS, funds.handle_schedule13)


__all__ = ["funds", "insider", "register_all_handlers"]
