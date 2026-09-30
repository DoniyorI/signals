import pytest

from tests.api.seed import ACME, FUND, GLOBEX, NEWCO


def test_lookup_by_cik_and_ticker(api, world):
    by_cik = api.get(f"/api/companies/{ACME}").json()
    by_ticker = api.get("/api/companies/acme").json()
    assert by_cik["name"] == by_ticker["name"] == "Acme Corp"
    assert by_cik["ticker"] == by_ticker["ticker"] == "ACME"
    assert by_cik["cik"] == by_ticker["cik"] == ACME


def test_company_lookup_by_old_and_reused_ticker(api, world):
    old = api.get("/api/companies/GBX").json()
    assert old["cik"] == GLOBEX
    assert old["former_tickers"] == ["GBX"]
    assert old["ticker"] == "GLBX"

    reused = api.get("/api/companies/XYZ").json()
    assert reused["cik"] == NEWCO


def test_unknown_company_404(api, world):
    assert api.get("/api/companies/9999999").status_code == 404
    assert api.get("/api/companies/NOPE").status_code == 404


def test_prices_and_markers(api, world):
    body = api.get(f"/api/companies/{ACME}/prices").json()
    assert len(body["bars"]) == 19
    assert body["bars"] == sorted(body["bars"], key=lambda b: b["date"])
    kinds = {m["kind"] for m in body["markers"]}
    assert {"buy", "sell", "form144", "stake"} <= kinds


def test_institutions_latest_period(api, world):
    body = api.get(f"/api/companies/{ACME}/institutions").json()
    assert body["period"] == "2024-06-30"
    assert body["exit_count"] == 0
    fund_row = next(r for r in body["rows"] if r["fund"]["cik"] == FUND)
    assert fund_row["change"] == "ADD"


def test_net_buying_12m(api, world):
    body = api.get(f"/api/companies/{ACME}")
    net_12m = next(w for w in body.json()["net_buying"] if w["window"] == "12m")
    assert net_12m["buys_usd"] == pytest.approx(10_000.0 + 1_500_000.0 + 2_500_000.0)


def test_company_insiders_roster(api, world):
    roster = api.get(f"/api/companies/{ACME}/insiders").json()
    ciks = {row["owner"]["cik"] for row in roster}
    assert 2000001 in ciks  # Doe Jane, CEO of Acme


def test_stakes_current_only(api, world):
    all_stakes = api.get(f"/api/companies/{ACME}/stakes").json()
    current = api.get(f"/api/companies/{ACME}/stakes", params={"current_only": "true"}).json()
    assert len(all_stakes) == len(current) == 1
    assert all_stakes[0]["is_activist"] is True


def test_company_form144_filter(api, world):
    pending = api.get(f"/api/companies/{GLOBEX}/form144", params={"status": "pending"}).json()
    assert len(pending) == 1
    matched = api.get(f"/api/companies/{ACME}/form144", params={"status": "matched"}).json()
    assert len(matched) == 1
