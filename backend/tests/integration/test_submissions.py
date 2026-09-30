"""submissions.zip loader: issuers, ticker evidence and SEC acceptance timestamps."""

import json
import zipfile
from datetime import date, datetime

import pytest
from sqlalchemy import select

from signals.db.models import FilingAcceptance, Issuer, TickerEvidence
from signals.domain.calendars import ET
from signals.domain.tickers import current_symbol
from signals.reference.companies import (
    load_submissions_zip,
    parse_acceptance_datetime,
    parse_submissions_json,
    parse_submissions_page,
)
from signals.sec.sgml import SgmlFiling


def acme_json(**overrides) -> str:
    doc = {
        "cik": "1000001",
        "name": "Acme Corp",
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "tickers": ["ACME"],
        "exchanges": ["Nasdaq"],
        "filings": {
            "recent": {
                "accessionNumber": [],
                "form": [],
                "filingDate": [],
                "acceptanceDateTime": [],
            },
            "files": [],
        },
    }
    doc.update(overrides)
    return json.dumps(doc)


def test_acceptance_matches_sgml(fixture_bytes, manifest):
    exp = manifest["submissions_owner"]["expect"]
    sgml = SgmlFiling.from_txt(fixture_bytes("form4_buy_single"))
    assert parse_acceptance_datetime(exp["acceptanceDateTime"]) == sgml.accepted_at


def test_parse_acceptance_datetime_rejects_naive_values():
    with pytest.raises(ValueError):
        parse_acceptance_datetime("2025-03-31T13:18:52")


def test_parse_main_file(fixture_bytes, manifest):
    rec = parse_submissions_json(fixture_bytes("submissions_owner"))
    accs = {f.accession_no for f in rec.filings}
    assert manifest["submissions_owner"]["expect"]["accession"] in accs


def test_parse_main_file_fields(fixture_bytes, manifest):
    entry = manifest["submissions_owner"]
    exp = entry["expect"]
    rec = parse_submissions_json(fixture_bytes("submissions_owner"))
    assert (rec.cik, rec.name, rec.entity_type) == (entry["cik"], "Elam Nevan C", "other")
    assert (rec.sic, rec.sic_description, rec.tickers, rec.state_of_inc) == (None, None, (), None)
    assert len(rec.filings) == exp["n_recent"]
    filing = next(f for f in rec.filings if f.accession_no == exp["accession"])
    assert (filing.form, filing.filing_date) == (exp["form"], date.fromisoformat(exp["filingDate"]))
    assert filing.acceptance == datetime.fromisoformat(exp["sgml_accepted_at"])


def test_parse_overflow_page():
    page = json.dumps(
        {
            "accessionNumber": ["0001000001-19-000001", "0001000001-19-000002"],
            "form": ["4", "10-K"],
            "filingDate": ["2019-02-01", "2019-03-01"],
            "acceptanceDateTime": ["2019-02-01T21:05:00.000Z", ""],
        }
    ).encode()
    first, second = parse_submissions_page(page)
    assert (first.accession_no, first.form) == ("0001000001-19-000001", "4")
    assert first.acceptance == datetime(2019, 2, 1, 16, 5, tzinfo=ET)
    assert second.acceptance is None


def test_load_zip_builds_acceptance_and_issuers(session, tmp_path, fixture_bytes, manifest):
    z = tmp_path / "submissions.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(
            f"CIK{manifest['submissions_owner']['cik']:010d}.json",
            fixture_bytes("submissions_owner"),
        )
        zf.writestr("CIK0001000001.json", acme_json())
    res = load_submissions_zip(session, z)
    issuer = session.get(Issuer, 1000001)
    assert res.issuers == 1 and issuer is not None and issuer.sic == 3571
    acc = manifest["submissions_owner"]["expect"]["accession"]
    assert session.get(FilingAcceptance, acc) is not None
    assert load_submissions_zip(session, z).acceptances == 0  # idempotent


def test_load_zip_uses_member_cik_for_overflow_pages_and_tracked_forms_only(session, tmp_path):
    z = tmp_path / "submissions.zip"
    recent = {
        "accessionNumber": ["0001000001-24-000009", "0001000001-24-000010"],
        "form": ["4", "8-K"],
        "filingDate": ["2024-01-16", "2024-01-17"],
        "acceptanceDateTime": ["2024-01-16T21:30:00.000Z", "2024-01-17T13:00:00.000Z"],
    }
    page = {
        "accessionNumber": ["0001000001-19-000001", "0001000001-19-000002"],
        "form": ["13F-HR", "10-K"],
        "filingDate": ["2019-02-01", "2019-03-01"],
        "acceptanceDateTime": ["2019-02-01T21:05:00.000Z", "2019-03-01T12:00:00.000Z"],
    }
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CIK0001000001.json", acme_json(filings={"recent": recent, "files": []}))
        zf.writestr("CIK0001000001-submissions-001.json", json.dumps(page))
    res = load_submissions_zip(session, z)
    assert (res.entities, res.issuers, res.acceptances, res.errors) == (1, 1, 2, 0)
    rows = session.scalars(select(FilingAcceptance).order_by(FilingAcceptance.accession_no)).all()
    assert [(r.accession_no, r.cik, r.form_type) for r in rows] == [
        ("0001000001-19-000001", 1000001, "13F-HR"),
        ("0001000001-24-000009", 1000001, "4"),
    ]
    assert rows[0].filing_date == date(2019, 2, 1)
    assert rows[1].accepted_at == datetime(2024, 1, 16, 16, 30, tzinfo=ET)


def test_load_zip_sets_issuer_fields_and_records_primary_ticker_only(session, tmp_path):
    z = tmp_path / "submissions.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr(
            "CIK0001000001.json",
            acme_json(
                tickers=["ACME", "ACME-P"],
                exchanges=["Nasdaq", "Nasdaq"],
                stateOfIncorporation="DE",
                fiscalYearEnd="0930",
            ),
        )
    load_submissions_zip(session, z, seen_on=date(2026, 9, 27))
    issuer = session.get(Issuer, 1000001)
    assert issuer is not None
    assert (issuer.name, issuer.sic_description, issuer.exchange) == (
        "Acme Corp",
        "Electronic Computers",
        "Nasdaq",
    )
    assert (issuer.state_of_inc, issuer.fiscal_year_end) == ("DE", "0930")
    evidence = session.scalars(select(TickerEvidence).where(TickerEvidence.issuer_cik == 1000001))
    assert [(e.symbol, e.min_seen, e.sources) for e in evidence] == [
        ("ACME", date(2026, 9, 27), ["submissions"])
    ]
    assert current_symbol(session, 1000001) == "ACME"


def test_load_zip_counts_and_skips_bad_members(session, tmp_path):
    z = tmp_path / "submissions.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("CIK0001000002.json", b"{not json")
        zf.writestr("CIK0001000001.json", acme_json())
        zf.writestr("README.txt", b"ignored")
    res = load_submissions_zip(session, z)
    assert (res.entities, res.issuers, res.errors) == (1, 1, 1)
    assert session.get(Issuer, 1000001) is not None
