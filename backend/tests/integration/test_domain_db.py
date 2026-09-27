from datetime import date

from sqlalchemy import text

from signals.domain.appstate import get_state, set_state
from signals.domain.feed import FeedItemIn, summarize_trade, upsert_feed_item
from signals.domain.tickers import (
    canonical_symbol,
    current_symbol,
    issuer_for_symbol,
    rebuild_tickers,
    record_ticker_evidence,
    resolve_symbol,
)
from tests.factories import make_issuer


def test_canonical_symbol():
    assert canonical_symbol("brk-b") == "BRK.B"
    assert canonical_symbol("BRK/B") == "BRK.B"  # OpenFIGI uses a slash
    assert canonical_symbol(" aapl ") == "AAPL"
    assert canonical_symbol("NONE") is None and canonical_symbol("common stock") is None


def test_ticker_change_intervals(session):
    make_issuer(session, cik=1000002, name="Globex Inc", ticker="GBX", ticker_from=date(2016, 1, 5))
    record_ticker_evidence(session, 1000002, "GBX", date(2016, 1, 5), "form4")
    record_ticker_evidence(session, 1000002, "GLBX", date(2022, 6, 10), "form4")
    record_ticker_evidence(session, 1000002, "GBX", date(2021, 3, 1), "form4")  # out of order
    rebuild_tickers(session, [1000002])
    assert resolve_symbol(session, 1000002, date(2020, 1, 1)) == "GBX"
    assert resolve_symbol(session, 1000002, date(2023, 1, 1)) == "GLBX"
    assert current_symbol(session, 1000002) == "GLBX"
    assert issuer_for_symbol(session, "GBX", date(2020, 1, 1)) == 1000002


def test_reused_ticker_resolves_by_date(session):
    make_issuer(session, cik=1000003, name="Old Co", ticker="XYZ", ticker_from=date(2016, 1, 1))
    make_issuer(session, cik=1000004, name="New Co", ticker="NEWC", ticker_from=date(2016, 1, 1))
    record_ticker_evidence(session, 1000003, "XYZ", date(2016, 2, 1), "form4")
    record_ticker_evidence(session, 1000003, "XYZA", date(2019, 1, 1), "form4")
    record_ticker_evidence(session, 1000004, "XYZ", date(2020, 5, 1), "form4")
    rebuild_tickers(session, [1000003, 1000004])
    assert issuer_for_symbol(session, "XYZ", date(2017, 1, 1)) == 1000003
    assert issuer_for_symbol(session, "XYZ") == 1000004


def test_feed_upsert_and_state(session):
    item = FeedItemIn(accession_no="0002000001-24-000001", form_type="4", summary="x")
    upsert_feed_item(session, item)
    upsert_feed_item(session, FeedItemIn(**{**item.__dict__, "summary": "y"}))
    assert session.execute(text("select summary from feed_items")).scalars().all() == ["y"]
    set_state(session, "live_poll", {"ok": True})
    assert get_state(session, "live_poll") == {"ok": True}


def test_summarize_trade():
    assert summarize_trade("buy", 12000, 41.25, 495000) == "Bought 12,000 sh @ $41.25 ($495,000)"
    assert summarize_trade("sell", 5000, None, None) == "Sold 5,000 sh"
