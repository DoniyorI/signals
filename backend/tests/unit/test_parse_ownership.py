import json
import re
from datetime import date
from pathlib import Path

import pytest

from signals.ingest.parsers.ownership import parse_ownership, to_jsonable
from signals.sec.sgml import SgmlFiling
from tests.conftest import FIXTURES_DIR

OWNERSHIP_KEYS = [
    "form4_buy_single",
    "form4_joint",
    "form4a_original",
    "form4a_amendment",
    "form4_10b5_1_flag",
    "form4_10b5_1_footnote",
    "form4_exercise_sale",
    "form4_footnote_price",
    "form4_value_owned",
    "form3",
    "form5",
]


def golden_path(key: str) -> Path:
    return FIXTURES_DIR / "golden" / f"{key}.json"


def _doc(key, fixture_bytes):
    xml = SgmlFiling.from_txt(fixture_bytes(key)).xml_documents()[0].xml()
    assert xml is not None
    return parse_ownership(xml)


def _rows(doc, table_kind, row_kind):
    return [r for r in doc.rows if r.table_kind == table_kind and r.row_kind == row_kind]


@pytest.mark.parametrize("key", OWNERSHIP_KEYS)
def test_matches_golden(key, fixture_bytes):
    assert to_jsonable(_doc(key, fixture_bytes)) == json.loads(golden_path(key).read_text())


@pytest.mark.parametrize(
    "key", ["form4_buy_single", "form4_joint", "form4_10b5_1_flag", "form4_exercise_sale"]
)
def test_manifest_anchors(key, fixture_bytes, manifest):
    doc, exp = _doc(key, fixture_bytes), manifest[key]["expect"]
    tx = _rows(doc, "nonderiv", "transaction")
    assert doc.issuer_cik == exp["issuer_cik"]
    assert sorted(o.cik for o in doc.owners) == sorted(exp["owner_ciks"])
    assert [r.code for r in tx] == exp["codes"]
    if "first_nonderiv" in exp:
        f = exp["first_nonderiv"]
        assert (
            str(tx[0].transaction_date),
            tx[0].shares,
            tx[0].price,
            tx[0].shares_owned_after,
        ) == (
            f["transaction_date"],
            f["shares"],
            f["price"],
            f["shares_owned_after"],
        )


@pytest.mark.parametrize("key", OWNERSHIP_KEYS)
def test_manifest_counts_and_codes(key, fixture_bytes, manifest):
    """Every ownership fixture against the anchors read independently from the filing."""
    doc, exp = _doc(key, fixture_bytes), manifest[key]["expect"]
    assert doc.document_type == exp["document_type"]
    assert doc.issuer_cik == exp["issuer_cik"]
    assert [o.cik for o in doc.owners] == exp["owner_ciks"]
    assert len(_rows(doc, "nonderiv", "transaction")) == exp["n_nonderiv_trans"]
    assert len(_rows(doc, "deriv", "transaction")) == exp["n_deriv_trans"]
    assert len(_rows(doc, "nonderiv", "holding")) == exp["n_nonderiv_holdings"]
    assert [r.code for r in _rows(doc, "nonderiv", "transaction")] == exp["codes"]
    assert [r.code for r in _rows(doc, "deriv", "transaction")] == exp["deriv_codes"]
    assert doc.aff10b5one == exp["aff10b5one"]
    mentions = sorted(k for k, v in doc.footnotes.items() if re.search(r"10b5-?1", v, re.I))
    assert mentions == exp["footnote_ids_with_10b5_1"]
    if "first_nonderiv" in exp:
        tx = _rows(doc, "nonderiv", "transaction")[0]
        f = exp["first_nonderiv"]
        assert str(tx.transaction_date) == f["transaction_date"]
        assert (tx.shares, tx.price, tx.shares_owned_after) == (
            f["shares"],
            f["price"],
            f["shares_owned_after"],
        )


def test_aff10b5one(fixture_bytes):
    assert _doc("form4_10b5_1_flag", fixture_bytes).aff10b5one is True
    assert _doc("form4_buy_single", fixture_bytes).aff10b5one in (False, None)


def test_amendment_has_original_date(fixture_bytes, manifest):
    d = _doc("form4a_amendment", fixture_bytes)
    assert d.document_type == "4/A"
    assert (
        str(d.date_of_original_submission)
        == manifest["form4a_amendment"]["expect"]["date_of_original_submission"]
    )


def test_row_numbers_count_per_table_and_kind(fixture_bytes):
    doc = _doc("form4_10b5_1_footnote", fixture_bytes)  # one nonderiv transaction + one holding
    assert [(r.table_kind, r.row_kind, r.row_no) for r in doc.rows] == [
        ("nonderiv", "transaction", 1),
        ("nonderiv", "holding", 1),
    ]
    amendment = _doc("form4a_amendment", fixture_bytes)
    assert [r.row_no for r in _rows(amendment, "nonderiv", "transaction")] == [1, 2, 3, 4, 5]
    assert [r.row_no for r in _rows(amendment, "deriv", "transaction")] == [1]


def test_coding_footnote_is_attached_to_code(fixture_bytes):
    """10b5-1 footnotes sit on <transactionCoding>; they must reach field_footnotes."""
    row = _rows(_doc("form4_10b5_1_footnote", fixture_bytes), "nonderiv", "transaction")[0]
    assert row.field_footnotes["code"] == ("F1",)
    assert row.field_footnotes["price"] == ("F2",)
    assert row.field_footnotes["nature_of_ownership"] == ("F3",)


def test_real_value_owned_row(fixture_bytes):
    row = _rows(_doc("form4_value_owned", fixture_bytes), "nonderiv", "transaction")[0]
    assert row.shares_owned_after is None and row.value_owned_after == 97594117.8
    assert row.field_footnotes == {"transaction_date": ("F1",)}


def test_real_footnote_only_price(fixture_bytes):
    doc = _doc("form4_footnote_price", fixture_bytes)
    row = _rows(doc, "nonderiv", "transaction")[0]
    assert row.price is None and row.field_footnotes["price"] == ("F1",)
    deriv = _rows(doc, "deriv", "transaction")[0]
    assert deriv.exercise_price is None and deriv.field_footnotes["exercise_price"] == ("F1",)
    assert deriv.exercise_date is None and deriv.expiration_date is None
    assert deriv.field_footnotes["expiration_date"] == ("F2",)
    assert (deriv.underlying_title, deriv.underlying_shares) == ("Common Stock", 224.0)


def test_derivative_transaction_fields(fixture_bytes):
    deriv = _rows(_doc("form4_exercise_sale", fixture_bytes), "deriv", "transaction")[0]
    assert deriv.security_title == "Employee stock option (right to buy)"
    assert (deriv.code, deriv.shares, deriv.price, deriv.acquired_disposed) == (
        "M",
        5937.0,
        0.0,
        "D",
    )
    assert deriv.exercise_price == 46.31 and deriv.expiration_date == date(2033, 8, 15)
    assert deriv.exercise_date is None and deriv.field_footnotes["exercise_date"] == ("F3",)
    assert (deriv.underlying_title, deriv.underlying_shares) == ("Common Stock", 5937.0)
    assert deriv.shares_owned_after == 9063.0 and deriv.equity_swap is False


def test_holdings_rows(fixture_bytes):
    rows = _rows(_doc("form5", fixture_bytes), "nonderiv", "holding")
    assert [(r.shares_owned_after, r.direct_indirect, r.nature_of_ownership) for r in rows] == [
        (873.91, "I", "Spouse"),
        (3006.98, "I", "By 401K Plan"),
        (18743.77, "D", None),
    ]
    assert rows[0].field_footnotes == {"direct_indirect": ("F1",)}
    assert all(r.code is None and r.transaction_date is None for r in rows)


def test_joint_owner_relationships(fixture_bytes):
    owners = _doc("form4_joint", fixture_bytes).owners
    assert [(o.cik, o.name, o.is_ten_pct_owner, o.is_director, o.is_officer) for o in owners] == [
        (2003074, "SYLEBRA CAPITAL LLC", True, False, False),
        (1745725, "Gibson Daniel Patrick", True, False, False),
    ]


INLINE = b"""<ownershipDocument><documentType>4</documentType>
<issuer><issuerCik>0001000001</issuerCik><issuerName>Acme</issuerName><issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerCik>0002000001</rptOwnerCik>
<rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isOfficer>true</isOfficer><officerTitle>CEO</officerTitle></reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>
<transactionDate><value>2024-01-15-05:00</value></transactionDate>
<transactionCoding><transactionFormType>4</transactionFormType><transactionCode>P</transactionCode></transactionCoding>
<transactionAmounts><transactionShares><value>100</value></transactionShares>
<transactionPricePerShare><footnoteId id="F1"/></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
<postTransactionAmounts><valueOwnedFollowingTransaction><value>5000</value></valueOwnedFollowingTransaction></postTransactionAmounts>
<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership></ownershipNature>
</nonDerivativeTransaction></nonDerivativeTable>
<footnotes><footnote id="F1">Weighted average price.</footnote></footnotes></ownershipDocument>"""


def test_inline_gotchas():
    d = parse_ownership(INLINE)
    r = d.rows[0]
    assert d.issuer_cik == 1000001 and d.owners[0].is_officer is True
    assert d.owners[0].is_director is False
    assert r.transaction_date == date(2024, 1, 15) and r.price is None
    assert r.field_footnotes["price"] == ("F1",)
    assert r.shares_owned_after is None and r.value_owned_after == 5000.0
    assert d.footnotes == {"F1": "Weighted average price."}


def test_to_jsonable_converts_dates_and_tuples():
    out = to_jsonable(parse_ownership(INLINE))
    assert out["owners"][0]["cik"] == 2000001
    assert out["rows"][0]["transaction_date"] == "2024-01-15"
    assert out["rows"][0]["field_footnotes"] == {"price": ["F1"]}
    assert json.loads(json.dumps(out)) == out


def test_rejects_non_ownership_xml():
    with pytest.raises(ValueError, match="ownershipDocument"):
        parse_ownership(b"<edgarSubmission><x>1</x></edgarSubmission>")
