"""Test helpers shared by workstream A's integration tests (not a conftest: import explicitly)."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from signals.db.models import Filing
from signals.domain.types import INSIDER_FORMS
from signals.ingest import dispatch
from signals.ingest.normalize_insider import normalize_ownership
from signals.ingest.parsers.ownership import parse_ownership
from signals.ingest.pipeline import ingest_raw
from signals.sec.sgml import SgmlFiling


def ownership_handler(session, sgml, filing, ctx) -> None:
    xml = next(d.xml() for d in sgml.xml_documents())
    assert xml is not None
    normalize_ownership(session, filing, parse_ownership(xml))


def register_ownership_handler() -> None:
    dispatch.reset_registry()
    dispatch.register_handler(INSIDER_FORMS, ownership_handler)


Loader = Callable[..., str]


def make_loader(fixture_bytes, settings, archive) -> Loader:
    """`load(session, key, force=False)`: ingest a recorded filing through ingest_raw,
    skipping it when it is already parsed unless forced. Returns the accession."""

    def load(session: Session, key: str, force: bool = False) -> str:
        raw = fixture_bytes(key)
        acc = SgmlFiling.from_txt(raw).accession_no
        existing = session.get(Filing, acc)
        if existing is not None and existing.parse_status == "parsed" and not force:
            return acc
        out = ingest_raw(
            session,
            raw,
            source="test",
            raw_path=None,
            first_seen_at=None,
            settings=settings,
            archive=archive,
        )
        assert out.status == "parsed", out.error
        return out.accession_no

    return load


def form144_handler(session, sgml, filing, ctx) -> None:
    from signals.ingest.normalize_form144 import normalize_form144
    from signals.ingest.parsers.form144 import parse_form144

    xml = next(d.xml() for d in sgml.xml_documents())
    assert xml is not None
    normalize_form144(session, filing, parse_form144(xml), sgml)


def register_form144_handler() -> None:
    from signals.domain.types import FORM144_FORMS

    dispatch.register_handler(FORM144_FORMS, form144_handler)
