from tests.api.seed import A_ROE_144, ACME, DOE, FUND


def test_crud(api):
    created = api.post("/api/watchlists", json={"name": "My List"}).json()
    wl_id = created["id"]
    assert created["items"] == []

    listed = api.get("/api/watchlists").json()
    assert any(w["id"] == wl_id for w in listed)

    got = api.get(f"/api/watchlists/{wl_id}").json()
    assert got["name"] == "My List"

    assert api.delete(f"/api/watchlists/{wl_id}").status_code == 204
    assert api.get(f"/api/watchlists/{wl_id}").status_code == 404


def test_duplicate_name_409(api):
    assert api.post("/api/watchlists", json={"name": "Dup"}).status_code == 201
    assert api.post("/api/watchlists", json={"name": "Dup"}).status_code == 409


def test_add_remove_items_and_404_unknown(api, world):
    wl_id = api.post("/api/watchlists", json={"name": "Items"}).json()["id"]

    unknown = api.post(f"/api/watchlists/{wl_id}/items", json={"kind": "insider", "cik": 9999999})
    assert unknown.status_code == 404

    added = api.post(f"/api/watchlists/{wl_id}/items", json={"kind": "insider", "cik": DOE}).json()
    assert {(i["kind"], i["cik"]) for i in added["items"]} == {("insider", DOE)}

    again = api.post(f"/api/watchlists/{wl_id}/items", json={"kind": "insider", "cik": DOE}).json()
    assert len(again["items"]) == 1  # adding twice is a no-op

    assert api.delete(f"/api/watchlists/{wl_id}/items/insider/{DOE}").status_code == 204
    after = api.get(f"/api/watchlists/{wl_id}").json()
    assert after["items"] == []


def test_activity_matches_watched(api, world):
    wl_id = api.post("/api/watchlists", json={"name": "Watch"}).json()["id"]
    api.post(f"/api/watchlists/{wl_id}/items", json={"kind": "company", "cik": ACME})
    api.post(f"/api/watchlists/{wl_id}/items", json={"kind": "fund", "cik": FUND})

    body = api.get(f"/api/watchlists/{wl_id}/activity").json()
    accessions = {i["accession_no"] for i in body["items"]}
    assert len(accessions) == 5
    assert A_ROE_144 not in accessions
