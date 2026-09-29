from datetime import date, datetime

from signals.domain.appstate import get_state
from signals.domain.calendars import ET
from signals.ingest import jobs_insider
from signals.ingest.feed import PollResult
from signals.ingest.gap_fill import GapFillResult
from signals.ingest.indexes import ReconcileResult
from signals.jobs import JOBS, JobContext, load_all_jobs
from signals.sec.client import SecClient
from tests.support import MockRouter

_BASE = "/files/structureddata/data/insider-transactions-data-sets"
LISTING_HTML = f"""
<a href="{_BASE}/2024q4_form345.zip">2024q4_form345.zip</a>
<a href="{_BASE}/2025q1_form345.zip">2025q1_form345.zip</a>
"""

FIRST_URL = f"https://www.sec.gov{_BASE}/2024q4_form345.zip"
SECOND_URL = f"https://www.sec.gov{_BASE}/2025q1_form345.zip"


def _ctx(settings, session_factory, archive, *, now, routes=None, progress=None) -> JobContext:
    client = SecClient(settings, http=MockRouter(routes or {}).client, sleep=lambda s: None)
    return JobContext(
        settings=settings,
        session_factory=session_factory,
        sec=client,
        archive=archive,
        request_id=None,
        params={},
        progress=progress if progress is not None else {},
        save_progress=lambda p: None,
        now=now,
    )


def test_jobs_registered():
    load_all_jobs()
    assert JOBS["live_poll"].interval_seconds == 60
    assert JOBS["reconcile_daily"].cron == {"hour": 6, "minute": 30}
    assert "backfill_insiders" in JOBS
    assert JOBS["bulk_check_insiders"].cron == {"day_of_week": "mon", "hour": 3, "minute": 0}


def test_live_poll_outside_window(session_factory, settings, tmp_archive):
    saturday = datetime(2024, 6, 8, 10, 0, tzinfo=ET)
    router = MockRouter({})
    client = SecClient(settings, http=router.client, sleep=lambda s: None)
    ctx = JobContext(
        settings,
        session_factory,
        client,
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
        lambda: saturday,
    )
    result = jobs_insider.live_poll(ctx)
    assert result == {"skipped": "outside window"}
    assert router.requests == []


def test_live_poll_within_window_runs_poll_feed(
    monkeypatch, session_factory, settings, tmp_archive
):
    captured = {}

    def fake_poll_feed(client, sf, *, now, settings, archive, **kwargs):
        captured["now"] = now
        return PollResult(
            pages=1,
            entries=2,
            new=1,
            errors=0,
            issuer_ciks=frozenset({42}),
            owner_ciks=frozenset({7}),
            filer_ciks=frozenset(),
        )

    monkeypatch.setattr(jobs_insider, "poll_feed", fake_poll_feed)
    monday = datetime(2024, 6, 10, 10, 0, tzinfo=ET)
    ctx = _ctx(settings, session_factory, tmp_archive, now=lambda: monday)
    result = jobs_insider.live_poll(ctx)
    assert result == {
        "pages": 1,
        "entries": 2,
        "new": 1,
        "errors": 0,
        "issuer_ciks": [42],
        "owner_ciks": [7],
        "filer_ciks": [],
    }
    assert captured["now"] == monday


def test_reconcile_daily_caps_at_seven_days_and_stores_last_day(
    monkeypatch, session, session_factory, settings, tmp_archive
):
    seen_days: list[date] = []

    def fake_reconcile_day(client, sf, day, *, settings, archive, **kwargs):
        seen_days.append(day)
        return ReconcileResult(day=day, listed=0, missing=0, ingested=0, errors=0)

    monkeypatch.setattr(jobs_insider, "reconcile_day", fake_reconcile_day)
    # A Monday, so "yesterday" (Sunday) isn't a business day but the cap still counts it.
    now = datetime(2024, 6, 10, 6, 30, tzinfo=ET)
    ctx = _ctx(settings, session_factory, tmp_archive, now=lambda: now)

    result = jobs_insider.reconcile_daily(ctx)
    session.commit()
    assert result is not None  # the real function always returns a dict, never None

    yesterday = date(2024, 6, 9)
    assert len(seen_days) <= 7
    assert all(d <= yesterday for d in seen_days)
    assert result["days"] == [d.isoformat() for d in seen_days]

    state = get_state(session, "reconcile_last_day")
    assert state == {"day": yesterday.isoformat()}


def test_reconcile_daily_resumes_after_last_day(
    monkeypatch, session, session_factory, settings, tmp_archive
):
    from signals.domain.appstate import set_state

    set_state(session, "reconcile_last_day", {"day": "2024-06-05"})
    session.commit()

    seen_days: list[date] = []
    monkeypatch.setattr(
        jobs_insider,
        "reconcile_day",
        lambda client, sf, day, **kw: (
            seen_days.append(day)
            or ReconcileResult(day=day, listed=0, missing=0, ingested=0, errors=0)
        ),
    )
    now = datetime(2024, 6, 10, 6, 30, tzinfo=ET)  # Monday; yesterday = Sunday 6/9
    ctx = _ctx(settings, session_factory, tmp_archive, now=lambda: now)
    jobs_insider.reconcile_daily(ctx)

    assert seen_days == [date(2024, 6, 6), date(2024, 6, 7)]  # Thu, Fri (Sat/Sun skipped)


def test_backfill_insiders_resumes(
    monkeypatch, session_factory, settings, tmp_archive, fixture_bytes
):
    fake_gap_result = GapFillResult(listed=0, ingested=0, skipped_existing=0, errors=0)
    monkeypatch.setattr(jobs_insider, "gap_fill", lambda *a, **k: fake_gap_result)

    routes = {
        jobs_insider.LISTING_URL: LISTING_HTML.encode(),
        SECOND_URL: fixture_bytes("bulk_345_slice"),
    }
    router = MockRouter(routes)
    client = SecClient(settings, http=router.client, sleep=lambda s: None)
    progress = {"datasets_done": ["2024q4_form345.zip"]}
    ctx = JobContext(
        settings,
        session_factory,
        client,
        tmp_archive,
        None,
        {},
        progress,
        lambda p: progress.update(p),
        lambda: datetime(2025, 6, 1, 12, 0, tzinfo=ET),
    )

    result = jobs_insider.backfill_insiders(ctx)
    assert result is not None  # the real function always returns a dict, never None

    fetched = [str(r.url) for r in router.requests]
    assert not any(url == FIRST_URL for url in fetched)
    assert sum(1 for url in fetched if url == SECOND_URL) == 1
    assert result["datasets_loaded"] == 2
    assert progress["datasets_done"] == ["2024q4_form345.zip", "2025q1_form345.zip"]


def test_bulk_check_insiders_loads_missing(
    session, session_factory, settings, tmp_archive, fixture_bytes
):
    from signals.domain.appstate import set_state

    set_state(session, "bulk_345_loaded", {"names": ["2024q4_form345.zip"]})
    session.commit()

    routes = {
        jobs_insider.LISTING_URL: LISTING_HTML.encode(),
        SECOND_URL: fixture_bytes("bulk_345_slice"),
    }
    router = MockRouter(routes)
    client = SecClient(settings, http=router.client, sleep=lambda s: None)
    ctx = JobContext(
        settings,
        session_factory,
        client,
        tmp_archive,
        None,
        {},
        {},
        lambda p: None,
        lambda: datetime(2025, 6, 1, 12, 0, tzinfo=ET),
    )

    result = jobs_insider.bulk_check_insiders(ctx)
    session.commit()
    assert result is not None  # the real function always returns a dict, never None

    assert result["newly_loaded"] == ["2025q1_form345.zip"]
    assert not any(str(r.url) == FIRST_URL for r in router.requests)
    state = get_state(session, "bulk_345_loaded")
    assert state is not None and set(state["names"]) == {"2024q4_form345.zip", "2025q1_form345.zip"}
