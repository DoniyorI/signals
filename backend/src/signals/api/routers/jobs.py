from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.schemas import JobRequestIn, JobRequestOut
from signals.db.models import JobRequest, Owner
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
        progress=row.progress,
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
    if body.kind == "refresh_insider_performance":
        owner = body.params.get("owner_cik")
        if type(owner) is not int or owner <= 0 or set(body.params) != {"owner_cik"}:
            raise HTTPException(422, "owner_cik must be a positive integer")
        if db.get(Owner, owner) is None:
            raise HTTPException(404, "insider not found")
    job_id = request_job(db, body.kind, body.params)
    row = db.get(JobRequest, job_id)
    assert row is not None
    return _job_request_out(row)


@router.get("/{job_id}", response_model=JobRequestOut)
def get_job(db: Db, job_id: int):
    row = db.get(JobRequest, job_id)
    if row is None:
        raise HTTPException(404, "job not found")
    return _job_request_out(row)
