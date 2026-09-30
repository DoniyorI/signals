"""`signals` command-line tool."""

import json
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import select

from signals.config import get_settings
from signals.db.models import JobRequest
from signals.db.session import make_engine, make_session_factory, session_scope
from signals.jobs import JOBS, load_all_jobs, request_job

app = typer.Typer(add_completion=False, no_args_is_help=True, help="SEC insider dashboard")
jobs_app = typer.Typer(no_args_is_help=True, help="Request and inspect worker jobs")
app.add_typer(jobs_app, name="jobs")

BACKEND_DIR = Path(__file__).resolve().parents[2]


def _session_factory():
    return make_session_factory(make_engine(get_settings().database_url))


@app.command()
def migrate() -> None:
    """Apply database migrations (alembic upgrade head)."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


@app.command()
def worker() -> None:
    """Run the scheduler and job worker (the only process that calls SEC)."""
    from signals.worker import main

    main()


@app.command()
def api(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Serve the read-only API."""
    import uvicorn

    uvicorn.run("signals.api.main:app", host=host, port=port)


@jobs_app.command("request")
def jobs_request(
    kind: str,
    params: Annotated[str, typer.Option(help="JSON object of job parameters")] = "{}",
) -> None:
    load_all_jobs()
    if kind not in JOBS:
        typer.echo(f"unknown job kind: {kind} (known: {', '.join(sorted(JOBS))})", err=True)
        raise typer.Exit(code=2)
    with session_scope(_session_factory()) as s:
        rid = request_job(s, kind, json.loads(params))
    typer.echo(f"{rid}\t{kind}\trequested")


@jobs_app.command("list")
def jobs_list(limit: int = 20) -> None:
    with session_scope(_session_factory()) as s:
        rows = s.scalars(select(JobRequest).order_by(JobRequest.id.desc()).limit(limit)).all()
        for r in rows:
            finished = r.finished_at.isoformat() if r.finished_at else "-"
            typer.echo(f"{r.id}\t{r.kind}\t{r.status}\t{r.requested_at.isoformat()}\t{finished}")


@app.command()
def reparse(
    status: Annotated[str | None, typer.Option(help="Reparse filings with this status")] = None,
    accession: Annotated[str | None, typer.Option(help="Reparse one accession")] = None,
) -> None:
    """Re-run parsers from the raw archive (no network)."""
    from signals.ingest.pipeline import reparse_accession
    from signals.sec.archive import RawArchive

    load_all_jobs()
    settings = get_settings()
    archive = RawArchive(settings.raw_archive_dir)
    factory = _session_factory()
    targets = [accession] if accession else []
    if not targets and status:
        from signals.db.models import Filing

        with session_scope(factory) as s:
            targets = list(
                s.scalars(select(Filing.accession_no).where(Filing.parse_status == status))
            )
    for acc in targets:
        with session_scope(factory) as s:
            out = reparse_accession(s, acc, settings=settings, archive=archive)
        typer.echo(f"{out.accession_no}\t{out.status}\t{out.error or ''}")


@app.command()
def openapi(out: Annotated[Path, typer.Option(help="Where to write openapi.json")]) -> None:
    """Write the API contract (OpenAPI JSON) used to generate the frontend types."""
    from signals.api.main import create_app

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n")
    typer.echo(f"wrote {out}")
