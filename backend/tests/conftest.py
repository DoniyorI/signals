"""Shared fixtures.

Each pytest session gets its own throwaway Postgres database (signals_test_<random>),
migrated with Alembic, so parallel worktrees never collide. Every test runs inside a
transaction that is rolled back; code under test may commit (it commits a savepoint).
"""

import json
import os
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import Session

from signals.config import Settings
from signals.db.session import make_engine
from tests.support import MockRouter

__all__ = ["FIXTURES_DIR", "MockRouter", "fixture_path"]

BACKEND_DIR = Path(__file__).resolve().parents[1]
FIXTURES_DIR = Path(__file__).parent / "fixtures"
ADMIN_URL = os.environ.get(
    "SIGNALS_TEST_ADMIN_URL", "postgresql+psycopg://signals:signals@127.0.0.1:5432/postgres"
)


def fixture_path(rel: str) -> Path:
    """Path of a recorded SEC/vendor fixture, relative to tests/fixtures/sec/."""
    return FIXTURES_DIR / "sec" / rel


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    name = f"signals_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = ADMIN_URL.rsplit("/", 1)[0] + f"/{name}"
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")
    try:
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def db_engine(db_url: str) -> Iterator[Engine]:
    engine = make_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def connection(db_engine: Engine) -> Iterator[Connection]:
    conn = db_engine.connect()
    trans = conn.begin()
    try:
        yield conn
    finally:
        trans.rollback()
        conn.close()


def _bound_session(connection: Connection) -> Session:
    return Session(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )


@pytest.fixture
def session(connection: Connection) -> Iterator[Session]:
    s = _bound_session(connection)
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def session_factory(connection: Connection) -> Callable[[], Session]:
    return lambda: _bound_session(connection)


@pytest.fixture
def settings(db_url: str, tmp_path: Path) -> Settings:
    return Settings(
        sec_user_agent="Signals Test test@example.com",
        database_url=db_url,
        raw_archive_dir=tmp_path / "raw",
        _env_file=None,  # pyright: ignore[reportCallIssue]
    )


@pytest.fixture
def tmp_archive(tmp_path: Path):
    from signals.sec.archive import RawArchive  # pyright: ignore[reportMissingImports]  # Task 6

    return RawArchive(tmp_path / "archive")


@pytest.fixture(scope="session")
def manifest() -> dict:
    path = FIXTURES_DIR / "sec" / "MANIFEST.json"
    return json.loads(path.read_text()) if path.exists() else {}


@pytest.fixture
def fixture_bytes(manifest: dict) -> Callable[[str], bytes]:
    def _read(key: str) -> bytes:
        return fixture_path(manifest[key]["file"]).read_bytes()

    return _read
