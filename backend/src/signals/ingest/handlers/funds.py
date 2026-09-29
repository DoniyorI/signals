"""Handlers for 13F and Schedules 13D/13G. Owned by workstream B (03-fund-stake-ingestion.md).

Both parsers work on bytes, so each XML document in the filing is identified by its own root
element (namespace already stripped by `parse_xml`) rather than the SGML header's free-text
`TYPE` field: `edgarSubmission` is always the 13F primary document (cover) and `informationTable`
is always the holdings table. A 13F-NT has no information table.
"""

from sqlalchemy.orm import Session

from signals.db.models import Filing
from signals.domain.types import FUND_FORMS, STAKE_FORMS
from signals.ingest.dispatch import HandlerContext, register_handler
from signals.ingest.normalize_funds import normalize_13f
from signals.ingest.normalize_stakes import normalize_stake
from signals.ingest.parsers.form13f import F13FHolding, parse_13f_infotable, parse_13f_primary
from signals.ingest.parsers.schedule13 import parse_schedule13
from signals.ingest.parsers.xmlutil import parse_xml
from signals.sec.sgml import SgmlFiling


def handle_13f(session: Session, sgml: SgmlFiling, filing: Filing, ctx: HandlerContext) -> None:
    """13F-HR(/A) and 13F-NT(/A): find the cover and (if present) the information table
    among the filing's XML documents by their root element, then hand both to `normalize_13f`."""
    cover = None
    holdings: list[F13FHolding] = []
    for doc in sgml.xml_documents():
        body = doc.xml()
        if body is None:
            continue
        root_tag = parse_xml(body).tag
        if root_tag == "edgarSubmission":
            cover = parse_13f_primary(body)
        elif root_tag == "informationTable":
            holdings = parse_13f_infotable(body)
    if cover is None:
        raise ValueError(f"{filing.accession_no}: no 13F primary document (edgarSubmission)")
    normalize_13f(session, filing, cover, holdings)


def handle_schedule13(
    session: Session, sgml: SgmlFiling, filing: Filing, ctx: HandlerContext
) -> None:
    """Schedule 13D/13G: the filing's first (and, in every recorded fixture, only) XML
    document holds the whole schedule."""
    docs = sgml.xml_documents()
    if not docs:
        raise ValueError(f"{filing.accession_no}: no XML document")
    body = docs[0].xml()
    assert body is not None
    doc = parse_schedule13(body, sgml.form_type)
    normalize_stake(session, filing, doc)


register_handler(FUND_FORMS, handle_13f)
register_handler(STAKE_FORMS, handle_schedule13)
