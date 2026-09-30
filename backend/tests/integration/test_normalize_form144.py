from dataclasses import replace
from datetime import date

import pytest
from sqlalchemy import select

from signals.db.models import FeedItem, Form144Notice, Issuer, Owner
from signals.ingest import dispatch
from signals.ingest.normalize_form144 import form144_summary, normalize_form144
from signals.ingest.normalize_insider import upsert_owner_role
from signals.ingest.parsers.form144 import parse_form144
from signals.sec.sgml import SgmlFiling
from tests.factories import make_issuer
from tests.integration.insider_support import make_loader, register_form144_handler


@pytest.fixture(autouse=True)
def form144_handler():
    dispatch.reset_registry()
    register_form144_handler()
    yield
    dispatch.reset_registry()


@pytest.fixture
def load(fixture_bytes, settings, tmp_archive):
    return make_loader(fixture_bytes, settings, tmp_archive)


def test_form144_row_and_feed(session, load, manifest):
    acc = load(session, "form144")
    exp = manifest["form144"]["expect"]
    notice = session.get(Form144Notice, acc)
    assert notice.shares_to_sell == exp["shares_to_sell"]
    assert notice.market_value_usd == exp["market_value_usd"]
    assert str(notice.approx_sale_date) == exp["approx_sale_date"]
    assert session.get(FeedItem, acc).summary.startswith("Plans to sell ")


def test_notice_fields_and_filer(session, load, manifest):
    acc = load(session, "form144")
    exp = manifest["form144"]["expect"]
    n = session.get(Form144Notice, acc)
    assert (n.filer_cik, n.issuer_cik) == (exp["filer_cik"], exp["issuer_cik"])
    assert (n.seller_name, n.relationship) == (exp["seller_name"], exp["relationship"])
    assert (n.broker, n.exchange) == (exp["broker"], exp["exchange"])
    assert n.shares_outstanding == exp["shares_outstanding"]
    assert str(n.plan_10b5_1_adopted) == exp["plan_10b5_1_adopted"]
    assert (n.security_class, n.acquired_how, n.acquired_date) == (
        "Common",
        "Restricted Stock Lapse",
        date(2021, 3, 6),
    )
    filer = session.get(Owner, exp["filer_cik"])
    assert (filer.name, filer.owner_type) == ("Salem-Jackson Kim", "person")
    assert session.get(Issuer, exp["issuer_cik"]).name == "AKAMAI TECHNOLOGIES INC"


def test_feed_item(session, load):
    fi = session.get(FeedItem, load(session, "form144"))
    assert (fi.form_type, fi.direction, fi.codes) == ("144", "sell", ["144"])
    assert (fi.owner_ciks, fi.owner_names, fi.owner_group) == (
        [1845739],
        "Salem-Jackson Kim",
        "1845739",
    )
    assert (fi.shares, fi.value_usd, fi.price) == (2013.0, 257664.0, 128.0)
    assert fi.summary == "Plans to sell 2,013 sh (~$257,664) around Sep 25, 2026"
    assert (fi.plan_10b5_1, fi.top_role) == ("flag", "Other officer")
    assert (fi.issuer_cik, fi.issuer_name, fi.filed_date) == (
        1086222,
        "AKAMAI TECHNOLOGIES INC",
        date(2026, 9, 25),
    )
    assert fi.lag_days is None and fi.first_trade_date is None


def test_known_form4_role_wins_for_top_role(session, load):
    make_issuer(session, cik=1086222, name="AKAMAI TECHNOLOGIES INC", ticker="AKAM")
    session.add(Owner(cik=1845739, name="Salem-Jackson Kim", owner_type="person"))
    session.flush()
    upsert_owner_role(
        session,
        owner_cik=1845739,
        issuer_cik=1086222,
        is_director=False,
        is_officer=True,
        officer_title="EVP and Chief Financial Officer",
        is_ten_pct_owner=False,
        is_other=False,
        other_text=None,
        filed=date(2026, 3, 2),
    )
    fi = session.get(FeedItem, load(session, "form144"))
    assert (fi.top_role, fi.ticker) == ("CFO", "AKAM")


def test_renormalizing_keeps_match(session, load):
    acc = load(session, "form144")
    session.get(Form144Notice, acc).matched_sale_accession = "0001845739-26-000001"
    session.flush()
    load(session, "form144", force=True)
    session.expire_all()
    assert session.get(Form144Notice, acc).matched_sale_accession == "0001845739-26-000001"
    assert len(session.scalars(select(Form144Notice)).all()) == 1


def test_issuer_falls_back_to_subject_company(session, fixture_bytes):
    from tests.factories import make_filing

    sgml = SgmlFiling.from_txt(fixture_bytes("form144"))
    xml = sgml.xml_documents()[0].xml()
    assert xml is not None
    doc = replace(parse_form144(xml), issuer_cik=None)
    filing = make_filing(
        session, accession_no=sgml.accession_no, form_type="144", issuer_cik=None, owners=()
    )
    normalize_form144(session, filing, doc, sgml)
    assert session.get(Form144Notice, sgml.accession_no).issuer_cik == 1086222


def test_summary_leaves_out_unknown_parts():
    assert form144_summary(1000.0, None, None) == "Plans to sell 1,000 sh"
    assert form144_summary(None, 5000.4, date(2026, 1, 2)) == (
        "Plans to sell (~$5,000) around Jan 02, 2026"
    )
    assert form144_summary(None, None, None) == "Plans to sell"
