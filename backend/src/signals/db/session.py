"""Engine and session helpers. Callers own their transactions."""

import random
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from signals.logging import get_logger

log = get_logger(__name__)


def run_transaction[T](factory: Callable[[], Session], operation: Callable[[Session], T]) -> T:
    """Retry a replayable transaction after a PostgreSQL concurrency abort.

    Retry the whole unit, including COMMIT, with a fresh session after rollback/close.
    Callers keep external side effects (downloads/checkpoints) outside this unit.
    """
    for attempt in range(4):
        try:
            with session_scope(factory) as session:
                result = operation(session)
            return result
        except DBAPIError as exc:
            sqlstate = getattr(exc.orig, "sqlstate", None)
            if sqlstate not in {"40P01", "40001"} or attempt == 3:
                raise
            delay = 0.25 * 2**attempt + random.uniform(0, 0.1)
            log.warning("transaction_retry", sqlstate=sqlstate, retry=attempt + 1, delay_s=delay)
            time.sleep(delay)
    raise AssertionError("unreachable")


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(factory: Callable[[], Session]) -> Generator[Session]:
    """Commit on success, roll back on error, always close."""
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
