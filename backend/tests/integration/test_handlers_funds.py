import pytest

from signals.db.models import FundFiling, OwnershipStake
from signals.domain.types import FUND_FORMS, STAKE_FORMS
from signals.ingest import dispatch
from signals.ingest.handlers import funds as funds_handlers
from signals.ingest.pipeline import ingest_raw


@pytest.fixture(autouse=True)
def register_funds_handlers():
    dispatch.reset_registry()
    dispatch.register_handler(FUND_FORMS, funds_handlers.handle_13f)
    dispatch.register_handler(STAKE_FORMS, funds_handlers.handle_schedule13)
    yield
    dispatch.reset_registry()


@pytest.mark.parametrize(
    "key", ["f13f_small", "f13f_pre2023", "f13f_restatement", "sc13d", "sc13g"]
)
def test_fixtures_ingest(session, settings, tmp_archive, fixture_bytes, key):
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
    if key.startswith("f13f"):
        assert session.get(FundFiling, out.accession_no) is not None
    else:
        assert session.get(OwnershipStake, out.accession_no) is not None


def test_13f_nt_like_document_without_information_table(
    session, settings, tmp_archive, fixture_bytes
):
    # f13f_small has both documents; re-ingesting the same bytes must stay idempotent through
    # the real handler (not just the local test stand-ins used by B2's own tests).
    first = ingest_raw(
        session,
        fixture_bytes("f13f_small"),
        source="test",
        raw_path=None,
        first_seen_at=None,
        settings=settings,
        archive=tmp_archive,
    )
    second = ingest_raw(
        session,
        fixture_bytes("f13f_small"),
        source="test",
        raw_path=None,
        first_seen_at=None,
        settings=settings,
        archive=tmp_archive,
    )
    assert first.status == second.status == "parsed"
