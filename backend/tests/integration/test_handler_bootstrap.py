"""Production startup and CLI reparse initialize the real handlers."""

import subprocess
import sys

import pytest
from typer.testing import CliRunner

from signals import cli
from signals.db.models import FundFiling, InsiderTransaction
from signals.ingest import dispatch
from signals.ingest.pipeline import ingest_raw
from signals.jobs import load_all_jobs


def test_fresh_worker_bootstrap_registers_all_tracked_forms():
    code = """
from signals.jobs import load_all_jobs
from signals.ingest.dispatch import registered_forms
from signals.domain.types import TRACKED_FORMS
load_all_jobs()
assert registered_forms() == TRACKED_FORMS, registered_forms()
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "key,model", [("form4_buy_single", InsiderTransaction), ("f13f_small", FundFiling)]
)
def test_bootstrap_dispatches_recorded_filing(
    session, settings, tmp_archive, fixture_bytes, key, model
):
    dispatch.reset_registry()
    load_all_jobs()
    try:
        outcome = ingest_raw(
            session,
            fixture_bytes(key),
            source="test",
            raw_path=None,
            first_seen_at=None,
            settings=settings,
            archive=tmp_archive,
        )
        assert outcome.status == "parsed", outcome.error
        assert session.query(model).filter_by(accession_no=outcome.accession_no).count() > 0
    finally:
        dispatch.reset_registry()


def test_cli_reparse_initializes_handlers(
    session, session_factory, settings, tmp_archive, fixture_bytes, manifest, monkeypatch
):
    accession = manifest["form4_buy_single"]["accession"]
    tmp_archive.put("filing", accession, fixture_bytes("form4_buy_single"))
    dispatch.reset_registry()
    monkeypatch.setattr(
        cli,
        "get_settings",
        lambda: settings.model_copy(update={"raw_archive_dir": tmp_archive.root}),
    )
    monkeypatch.setattr(cli, "_session_factory", lambda: session_factory)
    try:
        result = CliRunner().invoke(cli.app, ["reparse", "--accession", accession])
        assert result.exit_code == 0, result.output
        assert f"{accession}\tparsed" in result.output
        assert session.query(InsiderTransaction).filter_by(accession_no=accession).count() > 0
    finally:
        dispatch.reset_registry()
