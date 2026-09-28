"""Current tickers (company_tickers_exchange.json) and shares outstanding (XBRL frames)."""

import json
from datetime import date

from sqlalchemy import select

from signals.db.models import Issuer, TickerEvidence
from signals.domain.tickers import canonical_symbol, current_symbol
from signals.reference.companies import load_company_tickers_exchange
from signals.reference.shares import frames_url, load_shares_frames
from tests.factories import make_issuer

SEEN = date(2026, 9, 27)


def test_company_tickers_records_evidence(session, fixture_bytes, manifest):
    exp = manifest["company_tickers_exchange"]["expect"]
    n = load_company_tickers_exchange(
        session, fixture_bytes("company_tickers_exchange"), seen_on=SEEN
    )
    assert n == exp["n_entries"]
    cik, _name, ticker, _exchange = exp["fixture_issuer_rows"][0]
    assert current_symbol(session, cik) == canonical_symbol(ticker)


def test_company_tickers_current_symbol_is_the_first_listed_class(session, fixture_bytes):
    load_company_tickers_exchange(session, fixture_bytes("company_tickers_exchange"), seen_on=SEEN)
    # CNB Financial lists its common (CCNE) before its preferred (CCNEP).
    assert current_symbol(session, 736772) == "CCNE"
    evidence = session.scalars(select(TickerEvidence).where(TickerEvidence.issuer_cik == 736772))
    assert [(e.symbol, e.min_seen, e.sources) for e in evidence] == [
        ("CCNE", SEEN, ["company_tickers"])
    ]
    assert current_symbol(session, 1067983) == "BRK.B"  # listed as BRK-B
    issuer = session.get(Issuer, 1509261)
    assert issuer is not None and (issuer.name, issuer.exchange) == ("Rezolute, Inc.", "Nasdaq")


def test_company_tickers_keeps_existing_name_and_updates_exchange(session, fixture_bytes):
    make_issuer(session, cik=1509261, name="REZOLUTE INC (from filings)", ticker=None)
    load_company_tickers_exchange(session, fixture_bytes("company_tickers_exchange"), seen_on=SEEN)
    issuer = session.get(Issuer, 1509261)
    assert issuer is not None
    assert (issuer.name, issuer.exchange) == ("REZOLUTE INC (from filings)", "Nasdaq")
    assert current_symbol(session, 1509261) == "RZLT"


def test_frames_update_and_no_downgrade(session, fixture_bytes, manifest):
    sample = manifest["frames_sample"]["expect"]["sample"]
    make_issuer(session, cik=sample["cik"], name="AAR CORP", ticker="AIR")
    assert load_shares_frames(session, fixture_bytes("frames_sample")) == 1
    issuer = session.get(Issuer, sample["cik"])
    assert issuer is not None
    assert issuer.shares_outstanding == sample["val"]
    assert issuer.shares_outstanding_as_of == date.fromisoformat(sample["end"])

    older = {
        "ccp": "CY2025Q4I",
        "data": [{"cik": sample["cik"], "val": 1234, "end": "2025-12-31", "accn": "x"}],
    }
    assert load_shares_frames(session, json.dumps(older).encode()) == 0
    assert load_shares_frames(session, fixture_bytes("frames_sample")) == 0  # same as_of
    assert issuer.shares_outstanding == sample["val"]

    newer = {"data": [{"cik": sample["cik"], "val": 40_000_000, "end": "2026-09-30"}]}
    assert load_shares_frames(session, json.dumps(newer).encode()) == 1
    assert (issuer.shares_outstanding, issuer.shares_outstanding_as_of) == (
        40_000_000,
        date(2026, 9, 30),
    )


def test_frames_url():
    assert frames_url(2024, 2).endswith("/CY2024Q2I.json")
    assert frames_url(2016, 1) == (
        "https://data.sec.gov/api/xbrl/frames/dei/EntityCommonStockSharesOutstanding/"
        "shares/CY2016Q1I.json"
    )
