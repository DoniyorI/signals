from tests.api.seed import DOE, FUND, ROE, SMALL_FUND


def test_default_sort_rating_desc(api, world):
    items = api.get("/api/screener/insiders").json()["items"]
    assert [i["owner"]["cik"] for i in items] == [DOE, ROE]


def test_filters_role_and_min_rating(api, world):
    ceo_only = api.get("/api/screener/insiders", params={"roles": ["CEO"]}).json()["items"]
    assert [i["owner"]["cik"] for i in ceo_only] == [DOE]

    none = api.get("/api/screener/insiders", params={"min_rating": 99}).json()["items"]
    assert none == []


def test_window_return_filter(api, world):
    items = api.get("/api/screener/insiders", params={"window": "1y", "min_return": 0.15}).json()[
        "items"
    ]
    assert [i["owner"]["cik"] for i in items] == [DOE]


def test_pagination_stable(api, world):
    p1 = api.get("/api/screener/insiders", params={"limit": 1}).json()
    p2 = api.get("/api/screener/insiders", params={"limit": 1, "cursor": p1["next_cursor"]}).json()
    ciks = [i["owner"]["cik"] for i in p1["items"] + p2["items"]]
    assert ciks == [DOE, ROE]
    assert p2["next_cursor"] is None


def test_funds_tracked_only(api, world):
    tracked = api.get("/api/screener/funds").json()["items"]
    assert [i["fund"]["cik"] for i in tracked] == [FUND]

    all_funds = api.get("/api/screener/funds", params={"tracked_only": "false"}).json()["items"]
    assert {i["fund"]["cik"] for i in all_funds} == {FUND, SMALL_FUND}
