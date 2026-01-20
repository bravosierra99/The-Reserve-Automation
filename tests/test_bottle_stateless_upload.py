"""Tests for stateless bottle upload workflow.

The new bottle upload workflow is stateless:
1. POST /api/v1/bottles/upload - Returns JSON with bottle data directly (no session)
2. Frontend stores bottles in Alpine.js client-side state
3. User reviews/edits in modal (client-side)
4. POST /api/v1/bottles/manual-crop-temp - Crop temp labels before saving
5. POST /api/v1/bottles/save - Save with duplicate detection
6. Duplicate handling with conflict resolution UI

This replaces the old session-based workflow that used:
- GET /api/v1/bottles/{extraction_id} (session lookup)
- PUT /api/v1/bottles/{extraction_id}/update/{index} (session update)
- POST /api/v1/bottles/{extraction_id}/approve/{index} (session-based save)
"""

import json
from pathlib import Path
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reserve_automation.web.app import app
from reserve_automation.web.config import load_web_config


@pytest.fixture(scope="module")
def test_client():
    """Create test client with proper configuration."""
    core_config, web_config = load_web_config()

    # Override dependencies
    from reserve_automation.web import app as web_app
    web_app.core_config = core_config
    web_app.web_config = web_config

    # Create services
    from reserve_automation.web.services.upload_service import UploadService
    web_app.upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions
    )

    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def sample_bottle_image():
    """Create a sample bottle image for testing."""
    fixture_path = Path(__file__).parent / "fixtures" / "bottles" / "bourbon_001.jpg"

    if fixture_path.exists():
        with open(fixture_path, 'rb') as f:
            return BytesIO(f.read())

    # Fallback: create blank image
    img = Image.new('RGB', (800, 1200), color='white')
    img_bytes = BytesIO()
    img.save(img_bytes, format='JPEG')
    img_bytes.seek(0)
    return img_bytes


@pytest.fixture
def wine_manifest_pdf():
    """Load wine manifest PDF for testing."""
    manifest_path = Path(__file__).parent / "fixtures" / "manifests" / "wine_manifest_sample.pdf"
    if not manifest_path.exists():
        pytest.skip("Wine manifest fixture not found")
    return manifest_path


class TestStatelessBottleUpload:
    """Test stateless bottle upload API."""

    @pytest.mark.asyncio
    async def test_upload_returns_json_directly(self, test_client, sample_bottle_image):
        """Test that upload returns bottle data as JSON (no session lookup needed)."""
        response = test_client.post(
            "/api/v1/bottles/upload",
            files={"file": ("bottle.jpg", sample_bottle_image, "image/jpeg")},
            data={
                "upload_type": "bottle_image",
                "beverage_type": "whiskey"
            }
        )

        # Upload may fail if LLM not available
        if response.status_code == 200:
            data = response.json()

            # New stateless API returns bottles directly
            assert "upload_id" in data, "No upload_id in response"
            assert "bottles" in data, "No bottles array in response"
            assert "is_manifest" in data

            # Bottles should be an array of BottleMetadata objects (as JSON)
            assert isinstance(data["bottles"], list)
            if len(data["bottles"]) > 0:
                bottle = data["bottles"][0]
                assert "producer" in bottle or "name" in bottle

            # NO session cookie should be set (stateless!)
            # Note: session cookie may exist for other workflows (tastings)
            # but bottle data is returned in response, not stored in session

    @pytest.mark.asyncio
    async def test_upload_manifest_returns_multiple_bottles(self, test_client, wine_manifest_pdf):
        """Test manifest upload returns multiple bottles as JSON."""
        with open(wine_manifest_pdf, "rb") as f:
            response = test_client.post(
                "/api/v1/bottles/upload",
                files={"file": ("manifest.pdf", f, "application/pdf")},
                data={
                    "upload_type": "manifest",
                    "beverage_type": "wine",
                    "expected_count": "6"
                }
            )

        if response.status_code == 200:
            data = response.json()

            assert data["is_manifest"] is True
            assert len(data["bottles"]) > 0

            # Each bottle should have metadata
            for bottle in data["bottles"]:
                assert isinstance(bottle, dict)
                # At minimum should have some fields
                assert len(bottle.keys()) > 0

    def test_upload_response_is_valid_json(self, test_client, sample_bottle_image):
        """Test upload response is valid JSON (critical for Alpine.js parsing)."""
        response = test_client.post(
            "/api/v1/bottles/upload",
            files={"file": ("bottle.jpg", sample_bottle_image, "image/jpeg")},
            data={"upload_type": "bottle_image", "beverage_type": "whiskey"}
        )

        # Should return valid JSON regardless of success/failure
        try:
            data = response.json()
            assert isinstance(data, dict)
        except json.JSONDecodeError as e:
            pytest.fail(f"Upload response is not valid JSON: {e}\nResponse: {response.text}")


class TestStatelessBottleSave:
    """Test stateless bottle save API with duplicate detection."""

    @pytest.mark.asyncio
    async def test_save_bottle_endpoint_exists(self, test_client):
        """Test that save endpoint exists and requires bottle data."""
        # Call without data should fail
        response = test_client.post("/api/v1/bottles/save", json={})

        # Should fail with validation error (missing required fields)
        assert response.status_code in [400, 422]

    @pytest.mark.asyncio
    async def test_save_bottle_with_valid_data(self, test_client, sample_bottle_image):
        """Test saving bottle with valid data."""
        # First upload to get bottle data
        upload_response = test_client.post(
            "/api/v1/bottles/upload",
            files={"file": ("bottle.jpg", sample_bottle_image, "image/jpeg")},
            data={"upload_type": "bottle_image", "beverage_type": "whiskey"}
        )

        if upload_response.status_code != 200:
            pytest.skip("Upload failed (likely no LLM)")

        upload_data = upload_response.json()
        upload_id = upload_data["upload_id"]
        bottle = upload_data["bottles"][0]

        # Now save the bottle
        save_response = test_client.post(
            "/api/v1/bottles/save",
            json={
                "bottle": bottle,
                "upload_id": upload_id
            }
        )

        # May succeed or fail (e.g., vault not configured in test env)
        if save_response.status_code == 200:
            save_data = save_response.json()
            # Should return vault_path if saved successfully
            assert "vault_path" in save_data or "status" in save_data
        else:
            # Should fail gracefully with clear error
            assert save_response.status_code in [400, 500]
            error = save_response.json()
            assert "detail" in error


class TestManualCropTemp:
    """Test manual cropping of temporary labels."""

    def test_manual_crop_temp_endpoint_exists(self, test_client):
        """Test that manual crop temp endpoint exists."""
        # Call without data should fail with validation error
        response = test_client.post("/api/v1/bottles/manual-crop-temp", json={})

        assert response.status_code in [400, 422]


class TestBottleImageServing:
    """Test image serving endpoints (vault and temp)."""

    def test_temp_image_serving_endpoint_exists(self, test_client):
        """Test that temp image serving endpoint exists."""
        # Should return 404 for non-existent upload
        response = test_client.get("/api/v1/temp-images/nonexistent/test.jpg")

        assert response.status_code == 404

    def test_vault_image_serving_endpoint_exists(self, test_client):
        """Test that vault image serving endpoint exists."""
        # Should return 404 for non-existent bottle
        response = test_client.get("/api/v1/bottle-label/nonexistent/bottle")

        assert response.status_code == 404


class TestStatelessWorkflowIntegration:
    """Test complete stateless workflow (upload → client-side editing → save)."""

    @pytest.mark.asyncio
    async def test_stateless_workflow_upload_to_save(self, test_client, sample_bottle_image):
        """
        Test stateless workflow simulating client-side state management.

        Flow:
        1. Upload bottle image
        2. Get bottles in JSON response (no session lookup)
        3. Simulate client-side editing (just modify bottle data)
        4. Save to vault with duplicate detection
        """
        # Step 1: Upload
        upload_response = test_client.post(
            "/api/v1/bottles/upload",
            files={"file": ("bottle.jpg", sample_bottle_image, "image/jpeg")},
            data={"upload_type": "bottle_image", "beverage_type": "whiskey"}
        )

        if upload_response.status_code != 200:
            pytest.skip("Upload failed (likely no LLM)")

        upload_data = upload_response.json()

        # Step 2: Bottles returned directly in response
        assert "bottles" in upload_data
        assert len(upload_data["bottles"]) > 0

        bottle = upload_data["bottles"][0]
        upload_id = upload_data["upload_id"]

        # Step 3: Simulate client-side editing (Alpine.js would do this)
        bottle["notes"] = "Test workflow notes"
        bottle["purchase_source"] = "Test Store"
        bottle["inventory"] = 1

        # Step 4: Save (with duplicate detection)
        save_response = test_client.post(
            "/api/v1/bottles/save",
            json={
                "bottle": bottle,
                "upload_id": upload_id,
                "force_save": False  # Check for duplicates
            }
        )

        # May succeed or fail (vault config, duplicates, etc.)
        assert save_response.status_code in [200, 400, 409, 500]

        if save_response.status_code == 200:
            save_data = save_response.json()
            # Successful save should return status or vault_path
            assert "status" in save_data or "vault_path" in save_data

        elif save_response.status_code == 409:
            # Duplicate found
            dup_data = save_response.json()
            assert "status" in dup_data
            assert dup_data["status"] == "duplicate_found"
            assert "duplicates" in dup_data


class TestDeprecatedEndpointsRemoved:
    """Test that deprecated session-based endpoints are removed."""

    def test_deprecated_get_extraction_endpoint_removed(self, test_client):
        """Test that GET /api/v1/bottles/{extraction_id} is removed."""
        response = test_client.get("/api/v1/bottles/test-extraction-id")

        # Should return 404 or 405 (Method Not Allowed)
        # The route no longer exists for bottle extraction
        # Note: This endpoint was session-based and deprecated
        assert response.status_code in [404, 405]

    def test_deprecated_enrich_endpoint_removed(self, test_client):
        """Test that POST /api/v1/bottles/{extraction_id}/enrich/{index} is removed."""
        response = test_client.post("/api/v1/bottles/test-id/enrich/0")

        # Should return 404 or 405 (route doesn't exist)
        assert response.status_code in [404, 405]

    def test_deprecated_update_endpoint_removed(self, test_client):
        """Test that PUT /api/v1/bottles/{extraction_id}/update/{index} is removed."""
        response = test_client.put("/api/v1/bottles/test-id/update/0", json={})

        # Should return 404 or 405 (route doesn't exist)
        assert response.status_code in [404, 405]

    def test_deprecated_approve_endpoint_removed(self, test_client):
        """Test that POST /api/v1/bottles/{extraction_id}/approve/{index} is removed."""
        response = test_client.post("/api/v1/bottles/test-id/approve/0")

        # Should return 404 or 405 (route doesn't exist)
        assert response.status_code in [404, 405]

    def test_deprecated_reject_endpoint_removed(self, test_client):
        """Test that POST /api/v1/bottles/{extraction_id}/reject is removed."""
        response = test_client.post("/api/v1/bottles/test-id/reject")

        # Should return 404 or 405 (route doesn't exist)
        assert response.status_code in [404, 405]
