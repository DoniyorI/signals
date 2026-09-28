from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import func, select

from signals.db.models import (
    FeedItem,
    Filing,
    FilingOwner,
    InsiderHolding,
    InsiderTransaction,
    Issuer,
    Owner,
    OwnerRole,
    TickerEvidence,
)
from signals.domain.owner_group import owner_group_key
from signals.domain.tickers import current_symbol
from signals.domain.types import INSIDER_FORMS
from signals.ingest import dispatch
from signals.ingest.normalize_insider import (
    OwnerLine,
    TradeLine,
    build_feed_item,
    classify_owner_type,
    normalize_ownership,
    plan_flag_for_row,
)
from signals.ingest.parsers.ownership import (
    OwnershipDoc,
    OwnershipRow,
    ReportingOwner,
    parse_ownership,
)
from signals.ingest.pipeline import ingest_raw
from signals.sec.sgml import SgmlFiling
from tests.factories import make_filing, make_issuer


def _handle(session, sgml, filing, ctx):
    xml = next(d.xml() for d in sgml.xml_documents())
    assert xml is not None
    normalize_ownership(session, filing, parse_ownership(xml))


@pytest.fixture(autouse=True)
def ownership_handler():
    dispatch.reset_registry()
    dispatch.register_handler(INSIDER_FORMS, _handle)
    yield
    dispatch.reset_registry()


@pytest.fixture
def load(fixture_bytes, settings, tmp_archive):
    """Ingest a recorded filing through ingest_raw; skip when already parsed unless forced."""

    def _load(session, key: str, force: bool = False) -> str:
        raw = fixture_bytes(key)
        acc = SgmlFiling.from_txt(raw).accession_no
        existing = session.get(Filing, acc)
        if existing is not None and existing.parse_status == "parsed" and not force:
            return acc
        out = ingest_raw(
            session,
            raw,
            source="test",
            raw_path=None,
            first_seen_at=None,
            settings=settings,
            archive=tmp_archive,
        )
        assert out.status == "parsed", out.error
        return out.accession_no

    return _load


def plan_flags(session, acc: str, code: str) -> list[str]:
    return list(
        session.scalars(
            select(InsiderTransaction.plan_10b5_1).where(
                InsiderTransaction.accession_no == acc, InsiderTransaction.code == code
            )
        )
    )


def _tx(session, acc: str) -> list[InsiderTransaction]:
    return list(
        session.scalars(
            select(InsiderTransaction)
            .where(InsiderTransaction.accession_no == acc)
            .order_by(InsiderTransaction.table_kind.desc(), InsiderTransaction.row_no)
        )
    )


# --------------------------------------------------------------------------- plan tests
def test_joint_filing_links_all_owners(session, manifest, load):
    acc = load(session, "form4_joint")
    owners = session.scalars(
        select(FilingOwner.owner_cik).where(FilingOwner.accession_no == acc)
    ).all()
    assert sorted(owners) == sorted(manifest["form4_joint"]["expect"]["owner_ciks"])
    groups = set(
        session.scalars(
            select(InsiderTransaction.owner_group).where(InsiderTransaction.accession_no == acc)
        )
    )
    assert groups == {owner_group_key(owners)}


def test_idempotent(session, load):
    load(session, "form4_buy_single")
    n1 = session.scalar(select(func.count(InsiderTransaction.id)))
    load(session, "form4_buy_single", force=True)
    assert session.scalar(select(func.count(InsiderTransaction.id))) == n1
    assert session.scalar(select(func.count()).select_from(FilingOwner)) == 1
    assert session.scalar(select(func.count()).select_from(OwnerRole)) == 1


def test_plan_flags(session, load):
    a = load(session, "form4_10b5_1_flag")
    b = load(session, "form4_10b5_1_footnote")
    assert set(plan_flags(session, a, code="S")) == {"flag"}
    assert "footnote" in set(plan_flags(session, b, code="S"))


def test_feed_item_for_purchase(session, load):
    acc = load(session, "form4_buy_single")
    fi = session.get(FeedItem, acc)
    assert fi is not None
    assert fi.direction == "buy" and fi.summary.startswith("Bought ") and "P" in fi.codes


def test_owner_type_heuristic():
    def mk(n, **k):
        return ReportingOwner(
            cik=1,
            name=n,
            is_director=k.get("d", False),
            is_officer=k.get("o", False),
            officer_title=None,
            is_ten_pct_owner=True,
            is_other=False,
            other_text=None,
        )

    assert classify_owner_type(mk("BERKSHIRE HATHAWAY INC")) == "entity"
    assert classify_owner_type(mk("BUFFETT WARREN E")) == "person"
    assert classify_owner_type(mk("SMITH CAPITAL JOHN", o=True)) == "person"
    assert classify_owner_type(mk("Partners Group Finance USD IC Ltd")) == "entity"
    assert classify_owner_type(mk("Acme Holdings L.P.")) == "entity"


def test_ticker_evidence_recorded(session, load):
    acc = load(session, "form4_buy_single")
    issuer = session.get(Filing, acc).issuer_cik
    assert (
        session.scalar(
            select(func.count())
            .select_from(TickerEvidence)
            .where(TickerEvidence.issuer_cik == issuer)
        )
        == 1
    )


# --------------------------------------------------------------------------- rows
def test_transaction_rows_carry_values_footnotes_and_derivative_fields(session, load):
    acc = load(session, "form4_exercise_sale")
    rows = _tx(session, acc)
    assert [(r.table_kind, r.row_no, r.code) for r in rows] == [
        ("nonderiv", 1, "M"),
        ("nonderiv", 2, "S"),
        ("deriv", 1, "M"),
    ]
    sale = rows[1]
    assert sale.value_usd == pytest.approx(5937 * 71.5508)
    assert (sale.shares, sale.price, sale.shares_owned_after) == (5937.0, 71.5508, 6500.0)
    assert (sale.acquired_disposed, sale.direct_indirect, sale.issuer_cik) == ("D", "D", 1484565)
    assert sorted(sale.footnotes) == ["F1", "F2"]
    assert sale.footnotes["F2"].startswith("This transaction was executed in multiple trades")
    assert sale.field_footnotes == {"price": ["F2"], "shares_owned_after": ["F1"]}
    assert sale.plan_10b5_1 == "none" and sale.flags == [] and sale.superseded_by is None
    option = rows[2]
    assert (option.exercise_price, option.expiration_date) == (46.31, date(2033, 8, 15))
    assert (option.underlying_title, option.underlying_shares) == ("Common Stock", 5937.0)


def test_value_owned_row(session, load):
    acc = load(session, "form4_value_owned")
    (row,) = _tx(session, acc)
    assert row.shares_owned_after is None and row.value_owned_after == 97594117.8
    assert row.value_usd == pytest.approx(3489183.531 * 1.58)


def test_holdings_rows(session, load):
    acc = load(session, "form5")
    rows = session.scalars(
        select(InsiderHolding)
        .where(InsiderHolding.accession_no == acc)
        .order_by(InsiderHolding.row_no)
    ).all()
    assert [(h.shares_owned, h.direct_indirect, h.nature_of_ownership) for h in rows] == [
        (873.91, "I", "Spouse"),
        (3006.98, "I", "By 401K Plan"),
        (18743.77, "D", None),
    ]
    assert rows[0].footnotes == {"F1": "Accumulated shares through Dividend Reinvestment"}
    assert {h.owner_group for h in rows} == {"1275520"} and {h.issuer_cik for h in rows} == {736772}
    assert session.scalar(select(func.count()).select_from(InsiderTransaction)) == 0


PRICE_BY_FOOTNOTE = b"""<ownershipDocument><documentType>4</documentType>
<issuer><issuerCik>0001000001</issuerCik><issuerName>Acme</issuerName>
<issuerTradingSymbol>ACME</issuerTradingSymbol></issuer>
<reportingOwner><reportingOwnerId><rptOwnerCik>0002000001</rptOwnerCik>
<rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
<reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>CFO</officerTitle>
</reportingOwnerRelationship></reportingOwner>
<nonDerivativeTable><nonDerivativeTransaction><securityTitle><value>Common</value></securityTitle>
<transactionDate><value>2024-01-12</value></transactionDate>
<transactionCoding><transactionFormType>4</transactionFormType><transactionCode>P</transactionCode>
</transactionCoding><transactionAmounts><transactionShares><value>100</value></transactionShares>
<transactionPricePerShare><footnoteId id="F1"/></transactionPricePerShare>
<transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
</transactionAmounts><postTransactionAmounts><sharesOwnedFollowingTransaction><value>600</value>
</sharesOwnedFollowingTransaction></postTransactionAmounts>
<ownershipNature><directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
</ownershipNature></nonDerivativeTransaction></nonDerivativeTable>
<footnotes><footnote id="F1">Weighted average price.</footnote></footnotes></ownershipDocument>"""


def test_price_missing_flag_and_feed_item_without_price(session):
    filing = make_filing(session, filed_date=date(2024, 1, 16), owners=())
    normalize_ownership(session, filing, parse_ownership(PRICE_BY_FOOTNOTE))
    (row,) = _tx(session, filing.accession_no)
    assert row.flags == ["price_missing"] and row.price is None and row.value_usd is None
    assert row.footnotes == {"F1": "Weighted average price."}
    fi = session.get(FeedItem, filing.accession_no)
    assert fi is not None
    assert (fi.direction, fi.shares, fi.price, fi.value_usd) == ("buy", 100.0, None, None)
    assert fi.summary == "Bought 100 sh"


# --------------------------------------------------------------------------- reference rows
def test_new_issuer_and_owners_created(session, load):
    load(session, "form4_joint")
    assert session.get(Issuer, 1789029).name == "Aeva Technologies, Inc."
    sylebra, gibson = session.get(Owner, 2003074), session.get(Owner, 1745725)
    assert (sylebra.name, sylebra.owner_type) == ("SYLEBRA CAPITAL LLC", "entity")
    assert (gibson.name, gibson.owner_type) == ("Gibson Daniel Patrick", "person")
    role = session.get(OwnerRole, (1745725, 1789029))
    assert role.roles == ["10% owner"] and role.is_ten_pct_owner is True
    assert (role.first_filed, role.last_filed) == (date(2025, 3, 31), date(2025, 3, 31))


def test_existing_issuer_keeps_reference_fields(session, load):
    make_issuer(session, cik=1509261, name="REZOLUTE INC", sector="Health Care", sic=2834)
    acc = load(session, "form4_buy_single")
    issuer = session.get(Issuer, 1509261)
    assert (issuer.name, issuer.sector, issuer.sic) == ("REZOLUTE INC", "Health Care", 2834)
    assert session.get(FeedItem, acc).sector == "Health Care"


def test_tickers_rebuilt_from_filing_symbol(session, load):
    acc = load(session, "form4_buy_single")
    assert current_symbol(session, 1509261) == "RZLT"
    assert session.get(FeedItem, acc).ticker == "RZLT"


def _synthetic_doc(title: str) -> OwnershipDoc:
    owner = ReportingOwner(
        cik=2000001,
        name="Doe Jane",
        is_director=False,
        is_officer=True,
        officer_title=title,
        is_ten_pct_owner=False,
        is_other=False,
        other_text=None,
    )
    return OwnershipDoc(
        document_type="4",
        period_of_report=None,
        date_of_original_submission=None,
        not_subject_to_section16=None,
        issuer_cik=1000001,
        issuer_name="Acme Corp",
        issuer_symbol="ACME",
        owners=(owner,),
        aff10b5one=None,
        rows=(),
        footnotes={},
        remarks=None,
    )


def test_owner_roles_follow_newest_filing(session):
    newer = make_filing(
        session, accession_no="0002000001-24-000002", filed_date=date(2024, 3, 1), owners=()
    )
    older = make_filing(
        session, accession_no="0002000001-24-000001", filed_date=date(2024, 1, 5), owners=()
    )
    normalize_ownership(session, newer, _synthetic_doc("Chief Executive Officer"))
    normalize_ownership(session, older, _synthetic_doc("Chief Financial Officer"))
    role = session.get(OwnerRole, (2000001, 1000001))
    assert (role.officer_title, role.roles) == ("Chief Executive Officer", ["CEO"])
    assert (role.first_filed, role.last_filed) == (date(2024, 1, 5), date(2024, 3, 1))


# --------------------------------------------------------------------------- feed items
def test_feed_item_for_joint_purchase(session, load):
    acc = load(session, "form4_joint")
    fi = session.get(FeedItem, acc)
    assert fi.owner_ciks == [2003074, 1745725]
    assert fi.owner_names == "SYLEBRA CAPITAL LLC; Gibson Daniel Patrick"
    assert fi.owner_group == "1745725|2003074" and fi.top_role == "10% owner"
    assert (fi.direction, fi.codes, fi.plan_10b5_1) == ("buy", ["P"], "none")
    assert fi.shares == 3_559_227.0
    assert fi.value_usd == pytest.approx(23_284_843.59)
    assert fi.price == pytest.approx(23_284_843.59 / 3_559_227)
    assert fi.summary == "Bought 3,559,227 sh @ $6.54 ($23,284,844)"
    assert (fi.first_trade_date, fi.lag_days) == (date(2025, 3, 27), 2)
    assert (fi.issuer_cik, fi.issuer_name, fi.ticker) == (
        1789029,
        "Aeva Technologies, Inc.",
        "AEVA",
    )
    assert fi.filed_date == date(2025, 3, 31) and fi.accepted_at is not None


def test_feed_item_sale_dominates_exercise(session, load):
    acc = load(session, "form4_exercise_sale")
    fi = session.get(FeedItem, acc)
    assert (fi.direction, fi.codes) == ("sell", ["M", "S"])
    assert (fi.shares, fi.price) == (5937.0, 71.5508)
    assert fi.summary == "Sold 5,937 sh @ $71.55 ($424,797)"
    assert (fi.first_trade_date, fi.lag_days, fi.top_role) == (date(2025, 3, 28), 1, "Director")


def test_feed_item_flagged_plan_and_top_role(session, load):
    acc = load(session, "form4_10b5_1_flag")
    fi = session.get(FeedItem, acc)
    assert (fi.plan_10b5_1, fi.top_role, fi.lag_days) == ("flag", "CEO", 0)


def test_feed_item_form3_and_codes_only(session, load):
    f3 = session.get(FeedItem, load(session, "form3"))
    assert (f3.direction, f3.codes, f3.value_usd) == ("other", [], None)
    assert f3.summary == "Initial holdings: 1 security" and f3.lag_days is None
    m_only = session.get(FeedItem, load(session, "form4_footnote_price"))
    assert (m_only.direction, m_only.codes) == ("other", ["M"])
    assert m_only.summary == "Option exercise" and m_only.lag_days is None
    assert m_only.first_trade_date == date(2025, 3, 30)


# --------------------------------------------------------------------------- plan flag rule
def _row(**footnotes) -> OwnershipRow:
    return OwnershipRow(
        table_kind="nonderiv",
        row_kind="transaction",
        row_no=1,
        security_title=None,
        transaction_date=None,
        deemed_execution_date=None,
        code="S",
        form_type="4",
        equity_swap=None,
        timeliness=None,
        shares=None,
        price=None,
        acquired_disposed="D",
        shares_owned_after=None,
        value_owned_after=None,
        direct_indirect="D",
        nature_of_ownership=None,
        exercise_price=None,
        exercise_date=None,
        expiration_date=None,
        underlying_title=None,
        underlying_shares=None,
        field_footnotes={k: tuple(v) for k, v in footnotes.items()},
    )


def test_plan_flag_rule():
    doc = replace(
        _synthetic_doc("CEO"), footnotes={"F1": "Sold under a Rule 10B5-1 plan", "F2": "x"}
    )
    assert plan_flag_for_row(_row(code=["F1"]), doc) == "footnote"
    assert plan_flag_for_row(_row(price=["F2"]), doc) == "none"
    assert (
        plan_flag_for_row(_row(), replace(doc, remarks="Trades under a 10b51 plan")) == "footnote"
    )
    assert plan_flag_for_row(_row(price=["F2"]), replace(doc, aff10b5one=True)) == "flag"
    assert plan_flag_for_row(_row(code=["F1"]), replace(doc, aff10b5one=False)) == "footnote"


def test_feed_item_aggregates_footnote_plan_and_holdings_summary(session, load):
    planned = session.get(FeedItem, load(session, "form4_10b5_1_footnote"))
    assert (planned.plan_10b5_1, planned.direction) == ("footnote", "sell")
    annual = session.get(FeedItem, load(session, "form5"))
    assert (annual.direction, annual.codes, annual.summary) == (
        "other",
        [],
        "Holdings: 3 securities",
    )


def _line(code, shares, price, table_kind="nonderiv"):
    value = shares * price if shares is not None and price is not None else None
    return TradeLine(table_kind, code, date(2024, 1, 10), shares, price, value, "none")


def _item(*trades):
    return build_feed_item(
        accession_no="0000000001-24-000001",
        form_type="4",
        accepted_at=None,
        filed_date=date(2024, 1, 12),
        issuer_cik=1,
        issuer_name="Acme",
        ticker=None,
        sector=None,
        owners=[OwnerLine(2, "Doe Jane", ("CEO",))],
        trades=list(trades),
        n_holdings=0,
    )


def test_direction_compares_values_then_shares():
    bigger_sale = _item(_line("P", 100, 10.0), _line("S", 50, 30.0))
    assert (bigger_sale.direction, bigger_sale.value_usd, bigger_sale.shares) == (
        "sell",
        1500.0,
        50.0,
    )
    unpriced = _item(_line("P", 300, None), _line("S", 100, None))
    assert (unpriced.direction, unpriced.shares, unpriced.value_usd) == ("buy", 300.0, None)
    assert _item(_line("P", 100, 10.0), _line("S", 100, 10.0)).direction == "other"
    derivative_only = _item(_line("P", 100, 1.0, table_kind="deriv"))
    assert (derivative_only.direction, derivative_only.codes) == ("other", ("P",))
    # lag is counted to the filed date when the acceptance time is unknown
    assert _item(_line("P", 1, 1.0)).lag_days == 2
