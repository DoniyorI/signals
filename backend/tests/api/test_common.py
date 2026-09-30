import base64
import csv
import io
from datetime import date, datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from signals.api.csv import csv_response
from signals.api.pagination import (
    SortKey,
    decode_cursor,
    encode_cursor,
    paginate,
    parse_datetime,
    parse_str,
)
from signals.api.queries.common import (
    current_symbols,
    issuer_ref,
    latest_close,
    rating_of,
    sec_url,
)
from signals.api.schemas import FeedItemOut, InsiderScreenRow, IssuerRef, Rating
from signals.db.models import FeedItem, Issuer
from signals.domain.calendars import ET
from signals.domain.feed import FeedItemIn, upsert_feed_item
from tests.api.seed import ACME, GLOBEX, NEWCO, OLDCO
from tests.factories import make_profile_stats


def sample_feed_item(**overrides) -> dict:
    item = {
        "accession_no": "0002000001-24-000001",
        "sec_url": "https://www.sec.gov/Archives/edgar/data/2000001/000200000124000001/0002000001-24-000001-index.htm",
        "form_type": "4",
        "accepted_at": "2024-06-03T16:30:00-04:00",
        "filed_date": "2024-06-03",
        "issuer": {"cik": 1000001, "name": "Acme Corp", "ticker": "ACME"},
        "owners": [{"cik": 2000001, "name": "Doe Jane"}],
        "top_role": "CEO",
        "direction": "buy",
        "codes": ["P"],
        "value_usd": 10000.0,
        "shares": 1000.0,
        "price": 10.0,
        "plan_10b5_1": "none",
        "badges": ["cluster_buy", "top_exec"],
        "market_cap_usd": 1e10,
        "sector": "Technology",
        "summary": "Bought 1,000 sh @ $10.00 ($10,000)",
        "lag_days": 2,
    }
    return {**item, **overrides}


def _body_bytes(body: bytes | memoryview) -> bytes:
    """`Response.body` is typed `bytes | memoryview`; our responses always render `bytes`."""
    return bytes(body)


def _csv_rows(body: bytes | memoryview) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(_body_bytes(body).decode())))


# --------------------------------------------------------------------------- cursors
def test_cursor_roundtrip():
    c = encode_cursor({"a": "2024-06-07T16:00:00-04:00", "k": "0002000001-24-000009"})
    assert decode_cursor(c) == {"a": "2024-06-07T16:00:00-04:00", "k": "0002000001-24-000009"}
    assert decode_cursor(None) is None
    with pytest.raises(HTTPException):
        decode_cursor("not-base64!")


@pytest.mark.parametrize(
    "cursor",
    [
        base64.urlsafe_b64encode(b"[1, 2]").decode(),  # JSON, but not an object
        base64.urlsafe_b64encode(b"{not json").decode(),
        "abcde",  # impossible base64 length
    ],
)
def test_decode_cursor_rejects_garbage_with_400(cursor):
    with pytest.raises(HTTPException) as err:
        decode_cursor(cursor)
    assert (err.value.status_code, err.value.detail) == (400, "invalid cursor")


def _seed_feed_rows(session) -> None:
    for accession, hour in [
        ("0000000001-24-000001", 9),
        ("0000000001-24-000002", None),
        ("0000000001-24-000003", 9),
        ("0000000001-24-000004", 11),
        ("0000000001-24-000005", None),
    ]:
        accepted = None if hour is None else datetime(2024, 6, 3, hour, tzinfo=ET)
        upsert_feed_item(
            session, FeedItemIn(accession_no=accession, form_type="4", accepted_at=accepted)
        )


FEED_KEYS = [
    SortKey("a", FeedItem.accepted_at, desc=True, nullable=True, parse=parse_datetime),
    SortKey("k", FeedItem.accession_no, desc=True, parse=parse_str),
]


def test_paginate_walks_every_row_once_with_nulls_last(session):
    _seed_feed_rows(session)
    got: list[str] = []
    cursor = None
    for _ in range(10):
        rows, cursor = paginate(session, select(FeedItem.accession_no), FEED_KEYS, cursor, 2)
        got += [row.accession_no for row in rows]
        if cursor is None:
            break
    assert got == [
        "0000000001-24-000004",  # 11:00
        "0000000001-24-000003",  # 09:00, higher accession first
        "0000000001-24-000001",  # 09:00
        "0000000001-24-000005",  # no acceptance time: last
        "0000000001-24-000002",
    ]


@pytest.mark.parametrize(
    "position",
    [{"a": 5, "k": "0000000001-24-000001"}, {"k": "0000000001-24-000001"}, {"a": None, "k": None}],
)
def test_paginate_rejects_malformed_positions(session, position):
    with pytest.raises(HTTPException) as err:
        paginate(session, select(FeedItem.accession_no), FEED_KEYS, encode_cursor(position), 2)
    assert err.value.status_code == 400


# --------------------------------------------------------------------------- CSV
def test_csv_flattens():
    r = csv_response([FeedItemOut.model_validate(sample_feed_item())], "feed.csv")
    head = _body_bytes(r.body).decode().splitlines()[0].split(",")
    assert r.media_type == "text/csv" and "issuer.name" in head and "badges" in head


def test_csv_joins_lists_and_blanks_missing_values():
    item = sample_feed_item(
        issuer=None,
        owners=[
            {"cik": 2000003, "name": "Acme Holdings LP"},
            {"cik": 2000004, "name": "Smith John"},
        ],
        badges=["cluster_buy", "big_stake"],
        price=None,
    )
    r = csv_response([FeedItemOut.model_validate(item)], "feed.csv")
    (row,) = _csv_rows(r.body)
    assert row["owners.name"] == "Acme Holdings LP;Smith John"
    assert row["owners.cik"] == "2000003;2000004"
    assert row["badges"] == "cluster_buy;big_stake"
    assert (row["issuer.name"], row["price"]) == ("", "")
    assert r.headers["content-disposition"] == 'attachment; filename="feed.csv"'


def test_csv_without_rows_still_has_the_header():
    r = csv_response([], "feed.csv", model=FeedItemOut)
    lines = _body_bytes(r.body).decode().splitlines()
    assert len(lines) == 1 and "accession_no" in lines[0] and "issuer.ticker" in lines[0]


def test_csv_expands_mapping_fields_by_key():
    row = InsiderScreenRow(
        owner={"cik": 1, "name": "A"},  # pyright: ignore[reportArgumentType]
        primary_issuer=None,
        roles=["CEO"],
        sector=None,
        rating=Rating(score=None, confidence=None, n=0),
        avg_roi_6m=None,
        hit_rate=None,
        n_decisions=0,
        last_trade_date=None,
        windows={"ytd": 0.1, "1y": None},
        risk_label=None,
    )
    (out,) = _csv_rows(csv_response([row], "screen.csv").body)
    assert (out["windows.ytd"], out["windows.1y"], out["roles"]) == ("0.1", "", "CEO")


# --------------------------------------------------------------------------- query helpers
def test_seed_world_builds(world, session):
    assert session.get(Issuer, 1000002).name == "Globex Inc"


def test_current_symbols_follow_ticker_changes(world, session):
    assert current_symbols(session, [ACME, GLOBEX, OLDCO, NEWCO, 999]) == {
        ACME: "ACME",
        GLOBEX: "GLBX",
        OLDCO: "XYZA",
        NEWCO: "XYZ",
    }


def test_issuer_ref_uses_current_ticker(world, session):
    assert issuer_ref(session, GLOBEX) == IssuerRef(cik=GLOBEX, name="Globex Inc", ticker="GLBX")
    assert issuer_ref(session, 999) == IssuerRef(cik=999, name="CIK 999", ticker=None)


def test_latest_close(world, session):
    assert latest_close(session, "ACME") == (10.0, date(2024, 6, 14))
    assert latest_close(session, "NOPE") is None


def test_rating_of(session):
    assert rating_of(None) == Rating(score=None, confidence=None, n=0)
    stats = make_profile_stats(session, rating=80, confidence="low", n_complete=3)
    assert rating_of(stats) == Rating(score=80, confidence="low", n=3)


def test_sec_url():
    assert sec_url(1000001, "0002000001-24-000001") == (
        "https://www.sec.gov/Archives/edgar/data/1000001/000200000124000001/"
        "0002000001-24-000001-index.htm"
    )
    # A malformed accession never breaks a page: fall back to the company's filing list.
    assert sec_url(1000001, "test-1-2") == (
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1000001"
    )
