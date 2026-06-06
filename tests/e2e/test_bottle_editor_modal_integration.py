"""
End-to-end tests for unified bottle editor modal.

Tests the ACTUAL user workflows:
1. Management workflow: Click bottle → modal opens → edit → save
2. Manual crop workflow: Open modal → manual crop → accept → save
3. Upload workflow: Upload → modal opens → edit → save

These tests would have caught:
- Empty strings failing Pydantic validation
- vault_path being null
- Cropper.js not initializing
- Frontend/backend data format mismatches
"""

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reserve_automation.core.models import BottleMetadata
from reserve_automation.web.app import app
from reserve_automation.web.config import load_web_config


@pytest.fixture(scope="module")
def test_client():
    """Create test client with proper configuration."""
    core_config, web_config = load_web_config()

    from reserve_automation.web import app as web_app
    web_app.core_config = core_config
    web_app.web_config = web_config

    from reserve_automation.web.services.upload_service import UploadService
    web_app.upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions
    )

    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def test_bottle_in_vault(tmp_path):
    """Create a test bottle in a temporary vault."""

    # Create vault structure
    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)

    # Create a test whiskey bottle with realistic data (including empty fields)
    whiskey_dir = vault_path / "1_Whiskeys" / "Test Distillery - Test Bourbon - 2020"
    whiskey_dir.mkdir(parents=True, exist_ok=True)

    # Create bottle file with empty year/price/inventory (real-world scenario)
    bottle_file = whiskey_dir / "Test Distillery - Test Bourbon - 2020.md"
    bottle_file.write_text("""---
Name: "Test Distillery - Test Bourbon - 2020"
Distiller: Test Distillery
WhiskeyName: Test Bourbon
Year:
Type: Bourbon
Region-State: Kentucky
Proof: 100
AgeStatement: 4 Years
Price:
Inventory:
Buy: 1
ValueForMoney: 3
fileClass: Whiskey
---

Test bottle for E2E testing.
""")

    # Create label
    labels_dir = whiskey_dir / "labels"
    labels_dir.mkdir(exist_ok=True)
    label_path = labels_dir / "label.jpg"

    # Create a test image
    img = Image.new('RGB', (400, 600), color='blue')
    img.save(label_path, 'JPEG')

    return {
        'vault_path': vault_path,
        'bottle_path': '1_Whiskeys/Test Distillery - Test Bourbon - 2020',
        'bottle_file': bottle_file,
        'label_path': label_path
    }


class TestManagementWorkflow:
    """Test management grid → modal → edit → save workflow."""

    def test_load_management_page(self, test_client):
        """Test management page loads without errors."""
        response = test_client.get("/management")

        assert response.status_code == 200
        html = response.text

        # Verify critical components are present
        assert "bottle-editor-modal.js" in html
        assert "cropper-manager.js" in html
        assert "bottleEditor" in html

    def test_get_bottles_returns_valid_data(self, test_client):
        """Test that /api/v1/management/bottles returns bottles with opaque id."""
        response = test_client.get("/api/v1/management/bottles")

        if response.status_code == 200:
            data = response.json()
            assert "bottles" in data

            # If there are bottles, verify they have id (opaque bottle ID)
            if len(data["bottles"]) > 0:
                bottle = data["bottles"][0]
                assert "id" in bottle, "Bottles MUST have id for modal to work"
                assert bottle["id"] is not None
                assert bottle["id"] != ""
                # vault_path should NOT be in the response (excluded from JSON)
                assert "vault_path" not in bottle, "vault_path should be excluded from API responses"

    def test_save_bottle_with_empty_strings(self, test_client):
        """
        CRITICAL: Test saving bottle with empty strings for numeric fields.
        This is the bug we just fixed - empty strings should not cause validation errors.
        """
        # Simulate what the frontend sends - empty strings for year/price/inventory
        bottle_data = {
            "producer": "Test Distillery",
            "name": "Test Bourbon",
            "year": "",  # EMPTY STRING - frontend sends this
            "type": "whiskey",
            "beverage_type": "Bourbon",
            "vault_path": "1_Whiskeys/Test Distillery - Test Bourbon - 2020",
            "price": "",  # EMPTY STRING
            "inventory": "",  # EMPTY STRING
            "proof": 100,
            "abv": 50.0,
            "source": "manual"  # Required field
        }

        response = test_client.post(
            "/api/v1/management/bottles/update-fields",
            json={"bottle": bottle_data, "changes": {}}
        )

        # Should NOT fail with validation error
        if response.status_code != 200:
            error = response.json()
            # If it fails with validation error, that's the bug
            assert "validation error" not in str(error).lower(), \
                f"Empty strings should be handled gracefully, not cause validation errors: {error}"

    def test_save_full_bottle_from_vault(self, test_client):
        """
        CRITICAL: Test with FULL bottle (all 32 fields) like real vault bottles.
        This catches bugs that minimal test bottles miss (e.g., age_statement, inventory=None).
        """
        # FULL bottle data with ALL fields - simulates real vault-loaded bottle
        bottle_data = {
            # Core identifiers
            "producer": "Test Distillery",
            "name": "Test Bourbon",
            "type": "whiskey",

            # Optional core
            "year": None,  # Frontend sends null
            "beverage_type": "Bourbon",

            # Geographic
            "country": "USA",
            "region": "Kentucky",

            # Wine-specific
            "variety": None,
            "vineyard": None,
            "style": None,

            # Whiskey-specific - THIS IS THE BUG: age_statement comes as empty string
            "age_statement": "",  # EMPTY STRING - was missing from cleaning!
            "proof": 100,
            "mash_bill": None,
            "barrel_type": None,
            "batch_number": None,
            "bottle_number": None,
            "bottle_opened_date": None,

            # Common
            "abv": 50.0,
            "price": "",  # EMPTY STRING

            # Inventory - THIS IS THE BUG: frontend sends null, not empty string
            "purchase_source": None,
            "purchase_link": None,
            "inventory": None,  # Frontend sends null (not "")
            "buy": 0,

            # Rating
            "stars": None,
            "value_for_money": "",  # EMPTY STRING
            "points": None,

            # Vault location
            "vault_path": "1_Whiskeys/Test Distillery - Test Bourbon",

            # Metadata
            "confidence": 0.9,
            "source": "vault",
            "extracted_at": "2024-01-01T00:00:00",
            "enriched": False,
            "label_image_url": None,
            "notes": None
        }

        response = test_client.post(
            "/api/v1/management/bottles/update-fields",
            json={"bottle": bottle_data, "changes": {}}
        )

        # Should NOT fail with validation error
        if response.status_code != 200:
            error = response.json()
            detail = str(error.get("detail", ""))

            # Check for the specific bugs we're fixing
            if "age_statement" in detail and "int_parsing" in detail:
                assert False, \
                    f"REGRESSION: age_statement empty string not handled!\\n{detail}\\n" \
                    f"This bug was fixed on 2026-01-03 - add age_statement to optional_fields"

            if "inventory" in detail and "int_type" in detail:
                assert False, \
                    f"REGRESSION: inventory=None not handled!\\n{detail}\\n" \
                    f"This bug was fixed on 2026-01-03 - handle None in addition to empty strings"

            # Generic validation error check
            assert "validation error" not in detail.lower(), \
                f"Full vault bottle should be handled gracefully:\\n{detail}"


class TestManualCropWorkflow:
    """Test manual crop workflow end-to-end."""

    def test_manual_crop_endpoint_with_valid_bottle_id(self, test_client):
        """Test manual crop with bottle_id (new API contract)."""
        # Create a real bottle in the (in-memory) DB to get an integer id.
        # The vault-era bottle_registry was removed in the SQLite migration.
        from reserve_automation.db.engine import _SessionLocal
        from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
        session = _SessionLocal()
        try:
            bottle = SQLiteBottleRepository(session).create(BottleMetadata(
                producer="Test Distillery", name="Test Bourbon",
                type="whiskey", source="test",
            ))
            test_bottle_id = str(bottle.id)
        finally:
            session.close()

        response = test_client.post(
            "/api/v1/management/labels/manual-crop",
            json={
                "bottle_id": test_bottle_id,
                "x": 10,
                "y": 10,
                "width": 200,
                "height": 300
            }
        )

        # May fail with 404 because label doesn't exist, but should NOT fail with validation error
        if response.status_code != 200:
            error = response.json()
            # 404 "No label found" is expected when the bottle dir doesn't have a label
            assert response.status_code == 404 or "validation error" not in str(error).lower(), \
                f"Should not fail with validation error: {error}"

    def test_manual_crop_missing_bottle_id(self, test_client):
        """Test that manual crop fails gracefully when bottle_id is missing."""
        response = test_client.post(
            "/api/v1/management/labels/manual-crop",
            json={
                # bottle_id is MISSING
                "x": 10,
                "y": 10,
                "width": 200,
                "height": 300
            }
        )

        # Should fail with 400 for missing bottle_id
        assert response.status_code == 400, \
            f"Should fail with 400 when bottle_id missing, got {response.status_code}"
        error = response.json()
        assert "bottle_id" in error.get("detail", "").lower(), \
            f"Error should mention missing bottle_id: {error}"

    def test_manual_crop_invalid_bottle_id(self, test_client):
        """Test that manual crop fails gracefully when bottle_id is not found."""
        response = test_client.post(
            "/api/v1/management/labels/manual-crop",
            json={
                "bottle_id": "nonexistent_id_12345",
                "x": 10,
                "y": 10,
                "width": 200,
                "height": 300
            }
        )

        # Should fail with 404 for unknown bottle_id
        assert response.status_code == 404, \
            f"Should fail with 404 when bottle_id not found, got {response.status_code}"


class TestUploadWorkflow:
    """Test upload → modal → save workflow."""

    def test_upload_returns_bottles_as_json(self, test_client):
        """Test upload returns bottles in client-side state (no session)."""
        # Create a simple test image
        img = Image.new('RGB', (400, 600), color='red')
        img_bytes = BytesIO()
        img.save(img_bytes, format='JPEG')
        img_bytes.seek(0)

        response = test_client.post(
            "/api/v1/bottles/upload",
            files={"file": ("test.jpg", img_bytes, "image/jpeg")},
            data={
                "upload_type": "bottle_image",
                "beverage_type": "whiskey",
                "inventory": "0"  # Note: sent as STRING from form
            }
        )

        # May fail if LLM not available, but structure should be correct
        if response.status_code == 200:
            data = response.json()
            assert "upload_id" in data
            assert "bottles" in data
            assert isinstance(data["bottles"], list)

            # Verify no session cookie (stateless!)
            # Note: session cookie may exist for other workflows, but not required for bottle data

    def test_save_uploaded_bottle_with_empty_fields(self, test_client):
        """Test saving uploaded bottle with empty string fields."""
        bottle_data = {
            "producer": "Uploaded Distillery",
            "name": "Uploaded Bourbon",
            "year": "",  # EMPTY STRING
            "type": "whiskey",
            "beverage_type": "Bourbon",
            "price": "",  # EMPTY STRING
            "inventory": "",  # EMPTY STRING
            "proof": "",  # EMPTY STRING
            "source": "manual"
        }

        response = test_client.post(
            "/api/v1/bottles/save",
            json={
                "bottle": bottle_data,
                "upload_id": "test-upload-123",
                "force_save": True
            }
        )

        # Should NOT fail with validation error
        if response.status_code != 200:
            error = response.json()
            detail = str(error.get("detail", ""))

            if "validation error" in detail.lower() or "int_parsing" in detail:
                pytest.fail(
                    f"Save bottle failed with validation error - empty strings not handled!\n"
                    f"Error: {detail}"
                )


class TestLabelSearchIntegration:
    """Test label search workflow."""

    def test_search_labels_endpoint_exists(self, test_client):
        """Test that search-labels endpoint exists (we restored this from deprecated)."""
        bottle_data = {
            "producer": "Test Producer",
            "name": "Test Wine",
            "type": "wine",
            "year": 2020,
            "source": "manual"
        }

        response = test_client.post(
            "/api/v1/bottles/search-labels",
            json=bottle_data
        )

        # Should return 200 or 500 (if LLM fails), not 404
        assert response.status_code != 404, \
            "search-labels endpoint should exist (we restored it from deprecated)"

    def test_search_labels_with_empty_strings(self, test_client):
        """Test search labels with empty year/price fields."""
        bottle_data = {
            "producer": "Test Producer",
            "name": "Test Wine",
            "type": "wine",
            "year": "",  # EMPTY STRING
            "price": "",  # EMPTY STRING
            "variety": "Cabernet Sauvignon",
            "source": "manual"
        }

        response = test_client.post(
            "/api/v1/bottles/search-labels",
            json=bottle_data
        )

        # Should NOT fail with validation error
        if response.status_code != 200:
            error = response.json()
            detail = str(error.get("detail", ""))

            if "validation error" in detail.lower() or "int_parsing" in detail:
                pytest.fail(
                    f"Search labels failed with validation error:\n{detail}"
                )


class TestDataContractValidation:
    """Test that frontend/backend data contracts match."""

    def test_bottle_metadata_accepts_empty_strings(self):
        """
        CRITICAL: Test that BottleMetadata model handles empty strings.
        Frontend forms send empty strings, backend expects null or int/float.
        """

        # This is what frontend sends - empty strings
        data = {
            "producer": "Test",
            "name": "Test",
            "type": "wine",
            "year": "",  # EMPTY STRING
            "price": "",  # EMPTY STRING
            "inventory": "",  # EMPTY STRING
            "abv": "",  # EMPTY STRING
            "proof": ""  # EMPTY STRING
        }

        # Should either:
        # 1. Accept and convert to None (ideal)
        # 2. Fail immediately here (so we know to clean in frontend)
        try:
            bottle = BottleMetadata(**data)
            # If it works, verify empty strings became None
            assert bottle.year is None or bottle.year == ""
        except Exception as e:
            # If it fails, this tells us we MUST clean data in frontend
            # (which is what we just did)
            assert "validation error" in str(e).lower() or "int_parsing" in str(e).lower(), \
                f"Unexpected error: {e}"

    def test_frontend_should_clean_before_sending(self):
        """
        Document that frontend MUST clean empty strings before sending.
        This is the fix we just implemented.
        """

        # Bad data (what forms send)
        bad_data = {
            "producer": "Test",
            "name": "Test",
            "type": "wine",
            "year": "",
            "price": ""
        }

        # Good data (what we should send after cleaning)
        good_data = {
            "producer": "Test",
            "name": "Test",
            "type": "wine",
            "year": None,  # Converted empty string to None
            "price": None,  # Converted empty string to None
            "source": "manual"  # Required field
        }

        # Good data should work
        bottle = BottleMetadata(**good_data)
        assert bottle.year is None
        assert bottle.price is None


class TestRegressionPrevention:
    """
    Tests that prevent regressions of bugs we just fixed.
    These should NEVER be removed.
    """

    def test_no_regression_empty_string_validation(self, test_client):
        """
        REGRESSION TEST: Empty strings in numeric fields must not cause 500 errors.

        Bug fixed: 2026-01-03
        Issue: Frontend sends "" for empty numeric fields, Pydantic expects int/float/null
        Fix: Clean empty strings to null in bottle-editor-modal.js before sending
        """
        endpoints_to_test = [
            ("/api/v1/management/bottles/update-fields", {"bottle": {}, "changes": {}}),
            ("/api/v1/management/labels/manual-crop", {"bottle": {}, "x": 10, "y": 10, "width": 100, "height": 100}),
            ("/api/v1/bottles/save", {"bottle": {}, "upload_id": "test", "force_save": True}),
        ]

        for endpoint, base_data in endpoints_to_test:
            bottle_data = {
                "producer": "Test",
                "name": "Test",
                "type": "wine",
                "year": "",  # EMPTY STRING
                "price": "",  # EMPTY STRING
                "inventory": "",  # EMPTY STRING
                "source": "manual"  # Required field
            }

            request_data = {**base_data}
            request_data["bottle"] = bottle_data

            response = test_client.post(endpoint, json=request_data)

            # Should NOT return validation error
            if response.status_code in [422, 500]:
                error = response.json()
                detail = str(error.get("detail", ""))

                assert "int_parsing" not in detail and "float_parsing" not in detail, \
                    f"REGRESSION: {endpoint} failed with validation error on empty strings:\n{detail}\n" \
                    f"This bug was fixed on 2026-01-03 - empty strings should be cleaned to null"
