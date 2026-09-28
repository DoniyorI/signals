"""The real dispatch registration for Forms 3/4/5(+/A) and Form 144 (Task A6)."""

import pytest

from signals.domain.types import FORM144_FORMS, INSIDER_FORMS
from signals.ingest import dispatch
from signals.ingest.pipeline import ingest_raw

OWNERSHIP_KEYS = [
    "form4_buy_single",
    "form4_joint",
    "form4a_original",
    "form4a_amendment",
    "form4_10b5_1_flag",
    "form4_10b5_1_footnote",
    "form4_exercise_sale",
    "form4_footnote_price",
    "form4_value_owned",
    "form3",
    "form5",
]


@pytest.fixture(autouse=True)
def real_handlers():
    import signals.ingest.handlers  # noqa: F401  registers handle_ownership/handle_form144
    from signals.ingest.handlers.insider import handle_form144, handle_ownership

    dispatch.reset_registry()
    dispatch.register_handler(INSIDER_FORMS, handle_ownership)
    dispatch.register_handler(FORM144_FORMS, handle_form144)
    yield
    dispatch.reset_registry()


@pytest.mark.parametrize("key", [*OWNERSHIP_KEYS, "form144"])
def test_all_ownership_fixtures_ingest(session, fixture_bytes, settings, tmp_archive, key):
    out = ingest_raw(
        session,
        fixture_bytes(key),
        source="test",
        raw_path=None,
        first_seen_at=None,
        settings=settings,
        archive=tmp_archive,
    )
    assert out.status == "parsed", out.error


def test_registered_forms():
    assert dispatch.registered_forms() >= INSIDER_FORMS | FORM144_FORMS
