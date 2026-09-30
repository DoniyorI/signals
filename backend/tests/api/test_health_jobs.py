from datetime import timedelta

import pytest

from signals.db.models import FeedItem, Filing
from signals.domain.appstate import set_state
from tests.api.seed import FROZEN_NOW


def test_feed_delay_percentiles(api, session):
    base = FROZEN_NOW - timedelta(hours=2)
    for i, delay in enumerate([30, 60, 90, 120]):
        session.add(FeedItem(accession_no=f"0009999999-24-00000{i}", form_type="4"))
        session.add(
            Filing(
                accession_no=f"0009999999-24-00000{i}",
                form_type="4",
                primary_cik=9999999,
                filed_date=base.date(),
                accepted_at=base,
                accepted_at_source="sgml",
                source="feed",
                parse_status="parsed",
                first_seen_at=base + timedelta(seconds=delay),
            )
        )
    session.flush()

    body = api.get("/api/health").json()
    assert body["feed_delay_p50_s"] == pytest.approx(75.0)
    assert body["feed_delay_p95_s"] == pytest.approx(115.5)
    assert body["last_filing_seen_at"] is not None


def test_parse_errors_listed_and_warn(api, session):
    session.add(
        Filing(
            accession_no="0009999998-24-000001",
            form_type="4",
            primary_cik=9999998,
            filed_date=FROZEN_NOW.date(),
            source="feed",
            parse_status="error",
            parse_error="boom: bad XML",
            parsed_at=FROZEN_NOW - timedelta(hours=1),
        )
    )
    session.flush()

    body = api.get("/api/health").json()
    assert body["status"] == "warn"
    assert any(e["accession_no"] == "0009999998-24-000001" for e in body["parse_errors"])
    matched = next(e for e in body["parse_errors"] if e["accession_no"] == "0009999998-24-000001")
    assert matched["error"] == "boom: bad XML"


def test_blocked_is_error(api, session):
    set_state(
        session, "sec_blocked_until", {"until": (FROZEN_NOW + timedelta(minutes=5)).isoformat()}
    )
    session.flush()

    body = api.get("/api/health").json()
    assert body["status"] == "error"
    assert body["sec_blocked_until"] is not None


def test_jobs_post_and_list(api):
    r = api.post("/api/jobs", json={"kind": "backfill_all"})
    assert r.status_code == 202
    body = r.json()
    assert body["kind"] == "backfill_all"
    assert body["status"] == "requested"

    listed = api.get("/api/jobs").json()
    assert any(j["id"] == body["id"] for j in listed)

    bad = api.post("/api/jobs", json={"kind": "nope"})
    assert bad.status_code == 422
