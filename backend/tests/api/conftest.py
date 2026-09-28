"""Fixtures for API tests: a TestClient bound to the test session, and the seed world."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from signals.api.deps import get_curve_service, get_db
from signals.api.main import create_app
from signals.api.queries import common
from tests.api.seed import FROZEN_NOW, FakeCurves, SeedIds, seed_world


@pytest.fixture
def api(session: Session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The API over the test session, with the clock frozen at FROZEN_NOW and fake curves."""
    monkeypatch.setattr(common, "now_et", lambda: FROZEN_NOW)
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_curve_service] = FakeCurves
    return TestClient(app)


@pytest.fixture
def world(session: Session) -> SeedIds:
    return seed_world(session)
