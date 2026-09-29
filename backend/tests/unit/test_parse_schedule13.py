import json
from datetime import date
from pathlib import Path

import pytest

from signals.ingest.parsers.schedule13 import parse_schedule13, to_jsonable
from signals.sec.sgml import SgmlFiling

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
KEYS = ["sc13d", "sc13g"]


def golden_path(key: str) -> Path:
    return GOLDEN_DIR / f"{key}.json"


def _parse(fixture_bytes, key: str):
    sg = SgmlFiling.from_txt(fixture_bytes(key))
    doc = next(d for d in sg.xml_documents() if d.type == sg.form_type)
    body = doc.xml()
    assert body is not None
    return parse_schedule13(body, sg.form_type)


@pytest.mark.parametrize("key", KEYS)
def test_matches_golden_and_anchors(key, fixture_bytes, manifest):
    doc = _parse(fixture_bytes, key)
    assert to_jsonable(doc) == json.loads(golden_path(key).read_text())
    exp = manifest[key]["expect"]
    assert doc.issuer_cik == exp["issuer_cik"]
    assert doc.cusip == exp["cusip"]
    assert len(doc.persons) == exp["n_persons"]
    percents = [p.percent_of_class for p in doc.persons if p.percent_of_class is not None]
    assert max(percents) == pytest.approx(exp["max_percent_of_class"] / 100)


def test_sc13d_persons_and_purpose(fixture_bytes):
    doc = _parse(fixture_bytes, "sc13d")
    assert doc.form_type == "SCHEDULE 13D"
    assert doc.issuer_name == "Electra Therapeutics, Inc."
    assert doc.event_date == date(2026, 9, 21)
    assert doc.amendment_no is None
    names = [p.name for p in doc.persons]
    assert names == [
        "ORBIMED ADVISORS LLC",
        "ORBIMED CAPITAL GP VII LLC",
        "OrbiMed Genesis GP LLC",
    ]
    assert [p.cik for p in doc.persons] == [1055951, 1760648, 1808744]
    assert [p.percent_of_class for p in doc.persons] == [
        pytest.approx(0.11),
        pytest.approx(0.082),
        pytest.approx(0.028),
    ]
    top = doc.persons[0]
    assert (
        top.sole_voting,
        top.shared_voting,
        top.sole_dispositive,
        top.shared_dispositive,
        top.aggregate_owned,
    ) == (0.0, 6885170.0, 0.0, 6885170.0, 6885170.0)
    assert top.type_of_reporting_person == "IA"
    assert doc.purpose is not None
    assert doc.purpose.startswith("This Statement on Schedule 13D relates")
    assert len(doc.purpose) <= 4000


def test_sc13g_single_person_and_no_purpose(fixture_bytes):
    doc = _parse(fixture_bytes, "sc13g")
    assert doc.form_type == "SCHEDULE 13G"
    assert doc.issuer_name == "ADDENTAX GROUP CORP."
    assert doc.event_date == date(2026, 9, 22)
    assert len(doc.persons) == 1
    person = doc.persons[0]
    # The single filer's CIK isn't repeated inside the person block for this fixture.
    assert (person.name, person.cik) == ("Yip Wai Lun", None)
    assert person.percent_of_class == pytest.approx(0.099)
    assert (
        person.sole_voting,
        person.shared_voting,
        person.sole_dispositive,
        person.shared_dispositive,
    ) == (208334.0, 0.0, 208334.0, 0.0)
    assert person.aggregate_owned == 208334.0
    assert person.type_of_reporting_person == "IN"
    assert doc.purpose is None  # only 13D carries an Item 4 purpose


def test_percent_of_class_ignores_item4_and_signature_block(fixture_bytes):
    # structure_note: ignore signatureInformation/reportingPersonName and
    # items/item4/classPercent, which repeats as the string '9.90%'.
    doc = _parse(fixture_bytes, "sc13g")
    assert len(doc.persons) == 1  # not 2: signatureInformation isn't a reporting person
    assert doc.persons[0].percent_of_class == pytest.approx(0.099)  # not '9.90%' mis-parsed
