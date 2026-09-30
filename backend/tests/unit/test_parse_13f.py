import json
from datetime import date
from pathlib import Path

import pytest

from signals.ingest.parsers.form13f import (
    parse_13f_infotable,
    parse_13f_primary,
    to_jsonable,
    value_to_usd,
)
from signals.sec.sgml import SgmlDocument, SgmlFiling

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
KEYS = ["f13f_small", "f13f_pre2023", "f13f_restatement"]


def golden_path(key: str) -> Path:
    return GOLDEN_DIR / f"{key}.json"


def _xml(doc: SgmlDocument) -> bytes:
    body = doc.xml()
    assert body is not None, f"document {doc.type} has no XML body"
    return body


def _parse(raw: bytes):
    sg = SgmlFiling.from_txt(raw)
    docs = {d.type: d for d in sg.xml_documents()}
    cover = parse_13f_primary(_xml(docs[sg.form_type]))
    rows = parse_13f_infotable(_xml(docs["INFORMATION TABLE"]))
    return cover, rows


def test_value_to_usd_boundary():
    assert value_to_usd(1234, date(2022, 11, 14)) == 1_234_000.0
    assert value_to_usd(1234, date(2023, 1, 2)) == 1_234_000.0
    assert value_to_usd(1234, date(2023, 1, 3)) == 1234.0


@pytest.mark.parametrize("key", KEYS)
def test_matches_golden_and_anchors(key, fixture_bytes, manifest):
    cover, rows = _parse(fixture_bytes(key))
    assert to_jsonable(cover, rows) == json.loads(golden_path(key).read_text())
    exp = manifest[key]["expect"]
    # The manifest keeps the filing's own MM-DD-YYYY spelling.
    assert cover.period_of_report.strftime("%m-%d-%Y") == exp["period_of_report"]
    assert len(rows) == exp["n_rows"]
    assert sum(r.value_reported for r in rows) == pytest.approx(exp["table_value_total"], rel=1e-6)
    assert cover.table_entry_total == exp["table_entry_total"]
    assert cover.table_value_total == pytest.approx(exp["table_value_total"])
    assert cover.amendment_type == exp["amendment_type"]
    first = exp["first_row"]
    assert (rows[0].cusip, rows[0].value_reported) == (first["cusip"], first["value_reported"])
    assert [r.row_no for r in rows] == list(range(1, len(rows) + 1))


def test_restatement_type(fixture_bytes):
    cover, _ = _parse(fixture_bytes("f13f_restatement"))
    assert cover.amendment_type == "RESTATEMENT" and cover.is_amendment is True
    assert cover.amendment_no == 1 and cover.submission_type == "13F-HR/A"


def test_original_is_not_an_amendment(fixture_bytes):
    cover, _ = _parse(fixture_bytes("f13f_small"))
    assert cover.is_amendment is False and cover.amendment_type is None
    assert cover.manager_name == "LONE PINE CAPITAL LLC" and cover.other_included_managers == 0


def test_other_managers_kept_verbatim(fixture_bytes):
    cover, rows = _parse(fixture_bytes("f13f_pre2023"))
    assert cover.other_included_managers == 14 and cover.report_type == "13F COMBINATION REPORT"
    assert rows[0].other_manager == "4,8,11" and rows[0].investment_discretion == "DFND"


PRIMARY_NEW_HOLDINGS = b"""<?xml version="1.0" encoding="UTF-8"?>
<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData><submissionType>13F-HR/A</submissionType>
    <filerInfo><periodOfReport>03-31-2024</periodOfReport></filerInfo></headerData>
  <formData>
    <coverPage>
      <reportCalendarOrQuarter>03-31-2024</reportCalendarOrQuarter>
      <isAmendment>true</isAmendment>
      <amendmentNo>2</amendmentNo>
      <amendmentInfo><amendmentType>NEW HOLDINGS</amendmentType></amendmentInfo>
      <filingManager><name>Example Capital</name></filingManager>
      <reportType>13F HOLDINGS REPORT</reportType>
    </coverPage>
    <summaryPage>
      <otherIncludedManagersCount>0</otherIncludedManagersCount>
      <tableEntryTotal>1</tableEntryTotal>
      <tableValueTotal>1,500</tableValueTotal>
      <isConfidentialOmitted>true</isConfidentialOmitted>
    </summaryPage>
  </formData>
</edgarSubmission>"""

PRIMARY_NOTICE = b"""<edgarSubmission xmlns="http://www.sec.gov/edgar/thirteenffiler">
  <headerData><submissionType>13F-NT</submissionType>
    <filerInfo><periodOfReport>06-30-2026</periodOfReport></filerInfo></headerData>
  <formData>
    <coverPage>
      <reportCalendarOrQuarter>06-30-2026</reportCalendarOrQuarter>
      <filingManager><name>BRAMSON EDWARD J</name></filingManager>
      <reportType>13F NOTICE</reportType>
    </coverPage>
  </formData>
</edgarSubmission>"""

INFOTABLE_OPTIONS = b"""<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer><titleOfClass>COM</titleOfClass>
    <cusip> 000000aa1 </cusip><figi>BBG000TEST01</figi><value>1,500</value>
    <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt><sshPrnamtType>sh</sshPrnamtType></shrsOrPrnAmt>
    <putCall>Call</putCall><investmentDiscretion>SOLE</investmentDiscretion>
    <votingAuthority><Sole>100</Sole><Shared>0</Shared><None>0</None></votingAuthority>
  </infoTable>
  <infoTable>
    <nameOfIssuer>ACME CORP</nameOfIssuer><titleOfClass>NOTE 2.5%</titleOfClass>
    <cusip>000000AB9</cusip><value>2000</value>
    <shrsOrPrnAmt><sshPrnamt>2000000</sshPrnamt><sshPrnamtType>PRN</sshPrnamtType></shrsOrPrnAmt>
    <investmentDiscretion>SOLE</investmentDiscretion>
  </infoTable>
</informationTable>"""


def test_new_holdings_amendment_kept_verbatim():
    cover = parse_13f_primary(PRIMARY_NEW_HOLDINGS)
    assert cover.amendment_type == "NEW HOLDINGS" and cover.amendment_no == 2
    assert cover.period_of_report == date(2024, 3, 31) and cover.table_value_total == 1500.0
    assert cover.is_confidential_omitted is True


def test_notice_cover_without_summary_page():
    cover = parse_13f_primary(PRIMARY_NOTICE)
    assert cover.submission_type == "13F-NT" and cover.report_type == "13F NOTICE"
    assert cover.is_amendment is False and cover.amendment_type is None
    assert (cover.table_entry_total, cover.table_value_total) == (None, None)
    assert cover.other_included_managers is None and cover.is_confidential_omitted is None


def test_infotable_normalizes_cusip_put_call_and_prn():
    rows = parse_13f_infotable(INFOTABLE_OPTIONS)
    call, note = rows
    assert (call.cusip, call.put_call, call.sh_prn, call.figi) == (
        "000000AA1",
        "CALL",
        "SH",
        "BBG000TEST01",
    )
    assert (call.value_reported, call.shares, call.voting_sole) == (1500.0, 100.0, 100.0)
    assert (note.sh_prn, note.put_call, note.voting_sole, note.figi) == ("PRN", None, None, None)


def test_infotable_row_without_cusip_is_an_error():
    xml = INFOTABLE_OPTIONS.replace(b"<cusip>000000AB9</cusip>", b"<cusip> </cusip>")
    with pytest.raises(ValueError, match="row 2"):
        parse_13f_infotable(xml)


def test_primary_without_period_is_an_error():
    xml = PRIMARY_NOTICE.replace(b"06-30-2026", b"")
    with pytest.raises(ValueError, match="period"):
        parse_13f_primary(xml)
