"""Tests for cocktail tasting API endpoints.

CRITICAL: These tests use an isolated test vault at /tmp/test-vault-cocktails-*.
"""

import pytest


class TestCreateCocktailTasting:
    """Test POST /api/v1/cocktails/{id}/tastings."""

    def test_create_tasting(self, test_client, test_vault):
        # Get a cocktail ID
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        mule = next(c for c in cocktails if c["name"] == "Moscow Mule")

        # Create a tasting
        response = test_client.post(f"/api/v1/cocktails/{mule['id']}/tastings", json={
            "taster_name": "TestTaster",
            "score": 8.0,
            "notes": "Delicious and refreshing",
            "bartender": "TestBartender",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["taster_name"] == "TestTaster"
        assert data["score"] == 8.0
        assert data["notes"] == "Delicious and refreshing"
        assert data["bartender"] == "TestBartender"
        assert data["recipe_name"] == "Moscow Mule"
        assert data["id"] is not None
        assert data["tasting_date"] is not None

        # Verify file was created
        tasting_dir = test_vault / "3_Cocktails" / "Moscow Mule"
        tasting_files = list(tasting_dir.glob("Tasting-*-TestTaster.md"))
        assert len(tasting_files) >= 1

    def test_create_tasting_minimal(self, test_client):
        """Create tasting with just a name (no score/notes)."""
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        mule = next(c for c in cocktails if c["name"] == "Moscow Mule")

        response = test_client.post(f"/api/v1/cocktails/{mule['id']}/tastings", json={
            "taster_name": "MinimalTaster",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["taster_name"] == "MinimalTaster"
        assert data["score"] is None
        assert data["notes"] is None

    def test_create_tasting_nonexistent_cocktail(self, test_client):
        response = test_client.post("/api/v1/cocktails/nonexistent123/tastings", json={
            "taster_name": "Test",
        })
        assert response.status_code == 404

    def test_create_tasting_empty_name_fails(self, test_client):
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        mule = next(c for c in cocktails if c["name"] == "Moscow Mule")

        response = test_client.post(f"/api/v1/cocktails/{mule['id']}/tastings", json={
            "taster_name": "",
        })
        assert response.status_code == 422

    def test_create_tasting_with_bottles_used(self, test_client):
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        mule = next(c for c in cocktails if c["name"] == "Moscow Mule")

        response = test_client.post(f"/api/v1/cocktails/{mule['id']}/tastings", json={
            "taster_name": "BottleTester",
            "score": 9.0,
            "bottles_used": [
                {"recipe_ingredient": "Vodka", "actual_product": "Svedka"},
                {"recipe_ingredient": "Ginger Beer", "actual_product": "Fever-Tree"},
            ],
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["bottles_used"]) == 2
        assert data["bottles_used"][0]["recipe_ingredient"] == "Vodka"
        assert data["bottles_used"][0]["actual_product"] == "Svedka"


class TestListCocktailTastings:
    """Test GET /api/v1/cocktails/{id}/tastings."""

    def test_list_tastings(self, test_client):
        """List tastings for a cocktail that has tastings (seeded + created above)."""
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        mule = next(c for c in cocktails if c["name"] == "Moscow Mule")

        response = test_client.get(f"/api/v1/cocktails/{mule['id']}/tastings")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        # Should have at least the seeded tasting + ones created in tests above
        assert len(data) >= 1

        # Check structure of a tasting
        tasting = data[0]
        assert "id" in tasting
        assert "taster_name" in tasting
        assert "tasting_date" in tasting
        assert "recipe_name" in tasting
        assert "score" in tasting
        assert "bottles_used" in tasting

    def test_list_tastings_empty_cocktail(self, test_client, test_vault):
        """Cocktail with no tastings returns empty list."""
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        of = next(c for c in cocktails if c["name"] == "Old Fashioned")

        response = test_client.get(f"/api/v1/cocktails/{of['id']}/tastings")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_list_tastings_nonexistent_cocktail(self, test_client):
        response = test_client.get("/api/v1/cocktails/nonexistent123/tastings")
        assert response.status_code == 404


class TestTastingVaultFile:
    """Test that tasting files are correctly created in the vault."""

    def test_tasting_file_has_correct_frontmatter(self, test_client, test_vault):
        """Verify the vault file has correct YAML frontmatter."""
        import yaml

        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        mule = next(c for c in cocktails if c["name"] == "Moscow Mule")

        # Create a tasting with known data
        response = test_client.post(f"/api/v1/cocktails/{mule['id']}/tastings", json={
            "taster_name": "FrontmatterTest",
            "score": 7.5,
            "notes": "Testing frontmatter",
            "bartender": "TestBarkeep",
        })
        assert response.status_code == 200

        # Find the tasting file
        tasting_dir = test_vault / "3_Cocktails" / "Moscow Mule"
        tasting_files = list(tasting_dir.glob("Tasting-*-FrontmatterTest.md"))
        assert len(tasting_files) == 1

        # Parse frontmatter
        content = tasting_files[0].read_text()
        import re
        match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL | re.MULTILINE)
        assert match is not None

        metadata = yaml.safe_load(match.group(1))
        assert metadata["fileClass"] == "Cocktail Tasting"
        assert metadata["TasterName"] == "FrontmatterTest"
        assert metadata["Score"] == 7.5
        assert metadata["Bartender"] == "TestBarkeep"
        assert metadata["Notes"] == "Testing frontmatter"
        assert "Moscow Mule" in str(metadata.get("LinkedCocktail", ""))

    def test_tasting_roundtrip(self, test_client, test_vault):
        """Create a tasting via API, then read it back via list endpoint."""
        response = test_client.get("/api/v1/cocktails")
        cocktails = response.json()
        mule = next(c for c in cocktails if c["name"] == "Moscow Mule")

        # Create
        response = test_client.post(f"/api/v1/cocktails/{mule['id']}/tastings", json={
            "taster_name": "RoundtripTest",
            "score": 6.0,
            "notes": "Round trip test",
        })
        assert response.status_code == 200

        # Read back
        response = test_client.get(f"/api/v1/cocktails/{mule['id']}/tastings")
        assert response.status_code == 200
        tastings = response.json()

        roundtrip = [t for t in tastings if t["taster_name"] == "RoundtripTest"]
        assert len(roundtrip) == 1
        assert roundtrip[0]["score"] == 6.0
        assert roundtrip[0]["notes"] == "Round trip test"
        assert roundtrip[0]["recipe_name"] == "Moscow Mule"
