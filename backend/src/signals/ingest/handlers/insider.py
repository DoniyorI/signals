"""Handlers for Forms 3/4/5 (+/A) and Form 144. Owned by workstream A (02-insider-ingestion.md)."""

from lxml import etree
from sqlalchemy.orm import Session

from signals.db.models import Filing
from signals.domain.types import FORM144_FORMS, INSIDER_FORMS
from signals.ingest.dispatch import HandlerContext, register_handler
from signals.ingest.normalize_form144 import normalize_form144
from signals.ingest.normalize_insider import normalize_ownership
from signals.ingest.parsers.form144 import parse_form144
from signals.ingest.parsers.ownership import parse_ownership
from signals.ingest.parsers.xmlutil import parse_xml
from signals.sec.sgml import SgmlFiling


def _first_xml(sgml: SgmlFiling) -> bytes:
    xml = next((raw for d in sgml.xml_documents() if (raw := d.xml()) is not None), None)
    if xml is None:
        raise ValueError(f"{sgml.accession_no}: no XML document found")
    return xml


def _ownership_xml(sgml: SgmlFiling) -> bytes:
    """The first XML document whose root is <ownershipDocument> (a filing can bundle
    other XML exhibits alongside the Form 3/4/5 body)."""
    for doc in sgml.xml_documents():
        raw = doc.xml()
        if raw is None:
            continue
        try:
            root = parse_xml(raw)
        except etree.XMLSyntaxError:
            continue
        if root.tag == "ownershipDocument":
            return raw
    raise ValueError(f"{sgml.accession_no}: no <ownershipDocument> XML found")


def handle_ownership(
    session: Session, sgml: SgmlFiling, filing: Filing, ctx: HandlerContext
) -> None:
    normalize_ownership(session, filing, parse_ownership(_ownership_xml(sgml)))


def handle_form144(session: Session, sgml: SgmlFiling, filing: Filing, ctx: HandlerContext) -> None:
    normalize_form144(session, filing, parse_form144(_first_xml(sgml)), sgml)


register_handler(INSIDER_FORMS, handle_ownership)
register_handler(FORM144_FORMS, handle_form144)
