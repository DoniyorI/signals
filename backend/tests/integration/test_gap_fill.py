from datetime import date, datetime
from importlib import import_module

import pytest

from signals.domain.calendars import ET
from signals.ingest.gap_fill import gap_fill
from signals.ingest.indexes import daily_index_url, full_index_url
from signals.sec.client import SecClient, SecNotFoundError
from signals.sec.ratelimit import TokenBucket
from tests.integration.insider_support import idx_line, idx_text
from tests.support import MockRouter


def _client(settings, routes: dict) -> tuple[SecClient, MockRouter]:
    router = MockRouter(routes)
    limiter = TokenBucket(rate=1000, capacity=1000)
    return SecClient(settings, http=router.client, sleep=lambda s: None, limiter=limiter), router


def test_filters_forms_and_dates(session_factory, settings, tmp_archive):
    rows = [
        idx_line(
            form_type="144",
            company="In Range Co",
            cik=1000001,
            date_filed="2025-01-15",
            accession="0001000001-25-000001",
        ),
        idx_line(
            form_type="144",
            company="Too Early Co",
            cik=1000002,
            date_filed="2024-12-31",
            accession="0001000002-25-000001",
        ),
        idx_line(
            form_type="13F-HR",
            company="Wrong Form Co",
            cik=1000003,
            date_filed="2025-02-01",
            accession="0001000003-25-000001",
        ),
        idx_line(
            form_type="144",
            company="Too Late Co",
            cik=1000004,
            date_filed="2025-04-05",
            accession="0001000004-25-000001",
        ),
    ]
    client, router = _client(settings, {full_index_url(2025, 1): idx_text(rows).encode()})
    result = gap_fill(
        client,
        session_factory,
        form_types=["144"],
        start=date(2025, 1, 1),
        end=date(2025, 3, 31),
        settings=settings,
        archive=tmp_archive,
        progress={},
        save_progress=lambda p: None,
    )
    assert result.listed == 1
    fetched = [str(r.url) for r in router.requests]
    assert any(url.endswith("0001000001-25-000001.txt") for url in fetched)
    for excluded in ("0001000002-25-000001", "0001000003-25-000001", "0001000004-25-000001"):
        assert not any(excluded in url for url in fetched)


def test_resumes_from_progress(session_factory, settings, tmp_archive):
    client, router = _client(settings, {})  # nothing routed; 2025Q1 must never be requested
    result = gap_fill(
        client,
        session_factory,
        form_types=["144"],
        start=date(2025, 1, 1),
        end=date(2025, 3, 31),
        settings=settings,
        archive=tmp_archive,
        progress={"quarters_done": ["2025Q1"]},
        save_progress=lambda p: None,
    )
    assert router.requests == []
    assert result.listed == 0


def test_saves_offset_every_200(session_factory, settings, tmp_archive):
    rows = [
        idx_line(
            form_type="144",
            company=f"Co {i}",
            cik=2_000_000 + i,
            date_filed="2025-01-10",
            accession=f"0002{i:06d}-25-000001",
        )
        for i in range(450)
    ]
    client, _router = _client(settings, {full_index_url(2025, 1): idx_text(rows).encode()})

    saved: list[dict] = []
    result = gap_fill(
        client,
        session_factory,
        form_types=["144"],
        start=date(2025, 1, 1),
        end=date(2025, 3, 31),
        settings=settings,
        archive=tmp_archive,
        progress={},
        save_progress=lambda p: saved.append(p),
    )

    assert result.listed == 450
    offsets = [s["current"]["offset"] for s in saved if "current" in s]
    assert offsets == [200, 400, 450]
    # These attempts all return 404. Keep the scan offset, but never mark the quarter done.
    assert result.errors == 450
    assert not saved[-1].get("quarters_done")
    assert len(saved[-1]["pending_failures"]["2025Q1"]) == 450


def test_current_quarter_uses_daily_index(session_factory, settings, tmp_archive, monkeypatch):
    monkeypatch.setattr(
        import_module("signals.ingest.gap_fill"),
        "now_et",
        lambda: datetime(2026, 9, 30, 12, tzinfo=ET),
    )
    day = date(2026, 9, 29)
    client, router = _client(settings, {daily_index_url(day): idx_text([]).encode()})

    gap_fill(
        client,
        session_factory,
        form_types=["144"],
        start=day,
        end=day,
        settings=settings,
        archive=tmp_archive,
        progress={},
        save_progress=lambda p: None,
    )

    fetched = [str(r.url) for r in router.requests]
    assert daily_index_url(day) in fetched
    year, quarter = day.year, (day.month - 1) // 3 + 1
    assert full_index_url(year, quarter) not in fetched


def test_missing_full_index_retains_checkpoint_until_retry(session_factory, settings, tmp_archive):
    url = full_index_url(2025, 2)
    client, router = _client(settings, {url: 404})
    progress = {
        "quarters_done": ["2025Q1"],
        "current": {"quarter": "2025Q2", "offset": 200},
    }
    saved = []

    def fill():
        return gap_fill(
            client,
            session_factory,
            form_types=["144"],
            start=date(2025, 1, 1),
            end=date(2025, 6, 30),
            settings=settings,
            archive=tmp_archive,
            progress=progress,
            save_progress=saved.append,
        )

    with pytest.raises(SecNotFoundError, match=r"2025/QTR2/form\.idx"):
        fill()
    assert saved == []
    assert progress == {
        "quarters_done": ["2025Q1"],
        "current": {"quarter": "2025Q2", "offset": 200},
    }

    router.routes[url] = idx_text([]).encode()
    assert fill().errors == 0
    assert progress["quarters_done"] == ["2025Q1", "2025Q2"]
    assert "current" not in progress
    assert [str(r.url) for r in router.requests] == [url, url]


def test_missing_current_quarter_day_is_retryable(
    session_factory, settings, tmp_archive, monkeypatch
):
    monkeypatch.setattr(
        import_module("signals.ingest.gap_fill"),
        "now_et",
        lambda: datetime(2026, 9, 30, 12, tzinfo=ET),
    )
    day = date(2026, 9, 29)
    url = daily_index_url(day)
    client, router = _client(settings, {url: 404})
    progress, saved = {}, []

    def fill():
        return gap_fill(
            client,
            session_factory,
            form_types=["144"],
            start=day,
            end=day,
            settings=settings,
            archive=tmp_archive,
            progress=progress,
            save_progress=saved.append,
        )

    with pytest.raises(SecNotFoundError, match=f"form.{day:%Y%m%d}.idx"):
        fill()
    assert progress == {} and saved == []
    router.routes[url] = idx_text([]).encode()
    assert fill().errors == 0
    assert progress["quarters_done"] == [f"{day.year}Q{(day.month - 1) // 3 + 1}"]
    assert [str(r.url) for r in router.requests] == [url, url]


def test_current_quarter_follows_eastern_date_at_utc_rollover(
    session_factory, settings, tmp_archive, monkeypatch
):
    module = import_module("signals.ingest.gap_fill")

    class UtcDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 1)

    # Docker is already in Q4 while the SEC is still on the last evening of Q3.
    monkeypatch.setattr(module, "date", UtcDate)
    monkeypatch.setattr(
        module, "now_et", lambda: datetime(2026, 9, 30, 21, tzinfo=ET), raising=False
    )
    day = date(2026, 9, 29)
    daily_url = daily_index_url(day)
    full_url = full_index_url(2026, 3)
    client, router = _client(
        settings, {daily_url: idx_text([]).encode(), full_url: idx_text([]).encode()}
    )
    gap_fill(
        client,
        session_factory,
        form_types=["144"],
        start=day,
        end=day,
        settings=settings,
        archive=tmp_archive,
        progress={},
        save_progress=lambda p: None,
    )
    assert [str(r.url) for r in router.requests] == [daily_url]
