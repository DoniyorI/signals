import pytest

from signals.domain.accession import (
    accession_nodash,
    filing_index_url,
    filing_txt_url,
    normalize_accession,
)
from signals.domain.owner_group import owner_group_ciks, owner_group_key
from signals.domain.portfolio import (
    allocation_slices,
    effective_n,
    fund_high_conviction,
    top5_weight,
)
from signals.domain.roles import normalize_roles, top_role
from signals.domain.types import BENCHMARK_SYMBOLS, SECTOR_ETF, Role, Sector


def test_accession_forms():
    assert normalize_accession("000032019324000001") == "0000320193-24-000001"
    assert normalize_accession("0000320193-24-000001") == "0000320193-24-000001"
    assert accession_nodash("0000320193-24-000001") == "000032019324000001"
    with pytest.raises(ValueError):
        normalize_accession("12345")


def test_filing_urls():
    assert filing_txt_url(320193, "0000320193-24-000001") == (
        "https://www.sec.gov/Archives/edgar/data/320193/0000320193-24-000001.txt"
    )
    assert filing_index_url(320193, "0000320193-24-000001") == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019324000001/"
        "0000320193-24-000001-index.htm"
    )


def test_owner_group_key():
    assert owner_group_key([1067983, 315090]) == "315090|1067983"
    assert owner_group_key([5, 5]) == "5"
    assert owner_group_ciks("315090|1067983") == [315090, 1067983]
    with pytest.raises(ValueError):
        owner_group_key([])


@pytest.mark.parametrize(
    "title,flags,expected",
    [
        ("Chief Executive Officer", dict(is_officer=True), [Role.CEO]),
        ("President and CEO", dict(is_officer=True), [Role.CEO, Role.PRESIDENT]),
        ("EVP, CFO", dict(is_officer=True), [Role.CFO]),
        ("Principal Financial Officer", dict(is_officer=True), [Role.CFO]),
        ("Co-CEO", dict(is_officer=True), [Role.CEO]),
        (
            "Chairman of the Board",
            dict(is_officer=True, is_director=True),
            [Role.CHAIR, Role.DIRECTOR],
        ),
        ("SVP, General Counsel", dict(is_officer=True), [Role.GENERAL_COUNSEL]),
        ("COO", dict(is_officer=True), [Role.COO]),
        ("Executive Vice President", dict(is_officer=True), [Role.OTHER_OFFICER]),
        ("Vice Chairman", dict(is_officer=True), [Role.OTHER_OFFICER]),
        ("Chief Accounting Officer", dict(is_officer=True), [Role.OTHER_OFFICER]),
        (None, dict(is_officer=True), [Role.OTHER_OFFICER]),
        (None, dict(is_ten_pct_owner=True), [Role.TEN_PCT_OWNER]),
        (None, dict(is_director=True, is_other=True), [Role.DIRECTOR, Role.OTHER]),
    ],
)
def test_normalize_roles(title, flags, expected):
    base = dict(is_director=False, is_officer=False, is_ten_pct_owner=False, is_other=False)
    assert normalize_roles(title, **{**base, **flags}) == expected


def test_top_role_and_constants():
    assert top_role([Role.DIRECTOR, Role.CFO]) == Role.CFO
    assert top_role([]) is None
    assert SECTOR_ETF[Sector("Real Estate")] == "XLRE"
    assert BENCHMARK_SYMBOLS[:2] == ("SPY", "QQQ") and len(BENCHMARK_SYMBOLS) == 13


def test_portfolio_helpers():
    assert effective_n([0.5, 0.5]) == 2.0 and effective_n([1.0]) == 1.0
    assert effective_n([0.25] * 4) == 4.0 and effective_n([2, 2]) == 2.0
    assert effective_n([]) is None
    assert top5_weight([0.3, 0.2, 0.2, 0.1, 0.1, 0.1]) == pytest.approx(0.9)
    assert [(s["key"], s["weight"]) for s in allocation_slices({"A": 30, "B": 70})] == [
        ("B", 0.7),
        ("A", 0.3),
    ]
    assert fund_high_conviction([0.06, 0.01, 0.01], ["ADD", "NEW", "ADD"], [60, 50, 1]) == [
        True,
        True,
        False,
    ]
