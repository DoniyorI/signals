from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.schemas import JobRequestIn, JobRequestOut
from signals.db.models import JobRequest
from signals.jobs import load_all_jobs, request_job

router = APIRouter(prefix="/jobs", tags=["jobs"])
Db = Annotated[Session, Depends(get_db)]


def _job_request_out(row: JobRequest) -> JobRequestOut:
    return JobRequestOut(
        id=row.id,
        kind=row.kind,
        status=row.status,
        requested_at=row.requested_at,
        finished_at=row.finished_at,
        error=row.error,
    )


@router.get("", response_model=list[JobRequestOut])
def list_jobs(db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 20):
    rows = db.execute(
        select(JobRequest).order_by(JobRequest.requested_at.desc()).limit(limit)
    ).scalars()
    return [_job_request_out(r) for r in rows]


@router.post("", response_model=JobRequestOut, status_code=202)
def create_job(db: Db, body: JobRequestIn):
    if body.kind not in load_all_jobs():
        raise HTTPException(422, f"unknown job kind {body.kind!r}")
    job_id = request_job(db, body.kind, body.params)
    row = db.get(JobRequest, job_id)
    assert row is not None
    return _job_request_out(row)
