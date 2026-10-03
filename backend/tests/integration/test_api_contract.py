import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from signals.api.deps import get_db
from signals.api.main import create_app
from signals.cli import app as cli_app
from signals.prices.base import BAR_COLUMNS, get_bars
from tests.factories import make_prices

PATHS = {
    "/api/feed", "/api/feed/summary", "/api/insiders/{cik}", "/api/insiders/{cik}/decisions",
    "/api/insiders/{cik}/transactions", "/api/insiders/{cik}/performance",
    "/api/insiders/{cik}/holdings", "/api/insiders/{cik}/form144", "/api/companies/{ref}",
    "/api/companies/{cik}/prices", "/api/companies/{cik}/insiders",
    "/api/companies/{cik}/institutions", "/api/companies/{cik}/stakes",
    "/api/companies/{cik}/form144", "/api/funds/{cik}", "/api/funds/{cik}/holdings",
    "/api/funds/{cik}/performance", "/api/screener/insiders", "/api/screener/funds",
    "/api/compare", "/api/search", "/api/watchlists", "/api/watchlists/{watchlist_id}",
    "/api/watchlists/{watchlist_id}/items", "/api/watchlists/{watchlist_id}/items/{kind}/{cik}",
    "/api/watchlists/{watchlist_id}/activity", "/api/health", "/api/health/completeness",
    "/api/jobs", "/api/jobs/{job_id}",
}  # fmt: skip


@pytest.fixture
def client(session):
    app = create_app()

    def _db():
        yield session

    app.dependency_overrides[get_db] = _db
    return TestClient(app)


def test_openapi_has_every_path(client):
    assert set(client.get("/api/openapi.json").json()["paths"]) == PATHS


def test_stub_returns_501():
    # Not /api/feed: workstream E implements it, so it's no longer a stub. A throwaway
    # route still exercises main.py's NotImplementedError -> 501 handler directly.
    app = create_app()

    @app.get("/api/_test_stub")
    def _stub():
        raise NotImplementedError

    r = TestClient(app).get("/api/_test_stub")
    assert r.status_code == 501 and r.json() == {"detail": "not implemented"}


def test_health_warns_before_first_scheduled_updates(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["status"] == "warn"
    assert r.json()["catch_up"]["status"] == "idle"
    assert "prices_daily" in r.json()["catch_up"]["behind"]


def test_get_bars_sorted(session):
    make_prices(session, "ACME", date(2024, 1, 2), [10, 11])
    make_prices(session, "AAA", date(2024, 1, 2), [5])
    df = get_bars(session, ["ACME", "AAA"], date(2024, 1, 1), date(2024, 1, 31))
    assert list(df.columns) == list(BAR_COLUMNS)
    assert list(df["symbol"]) == ["AAA", "ACME", "ACME"]


def test_openapi_cli_writes_contract(tmp_path, monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "Signals Test test@example.com")
    out = tmp_path / "openapi.json"
    result = CliRunner().invoke(cli_app, ["openapi", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert set(json.loads(out.read_text())["paths"]) == PATHS
