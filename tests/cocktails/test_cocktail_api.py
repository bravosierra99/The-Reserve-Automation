"""Tests for cocktail API endpoints.

Uses in-memory SQLite database for test isolation.
"""

from pathlib import Path

import pytest

# formatApiError lives in the base-page module (extracted from base.html
# July 2026 for vitest coverage — tests/js/base-page.test.js).
_BASE_PAGE_MODULE = (
    Path(__file__).parents[2]
    / "src/reserve_automation/web/static/js/components/base-page.js"
)


class TestCocktailPagesRender:
    """Smoke-test that the HTML pages render (catches Jinja/template breakage
    that the JSON API tests cannot see)."""

    def test_cocktails_page_renders(self, test_client):
        response = test_client.get("/cocktails")
        assert response.status_code == 200
        # Shared error helper is wired in via the base-page module
        assert "/static/js/components/base-page.js" in response.text
        assert "formatApiError" in _BASE_PAGE_MODULE.read_text(encoding="utf-8")
        # The page logic lives in static/js/cocktails/cocktails-page.js
        # (extracted July 2026); the page must load it and the module must
        # define the Alpine factory. Behavior is unit-tested in
        # tests/js/cocktails-page.test.js.
        assert '/static/js/cocktails/cocktails-page.js"></script>' in response.text, (
            "cocktails page no longer loads its component module — the page "
            "would render but the Alpine component would be undefined"
        )
        page_js = (
            Path(__file__).parents[2]
            / "src/reserve_automation/web/static/js/cocktails/cocktails-page.js"
        ).read_text(encoding="utf-8")
        assert "window.cocktailsApp" in page_js

    def test_cocktail_detail_page_renders(self, test_client):
        mule = next(c for c in test_client.get("/api/v1/cocktails").json()
                    if c["name"] == "Moscow Mule")
        response = test_client.get(f"/cocktails/{mule['id']}/detail")
        assert response.status_code == 200
        # The page logic (incl. the create-on-the-fly ingredient flow) lives in
        # static/js/cocktails/cocktail-detail.js (extracted July 2026); the
        # page must load it. Behavior is unit-tested in
        # tests/js/cocktail-detail.test.js.
        assert '/static/js/cocktails/cocktail-detail.js"></script>' in response.text, (
            "cocktail detail page no longer loads its component module — the "
            "page would render but the Alpine component would be undefined"
        )
        detail_js = (
            Path(__file__).parents[2]
            / "src/reserve_automation/web/static/js/cocktails/cocktail-detail.js"
        ).read_text(encoding="utf-8")
        assert "window.cocktailDetailApp" in detail_js
        assert "createAndSelectIngredient" in detail_js


class TestCocktailList:
    """Test GET /api/v1/cocktails."""

    def test_list_cocktails(self, test_client):
        response = test_client.get("/api/v1/cocktails")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        names = [c["name"] for c in data]
        assert "Moscow Mule" in names
        assert "Old Fashioned" in names

    def test_list_with_search(self, test_client):
        response = test_client.get("/api/v1/cocktails?q=mule")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Moscow Mule"

    def test_list_search_by_ingredient(self, test_client):
        response = test_client.get("/api/v1/cocktails?q=bourbon")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Old Fashioned"


class TestCocktailGet:
    """Test GET /api/v1/cocktails/{id}."""

    def test_get_cocktail(self, test_client):
        # Get ID first
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        mule = next(c for c in cocktails if c["name"] == "Moscow Mule")

        response = test_client.get(f"/api/v1/cocktails/{mule['id']}")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Moscow Mule"
        assert data["method"] == "built"
        assert len(data["ingredients"]) == 3
        assert data["ingredients"][0]["ingredient"] == "Vodka"
        assert data["ingredients"][0]["amount"] == 2
        assert data["ingredients"][0]["unit"] == "oz"

    def test_get_nonexistent(self, test_client):
        response = test_client.get("/api/v1/cocktails/99999")
        assert response.status_code == 404


class TestCocktailSearch:
    """Test GET /api/v1/cocktails/search."""

    def test_search_by_name(self, test_client):
        response = test_client.get("/api/v1/cocktails/search?q=old")
        assert response.status_code == 200
        data = response.json()
        names = [c["name"] for c in data]
        assert "Old Fashioned" in names

    def test_search_empty(self, test_client):
        response = test_client.get("/api/v1/cocktails/search?q=")
        assert response.status_code == 400


class TestCocktailCreate:
    """Test POST /api/v1/cocktails."""

    def test_create_cocktail(self, test_client):
        response = test_client.post("/api/v1/cocktails", json={
            "name": "Whiskey Sour",
            "description": "A classic sour cocktail",
            "ingredients": [
                {"ingredient": "Bourbon", "amount": 2, "unit": "oz"},
                {"ingredient": "Lime Juice", "amount": 0.75, "unit": "oz"},
                {"ingredient": "Simple Syrup", "amount": 0.5, "unit": "oz"},
            ],
            "instructions": ["Combine in shaker", "Shake with ice", "Strain into glass"],
            "method": "shaken",
            "style": "classic",
            "glassware": "coupe",
            "garnish": "cherry",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Whiskey Sour"
        assert data["method"] == "shaken"
        assert len(data["ingredients"]) == 3
        assert data["id"] is not None

    def test_create_duplicate_fails(self, test_client):
        response = test_client.post("/api/v1/cocktails", json={
            "name": "Moscow Mule",
        })
        assert response.status_code == 409

    def test_create_without_name_fails(self, test_client):
        response = test_client.post("/api/v1/cocktails", json={})
        assert response.status_code == 422


class TestCocktailUpdate:
    """Test PUT /api/v1/cocktails/{id}."""

    def test_update_cocktail(self, test_client):
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        mule = next(c for c in cocktails if c["name"] == "Moscow Mule")

        response = test_client.put(f"/api/v1/cocktails/{mule['id']}", json={
            "garnish": "lime wheel",
            "description": "A refreshing copper mug cocktail",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["garnish"] == "lime wheel"
        assert data["description"] == "A refreshing copper mug cocktail"

    def test_update_nonexistent(self, test_client):
        response = test_client.put("/api/v1/cocktails/99999", json={"garnish": "test"})
        assert response.status_code == 404

    def test_parent_cocktail_survives_edit_roundtrip(self, test_client):
        """Regression (July 2026): parent_cocktail was missing from API
        responses, so the detail page's edit form seeded it as null and every
        recipe edit silently wiped a stored parent."""
        created = test_client.post("/api/v1/cocktails", json={
            "name": "Kentucky Mule",
            "parent_cocktail": "Moscow Mule",
            "ingredients": [{"ingredient": "Bourbon", "amount": 2, "unit": "oz"}],
        })
        assert created.status_code == 200
        cid = created.json()["id"]

        # The GET response must expose the parent (this was the missing piece)
        fetched = test_client.get(f"/api/v1/cocktails/{cid}").json()
        assert fetched["parent_cocktail"] == "Moscow Mule"

        # An edit that PUTs the fetched value back must not change it —
        # mirrors what the detail page's edit form sends.
        response = test_client.put(f"/api/v1/cocktails/{cid}", json={
            "garnish": "candied ginger",
            "parent_cocktail": fetched["parent_cocktail"] or None,
        })
        assert response.status_code == 200
        assert response.json()["parent_cocktail"] == "Moscow Mule"

        test_client.delete(f"/api/v1/cocktails/{cid}")


class TestCocktailDelete:
    """Test DELETE /api/v1/cocktails/{id}."""

    def test_delete_cocktail(self, test_client):
        # Create one to delete
        response = test_client.post("/api/v1/cocktails", json={
            "name": "ToDeleteCocktail",
        })
        assert response.status_code == 200
        cid = response.json()["id"]

        response = test_client.delete(f"/api/v1/cocktails/{cid}")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        # Verify it's gone
        response = test_client.get(f"/api/v1/cocktails/{cid}")
        assert response.status_code == 404

    def test_delete_nonexistent(self, test_client):
        response = test_client.delete("/api/v1/cocktails/99999")
        assert response.status_code == 404


class TestCocktailPages:
    """Test page routes."""

    def test_cocktails_page(self, test_client):
        response = test_client.get("/cocktails")
        assert response.status_code == 200

    def test_cocktail_detail_page(self, test_client):
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        cid = cocktails[0]["id"]
        response = test_client.get(f"/cocktails/{cid}/detail")
        assert response.status_code == 200


class TestIngredientYamlRoundtrip:
    """Test that ingredients survive create+read cycle."""

    def test_created_cocktail_has_ingredients(self, test_client):
        """Creating a cocktail and reading it back preserves ingredients."""
        # Use the Whiskey Sour we created earlier
        response = test_client.get("/api/v1/cocktails/search?q=whiskey sour")
        data = response.json()
        if not data:
            pytest.skip("Whiskey Sour not found (depends on test ordering)")

        sour = data[0]
        assert len(sour["ingredients"]) == 3
        assert sour["ingredients"][0]["ingredient"] == "Bourbon"
        assert sour["ingredients"][0]["amount"] == 2
        assert sour["ingredients"][0]["unit"] == "oz"
