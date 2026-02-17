"""Tests for ingredient API endpoints.

CRITICAL: These tests use an isolated test vault at /tmp/test-vault-ingredients-*.
NEVER run tests against the real vault.
"""

import pytest
from pathlib import Path


class TestIngredientList:
    """Test GET /api/v1/ingredients endpoints."""

    def test_list_tree(self, test_client):
        """GET /api/v1/ingredients returns tree structure."""
        response = test_client.get("/api/v1/ingredients")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have root nodes: Spirit, Mixer, Garnish
        root_names = [n["name"] for n in data]
        assert "Spirit" in root_names
        assert "Mixer" in root_names
        assert "Garnish" in root_names

    def test_list_tree_has_children(self, test_client):
        """Tree nodes have children populated."""
        response = test_client.get("/api/v1/ingredients")
        data = response.json()
        spirit = next(n for n in data if n["name"] == "Spirit")
        child_names = [c["name"] for c in spirit["children"]]
        assert "Vodka" in child_names
        assert "Gin" in child_names

    def test_list_flat(self, test_client):
        """GET /api/v1/ingredients?flat=true returns flat list."""
        response = test_client.get("/api/v1/ingredients?flat=true")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        names = [n["name"] for n in data]
        assert "Spirit" in names
        assert "Vodka" in names
        assert "Svedka Vanilla Vodka" in names
        # Flat items should not have children key
        assert "children" not in data[0]

    def test_ancestors_computed(self, test_client):
        """Flat list includes ancestors."""
        response = test_client.get("/api/v1/ingredients?flat=true")
        data = response.json()
        svedka = next(n for n in data if n["name"] == "Svedka Vanilla Vodka")
        assert "Vanilla Vodka" in svedka["ancestors"]
        assert "Flavored Vodka" in svedka["ancestors"]
        assert "Vodka" in svedka["ancestors"]
        assert "Spirit" in svedka["ancestors"]


class TestIngredientGet:
    """Test GET /api/v1/ingredients/{id}."""

    def test_get_by_id(self, test_client):
        """Can retrieve ingredient by ID."""
        # First get the list to find an ID
        response = test_client.get("/api/v1/ingredients?flat=true")
        data = response.json()
        vodka = next(n for n in data if n["name"] == "Vodka")
        vodka_id = vodka["id"]

        # Get by ID
        response = test_client.get(f"/api/v1/ingredients/{vodka_id}")
        assert response.status_code == 200
        result = response.json()
        assert result["name"] == "Vodka"
        assert result["id"] == vodka_id

    def test_get_nonexistent(self, test_client):
        """Getting nonexistent ID returns 404."""
        response = test_client.get("/api/v1/ingredients/nonexistent123")
        assert response.status_code == 404

    def test_get_includes_children(self, test_client):
        """Get by ID includes children."""
        response = test_client.get("/api/v1/ingredients?flat=true")
        data = response.json()
        spirit = next(n for n in data if n["name"] == "Spirit")

        response = test_client.get(f"/api/v1/ingredients/{spirit['id']}")
        result = response.json()
        child_names = [c["name"] for c in result["children"]]
        assert "Vodka" in child_names


class TestIngredientSearch:
    """Test GET /api/v1/ingredients/search."""

    def test_search_by_name(self, test_client):
        """Search finds ingredients by name."""
        response = test_client.get("/api/v1/ingredients/search?q=vodka")
        assert response.status_code == 200
        data = response.json()
        names = [n["name"] for n in data]
        assert "Vodka" in names
        assert "Flavored Vodka" in names
        assert "Vanilla Vodka" in names
        assert "Svedka Vanilla Vodka" in names

    def test_search_by_brand(self, test_client):
        """Search finds products by name."""
        response = test_client.get("/api/v1/ingredients/search?q=svedka")
        assert response.status_code == 200
        data = response.json()
        names = [n["name"] for n in data]
        assert "Svedka Vanilla Vodka" in names

    def test_search_case_insensitive(self, test_client):
        """Search is case-insensitive."""
        response = test_client.get("/api/v1/ingredients/search?q=VODKA")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0

    def test_search_no_results(self, test_client):
        """Search with no matches returns empty list."""
        response = test_client.get("/api/v1/ingredients/search?q=nonexistentxyz")
        assert response.status_code == 200
        data = response.json()
        assert data == []

    def test_search_empty_query(self, test_client):
        """Search with empty query returns 400."""
        response = test_client.get("/api/v1/ingredients/search?q=")
        assert response.status_code == 400


class TestIngredientDescendants:
    """Test GET /api/v1/ingredients/{id}/descendants."""

    def test_get_descendants(self, test_client):
        """Gets all descendants of an ingredient."""
        # Find Spirit's ID
        response = test_client.get("/api/v1/ingredients?flat=true")
        data = response.json()
        spirit = next(n for n in data if n["name"] == "Spirit")

        response = test_client.get(f"/api/v1/ingredients/{spirit['id']}/descendants")
        assert response.status_code == 200
        descendants = response.json()
        desc_names = [d["name"] for d in descendants]
        assert "Vodka" in desc_names
        assert "Gin" in desc_names
        assert "Flavored Vodka" in desc_names
        assert "Vanilla Vodka" in desc_names
        assert "Svedka Vanilla Vodka" in desc_names
        assert "Spirit" not in desc_names  # Self excluded

    def test_descendants_of_leaf(self, test_client):
        """Leaf node has no descendants."""
        response = test_client.get("/api/v1/ingredients?flat=true")
        data = response.json()
        lime = next(n for n in data if n["name"] == "Lime")

        response = test_client.get(f"/api/v1/ingredients/{lime['id']}/descendants")
        assert response.status_code == 200
        assert response.json() == []


class TestIngredientCreate:
    """Test POST /api/v1/ingredients."""

    def test_create_root_ingredient(self, test_client, test_vault):
        """Create a new root ingredient."""
        response = test_client.post("/api/v1/ingredients", json={
            "name": "Bitters",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Bitters"
        assert data["parent"] is None
        assert data["id"] is not None

        # Verify file was created
        bitters_dir = test_vault / "2_Ingredients" / "Bitters"
        assert bitters_dir.exists()
        assert (bitters_dir / "Bitters.md").exists()

    def test_create_child_ingredient(self, test_client, test_vault):
        """Create an ingredient as child of existing node."""
        response = test_client.post("/api/v1/ingredients", json={
            "name": "Angostura Bitters",
            "parent": "Bitters",
            "cost": 8.99,
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Angostura Bitters"
        assert data["parent"] == "Bitters"
        assert data["cost"] == 8.99
        assert data["is_product"] is True

    def test_create_duplicate_name_fails(self, test_client):
        """Creating ingredient with existing name fails."""
        response = test_client.post("/api/v1/ingredients", json={
            "name": "Vodka",
        })
        assert response.status_code == 409

    def test_create_with_nonexistent_parent_fails(self, test_client):
        """Creating ingredient with nonexistent parent fails."""
        response = test_client.post("/api/v1/ingredients", json={
            "name": "TestChild",
            "parent": "NonExistentParent",
        })
        assert response.status_code == 404

    def test_create_without_name_fails(self, test_client):
        """Creating ingredient without name fails."""
        response = test_client.post("/api/v1/ingredients", json={})
        assert response.status_code == 422


class TestIngredientUpdate:
    """Test PUT /api/v1/ingredients/{id}."""

    def test_update_fields(self, test_client):
        """Update product fields on an ingredient."""
        # Find Lime's ID
        response = test_client.get("/api/v1/ingredients?flat=true")
        data = response.json()
        lime = next(n for n in data if n["name"] == "Lime")

        response = test_client.put(f"/api/v1/ingredients/{lime['id']}", json={
            "notes": "Fresh limes only",
            "cost": 1.99,
        })
        assert response.status_code == 200
        result = response.json()
        assert result["notes"] == "Fresh limes only"
        assert result["cost"] == 1.99

    def test_update_nonexistent_fails(self, test_client):
        """Updating nonexistent ingredient fails."""
        response = test_client.put("/api/v1/ingredients/nonexistent123", json={
            "notes": "test"
        })
        assert response.status_code == 404


class TestIngredientDelete:
    """Test DELETE /api/v1/ingredients/{id}."""

    def test_delete_leaf_ingredient(self, test_client, test_vault):
        """Delete a leaf ingredient (no children)."""
        # Create a disposable ingredient first
        response = test_client.post("/api/v1/ingredients", json={
            "name": "ToDelete",
        })
        assert response.status_code == 200
        ing_id = response.json()["id"]

        # Delete it
        response = test_client.delete(f"/api/v1/ingredients/{ing_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "deleted"

        # Verify directory removed
        assert not (test_vault / "2_Ingredients" / "ToDelete").exists()

    def test_delete_with_children_fails(self, test_client):
        """Deleting ingredient with children fails."""
        # Find Spirit's ID (has children)
        response = test_client.get("/api/v1/ingredients?flat=true")
        data = response.json()
        spirit = next(n for n in data if n["name"] == "Spirit")

        response = test_client.delete(f"/api/v1/ingredients/{spirit['id']}")
        assert response.status_code == 409

    def test_delete_nonexistent_fails(self, test_client):
        """Deleting nonexistent ingredient fails."""
        response = test_client.delete("/api/v1/ingredients/nonexistent123")
        assert response.status_code == 404


class TestIngredientPage:
    """Test page routes."""

    def test_ingredients_page_loads(self, test_client):
        """Ingredients page loads successfully."""
        response = test_client.get("/ingredients")
        assert response.status_code == 200


class TestProductDetection:
    """Test is_product detection via API."""

    def test_product_flagged_in_tree(self, test_client):
        """Products are flagged in tree response."""
        response = test_client.get("/api/v1/ingredients?flat=true")
        data = response.json()
        svedka = next(n for n in data if n["name"] == "Svedka Vanilla Vodka")
        assert svedka["is_product"] is True

        vodka = next(n for n in data if n["name"] == "Vodka")
        assert vodka["is_product"] is False

    def test_product_fields_in_response(self, test_client):
        """Product fields are included in response."""
        response = test_client.get("/api/v1/ingredients?flat=true")
        data = response.json()
        svedka = next(n for n in data if n["name"] == "Svedka Vanilla Vodka")
        assert svedka["cost"] == 12.99
        assert svedka["volume_ml"] == 750
        assert svedka["abv"] == 35.0
