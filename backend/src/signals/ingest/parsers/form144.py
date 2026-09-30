"""Form 144 (notice of proposed sale), electronic XML since 2023-04-13, as a dataclass.

Pure: bytes in, dataclass out. Element paths follow the EDGAR Form 144 XML technical
specification and the recorded fixture: `formData/issuerInfo` (issuer, seller and
relationships), `securitiesInformation` (one line per class and broker: units to sell,
market value, units outstanding, sale date, exchange), `securitiesToBeSold` (how and when
the shares were acquired), `securitiesSoldInPast3Months` and `noticeSignature`.
"""

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any

from lxml import etree

from signals.ingest.parsers.xmlutil import parse_xml, text, to_date, to_float


@dataclass(frozen=True)
class Form144Doc:
    issuer_cik: int | None
    issuer_name: str | None
    seller_name: str | None
    relationships: tuple[str, ...]
    security_class: str | None
    broker: str | None
    shares_to_sell: float | None
    market_value_usd: float | None
    shares_outstanding: float | None
    approx_sale_date: date | None
    exchange: str | None
    acquired_how: str | None
    acquired_date: date | None
    plan_10b5_1_adopted: date | None
    sold_past_3m: tuple[tuple[date | None, float | None, float | None], ...]
    # (sale date, shares, gross proceeds)


def _sum(values: list[float | None]) -> float | None:
    known = [v for v in values if v is not None]
    return sum(known) if known else None


def _cik(value: str | None) -> int | None:
    return int(value) if value is not None and value.strip().isdigit() else None


def parse_form144(xml: bytes) -> Form144Doc:
    root = parse_xml(xml)
    form = root.find("formData")
    if root.tag != "edgarSubmission" or form is None or form.find("issuerInfo") is None:
        raise ValueError(f"not a Form 144 edgarSubmission: <{root.tag}>")
    issuer = form.find("issuerInfo")
    assert issuer is not None
    lines = form.findall("securitiesInformation")
    first_line: etree._Element | None = lines[0] if lines else None
    first_acquired = form.find("securitiesToBeSold")

    def first(path: str) -> str | None:
        return text(first_line, path) if first_line is not None else None

    return Form144Doc(
        issuer_cik=_cik(text(issuer, "issuerCik")),
        issuer_name=text(issuer, "issuerName"),
        seller_name=text(issuer, "nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold"),
        relationships=tuple(
            value
            for el in issuer.findall("relationshipsToIssuer/relationshipToIssuer")
            if (value := (el.text or "").strip())
        ),
        security_class=first("securitiesClassTitle"),
        broker=first("brokerOrMarketmakerDetails/name"),
        shares_to_sell=_sum([to_float(text(el, "noOfUnitsSold")) for el in lines]),
        market_value_usd=_sum([to_float(text(el, "aggregateMarketValue")) for el in lines]),
        shares_outstanding=to_float(first("noOfUnitsOutstanding")),
        approx_sale_date=to_date(first("approxSaleDate")),
        exchange=first("securitiesExchangeName"),
        acquired_how=(
            text(first_acquired, "natureOfAcquisitionTransaction")
            if first_acquired is not None
            else None
        ),
        acquired_date=(
            to_date(text(first_acquired, "acquiredDate")) if first_acquired is not None else None
        ),
        plan_10b5_1_adopted=to_date(
            text(form, "noticeSignature/planAdoptionDates/planAdoptionDate")
        ),
        sold_past_3m=tuple(
            (
                to_date(text(el, "saleDate")),
                to_float(text(el, "amountOfSecuritiesSold")),
                to_float(text(el, "grossProceeds")),
            )
            for el in form.findall("securitiesSoldInPast3Months")
        ),
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def to_jsonable(doc: Form144Doc) -> dict:
    """Dates become ISO strings and tuples lists (the golden file uses this form)."""
    return _jsonable(asdict(doc))
