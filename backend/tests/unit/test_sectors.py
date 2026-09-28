"""SIC code to sector mapping (spec 7.7)."""

import pytest

from signals.db.models import Issuer
from signals.domain.types import Sector
from signals.reference.sectors import assign_sectors, load_sic_rules, sector_for_sic
from tests.factories import make_issuer

CASES = {
    3674: "Technology",
    3571: "Technology",
    3577: "Technology",
    7372: "Technology",
    3661: "Technology",
    2834: "Health Care",
    2836: "Health Care",
    3841: "Health Care",
    8062: "Health Care",
    8071: "Health Care",
    6022: "Financials",
    6211: "Financials",
    6311: "Financials",
    6798: "Real Estate",
    6512: "Real Estate",
    1311: "Energy",
    2911: "Energy",
    1381: "Energy",
    4922: "Energy",
    4911: "Utilities",
    4931: "Utilities",
    4941: "Utilities",
    4813: "Communication Services",
    4841: "Communication Services",
    7812: "Communication Services",
    2711: "Communication Services",
    5812: "Consumer Discretionary",
    3711: "Consumer Discretionary",
    5961: "Consumer Discretionary",
    7011: "Consumer Discretionary",
    2080: "Consumer Staples",
    2000: "Consumer Staples",
    5411: "Consumer Staples",
    2111: "Consumer Staples",
    2844: "Consumer Staples",
    3721: "Industrials",
    4512: "Industrials",
    3531: "Industrials",
    4011: "Industrials",
    8711: "Industrials",
    1040: "Materials",
    2821: "Materials",
    2800: "Materials",
    3312: "Materials",
    1400: "Materials",
}


@pytest.mark.parametrize(("sic", "sector"), CASES.items())
def test_sector_for_sic(sic, sector):
    assert sector_for_sic(sic) == Sector(sector)


@pytest.mark.parametrize("sic", [6770, 9995, None])
def test_no_sector(sic):
    assert sector_for_sic(sic) is None


def test_every_four_digit_sic_is_covered():
    rules = load_sic_rules()
    uncovered = [
        sic for sic in range(10000) if not any(r.sic_from <= sic <= r.sic_to for r in rules)
    ]
    assert uncovered == []


def test_assign_sectors(session):
    make_issuer(session, cik=1000009, sic=2834, sector=None)
    assert assign_sectors(session, [1000009]) == 1
    issuer = session.get(Issuer, 1000009)
    assert issuer is not None and issuer.sector == "Health Care"


def test_assign_sectors_is_a_derivation_and_idempotent(session):
    make_issuer(session, cik=1000010, sic=6798, sector=None, ticker="REIT")
    make_issuer(session, cik=1000011, sic=None, sector="Technology", ticker="NOSIC")
    make_issuer(session, cik=1000012, sic=6770, sector="Financials", ticker="SPAC")
    assert assign_sectors(session) == 3
    sectors = {cik: session.get(Issuer, cik) for cik in (1000010, 1000011, 1000012)}
    assert {cik: i.sector for cik, i in sectors.items() if i is not None} == {
        1000010: "Real Estate",
        1000011: None,
        1000012: None,
    }
    assert assign_sectors(session) == 0
