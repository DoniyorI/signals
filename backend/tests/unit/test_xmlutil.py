from datetime import date

from signals.ingest.parsers.xmlutil import (
    FieldValue,
    field,
    parse_xml,
    text,
    to_bool,
    to_date,
    to_float,
)


def test_field_value_and_footnote():
    el = parse_xml(
        b'<r><p><value>10.5</value><footnoteId id="F1"/></p><q><footnoteId id="F2"/></q></r>'
    )
    assert field(el, "p") == FieldValue("10.5", ("F1",))
    assert field(el, "q") == FieldValue(None, ("F2",))
    assert field(el, "missing") == FieldValue(None, ())


def test_plain_text_without_value_wrapper():
    el = parse_xml(b"<r><issuerCik>0001000001</issuerCik></r>")
    assert field(el, "issuerCik") == FieldValue("0001000001", ())
    assert text(el, "issuerCik") == "0001000001" and text(el, "nope") is None


def test_conversions():
    assert to_bool("1") is True and to_bool("false") is False and to_bool(None) is None
    assert to_bool("Y") is True and to_bool("N") is False
    assert to_float("1,234.50") == 1234.5 and to_float("") is None and to_float("$5") == 5.0
    assert to_float("9.90%") == 9.9
    assert to_date("2024-01-15-05:00") == date(2024, 1, 15)
    assert to_date("15-JAN-2024") == date(2024, 1, 15)
    assert to_date("03-31-2024") == date(2024, 3, 31)
    assert to_date("03/31/2024") == date(2024, 3, 31)
    assert to_date("20240115") == date(2024, 1, 15) and to_date("") is None


def test_namespaces_stripped():
    el = parse_xml(
        b'<ns1:informationTable xmlns:ns1="http://x"><ns1:infoTable/></ns1:informationTable>'
    )
    assert el.tag == "informationTable" and el[0].tag == "infoTable"
