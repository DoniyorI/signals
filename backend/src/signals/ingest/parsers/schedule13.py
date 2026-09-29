"""Schedule 13D and 13G (XML, filed 2024-12-18 onward): beneficial-ownership stakes.

Element names follow the SEC Schedule 13D/13G XML technical specifications and the recorded
fixtures. The two forms share a shape (issuer, reporting persons, percent of class) but differ
in element names:
- 13D's issuer CIK element is `issuerCIK`; its persons are `reportingPersons/reportingPersonInfo`
  with `percentOfClass`; it alone carries an Item 4 purpose.
- 13G's issuer CIK element is `issuerCik`; its persons are `coverPageHeaderReportingPersonDetails`
  with `classPercent`. `items/item4/classPercent` and `signatureInformation/reportingPersonName`
  are not reporting-person data and must not be read as such.

`parse_xml` strips namespaces, so every path below is namespace-agnostic.
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from lxml import etree

from signals.ingest.parsers.xmlutil import parse_xml, text, to_date, to_float

PURPOSE_MAX_CHARS = 4000


@dataclass(frozen=True)
class ReportingPerson:
    name: str
    cik: int | None
    sole_voting: float | None
    shared_voting: float | None
    sole_dispositive: float | None
    shared_dispositive: float | None
    aggregate_owned: float | None
    percent_of_class: float | None  # fraction
    type_of_reporting_person: str | None


@dataclass(frozen=True)
class Schedule13Doc:
    form_type: str
    issuer_cik: int | None
    issuer_name: str | None
    cusip: str | None
    event_date: date | None
    amendment_no: int | None
    persons: tuple[ReportingPerson, ...]
    purpose: str | None  # 13D Item 4, truncated to 4000 chars


def _to_cik(raw: str | None) -> int | None:
    if raw is None:
        return None
    stripped = raw.strip()
    return int(stripped) if stripped.isdigit() else None


def _to_int(raw: str | None) -> int | None:
    value = to_float(raw)
    return int(value) if value is not None else None


def _to_fraction(raw: str | None) -> float | None:
    value = to_float(raw)
    return value / 100 if value is not None else None


def _cusip(raw: str | None) -> str | None:
    if raw is None:
        return None
    cleaned = raw.strip().upper()
    return cleaned or None


def _13d_person(node: etree._Element) -> ReportingPerson:
    return ReportingPerson(
        name=text(node, "reportingPersonName") or "",
        cik=_to_cik(text(node, "reportingPersonCIK")),
        sole_voting=to_float(text(node, "soleVotingPower")),
        shared_voting=to_float(text(node, "sharedVotingPower")),
        sole_dispositive=to_float(text(node, "soleDispositivePower")),
        shared_dispositive=to_float(text(node, "sharedDispositivePower")),
        aggregate_owned=to_float(text(node, "aggregateAmountOwned")),
        percent_of_class=_to_fraction(text(node, "percentOfClass")),
        type_of_reporting_person=text(node, "typeOfReportingPerson"),
    )


def _13g_person(node: etree._Element) -> ReportingPerson:
    shares = node.find("reportingPersonBeneficiallyOwnedNumberOfShares")
    return ReportingPerson(
        name=text(node, "reportingPersonName") or "",
        # Not present for a single individual filer in the recorded fixture; read defensively
        # in case a joint 13G repeats it the way 13D does.
        cik=_to_cik(text(node, "reportingPersonCIK")),
        sole_voting=to_float(text(shares, "soleVotingPower")) if shares is not None else None,
        shared_voting=to_float(text(shares, "sharedVotingPower")) if shares is not None else None,
        sole_dispositive=(
            to_float(text(shares, "soleDispositivePower")) if shares is not None else None
        ),
        shared_dispositive=(
            to_float(text(shares, "sharedDispositivePower")) if shares is not None else None
        ),
        aggregate_owned=to_float(
            text(node, "reportingPersonBeneficiallyOwnedAggregateNumberOfShares")
        ),
        percent_of_class=_to_fraction(text(node, "classPercent")),
        type_of_reporting_person=text(node, "typeOfReportingPerson"),
    )


def parse_schedule13(xml: bytes, form_type: str) -> Schedule13Doc:
    """`edgarSubmission` root, either schema. `form_type` (the filing's own CONFORMED
    SUBMISSION TYPE, e.g. from the SGML header) selects 13D vs 13G element names."""
    root = parse_xml(xml)
    is_13d = form_type.upper().startswith("SCHEDULE 13D")
    cover = root.find("formData/coverPageHeader")

    issuer_cik_path = "issuerInfo/issuerCIK" if is_13d else "issuerInfo/issuerCik"
    event_date_path = "dateOfEvent" if is_13d else "eventDateRequiresFilingThisStatement"

    def cover_text(path: str) -> str | None:
        return text(cover, path) if cover is not None else None

    # amendmentNo's element name is unverified: neither recorded fixture is an amendment.
    # This reads as None if the real name differs, rather than raising.
    amendment_no = _to_int(cover_text("amendmentNo"))

    if is_13d:
        persons = tuple(_13d_person(p) for p in root.iter("reportingPersonInfo"))
        purpose = text(root, "formData/items1To7/item4/transactionPurpose")
    else:
        persons = tuple(_13g_person(p) for p in root.iter("coverPageHeaderReportingPersonDetails"))
        purpose = None
    if purpose is not None:
        purpose = purpose[:PURPOSE_MAX_CHARS]

    return Schedule13Doc(
        form_type=form_type,
        issuer_cik=_to_cik(cover_text(issuer_cik_path)),
        issuer_name=cover_text("issuerInfo/issuerName"),
        cusip=_cusip(cover_text("issuerInfo/issuerCusips/issuerCusipNumber")),
        event_date=to_date(cover_text(event_date_path)),
        amendment_no=amendment_no,
        persons=persons,
        purpose=purpose,
    )


def to_jsonable(doc: Schedule13Doc) -> dict[str, Any]:
    """A JSON-ready view of one parsed filing (golden files, debugging)."""
    data = asdict(doc)
    data["persons"] = list(data["persons"])  # asdict keeps the tuple; JSON only has arrays
    if doc.event_date is not None:
        data["event_date"] = doc.event_date.isoformat()
    return data
