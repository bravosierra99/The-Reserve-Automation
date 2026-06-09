"""API shape tests for the bottle collection endpoint.

The /bottles page fetches ALL its data from /api/v1/bottles/collection.
If the API returns the wrong shape, the page renders empty with no error.
These tests ensure the API contract is stable.

What breaks without these tests:
- A field renamed on BottleMetadata silently makes all cards blank
- A missing 'count' key causes the JS counter to show 'undefined'
- A 500 error on the collection route leaves users staring at a spinner
"""



COLLECTION_URL = "/api/v1/bottles/collection"
REQUIRED_BOTTLE_FIELDS = {"id", "name", "producer", "type", "beverage_type", "inventory"}


class TestCollectionAPIShape:
    def test_collection_returns_200(self, ui_client):
        resp = ui_client.get(COLLECTION_URL)
        assert resp.status_code == 200

    def test_collection_returns_expected_keys(self, ui_client):
        data = ui_client.get(COLLECTION_URL).json()
        assert "bottles" in data, "Response must have 'bottles' key"
        assert "count" in data, "Response must have 'count' key"

    def test_count_matches_bottles_length(self, ui_client):
        data = ui_client.get(COLLECTION_URL).json()
        assert data["count"] == len(data["bottles"]), (
            "count field must equal len(bottles); mismatch breaks the UI counter"
        )

    def test_bottles_is_a_list(self, ui_client):
        data = ui_client.get(COLLECTION_URL).json()
        assert isinstance(data["bottles"], list)


class TestCollectionAPIWithData:
    """Require seeded data so we can inspect actual bottle records."""

    def test_seeded_bottles_appear_in_collection(self, ui_client, seeded_bottles):
        data = ui_client.get(COLLECTION_URL).json()
        ids = {str(b["id"]) for b in data["bottles"]}
        assert str(seeded_bottles["whiskey_id"]) in ids, "Seeded whiskey not in collection"
        assert str(seeded_bottles["wine_id"]) in ids, "Seeded wine not in collection"

    def test_each_bottle_has_required_fields(self, ui_client, seeded_bottles):
        data = ui_client.get(COLLECTION_URL).json()
        for bottle in data["bottles"]:
            missing = REQUIRED_BOTTLE_FIELDS - bottle.keys()
            assert not missing, (
                f"Bottle {bottle.get('id')} missing fields: {missing}. "
                f"JS grid will silently show blank values for these."
            )

    def test_bottle_id_is_present_and_truthy(self, ui_client, seeded_bottles):
        data = ui_client.get(COLLECTION_URL).json()
        for bottle in data["bottles"]:
            assert bottle.get("id"), f"Bottle missing id: {bottle}"

    def test_beverage_type_field_present(self, ui_client, seeded_bottles):
        """beverage_type drives the UI filter buttons; None/missing breaks filtering."""
        data = ui_client.get(COLLECTION_URL).json()
        for bottle in data["bottles"]:
            assert "beverage_type" in bottle, (
                f"Bottle {bottle.get('id')} missing beverage_type; filter will silently skip it"
            )

    def test_whiskey_bottle_has_correct_type(self, ui_client, seeded_bottles):
        data = ui_client.get(COLLECTION_URL).json()
        wid = str(seeded_bottles["whiskey_id"])
        bottle = next((b for b in data["bottles"] if str(b["id"]) == wid), None)
        assert bottle is not None
        assert bottle["type"] == "whiskey"

    def test_wine_bottle_has_correct_type(self, ui_client, seeded_bottles):
        data = ui_client.get(COLLECTION_URL).json()
        wid = str(seeded_bottles["wine_id"])
        bottle = next((b for b in data["bottles"] if str(b["id"]) == wid), None)
        assert bottle is not None
        assert bottle["type"] == "wine"


class TestBottleSearchAPI:
    """Bottle search backs the manual-tasting bottle picker.

    API contract: GET /api/v1/bottles/search?q=<term>
    Returns: {"query": str, "results": [{"bottle_name": str, "bottle_path": str, ...}]}
    """

    def test_search_returns_200(self, ui_client, seeded_bottles):
        resp = ui_client.get("/api/v1/bottles/search?q=Weller")
        assert resp.status_code == 200

    def test_search_response_has_results_key(self, ui_client, seeded_bottles):
        data = ui_client.get("/api/v1/bottles/search?q=Weller").json()
        assert "results" in data, (
            "Search response must have 'results' key; "
            "manual tasting picker reads data.results to populate bottle list"
        )

    def test_search_results_is_a_list(self, ui_client, seeded_bottles):
        data = ui_client.get("/api/v1/bottles/search?q=Weller").json()
        assert isinstance(data["results"], list)

    def test_search_finds_seeded_bottle(self, ui_client, seeded_bottles):
        data = ui_client.get("/api/v1/bottles/search?q=Weller").json()
        names = [r.get("bottle_name", "") for r in data["results"]]
        assert any("Weller" in n for n in names), (
            "Search for 'Weller' returned no matching bottles; "
            "manual tasting bottle picker will show empty results even when bottle exists in DB"
        )

    def test_search_returns_empty_results_for_no_match(self, ui_client, seeded_bottles):
        data = ui_client.get("/api/v1/bottles/search?q=XYZZY_NO_MATCH_9999").json()
        assert data.get("results") == [], "No-match search must return empty results list"

    def test_search_without_query_does_not_500(self, ui_client):
        resp = ui_client.get("/api/v1/bottles/search")
        assert resp.status_code != 500, "Missing q param must not cause a 500"
