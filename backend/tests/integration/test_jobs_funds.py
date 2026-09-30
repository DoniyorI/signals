from datetime import date

import httpx

from signals.db.models import FundManager, FundPosition, Security
from signals.domain.appstate import get_state, set_state
from signals.domain.types import FUND_FORMS, STAKE_FORMS
from signals.ingest import jobs_funds
from signals.jobs import JOBS, JobContext
from signals.reference.cusip import MapResult, OpenFigiClient
from signals.sec.client import SecClient
from tests.factories import make_fund_filing, make_fund_manager, make_fund_position, make_issuer
from tests.support import MockRouter

LISTING_HTML = (
    "<html><body>"
    '<a href="/files/datastandardsinnovation/data/form-13f-data-sets/2016q1_form13f.zip">'
    "2016q1_form13f.zip</a>"
    '<a href="/files/datastandardsinnovation/data/form-13f-data-sets/2026q2_form13f.zip">'
    "2026q2_form13f.zip</a>"
    "</body></html>"
)
OLD_URL = (
    "https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/2016q1_form13f.zip"
)
NEW_URL = (
    "https://www.sec.gov/files/datastandardsinnovation/data/form-13f-data-sets/2026q2_form13f.zip"
)


def _ctx(session_factory, settings, archive, *, sec=None, params=None, progress=None) -> JobContext:
    return JobContext(
        settings=settings,
        session_factory=session_factory,
        sec=sec or SecClient(settings, http=MockRouter({}).client, sleep=lambda s: None),
        archive=archive,
        request_id=None,
        params=dict(params or {}),
        progress=dict(progress if progress is not None else {}),
        save_progress=lambda p: None,
    )


def test_jobs_registered():
    for kind in (
        "backfill_funds",
        "bulk_check_funds",
        "cusip_map",
        "fund_changes",
        "tracked_funds_refresh",
    ):
        assert kind in JOBS, kind
    assert JOBS["backfill_funds"].cron is None
    assert JOBS["cusip_map"].cron is None
    assert JOBS["fund_changes"].cron is None
    assert JOBS["bulk_check_funds"].cron == {"day_of_week": "mon", "hour": 3, "minute": 15}
    assert JOBS["tracked_funds_refresh"].cron == {"day_of_week": "sun", "hour": 5, "minute": 0}


def test_backfill_funds_resumes(session_factory, settings, tmp_archive, fixture_bytes, monkeypatch):
    calls: list[str] = []
    gap_fill_calls: list[tuple[frozenset, date | None]] = []

    monkeypatch.setattr(
        jobs_funds, "_apply_acceptance", lambda ctx: calls.append("apply_acceptance")
    )

    def fake_gap_fill(ctx, forms, **kw):
        calls.append("gap_fill_funds" if forms == FUND_FORMS else "gap_fill_stakes")
        gap_fill_calls.append((forms, kw.get("start")))

    monkeypatch.setattr(jobs_funds, "_gap_fill", fake_gap_fill)
    monkeypatch.setattr(jobs_funds, "_openfigi_client", lambda ctx: None)
    monkeypatch.setattr(
        jobs_funds,
        "compute_fund_changes",
        lambda s, **kw: calls.append("compute_fund_changes") or 0,
    )
    monkeypatch.setattr(
        jobs_funds,
        "map_securities",
        lambda s, figi, **kw: calls.append("map_securities") or MapResult(0, 0, 0, 0),
    )
    monkeypatch.setattr(
        jobs_funds,
        "flag_value_unit_anomalies",
        lambda s, **kw: calls.append("flag_value_unit_anomalies") or 0,
    )
    monkeypatch.setattr(
        jobs_funds,
        "refresh_tracked_funds",
        lambda s, **kw: calls.append("refresh_tracked_funds") or 0,
    )

    router = MockRouter(
        {
            jobs_funds.LISTING_URL: LISTING_HTML.encode(),
            NEW_URL: fixture_bytes("bulk_13f_slice_2025"),
        }
    )
    sec = SecClient(settings, http=router.client, archive=tmp_archive, sleep=lambda s: None)
    progress = {"datasets_done": ["2016q1_form13f.zip"]}
    ctx = _ctx(session_factory, settings, tmp_archive, sec=sec, progress=progress)

    jobs_funds.backfill_funds(ctx)

    requested = [str(r.url) for r in router.requests]
    assert jobs_funds.LISTING_URL in requested
    assert NEW_URL in requested
    assert OLD_URL not in requested

    assert calls == [
        "apply_acceptance",
        "gap_fill_funds",
        "gap_fill_stakes",
        "compute_fund_changes",
        "map_securities",
        "flag_value_unit_anomalies",
        "refresh_tracked_funds",
    ]
    assert gap_fill_calls[0] == (FUND_FORMS, date(2026, 7, 1))
    assert gap_fill_calls[1] == (STAKE_FORMS, settings.stakes_start)
    assert ctx.progress["datasets_done"] == ["2016q1_form13f.zip", "2026q2_form13f.zip"]


def test_bulk_check_funds_loads_missing_datasets(
    session, session_factory, settings, tmp_archive, fixture_bytes
):
    set_state(session, jobs_funds.BULK_STATE_KEY, {"loaded": ["2016q1_form13f.zip"]})
    session.flush()
    router = MockRouter(
        {
            jobs_funds.LISTING_URL: LISTING_HTML.encode(),
            NEW_URL: fixture_bytes("bulk_13f_slice_2025"),
        }
    )
    sec = SecClient(settings, http=router.client, archive=tmp_archive, sleep=lambda s: None)
    ctx = _ctx(session_factory, settings, tmp_archive, sec=sec)

    result = jobs_funds.bulk_check_funds(ctx) or {}

    assert result["loaded"] == ["2026q2_form13f.zip"]
    requested = [str(r.url) for r in router.requests]
    assert OLD_URL not in requested and NEW_URL in requested

    session.expire_all()
    state = get_state(session, jobs_funds.BULK_STATE_KEY) or {}
    assert set(state["loaded"]) == {"2016q1_form13f.zip", "2026q2_form13f.zip"}


def test_cusip_map_job(session, session_factory, settings, tmp_archive, monkeypatch):
    make_issuer(session)  # cik=1000001, name="Acme Corp"
    filing = make_fund_filing(session)
    session.add(
        FundPosition(
            period=date(2024, 3, 31),
            accession_no=filing.accession_no,
            cusip="000000BB2",
            put_call="",
            filer_cik=filing.filer_cik,
            name_of_issuer="ACME CORP COM",
            shares=1.0,
            sh_prn="SH",
            value_usd=1.0,
            is_effective=True,
        )
    )
    session.flush()

    router = MockRouter(
        {
            "https://api.openfigi.com/v3/mapping": lambda r: httpx.Response(
                200, json=[{"warning": "no match"}]
            )
        }
    )
    monkeypatch.setattr(
        jobs_funds, "_openfigi_client", lambda ctx: OpenFigiClient(router.client, api_key=None)
    )
    ctx = _ctx(session_factory, settings, tmp_archive)

    result = jobs_funds.cusip_map(ctx) or {}

    assert result["mapped_name"] == 1
    session.expire_all()
    sec = session.get(Security, "000000BB2")
    assert sec is not None and sec.map_source == "name_match"


def test_fund_changes_job(session, session_factory, settings, tmp_archive):
    make_fund_manager(session)
    q1 = make_fund_filing(session, accession_no="0003000001-24-000001", period=date(2024, 3, 31))
    make_fund_position(
        session, accession_no=q1.accession_no, period=date(2024, 3, 31), cusip="000000AA1"
    )
    q2 = make_fund_filing(
        session,
        accession_no="0003000001-24-000002",
        period=date(2024, 6, 30),
        filed_date=date(2024, 8, 14),
    )
    make_fund_position(
        session,
        accession_no=q2.accession_no,
        period=date(2024, 6, 30),
        cusip="000000AA1",
        shares=150,
        value_usd=1500,
    )
    session.flush()
    ctx = _ctx(session_factory, settings, tmp_archive, params={"filer_ciks": [3000001]})

    result = jobs_funds.fund_changes(ctx) or {}

    assert result["changes"] >= 1
    session.expire_all()
    manager = session.get(FundManager, 3000001)
    assert manager.latest_period == date(2024, 6, 30)


def test_tracked_funds_refresh_job(session, session_factory, settings, tmp_archive):
    make_fund_manager(session, cik=9999999, name="Big Test Fund", is_tracked=False)
    manager = session.get(FundManager, 9999999)
    manager.latest_value_usd = 5e9
    manager.latest_positions = 10
    session.flush()
    ctx = _ctx(session_factory, settings, tmp_archive)

    result = jobs_funds.tracked_funds_refresh(ctx) or {}

    assert result["tracked"] == 1
    session.expire_all()
    assert session.get(FundManager, 9999999).is_tracked is True
