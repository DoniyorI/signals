import pytest

from tests.api.seed import ACME, DOE, FUND


def test_search_by_ticker(api, world):
    body = api.get("/api/search", params={"q": "acme"}).json()
    assert body["companies"][0]["cik"] == ACME
    assert body["companies"][0]["score"] == 1.0


def test_search_partial_name(api, world):
    body = api.get("/api/search", params={"q": "doe"}).json()
    assert DOE in {h["cik"] for h in body["insiders"]}


def test_search_by_cik(api, world):
    body = api.get("/api/search", params={"q": "3000001"}).json()
    assert body["funds"][0]["cik"] == FUND


def test_search_too_short(api):
    assert api.get("/api/search", params={"q": "a"}).status_code == 422


def test_compare_two(api, world):
    body = api.get("/api/compare", params={"ids": f"insider:{DOE},fund:{FUND}"}).json()
    assert len(body["profiles"]) == 2
    assert {p["id"] for p in body["profiles"]} == {f"insider:{DOE}", f"fund:{FUND}"}
    for profile in body["profiles"]:
        assert profile["curve"][0]["nav"] == pytest.approx(1.0)


def test_compare_invalid(api):
    assert api.get("/api/compare", params={"ids": "bogus:1"}).status_code == 400
    five = ",".join(f"insider:{cik}" for cik in range(5))
    assert api.get("/api/compare", params={"ids": five}).status_code == 400
