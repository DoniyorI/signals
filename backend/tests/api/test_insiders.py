import pytest

from tests.api.seed import (
    A_DOE_144,
    A_DOE_BUY,
    A_DOE_OLD,
    A_DOE_OLD_AMEND,
    A_DOE_SELL,
    A_ROE_144,
    ACME,
    DOE,
    NEWBIE,
    ROE,
)


def test_header_with_stats(api, world):
    body = api.get(f"/api/insiders/{DOE}", params={"basis": "filed"}).json()
    assert body["rating"] == {"score": 80, "confidence": "low", "n": 1}
    assert "CEO" in body["roles"][0]["roles"]


def test_insider_header_without_stats(api, world):
    r = api.get(f"/api/insiders/{NEWBIE}")
    assert r.status_code == 200
    body = r.json()
    assert body["rating"] == {"score": None, "confidence": None, "n": 0}
    assert body["avg_roi_6m"] is None
    assert body["n_decisions"] == 1


def test_unknown_insider_404(api):
    assert api.get("/api/insiders/9999999").status_code == 404


def test_decisions_basis_and_toggle(api, world):
    default = api.get(f"/api/insiders/{DOE}/decisions").json()["items"]
    assert {d["first_accession"] for d in default} == {A_DOE_BUY, A_DOE_OLD_AMEND}

    toggled = api.get(f"/api/insiders/{DOE}/decisions", params={"include_10b5_1": "true"}).json()[
        "items"
    ]
    assert {d["first_accession"] for d in toggled} == {A_DOE_BUY, A_DOE_OLD_AMEND, A_DOE_SELL}

    d0_filed = next(d for d in default if d["first_accession"] == A_DOE_OLD_AMEND)
    r6_filed = next(r for r in d0_filed["returns"] if r["horizon"] == "6m")
    executed = api.get(f"/api/insiders/{DOE}/decisions", params={"basis": "executed"}).json()
    d0_executed = next(d for d in executed["items"] if d["first_accession"] == A_DOE_OLD_AMEND)
    r6_executed = next(r for r in d0_executed["returns"] if r["horizon"] == "6m")
    assert r6_filed["raw"] == pytest.approx(0.15)
    assert r6_executed["raw"] == pytest.approx(0.17)
    assert r6_filed["raw"] != r6_executed["raw"]


def test_transactions_superseded_hidden(api, world):
    default = {
        t["accession_no"] for t in api.get(f"/api/insiders/{DOE}/transactions").json()["items"]
    }
    assert default == {A_DOE_OLD_AMEND, A_DOE_SELL, A_DOE_BUY}

    full = {
        t["accession_no"]
        for t in api.get(
            f"/api/insiders/{DOE}/transactions", params={"include_superseded": "true"}
        ).json()["items"]
    }
    assert full == {A_DOE_OLD, A_DOE_OLD_AMEND, A_DOE_SELL, A_DOE_BUY}


def test_performance_uses_curve_service(api, world):
    perf = api.get(f"/api/insiders/{DOE}/performance").json()
    assert perf["points"][-1]["nav"] == 1.10
    assert [w["window"] for w in perf["windows"]] == ["ytd", "1y", "3y", "5y"]
    assert perf["windows"][0]["ret"] == pytest.approx(0.1)
    assert perf["windows"][1]["ret"] == pytest.approx(0.2)
    assert perf["windows"][2]["ret"] is None
    assert perf["windows"][3]["ret"] is None
    assert perf["coverage_pct"] is None


def test_holdings_values(api, world):
    holdings = api.get(f"/api/insiders/{DOE}/holdings").json()
    acme_row = next(p for p in holdings["positions"] if p["issuer"]["cik"] == ACME)
    assert acme_row["value_usd"] == pytest.approx(110000.0)
    assert holdings["effective_n"] == pytest.approx(1.0)


def test_form144_status(api, world):
    doe_notices = api.get(f"/api/insiders/{DOE}/form144").json()
    matched = next(n for n in doe_notices if n["accession_no"] == A_DOE_144)
    assert matched["status"] == "matched"

    roe_notices = api.get(f"/api/insiders/{ROE}/form144").json()
    pending = next(n for n in roe_notices if n["accession_no"] == A_ROE_144)
    assert pending["status"] == "pending"
