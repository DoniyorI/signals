"""Form 13F-HR (+/A) and 13F-NT: the primary document (cover and summary) and the
information table (one row per holding).

Element names follow the EDGAR Form 13F XML technical specification and the recorded
fixtures. Namespaces vary by filer software (default namespace, `ns1:`, `n1:`), so every
path is namespace-agnostic. `value` is reported in thousands of dollars for filings made
before 2023-01-03 and in whole dollars from then on (`value_to_usd`).
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

from lxml import etree

from signals.ingest.parsers.xmlutil import parse_xml, text, to_bool, to_date, to_float

DOLLAR_VALUES_FROM = date(2023, 1, 3)

AmendmentType = Literal["RESTATEMENT", "NEW HOLDINGS"]


@dataclass(frozen=True)
class F13FCover:
    submission_type: str
    period_of_report: date
    is_amendment: bool
    amendment_no: int | None
    amendment_type: AmendmentType | None
    report_type: str | None
    manager_name: str
    other_included_managers: int | None
    table_entry_total: int | None
    table_value_total: float | None  # as reported (units depend on the filing date)
    is_confidential_omitted: bool | None


@dataclass(frozen=True)
class F13FHolding:
    row_no: int
    name_of_issuer: str
    title_of_class: str | None
    cusip: str
    figi: str | None
    value_reported: float
    shares: float
    sh_prn: Literal["SH", "PRN"]
    put_call: Literal["PUT", "CALL"] | None
    investment_discretion: str | None
    other_manager: str | None
    voting_sole: float | None
    voting_shared: float | None
    voting_none: float | None


def value_to_usd(value_reported: float, filed_date: date) -> float:
    """13F `value` in dollars: thousands before 2023-01-03, whole dollars from then on."""
    factor = 1000.0 if filed_date < DOLLAR_VALUES_FROM else 1.0
    return float(value_reported) * factor


def _to_int(s: str | None) -> int | None:
    number = to_float(s)
    return int(number) if number is not None else None


def _amendment_type(s: str | None) -> AmendmentType | None:
    value = " ".join((s or "").upper().split())
    if value == "RESTATEMENT":
        return "RESTATEMENT"
    if value == "NEW HOLDINGS":
        return "NEW HOLDINGS"
    return None


def parse_13f_primary(xml: bytes) -> F13FCover:
    """The `edgarSubmission` primary document. Dates are MM-DD-YYYY."""
    root = parse_xml(xml)
    cover = root.find("formData/coverPage")
    summary = root.find("formData/summaryPage")
    header_type = text(root, "headerData/submissionType")
    period_raw = (text(cover, "reportCalendarOrQuarter") if cover is not None else None) or text(
        root, "headerData/filerInfo/periodOfReport"
    )
    period = to_date(period_raw)
    if period is None:
        raise ValueError(f"13F primary document has no period of report ({period_raw!r})")

    def cover_text(path: str) -> str | None:
        return text(cover, path) if cover is not None else None

    def summary_text(path: str) -> str | None:
        return text(summary, path) if summary is not None else None

    return F13FCover(
        submission_type=(header_type or "").upper(),
        period_of_report=period,
        is_amendment=bool(to_bool(cover_text("isAmendment"))),
        amendment_no=_to_int(cover_text("amendmentNo")),
        amendment_type=_amendment_type(cover_text("amendmentInfo/amendmentType")),
        report_type=cover_text("reportType"),
        manager_name=cover_text("filingManager/name") or "",
        other_included_managers=_to_int(summary_text("otherIncludedManagersCount")),
        table_entry_total=_to_int(summary_text("tableEntryTotal")),
        table_value_total=to_float(summary_text("tableValueTotal")),
        is_confidential_omitted=to_bool(summary_text("isConfidentialOmitted")),
    )


def _required_number(row: etree._Element, path: str, row_no: int) -> float:
    raw = text(row, path)
    number = to_float(raw)
    if number is None:
        raise ValueError(f"13F information table row {row_no}: bad {path} {raw!r}")
    return number


def _sh_prn(raw: str | None, row_no: int) -> Literal["SH", "PRN"]:
    value = (raw or "").strip().upper()
    if value == "SH":
        return "SH"
    if value == "PRN":
        return "PRN"
    raise ValueError(f"13F information table row {row_no}: bad sshPrnamtType {raw!r}")


def _put_call(raw: str | None, row_no: int) -> Literal["PUT", "CALL"] | None:
    value = (raw or "").strip().upper()
    if not value:
        return None
    if value == "PUT":
        return "PUT"
    if value == "CALL":
        return "CALL"
    raise ValueError(f"13F information table row {row_no}: bad putCall {raw!r}")


def parse_13f_infotable(xml: bytes) -> list[F13FHolding]:
    """The `informationTable` document: one `F13FHolding` per `infoTable` row, in order."""
    root = parse_xml(xml)
    holdings: list[F13FHolding] = []
    for row_no, row in enumerate(root.iter("infoTable"), start=1):
        cusip = (text(row, "cusip") or "").strip().upper()
        if not cusip:
            raise ValueError(f"13F information table row {row_no}: no CUSIP")
        holdings.append(
            F13FHolding(
                row_no=row_no,
                name_of_issuer=text(row, "nameOfIssuer") or "",
                title_of_class=text(row, "titleOfClass"),
                cusip=cusip,
                figi=text(row, "figi"),
                value_reported=_required_number(row, "value", row_no),
                shares=_required_number(row, "shrsOrPrnAmt/sshPrnamt", row_no),
                sh_prn=_sh_prn(text(row, "shrsOrPrnAmt/sshPrnamtType"), row_no),
                put_call=_put_call(text(row, "putCall"), row_no),
                investment_discretion=text(row, "investmentDiscretion"),
                other_manager=text(row, "otherManager"),
                voting_sole=to_float(text(row, "votingAuthority/Sole")),
                voting_shared=to_float(text(row, "votingAuthority/Shared")),
                voting_none=to_float(text(row, "votingAuthority/None")),
            )
        )
    return holdings


def to_jsonable(cover: F13FCover, rows: list[F13FHolding]) -> dict[str, Any]:
    """A JSON-ready view of one parsed filing (golden files, debugging)."""
    head = asdict(cover)
    head["period_of_report"] = cover.period_of_report.isoformat()
    return {"cover": head, "holdings": [asdict(r) for r in rows]}
