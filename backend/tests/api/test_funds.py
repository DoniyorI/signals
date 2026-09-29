from tests.api.seed import CUSIP_ACME, FUND, SMALL_FUND


def test_fund_header(api, world):
    body = api.get(f"/api/funds/{FUND}").json()
    assert len(body["value_history"]) == 2
    assert body["latest_positions"] == 2
    assert body["rating"]["score"] == 65
    assert body["rating"]["confidence"] == "medium"


def test_fund_holdings_rows_and_exits(api, world):
    body = api.get(f"/api/funds/{FUND}/holdings").json()
    assert body["period"] == "2024-06-30"
    assert len(body["rows"]) == 2
    assert len(body["exits"]) == 1
    acme_row = next(r for r in body["rows"] if r["security"]["cusip"] == CUSIP_ACME)
    assert acme_row["high_conviction"] is True
    assert acme_row["change"] == "ADD"


def test_fund_performance_404_untracked(api, world):
    r = api.get(f"/api/funds/{SMALL_FUND}/performance")
    assert r.status_code == 404
    assert r.json()["detail"] == "performance is available for tracked funds only"


def test_unknown_fund_404(api, world):
    assert api.get("/api/funds/9999998").status_code == 404
    assert api.get("/api/funds/9999998/holdings").status_code == 404
    assert api.get("/api/funds/9999998/performance").status_code == 404
