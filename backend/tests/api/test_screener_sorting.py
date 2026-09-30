"""Displayed screener columns must order the whole result, across cursor pages."""

from datetime import date

import pytest

from signals.db.models import FundNavDaily, OwnerRole, Ticker
from tests.factories import make_fund_manager, make_issuer, make_owner, make_profile_stats


@pytest.fixture
def sortable_profiles(session):
    for cik, name in [(10, "Zulu"), (20, "alpha"), (30, "Alpha"), (40, "Beta")]:
        make_owner(session, cik=cik, name=name)
        manager = make_fund_manager(session, cik=cik, name=name, is_tracked=True)
        manager.latest_value_usd = {10: 200, 20: 100, 30: 100, 40: None}[cik]
        manager.latest_positions = {10: 2, 20: 3, 30: 3, 40: None}[cik]
        if cik != 40:
            make_issuer(
                session,
                cik=cik,
                name="Alpha" if cik == 20 else "Other",
                ticker="ZZZ" if cik != 20 else None,
            )
            session.add(
                OwnerRole(
                    owner_cik=cik,
                    issuer_cik=cik,
                    roles=["Director"] if cik == 10 else ["CEO", "Officer"],
                )
            )
        for kind in ["insider", "fund"]:
            for basis in ["filed", "executed"]:
                stats = make_profile_stats(session, kind=kind, cik=cik, basis=basis)
                stats.n_complete = 2
                stats.rating = 100 - cik
                stats.primary_issuer_cik = cik if cik != 40 else None
                stats.sector = {10: "Zulu", 20: "alpha", 30: "Alpha", 40: None}[cik]
                stats.risk_label = {10: "high", 20: "low", 30: "medium", 40: None}[cik]
        if cik != 40:
            for basis, day, coverage in [
                ("filed", date(2024, 1, 1), {10: 0.9, 20: 0.1, 30: 0.1}[cik]),
                ("filed", date(2024, 1, 2), {10: 0.2, 20: 0.8, 30: 0.8}[cik]),
                ("executed", date(2024, 1, 3), {10: 0.9, 20: 0.1, 30: 0.1}[cik]),
            ]:
                session.add(FundNavDaily(cik=cik, basis=basis, date=day, nav=1, coverage=coverage))
    # Company sort must use the displayed current ticker, never a historic one.
    session.add(
        Ticker(
            issuer_cik=10,
            symbol="AAA",
            valid_from=date(2000, 1, 1),
            valid_to=date(2009, 12, 31),
            source="test",
        )
    )
    session.flush()


@pytest.mark.parametrize("order", ["asc", "desc"])
@pytest.mark.parametrize(
    "kind,sort,asc,desc",
    [
        ("insiders", "owner", [20, 30, 40, 10], [10, 40, 30, 20]),
        ("insiders", "issuer", [20, 10, 30, 40], [30, 10, 20, 40]),
        ("insiders", "roles", [20, 30, 10, 40], [10, 30, 20, 40]),
        ("insiders", "sector", [20, 30, 10, 40], [10, 30, 20, 40]),
        ("insiders", "risk_label", [20, 30, 10, 40], [10, 30, 20, 40]),
        ("funds", "fund", [20, 30, 40, 10], [10, 40, 30, 20]),
        ("funds", "latest_value_usd", [20, 30, 10, 40], [10, 30, 20, 40]),
        ("funds", "positions", [10, 20, 30, 40], [30, 20, 10, 40]),
        ("funds", "top_sector", [20, 30, 10, 40], [10, 30, 20, 40]),
        ("funds", "risk_label", [20, 30, 10, 40], [10, 30, 20, 40]),
        ("funds", "coverage_pct", [10, 20, 30, 40], [30, 20, 10, 40]),
    ],
)
def test_display_column_sort_pages_with_ties_and_nulls(
    api,
    sortable_profiles,
    kind,
    sort,
    order,
    asc,
    desc,
):
    cursor = None
    items = []
    for _ in range(5):
        response = api.get(
            f"/api/screener/{kind}",
            params={
                "sort": sort,
                "order": order,
                "limit": 1,
                "cursor": cursor or "",
            },
        )
        assert response.status_code == 200, response.text
        page = response.json()
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert cursor is None
    identity = "owner" if kind == "insiders" else "fund"
    assert [item[identity]["cik"] for item in items] == (asc if order == "asc" else desc)
    if sort == "coverage_pct":
        assert [item["coverage_pct"] for item in items] == (
            [0.2, 0.8, 0.8, None] if order == "asc" else [0.8, 0.8, 0.2, None]
        )


def test_coverage_sort_matches_displayed_filed_coverage_on_executed_basis(api, sortable_profiles):
    response = api.get(
        "/api/screener/funds",
        params={
            "sort": "coverage_pct",
            "order": "desc",
            "basis": "executed",
        },
    )
    assert response.status_code == 200
    items = response.json()["items"]
    assert [row["fund"]["cik"] for row in items] == [30, 20, 10, 40]
    assert [row["coverage_pct"] for row in items] == [0.8, 0.8, 0.2, None]
