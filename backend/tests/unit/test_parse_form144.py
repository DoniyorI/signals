import json
from datetime import date

import pytest

from signals.ingest.parsers.form144 import parse_form144, to_jsonable
from signals.sec.sgml import SgmlFiling
from tests.conftest import FIXTURES_DIR


def _doc(fixture_bytes):
    xml = SgmlFiling.from_txt(fixture_bytes("form144")).xml_documents()[0].xml()
    assert xml is not None
    return parse_form144(xml)


def test_form144_matches_golden(fixture_bytes):
    golden = FIXTURES_DIR / "golden" / "form144.json"
    assert to_jsonable(_doc(fixture_bytes)) == json.loads(golden.read_text())


def test_form144_anchors(fixture_bytes, manifest):
    doc, exp = _doc(fixture_bytes), manifest["form144"]["expect"]
    assert doc.issuer_cik == exp["issuer_cik"]
    assert doc.shares_to_sell == exp["shares_to_sell"]
    assert doc.market_value_usd == exp["market_value_usd"]
    assert str(doc.approx_sale_date) == exp["approx_sale_date"]
    assert doc.seller_name == exp["seller_name"]
    assert doc.relationships == (exp["relationship"],)
    assert doc.shares_outstanding == exp["shares_outstanding"]
    assert (doc.exchange, doc.broker) == (exp["exchange"], exp["broker"])
    assert str(doc.plan_10b5_1_adopted) == exp["plan_10b5_1_adopted"]
    assert doc.sold_past_3m == ()


def test_form144_first_acquisition_line(fixture_bytes):
    doc = _doc(fixture_bytes)
    assert (doc.acquired_how, doc.acquired_date) == ("Restricted Stock Lapse", date(2021, 3, 6))
    assert doc.security_class == "Common" and doc.issuer_name == "AKAMAI TECHNOLOGIES INC"


MULTI = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/ownership" xmlns:com="http://www.sec.gov/edgar/common">
<headerData><submissionType>144/A</submissionType></headerData>
<formData>
<issuerInfo><issuerCik>0001000001</issuerCik><issuerName>Acme</issuerName>
<nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>Doe Jane
</nameOfPersonForWhoseAccountTheSecuritiesAreToBeSold>
<relationshipsToIssuer><relationshipToIssuer>Director</relationshipToIssuer>
<relationshipToIssuer>Officer</relationshipToIssuer></relationshipsToIssuer></issuerInfo>
<securitiesInformation><securitiesClassTitle>Class A</securitiesClassTitle>
<brokerOrMarketmakerDetails><name>Broker One</name></brokerOrMarketmakerDetails>
<noOfUnitsSold>1,000</noOfUnitsSold><aggregateMarketValue>50000.00</aggregateMarketValue>
<noOfUnitsOutstanding>9000000</noOfUnitsOutstanding><approxSaleDate>02/03/2025</approxSaleDate>
<securitiesExchangeName>NYSE</securitiesExchangeName></securitiesInformation>
<securitiesInformation><securitiesClassTitle>Class B</securitiesClassTitle>
<brokerOrMarketmakerDetails><name>Broker Two</name></brokerOrMarketmakerDetails>
<noOfUnitsSold>500</noOfUnitsSold><aggregateMarketValue>25000.50</aggregateMarketValue>
<noOfUnitsOutstanding>100</noOfUnitsOutstanding><approxSaleDate>02/10/2025</approxSaleDate>
<securitiesExchangeName>NASDAQ</securitiesExchangeName></securitiesInformation>
<securitiesSoldInPast3Months><sellerDetails><name>Doe Jane</name></sellerDetails>
<securitiesClassTitle>Class A</securitiesClassTitle><saleDate>12/02/2024</saleDate>
<amountOfSecuritiesSold>300</amountOfSecuritiesSold><grossProceeds>14100.00</grossProceeds>
</securitiesSoldInPast3Months>
<securitiesSoldInPast3Months><sellerDetails><name>Doe Jane</name></sellerDetails>
<securitiesClassTitle>Class A</securitiesClassTitle><saleDate>01/06/2025</saleDate>
<amountOfSecuritiesSold>200</amountOfSecuritiesSold><grossProceeds>9800</grossProceeds>
</securitiesSoldInPast3Months>
</formData></edgarSubmission>"""


def test_several_securities_lines_are_summed():
    doc = parse_form144(MULTI)
    assert (doc.shares_to_sell, doc.market_value_usd) == (1500.0, 75000.5)
    assert (doc.security_class, doc.broker, doc.exchange) == ("Class A", "Broker One", "NYSE")
    assert doc.approx_sale_date == date(2025, 2, 3) and doc.shares_outstanding == 9_000_000.0
    assert doc.relationships == ("Director", "Officer")
    assert doc.plan_10b5_1_adopted is None and doc.acquired_how is None


def test_sales_in_past_three_months():
    assert parse_form144(MULTI).sold_past_3m == (
        (date(2024, 12, 2), 300.0, 14100.0),
        (date(2025, 1, 6), 200.0, 9800.0),
    )


def test_rejects_other_documents():
    with pytest.raises(ValueError, match="Form 144"):
        parse_form144(b"<ownershipDocument><documentType>4</documentType></ownershipDocument>")
