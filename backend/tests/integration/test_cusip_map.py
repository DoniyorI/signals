import json
from datetime import date

import httpx

from signals.db.models import FundPosition, Security
from signals.reference.cusip import (
    FigiMatch,
    MapResult,
    OpenFigiClient,
    choose_listing,
    map_securities,
    name_match_issuer,
)
from tests.factories import make_fund_filing, make_issuer
from tests.support import MockRouter

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"


def _seed_position(session, *, accession_no: str, cusip: str, name_of_issuer: str) -> None:
    session.add(
        FundPosition(
            period=date(2024, 3, 31),
            accession_no=accession_no,
            cusip=cusip,
            put_call="",
            filer_cik=3000001,
            name_of_issuer=name_of_issuer,
            shares=100.0,
            sh_prn="SH",
            value_usd=1000.0,
            is_effective=True,
        )
    )
    session.flush()


def test_openfigi_fixture(fixture_bytes):
    router = MockRouter({OPENFIGI_URL: fixture_bytes("openfigi_sample")})
    client = OpenFigiClient(router.client, api_key=None)
    result = client.map_cusips(["037833100", "084670702", "000000000"])
    assert result["037833100"] is not None and result["037833100"].ticker == "AAPL"
    assert result["000000000"] is None
    # A single batch of 3 (well under the without-key batch size of 10) is one POST.
    assert len(router.requests) == 1
    sent = json.loads(router.requests[0].content)
    assert sent == [
        {"idType": "ID_CUSIP", "idValue": "037833100", "exchCode": "US"},
        {"idType": "ID_CUSIP", "idValue": "084670702", "exchCode": "US"},
        {"idType": "ID_CUSIP", "idValue": "000000000", "exchCode": "US"},
    ]
    assert "X-OPENFIGI-APIKEY" not in router.requests[0].headers


def test_batches_without_key(fake_clock):
    def echo(request: httpx.Request) -> httpx.Response:
        jobs = json.loads(request.content)
        return httpx.Response(200, json=[{"warning": "unused"} for _ in jobs])

    router = MockRouter({OPENFIGI_URL: echo})
    client = OpenFigiClient(
        router.client, api_key=None, sleep=fake_clock.sleep, clock=fake_clock.monotonic
    )
    cusips = [f"{i:09d}" for i in range(25)]
    client.map_cusips(cusips)
    assert len(router.requests) == 3
    assert [len(json.loads(r.content)) for r in router.requests] == [10, 10, 5]
    assert len(fake_clock.slept) == 2
    assert all(s >= 2.4 for s in fake_clock.slept)


def test_429_retry(fake_clock):
    calls = []

    def flaky(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"ratelimit-reset": "7"}, content=b"")
        return httpx.Response(
            200,
            json=[
                {
                    "data": [
                        {"figi": "F1", "ticker": "AAPL", "exchCode": "US", "marketSector": "Equity"}
                    ]
                }
            ],
        )

    router = MockRouter({OPENFIGI_URL: flaky})
    client = OpenFigiClient(
        router.client, api_key="k", sleep=fake_clock.sleep, clock=fake_clock.monotonic
    )
    result = client.map_cusips(["037833100"])
    assert len(calls) == 2
    assert fake_clock.slept == [7.0]
    assert result["037833100"] is not None and result["037833100"].ticker == "AAPL"


def test_choose_listing_prefers_equity_us():
    candidates = [
        {"marketSector": "Muni", "exchCode": "US", "ticker": "X", "figi": "F1"},
        {"marketSector": "Equity", "exchCode": "CA", "ticker": "Y", "figi": "F2"},
        {"marketSector": "Equity", "exchCode": "US", "ticker": "Z", "figi": "F3", "name": "Z Inc"},
    ]
    chosen = choose_listing(candidates)
    assert chosen == FigiMatch(
        ticker="Z",
        exch_code="US",
        figi="F3",
        security_type=None,
        name="Z Inc",
        market_sector="Equity",
    )


def test_choose_listing_falls_back_when_nothing_matches_both():
    candidates = [{"marketSector": "Muni", "exchCode": "CA", "ticker": "X", "figi": "F1"}]
    assert choose_listing(candidates) is not None
    assert choose_listing([]) is None


def test_name_match(session):
    make_issuer(session)  # cik=1000001, name="Acme Corp"
    assert name_match_issuer(session, "ACME CORP COM") == 1000001
    assert name_match_issuer(session, "ACMEX LTD") is None


def test_map_securities_end_to_end(session):
    make_issuer(session)  # cik=1000001, name="Acme Corp"
    filing = make_fund_filing(session)
    _seed_position(
        session, accession_no=filing.accession_no, cusip="037833100", name_of_issuer="APPLE INC"
    )
    _seed_position(
        session, accession_no=filing.accession_no, cusip="000000BB2", name_of_issuer="ACME CORP COM"
    )

    responses = {
        "037833100": {
            "data": [
                {
                    "figi": "BBG000B9XRY4",
                    "name": "APPLE INC",
                    "ticker": "AAPL",
                    "exchCode": "US",
                    "marketSector": "Equity",
                    "securityType": "Common Stock",
                }
            ]
        },
        "000000BB2": {"warning": "No identifier found."},
    }

    def respond(request: httpx.Request) -> httpx.Response:
        jobs = json.loads(request.content)
        assert {j["idValue"] for j in jobs} == set(responses)
        return httpx.Response(200, json=[responses[j["idValue"]] for j in jobs])

    router = MockRouter({OPENFIGI_URL: respond})
    figi = OpenFigiClient(router.client, api_key=None)
    result = map_securities(session, figi)
    assert result == MapResult(requested=2, mapped_openfigi=1, mapped_name=1, unresolved=0)

    apple = session.get(Security, "037833100")
    assert apple is not None
    assert (apple.ticker, apple.map_source, apple.map_status) == ("AAPL", "openfigi", "mapped")

    acme = session.get(Security, "000000BB2")
    assert acme is not None
    assert (acme.issuer_cik, acme.map_source, acme.map_status) == (1000001, "name_match", "mapped")


def test_map_securities_unresolved(session):
    filing = make_fund_filing(session)
    _seed_position(
        session,
        accession_no=filing.accession_no,
        cusip="000000CC3",
        name_of_issuer="TOTALLY UNKNOWN ENTITY XYZ",
    )
    router = MockRouter(
        {OPENFIGI_URL: lambda r: httpx.Response(200, json=[{"warning": "no match"}])}
    )
    figi = OpenFigiClient(router.client, api_key=None)
    result = map_securities(session, figi)
    assert result == MapResult(requested=1, mapped_openfigi=0, mapped_name=0, unresolved=1)
    sec = session.get(Security, "000000CC3")
    assert sec is not None and (sec.map_source, sec.map_status) == ("none", "unresolved")


def test_map_securities_skips_already_mapped(session):
    filing = make_fund_filing(session)
    _seed_position(
        session, accession_no=filing.accession_no, cusip="037833100", name_of_issuer="APPLE INC"
    )
    session.add(
        Security(cusip="037833100", ticker="AAPL", map_source="openfigi", map_status="mapped")
    )
    session.flush()

    def boom(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should not call OpenFIGI for an already-mapped security")

    router = MockRouter({OPENFIGI_URL: boom})
    figi = OpenFigiClient(router.client, api_key=None)
    result = map_securities(session, figi)
    assert result == MapResult(requested=0, mapped_openfigi=0, mapped_name=0, unresolved=0)
