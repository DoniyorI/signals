from dataclasses import replace
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

from signals.ingest.parsers.ownership import parse_ownership
from signals.sec.sgml import SgmlFiling


def load_script():
    spec = spec_from_file_location(
        "spot_check", Path(__file__).parents[3] / "scripts/spot_check.py"
    )
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compare_bulk_rounding_and_single_share_mismatch(fixture_bytes):
    script = load_script()
    xml = SgmlFiling.from_txt(fixture_bytes("form4_buy_single")).xml_documents()[0].xml()
    assert xml is not None
    doc = parse_ownership(xml)
    tx = next(row for row in doc.rows if row.code == "P")
    doc = replace(doc, rows=(replace(tx, price=12.3456),))
    row = SimpleNamespace(
        table_kind=tx.table_kind,
        row_no=tx.row_no,
        code=tx.code,
        transaction_date=tx.transaction_date,
        shares=tx.shares,
        price=12.35,
        shares_owned_after=tx.shares_owned_after,
    )
    assert script.compare([row], doc) == []
    row.shares += 1
    mismatch = script.compare([row], doc)
    assert len(mismatch) == 1 and "shares:" in mismatch[0]


def test_compare_missing_extra_and_null_rows(fixture_bytes):
    script = load_script()
    xml = SgmlFiling.from_txt(fixture_bytes("form4_buy_single")).xml_documents()[0].xml()
    assert xml is not None
    doc = parse_ownership(xml)
    assert len(script.compare([], doc)) >= 1
    tx = next(row for row in doc.rows if row.code == "P")
    row = SimpleNamespace(
        table_kind=tx.table_kind,
        row_no=tx.row_no,
        code=tx.code,
        transaction_date=tx.transaction_date,
        shares=None,
        price=tx.price,
        shares_owned_after=tx.shares_owned_after,
    )
    assert len(script.compare([row], doc)) == 1


def test_sample_is_bounded_reproducible_and_covers_populated_years(session):
    from datetime import date

    from tests.factories import make_filing, make_transaction

    script = load_script()
    for year in range(2016, 2027):
        for index in range(3):
            accession = f"0002000001-{year % 100:02d}-{index:06d}"
            make_filing(session, accession_no=accession, filed_date=date(year, 6, 1))
            make_transaction(session, accession_no=accession)
    sample = script.pick_sample(session)
    assert len(sample) == len(set(sample)) == 20
    assert sample == script.pick_sample(session)
    assert {int(accession[11:13]) for accession in sample} == set(range(16, 27))
    assert script.pick_sample(session, n=0) == []
    assert len(script.pick_sample(session, n=100)) == 33
