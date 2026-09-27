from datetime import date, datetime, timedelta

import pytest

from signals.sec.sgml import SgmlFiling
from tests.conftest import fixture_path


def _filing_keys(manifest):
    return sorted(k for k, v in manifest.items() if v["file"].startswith("filings/"))


def test_every_filing_fixture_header(manifest):
    keys = _filing_keys(manifest)
    assert len(keys) >= 17
    for key in keys:
        entry = manifest[key]
        sg = SgmlFiling.from_txt(fixture_path(entry["file"]).read_bytes())
        assert sg.accession_no == entry["accession"], key
        assert sg.form_type == entry["form_type"], key
        assert sg.filed_date == date.fromisoformat(entry["filed_date"]), key
        assert sg.accepted_at == datetime.fromisoformat(entry["accepted_at"]), key
        assert sg.accepted_at is not None and sg.accepted_at.tzinfo is not None, key


def test_dst_offsets(manifest):
    for key in _filing_keys(manifest):
        sg = SgmlFiling.from_txt(fixture_path(manifest[key]["file"]).read_bytes())
        assert sg.accepted_at is not None
        if 4 <= sg.accepted_at.month <= 10:
            assert sg.accepted_at.utcoffset() == timedelta(hours=-4), key


def test_roles_and_documents(fixture_bytes):
    joint = SgmlFiling.from_txt(fixture_bytes("form4_joint"))
    assert len(joint.ciks_by_role["REPORTING-OWNER"]) >= 2
    assert joint.ciks_by_role["ISSUER"] == [1789029]
    assert joint.primary_cik() in joint.ciks_by_role["REPORTING-OWNER"]
    assert joint.period_of_report == date(2025, 3, 27)

    f13 = SgmlFiling.from_txt(fixture_bytes("f13f_small"))
    types = [d.type for d in f13.xml_documents()]
    assert len(types) == 2 and "INFORMATION TABLE" in types
    assert f13.primary_cik() == 1061165

    sc = SgmlFiling.from_txt(fixture_bytes("sc13d"))
    assert "SCHEDULE 13D" in [d.type for d in sc.xml_documents()]
    assert sc.ciks_by_role["SUBJECT COMPANY"] == [2088082]
    assert sc.names_by_cik[2088082] == "Electra Therapeutics, Inc."


def test_xml_body_is_xml(fixture_bytes):
    doc = SgmlFiling.from_txt(fixture_bytes("form4_buy_single")).xml_documents()[0]
    xml = doc.xml()
    assert xml is not None and xml.lstrip().startswith((b"<?xml", b"<ownershipDocument"))


def test_rejects_non_sgml():
    with pytest.raises(ValueError):
        SgmlFiling.from_txt(b"<html>not a filing</html>")
