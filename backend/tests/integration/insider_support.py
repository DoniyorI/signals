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


def atom_entry(
    *,
    title: str,
    term: str,
    accession: str,
    cik: int,
    updated: str = "2026-01-02T09:00:00-05:00",
) -> str:
    """One synthetic Atom `<entry>` shaped like SEC's getcurrent feed."""
    nodash = accession.replace("-", "")
    href = f"https://www.sec.gov/Archives/edgar/data/{cik}/{nodash}/{accession}-index.htm"
    return f"""<entry>
<title>{title}</title>
<link rel="alternate" type="text/html" href="{href}"/>
<summary type="html">Filed: 2026-01-02 AccNo: {accession}</summary>
<updated>{updated}</updated>
<category scheme="https://www.sec.gov/" label="form type" term="{term}"/>
<id>urn:tag:sec.gov,2008:accession-number={accession}</id>
</entry>"""


def atom_feed(entries: list[str]) -> bytes:
    body = "\n".join(entries)
    return f"""<?xml version="1.0" encoding="ISO-8859-1" ?>
<feed xmlns="http://www.w3.org/2005/Atom">
<title>Latest Filings</title>
<updated>2026-01-02T09:00:00-05:00</updated>
{body}
</feed>""".encode()


def idx_line(*, form_type: str, company: str, cik: int, date_filed: str, accession: str) -> str:
    """One data row of a form.idx file. `date_filed` is YYYYMMDD (daily) or YYYY-MM-DD (full)."""
    filename = f"edgar/data/{cik}/{accession}.txt"
    return f"{form_type}  {company}    {cik}    {date_filed}    {filename}"


def idx_text(lines: list[str]) -> str:
    """A full form.idx body: the wrapped daily-index header, the dashed rule, then rows."""
    header = (
        "Description:           Daily Index of EDGAR Dissemination Feed by Form Type\n"
        "Form Type   Company Name                                                  CIK\n"
        "      Date Filed  File Name\n"
        "---------------------------------------------------------------------------------------------------------------------------------------------\n"
    )
    return header + "\n".join(lines) + "\n"
