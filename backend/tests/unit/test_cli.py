from sqlalchemy import create_engine, delete
from typer.testing import CliRunner

from signals.cli import app
from signals.config import get_settings
from signals.db.models import JobRequest
from signals.jobs import JOBS, register_job


def test_cli_jobs_request_and_list(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("SEC_USER_AGENT", "Signals Test test@example.com")
    get_settings.cache_clear()
    register_job("cli_demo")(lambda ctx: None)
    runner = CliRunner()
    try:
        made = runner.invoke(app, ["jobs", "request", "cli_demo", "--params", '{"x": [1]}'])
        assert made.exit_code == 0, made.output
        listed = runner.invoke(app, ["jobs", "list", "--limit", "5"])
        assert (
            listed.exit_code == 0 and "cli_demo" in listed.output and "requested" in listed.output
        )
        unknown = runner.invoke(app, ["jobs", "request", "no_such_job"])
        assert unknown.exit_code != 0
    finally:
        JOBS.pop("cli_demo", None)
        engine = create_engine(db_url)
        with engine.begin() as conn:
            conn.execute(delete(JobRequest).where(JobRequest.kind == "cli_demo"))
        engine.dispose()
        get_settings.cache_clear()
