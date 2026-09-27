from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from signals.api.deps import get_db
from signals.api.schemas import JobRequestIn, JobRequestOut

router = APIRouter(prefix="/jobs", tags=["jobs"])
Db = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[JobRequestOut])
def list_jobs(db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 20):
    raise NotImplementedError


@router.post("", response_model=JobRequestOut, status_code=202)
def create_job(db: Db, body: JobRequestIn):
    raise NotImplementedError
