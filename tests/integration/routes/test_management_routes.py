"""Integration tests for bottle management routes.

These tests verify the management UI workflow:
1. Load bottles from vault
2. Verify/enrich bottle metadata
3. Update bottle fields
4. Save changes back to vault

WHY THIS TEST EXISTS:
After a refactor broke all management imports and template paths, we realized
there were NO integration tests exercising these endpoints. This test ensures
the management workflow actually works end-to-end.
"""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from unittest.mock import Mock


@pytest.fixture
def client_with_vault(tmp_path):
    """Create test client with a real vault containing test bottles."""
    from reserve_automation.web import app as app_module
    from reserve_automation.core.config import Config

    # Create vault structure
    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)

    # Create a test whiskey bottle
    whiskey_dir = vault_path / "1_Whiskeys" / "Buffalo Trace - GEORGE T. STAGG - 2024"
    whiskey_dir.mkdir(parents=True, exist_ok=True)

    bottle_file = whiskey_dir / "Buffalo Trace - GEORGE T. STAGG - 2024.md"
    bottle_file.write_text("""---
Name: "Buffalo Trace - GEORGE T. STAGG - 2024"
Distiller: Buffalo Trace
WhiskeyName: GEORGE T. STAGG
Year: 2024
Type: Bourbon
Region-State: Kentucky
Proof: 130.4
AgeStatement: 15 Years
MashBill: Buffalo Trace Mash Bill #1
BarrelType: New Charred Oak
Price: 125
Inventory: 1
Buy: 1
ValueForMoney: 4
Stars: 4
---

# Buffalo Trace - GEORGE T. STAGG - 2024

A classic bourbon from Buffalo Trace.
""", encoding='utf-8')

    # Create a test wine bottle
    wine_dir = vault_path / "1_Wines" / "Chateau Margaux - Grand Vin - 2015"
    wine_dir.mkdir(parents=True, exist_ok=True)

    wine_file = wine_dir / "Chateau Margaux - Grand Vin - 2015.md"
    wine_file.write_text("""---
Name: "Chateau Margaux - Grand Vin - 2015"
Winemaker: Chateau Margaux
WineName: Grand Vin
Vintage: 2015
Type: Red
Country-Region: France - Bordeaux
Variety: Cabernet Sauvignon Blend
ABV: 13.5
Price: 450
Inventory: 1
Buy: 1
ValueForMoney: 5
Points: 95
Stars: 5
---

# Chateau Margaux - Grand Vin - 2015

A legendary Bordeaux.
""", encoding='utf-8')

    # Create templates directory
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir(exist_ok=True)

    # Create whiskey template
    whiskey_template = templates_dir / "whiskey.md.j2"
    whiskey_template.write_text("""---
Name: "{{ producer }} - {{ name }}{% if year %} - {{ year }}{% endif %}"
Distiller: {{ producer }}
WhiskeyName: {{ name }}
{% if year %}Year: {{ year }}{% endif %}
Type: {{ beverage_type | title }}
{% if region %}Region-State: {{ region }}{% endif %}
{% if proof %}Proof: {{ proof }}{% endif %}
{% if age_statement %}AgeStatement: {{ age_statement }}{% endif %}
{% if mash_bill %}MashBill: {{ mash_bill }}{% endif %}
{% if barrel_type %}BarrelType: {{ barrel_type }}{% endif %}
{% if price %}Price: {{ price }}{% endif %}
{% if inventory %}Inventory: {{ inventory }}{% endif %}
---

# {{ producer }} - {{ name }}{% if year %} - {{ year }}{% endif %}

""", encoding='utf-8')

    # Create wine template
    wine_template = templates_dir / "wine.md.j2"
    wine_template.write_text("""---
Name: "{{ producer }} - {{ name }}{% if year %} - {{ year }}{% endif %}"
Winemaker: {{ producer }}
WineName: {{ name }}
{% if year %}Vintage: {{ year }}{% endif %}
Type: {{ beverage_type | title }}
{% if country and region %}Country-Region: {{ country }} - {{ region }}{% endif %}
{% if variety %}Variety: {{ variety }}{% endif %}
{% if abv %}ABV: {{ abv }}{% endif %}
{% if price %}Price: {{ price }}{% endif %}
{% if inventory %}Inventory: {{ inventory }}{% endif %}
---

# {{ producer }} - {{ name }}{% if year %} - {{ year }}{% endif %}

""", encoding='utf-8')

    # Configure app
    config = Config(paths={"vault": str(vault_path), "templates_dir": str(templates_dir)})
    app_module.core_config = config

    # Initialize bottle registry for ID lookups
    from reserve_automation.core.bottle_registry import BottleRegistry
    app_module.bottle_registry = BottleRegistry()

    web_config = Mock()
    web_config.sessions.secret_key = "test-secret"
    web_config.sessions.max_age_hours = 24
    app_module.web_config = web_config

    return TestClient(app_module.app)


class TestManagementBottleList:
    """Test loading bottles from vault."""

    def test_get_all_bottles(self, client_with_vault):
        """GET /api/v1/management/bottles should load all bottles from vault."""
        response = client_with_vault.get("/api/v1/management/bottles")

        assert response.status_code == 200
        data = response.json()

        assert "bottles" in data
        assert "count" in data
        assert data["count"] >= 2  # At least our 2 test bottles

        # Verify we got the whiskey
        bottles = data["bottles"]
        stagg = next((b for b in bottles if "STAGG" in b.get("name", "")), None)
        assert stagg is not None
        assert stagg["producer"] == "Buffalo Trace"
        assert stagg["beverage_type"] == "Bourbon"

    def test_search_bottles(self, client_with_vault):
        """GET /api/v1/management/bottles/search should find bottles."""
        response = client_with_vault.get("/api/v1/management/bottles/search?q=Stagg")

        assert response.status_code == 200
        data = response.json()

        assert data["count"] >= 1
        assert "STAGG" in data["bottles"][0]["name"]


class TestManagementBottleUpdate:
    """Test updating bottle metadata - THE CRITICAL MISSING TESTS."""

    @pytest.mark.asyncio
    async def test_update_bottle_fields_saves_to_vault(self, client_with_vault, tmp_path):
        """POST /api/v1/management/bottles/update-fields should update vault files.

        THIS IS THE TEST THAT WOULD HAVE CAUGHT THE IMPORT/PATH ERRORS.
        """
        # First, get all bottles to find our test bottle
        list_response = client_with_vault.get("/api/v1/management/bottles")
        bottles = list_response.json()["bottles"]

        # Find the Stagg bottle
        stagg = next((b for b in bottles if "STAGG" in b.get("name", "")), None)
        assert stagg is not None, "Test bottle not found"

        # Update the price
        update_data = {
            "bottle": stagg,
            "updates": {
                "proof": 131.2,  # Changed from 130.4
                "price": 150     # Changed from 125
            }
        }

        response = client_with_vault.post(
            "/api/v1/management/bottles/update-fields",
            json=update_data
        )

        # This is where the import errors would fail
        assert response.status_code == 200, f"Update failed: {response.json()}"

        result = response.json()
        assert result["status"] == "success"
        assert "path" in result

        # Verify the file was actually updated
        # Look up vault_path from registry using bottle ID
        from reserve_automation.web import app as app_module
        bottle_vault_path = app_module.bottle_registry.get_path(stagg["id"])
        vault_path = tmp_path / "vault"
        bottle_file = vault_path / bottle_vault_path / f"{Path(bottle_vault_path).name}.md"

        assert bottle_file.exists(), "Bottle file should exist"

        content = bottle_file.read_text(encoding='utf-8')
        assert "Proof: 131.2" in content, "Proof should be updated in file"
        assert "Price: 150" in content, "Price should be updated in file"

    @pytest.mark.asyncio
    async def test_verify_bottle_metadata(self, client_with_vault):
        """POST /api/v1/management/bottles/{id}/verify should verify bottle.

        This endpoint uses ObsidianGenerator which requires correct template paths.
        """
        # Get a bottle
        list_response = client_with_vault.get("/api/v1/management/bottles")
        bottles = list_response.json()["bottles"]
        stagg = next((b for b in bottles if "STAGG" in b.get("name", "")), None)

        # Verify the bottle (index 0 for simplicity)
        verify_data = {"bottle": stagg}

        response = client_with_vault.post(
            "/api/v1/management/bottles/0/verify",
            json=verify_data
        )

        # This would fail with template path errors
        assert response.status_code == 200, f"Verify failed: {response.json()}"

        result = response.json()
        assert "original" in result
        assert "updated" in result
        assert "changes" in result

    @pytest.mark.asyncio
    async def test_update_producer_renames_directory(self, client_with_vault, tmp_path):
        """Updating producer/name/year should move the bottle directory."""
        list_response = client_with_vault.get("/api/v1/management/bottles")
        bottles = list_response.json()["bottles"]
        margaux = next((b for b in bottles if "Margaux" in b.get("producer", "")), None)

        # Look up vault_path from registry using bottle ID
        from reserve_automation.web import app as app_module
        margaux_vault_path = app_module.bottle_registry.get_path(margaux["id"])
        original_path = tmp_path / "vault" / margaux_vault_path
        assert original_path.exists(), "Original bottle directory should exist"

        # Change the vintage
        update_data = {
            "bottle": margaux,
            "updates": {
                "year": 2016  # Changed from 2015
            }
        }

        response = client_with_vault.post(
            "/api/v1/management/bottles/update-fields",
            json=update_data
        )

        assert response.status_code == 200
        result = response.json()
        assert result["moved"] == True, "Bottle should have been moved"

        # Verify old path is gone
        assert not original_path.exists(), "Old directory should be removed"

        # Verify new path exists
        new_path = tmp_path / "vault" / "1_Wines" / "Chateau Margaux - Grand Vin - 2016"
        assert new_path.exists(), "New directory should exist"

        # Verify file was updated
        bottle_file = new_path / "Chateau Margaux - Grand Vin - 2016.md"
        assert bottle_file.exists()
        content = bottle_file.read_text(encoding='utf-8')
        assert "Vintage: 2016" in content


class TestManagementTastingsSummary:
    """Test tasting statistics endpoints."""

    @pytest.mark.asyncio
    async def test_get_tastings_summary(self, client_with_vault, tmp_path):
        """POST /api/v1/management/bottles/tastings-summary should return tasting stats."""
        # Get bottles
        list_response = client_with_vault.get("/api/v1/management/bottles")
        bottles = list_response.json()["bottles"]

        # Test with whiskey (10-point scale)
        stagg = next((b for b in bottles if "STAGG" in b.get("name", "")), None)
        # Look up vault_path from registry using bottle ID
        from reserve_automation.web import app as app_module
        stagg_vault_path = app_module.bottle_registry.get_path(stagg["id"])
        bottle_dir = tmp_path / "vault" / stagg_vault_path
        tasting_file = bottle_dir / "Tasting-2024-12-30-TestTaster.md"
        tasting_file.write_text("""---
fileClass: Tasting
Date: 2024-12-30
TasterName: TestTaster
TotalScore: 9.5
LinkedBottle: "[[Buffalo Trace - GEORGE T. STAGG - 2024]]"
---

Great whiskey!
""", encoding='utf-8')

        response = client_with_vault.post(
            "/api/v1/management/bottles/tastings-summary",
            json={"bottle": stagg}
        )

        assert response.status_code == 200
        result = response.json()
        assert result["tasting_count"] == 1
        assert result["avg_score"] == 9.5
        assert result["max_score"] == 10  # Whiskey 10-point scale
        assert "TestTaster" in result["tasters"]

        # Test with wine (100-point scale)
        margaux = next((b for b in bottles if "Margaux" in b.get("producer", "")), None)
        # Look up vault_path from registry using bottle ID
        margaux_vault_path = app_module.bottle_registry.get_path(margaux["id"])
        wine_dir = tmp_path / "vault" / margaux_vault_path
        wine_tasting = wine_dir / "Tasting-2024-12-31-WineTaster.md"
        wine_tasting.write_text("""---
fileClass: Wine Tasting
Date: 2024-12-31
TasterName: WineTaster
Appearance: 4.5
Aroma: 4.0
Taste: 4.0
Aftertaste: 3.5
Overall: 2.5
AWS Score: 18.5
100pt Scale: 92.5
LinkedBottle: "[[Chateau Margaux - Grand Vin - 2015]]"
---

Excellent wine!
""", encoding='utf-8')

        response = client_with_vault.post(
            "/api/v1/management/bottles/tastings-summary",
            json={"bottle": margaux}
        )

        assert response.status_code == 200
        result = response.json()
        assert result["tasting_count"] == 1
        assert result["avg_score"] == 92.5  # 100-point scale
        assert result["max_score"] == 100   # Wine 100-point scale
        assert "WineTaster" in result["tasters"]


# ============================================================================
# Why These Tests Matter
# ============================================================================
"""
LESSONS LEARNED:

1. Integration tests should exercise COMPLETE workflows, not just happy paths
2. Any user-facing feature needs an end-to-end test that actually writes to disk
3. Template path calculations are fragile - test them with real file operations
4. Import errors in routes won't be caught by unit tests - need integration tests

WHAT WE SHOULD HAVE HAD:
- A test that loads bottles, modifies them, and saves them back
- A test that verifies ObsidianGenerator can actually find templates
- A test that verifies directory renaming works
- A test that verifies field mappings are correct

WHAT WOULD HAVE CAUGHT THE BUG:
- test_update_bottle_fields_saves_to_vault() - would fail on import
- test_verify_bottle_metadata() - would fail on template path
- test_update_producer_renames_directory() - would fail on ObsidianGenerator init

All three would have failed immediately with:
- ModuleNotFoundError: No module named 'reserve_automation.web.generators'
- Template directory does not exist: /mnt/d/.../src/templates
"""
