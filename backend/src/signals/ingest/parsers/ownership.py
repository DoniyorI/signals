"""Forms 3, 4 and 5 (and amendments): the `ownershipDocument` XML as typed dataclasses.

Pure: bytes in, dataclasses out. Element names follow the EDGAR ownership XML technical
specification (X0508) and the recorded fixtures. Gotchas handled here: values wrapped in
`<value>`, booleans as 1/0/true/false, dates with a timezone suffix, prices or dates given
only as a footnote reference (value None, footnote ids kept), and holdings reported as a
value (`valueOwnedFollowingTransaction`) instead of a share count.
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

from lxml import etree

from signals.ingest.parsers.xmlutil import FieldValue, field, parse_xml, text, to_bool, to_date
from signals.ingest.parsers.xmlutil import to_float as _to_float

TableKind = Literal["nonderiv", "deriv"]
RowKind = Literal["transaction", "holding"]

_ROW_ELEMENTS: dict[str, tuple[TableKind, RowKind]] = {
    "nonDerivativeTransaction": ("nonderiv", "transaction"),
    "nonDerivativeHolding": ("nonderiv", "holding"),
    "derivativeTransaction": ("deriv", "transaction"),
    "derivativeHolding": ("deriv", "holding"),
}

# Dataclass field -> element path inside a row (footnote ids under the path are kept).
_ROW_PATHS: dict[str, str] = {
    "security_title": "securityTitle",
    "transaction_date": "transactionDate",
    "deemed_execution_date": "deemedExecutionDate",
    "timeliness": "transactionTimeliness",
    "shares": "transactionAmounts/transactionShares",
    "price": "transactionAmounts/transactionPricePerShare",
    "acquired_disposed": "transactionAmounts/transactionAcquiredDisposedCode",
    "shares_owned_after": "postTransactionAmounts/sharesOwnedFollowingTransaction",
    "value_owned_after": "postTransactionAmounts/valueOwnedFollowingTransaction",
    "direct_indirect": "ownershipNature/directOrIndirectOwnership",
    "nature_of_ownership": "ownershipNature/natureOfOwnership",
    "exercise_price": "conversionOrExercisePrice",
    "exercise_date": "exerciseDate",
    "expiration_date": "expirationDate",
    "underlying_title": "underlyingSecurity/underlyingSecurityTitle",
    "underlying_shares": "underlyingSecurity/underlyingSecurityShares",
}


@dataclass(frozen=True)
class ReportingOwner:
    cik: int
    name: str
    is_director: bool
    is_officer: bool
    officer_title: str | None
    is_ten_pct_owner: bool
    is_other: bool
    other_text: str | None


@dataclass(frozen=True)
class OwnershipRow:
    table_kind: TableKind
    row_kind: RowKind
    row_no: int
    security_title: str | None
    transaction_date: date | None
    deemed_execution_date: date | None
    code: str | None
    form_type: str | None
    equity_swap: bool | None
    timeliness: str | None
    shares: float | None
    price: float | None
    acquired_disposed: Literal["A", "D"] | None
    shares_owned_after: float | None
    value_owned_after: float | None
    direct_indirect: Literal["D", "I"] | None
    nature_of_ownership: str | None
    exercise_price: float | None
    exercise_date: date | None
    expiration_date: date | None
    underlying_title: str | None
    underlying_shares: float | None
    field_footnotes: dict[str, tuple[str, ...]]  # e.g. {"price": ("F1",)}


@dataclass(frozen=True)
class OwnershipDoc:
    document_type: str
    period_of_report: date | None
    date_of_original_submission: date | None
    not_subject_to_section16: bool | None
    issuer_cik: int
    issuer_name: str
    issuer_symbol: str | None
    owners: tuple[ReportingOwner, ...]
    aff10b5one: bool | None
    rows: tuple[OwnershipRow, ...]
    footnotes: dict[str, str]
    remarks: str | None


def _paragraph(el: etree._Element | None) -> str | None:
    """All text under an element with whitespace runs collapsed (footnotes, remarks)."""
    if el is None:
        return None
    collapsed = " ".join("".join(str(part) for part in el.itertext()).split())
    return collapsed or None


def _cik(value: str | None, what: str) -> int:
    if value is None or not value.strip().isdigit():
        raise ValueError(f"missing or invalid {what} CIK: {value!r}")
    return int(value)


def _flag(rel: etree._Element | None, tag: str) -> bool:
    """Relationship checkboxes: missing means False."""
    return bool(to_bool(text(rel, tag))) if rel is not None else False


def _owner(el: etree._Element) -> ReportingOwner:
    rel = el.find("reportingOwnerRelationship")
    return ReportingOwner(
        cik=_cik(text(el, "reportingOwnerId/rptOwnerCik"), "reporting owner"),
        name=text(el, "reportingOwnerId/rptOwnerName") or "",
        is_director=_flag(rel, "isDirector"),
        is_officer=_flag(rel, "isOfficer"),
        officer_title=text(rel, "officerTitle") if rel is not None else None,
        is_ten_pct_owner=_flag(rel, "isTenPercentOwner"),
        is_other=_flag(rel, "isOther"),
        other_text=text(rel, "otherText") if rel is not None else None,
    )


def _acquired_disposed(value: str | None) -> Literal["A", "D"] | None:
    code = (value or "").strip().upper()
    return "A" if code == "A" else "D" if code == "D" else None


def _direct_indirect(value: str | None) -> Literal["D", "I"] | None:
    code = (value or "").strip().upper()
    return "D" if code == "D" else "I" if code == "I" else None


def _row(el: etree._Element, table_kind: TableKind, row_kind: RowKind, row_no: int) -> OwnershipRow:
    values: dict[str, FieldValue] = {name: field(el, path) for name, path in _ROW_PATHS.items()}
    footnotes: dict[str, tuple[str, ...]] = {
        name: fv.footnote_ids for name, fv in values.items() if fv.footnote_ids
    }
    coding = el.find("transactionCoding")
    code = form_type = None
    equity_swap: bool | None = None
    if coding is not None:
        code = text(coding, "transactionCode")
        form_type = text(coding, "transactionFormType")
        equity_swap = to_bool(text(coding, "equitySwapInvolved"))
        # Footnotes on the coding block (often the 10b5-1 note) belong to the code.
        coding_ids = tuple(fn.get("id", "") for fn in coding.iter("footnoteId") if fn.get("id"))
        if coding_ids:
            footnotes["code"] = coding_ids
    ordered = {name: footnotes[name] for name in sorted(footnotes)}

    def v(name: str) -> str | None:
        return values[name].value

    return OwnershipRow(
        table_kind=table_kind,
        row_kind=row_kind,
        row_no=row_no,
        security_title=v("security_title"),
        transaction_date=to_date(v("transaction_date")),
        deemed_execution_date=to_date(v("deemed_execution_date")),
        code=code.upper() if code else None,
        form_type=form_type,
        equity_swap=equity_swap,
        timeliness=v("timeliness"),
        shares=_to_float(v("shares")),
        price=_to_float(v("price")),
        acquired_disposed=_acquired_disposed(v("acquired_disposed")),
        shares_owned_after=_to_float(v("shares_owned_after")),
        value_owned_after=_to_float(v("value_owned_after")),
        direct_indirect=_direct_indirect(v("direct_indirect")),
        nature_of_ownership=v("nature_of_ownership"),
        exercise_price=_to_float(v("exercise_price")),
        exercise_date=to_date(v("exercise_date")),
        expiration_date=to_date(v("expiration_date")),
        underlying_title=v("underlying_title"),
        underlying_shares=_to_float(v("underlying_shares")),
        field_footnotes=ordered,
    )


def _rows(root: etree._Element) -> tuple[OwnershipRow, ...]:
    counters: dict[tuple[TableKind, RowKind], int] = {}
    rows: list[OwnershipRow] = []
    for table in ("nonDerivativeTable", "derivativeTable"):
        for table_el in root.findall(table):
            for el in table_el:
                kinds = _ROW_ELEMENTS.get(el.tag) if isinstance(el.tag, str) else None
                if kinds is None:
                    continue
                counters[kinds] = counters.get(kinds, 0) + 1
                rows.append(_row(el, kinds[0], kinds[1], counters[kinds]))
    return tuple(rows)


def parse_ownership(xml: bytes) -> OwnershipDoc:
    root = parse_xml(xml)
    if root.tag != "ownershipDocument":
        raise ValueError(f"expected an ownershipDocument, got <{root.tag}>")
    document_type = text(root, "documentType")
    if document_type is None:
        raise ValueError("ownershipDocument without documentType")
    footnotes = {
        fn.get("id", ""): _paragraph(fn) or ""
        for fn in root.findall("footnotes/footnote")
        if fn.get("id")
    }
    return OwnershipDoc(
        document_type=document_type,
        period_of_report=to_date(text(root, "periodOfReport")),
        date_of_original_submission=to_date(text(root, "dateOfOriginalSubmission")),
        not_subject_to_section16=to_bool(text(root, "notSubjectToSection16")),
        issuer_cik=_cik(text(root, "issuer/issuerCik"), "issuer"),
        issuer_name=text(root, "issuer/issuerName") or "",
        issuer_symbol=text(root, "issuer/issuerTradingSymbol"),
        owners=tuple(_owner(el) for el in root.findall("reportingOwner")),
        aff10b5one=to_bool(text(root, "aff10b5One")),
        rows=_rows(root),
        footnotes=footnotes,
        remarks=_paragraph(root.find("remarks")),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def to_jsonable(doc: OwnershipDoc) -> dict:
    """Dates become ISO strings and tuples lists (the golden files use this form)."""
    return _jsonable(asdict(doc))
