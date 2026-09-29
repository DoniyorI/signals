import pytest

from tests.api.seed import (
    A_DOE_144,
    A_GROUP_BUY,
    A_ROE_144,
    ACME,
)


def test_order_and_pagination(api, world):
    p1 = api.get("/api/feed", params={"limit": 4}).json()
    p2 = api.get("/api/feed", params={"limit": 4, "cursor": p1["next_cursor"]}).json()
    accs = [i["accession_no"] for i in p1["items"] + p2["items"]]
    assert len(accs) == 6 == len(set(accs))
    assert p2["next_cursor"] is None
    assert accs == list(world.feed_order)
    ts = [i["accepted_at"] for i in p1["items"]]
    assert ts == sorted(ts, reverse=True)


@pytest.mark.parametrize(
    "params,attr",
    [
        ({"direction": ["buy"]}, "buy_accessions"),
        ({"forms": ["13F"]}, "f13_accessions"),
        ({"include_10b5_1": "false"}, "non_planned_accessions"),
        ({"min_value": 1_000_000}, "big_accessions"),
        ({"owner_cik": 2000002}, "roe_accessions"),
        ({"badges": ["cluster_buy"]}, "cluster_accessions"),
    ],
)
def test_filters(api, world, params, attr):
    got = {i["accession_no"] for i in api.get("/api/feed", params=params).json()["items"]}
    assert got == getattr(world, attr)


def test_csv(api, world):
    r = api.get("/api/feed", params={"format": "csv"})
    assert r.headers["content-type"].startswith("text/csv")
    assert r.text.count("\n") == 7  # header + 6 rows


def test_invalid_cursor_400(api):
    assert api.get("/api/feed", params={"cursor": "zzz"}).status_code == 400


def test_owners_and_sec_url_shape(api, world):
    items = {i["accession_no"]: i for i in api.get("/api/feed").json()["items"]}
    group = items[A_GROUP_BUY]
    assert [o["name"] for o in group["owners"]] == ["Acme Holdings LP", "Smith John"]
    assert [o["cik"] for o in group["owners"]] == [2000003, 2000004]
    assert group["issuer"] == {"cik": ACME, "name": "Acme Corp", "ticker": "ACME"}
    assert group["sec_url"].startswith("https://www.sec.gov/Archives/edgar/data/2000003/")


def test_summary(api, world):
    s = api.get("/api/feed/summary", params={"date": "2024-06-05"}).json()
    assert s["counts_by_form"] == world.counts_on_0605
    assert [i["accession_no"] for i in s["top_buys"]] == world.top_buys_0605
    assert [i["accession_no"] for i in s["top_sells"]] == [A_ROE_144]
    assert [i["accession_no"] for i in s["late_filings"]] == [A_GROUP_BUY]
    (cluster,) = s["clusters"]
    assert cluster["issuer"]["cik"] == ACME
    assert (cluster["start_date"], cluster["end_date"]) == ("2024-05-29", "2024-06-03")
    assert cluster["owner_count"] == 3
    assert cluster["total_value_usd"] == pytest.approx(4_010_000.0)


def test_summary_defaults_to_today(api, world):
    s = api.get("/api/feed/summary").json()
    assert s["date"] == "2024-08-26"  # FROZEN_NOW's date
    assert s["counts_by_form"] == {}


def test_form144_matched_shows_in_feed(api, world):
    items = {
        i["accession_no"] for i in api.get("/api/feed", params={"forms": ["144"]}).json()["items"]
    }
    assert items == {A_ROE_144}  # A_DOE_144 was never a feed item (only the matched sale is)
    assert A_DOE_144 not in items
