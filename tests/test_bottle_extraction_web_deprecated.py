"""Tests for bottle extraction via web server."""

import json
from pathlib import Path
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from reserve_automation.core.config import Config
from reserve_automation.web.app import app
from reserve_automation.web.config import load_web_config


@pytest.fixture(scope="module")
def test_client():
    """Create test client for web application."""
    # Initialize config
    core_config, web_config = load_web_config()

    # Override dependencies
    from reserve_automation.web import app as web_app
    web_app.core_config = core_config
    web_app.web_config = web_config

    # Initialize bottle registry for ID lookups
    from reserve_automation.core.bottle_registry import BottleRegistry
    web_app.bottle_registry = BottleRegistry()

    # Create services
    from reserve_automation.web.services.upload_service import UploadService
    web_app.upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions
    )

    with TestClient(app) as client:
        yield client


@pytest.fixture
def wine_manifest_file():
    """Load wine manifest PDF as upload file."""
    manifest_path = Path(__file__).parent / "fixtures" / "manifests" / "wine_manifest_sample.pdf"
    return manifest_path


@pytest.fixture
def expected_results():
    """Load expected extraction results."""
    results_path = Path(__file__).parent / "fixtures" / "manifests" / "wine_manifest_expected.json"
    if not results_path.exists():
        pytest.skip("Expected results file not found")
    return json.loads(results_path.read_text())


class TestBottleUploadAPI:
    """Test bottle upload API endpoints."""

    @pytest.mark.asyncio
    async def test_upload_wine_manifest(self, test_client, wine_manifest_file):
        """Test uploading wine manifest via API."""
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {
                "upload_type": "manifest",
                "beverage_type": "wine"
            }

            response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        assert response.status_code == 200
        result = response.json()

        assert result["status"] == "completed"
        assert "extraction_id" in result
        assert result["bottles_count"] > 0
        assert result["upload_type"] == "manifest"

    @pytest.mark.asyncio
    async def test_upload_manifest_extracts_multiple_bottles(
        self,
        test_client,
        wine_manifest_file,
        expected_results
    ):
        """Test that manifest upload extracts expected number of bottles."""
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {
                "upload_type": "manifest",
                "beverage_type": "wine"
            }

            response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        assert response.status_code == 200
        result = response.json()

        # Allow ±1 tolerance
        expected_count = len(expected_results)
        assert abs(result["bottles_count"] - expected_count) <= 1

    @pytest.mark.asyncio
    async def test_upload_creates_session_cookie(self, test_client, wine_manifest_file):
        """Test that upload creates a session cookie."""
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {
                "upload_type": "manifest",
                "beverage_type": "wine"
            }

            response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        assert response.status_code == 200
        # Check for session cookie
        assert "session" in response.cookies

    def test_upload_invalid_file_type_rejected(self, test_client):
        """Test that invalid file types are rejected."""
        # Try uploading a text file
        files = {"file": ("test.txt", BytesIO(b"Not a valid file"), "text/plain")}
        data = {
            "upload_type": "manifest",
            "beverage_type": "wine"
        }

        response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        # Should reject invalid file type
        assert response.status_code in [400, 500]


class TestBottleReviewAPI:
    """Test bottle review API endpoints."""

    @pytest.mark.asyncio
    async def test_get_extraction_data(self, test_client, wine_manifest_file):
        """Test retrieving extraction data for review."""
        # First upload a file
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {
                "upload_type": "manifest",
                "beverage_type": "wine"
            }

            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        assert upload_response.status_code == 200
        extraction_id = upload_response.json()["extraction_id"]

        # Now get the extraction data
        response = test_client.get(f"/api/v1/bottles/{extraction_id}")

        assert response.status_code == 200
        result = response.json()

        assert result["extraction_id"] == extraction_id
        assert "bottles" in result
        assert len(result["bottles"]) > 0
        assert result["upload_type"] == "manifest"

    @pytest.mark.asyncio
    async def test_extraction_data_has_correct_structure(
        self,
        test_client,
        wine_manifest_file
    ):
        """Test that extraction data has correct structure."""
        # Upload
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {"upload_type": "manifest", "beverage_type": "wine"}
            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        extraction_id = upload_response.json()["extraction_id"]

        # Get extraction
        response = test_client.get(f"/api/v1/bottles/{extraction_id}")
        result = response.json()

        # Check structure
        first_bottle = result["bottles"][0]
        assert "bottle" in first_bottle
        assert "extraction_meta" in first_bottle
        assert "stage" in first_bottle
        assert first_bottle["stage"] == "extracted"

        # Check bottle data
        bottle_data = first_bottle["bottle"]
        assert "producer" in bottle_data
        assert "name" in bottle_data
        assert "beverage_type" in bottle_data


class TestBottleEnrichmentAPI:
    """Test bottle enrichment API endpoints."""

    @pytest.mark.asyncio
    async def test_enrich_bottle(self, test_client, wine_manifest_file):
        """Test enriching a bottle with web search."""
        # Upload
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {"upload_type": "manifest", "beverage_type": "wine"}
            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        extraction_id = upload_response.json()["extraction_id"]

        # Enrich first bottle
        enrich_response = test_client.post(
            f"/api/v1/bottles/{extraction_id}/enrich/0"
        )

        assert enrich_response.status_code == 200
        result = enrich_response.json()

        # API returns "suggestions_ready" when enrichment finds suggestions
        assert result["status"] in ["enriched", "already_enriched", "suggestions_ready"]
        # New API format returns suggestions and enrichment_meta instead of bottle
        assert "enrichment_meta" in result or "suggestions" in result

    @pytest.mark.asyncio
    async def test_enrichment_updates_stage(self, test_client, wine_manifest_file):
        """Test that enrichment completes successfully."""
        # Upload
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {"upload_type": "manifest", "beverage_type": "wine"}
            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        extraction_id = upload_response.json()["extraction_id"]

        # Enrich
        enrich_response = test_client.post(
            f"/api/v1/bottles/{extraction_id}/enrich/0"
        )

        # Verify enrichment was successful
        assert enrich_response.status_code == 200
        enrich_result = enrich_response.json()
        assert "status" in enrich_result
        assert enrich_result["status"] in ["enriched", "already_enriched", "suggestions_ready"]


class TestBottleUpdateAPI:
    """Test bottle update API endpoints."""

    @pytest.mark.asyncio
    async def test_update_bottle_data(self, test_client, wine_manifest_file):
        """Test updating bottle data via API."""
        # Upload
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {"upload_type": "manifest", "beverage_type": "wine"}
            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        extraction_id = upload_response.json()["extraction_id"]

        # Get current data
        get_response = test_client.get(f"/api/v1/bottles/{extraction_id}")
        bottle_data = get_response.json()["bottles"][0]["bottle"]

        # Modify data
        bottle_data["producer"] = "Updated Producer"
        bottle_data["year"] = 2024

        # Update
        update_response = test_client.put(
            f"/api/v1/bottles/{extraction_id}/update/0",
            json={"bottle": bottle_data}
        )

        assert update_response.status_code == 200

        # Verify update
        get_response2 = test_client.get(f"/api/v1/bottles/{extraction_id}")
        updated_bottle = get_response2.json()["bottles"][0]["bottle"]

        assert updated_bottle["producer"] == "Updated Producer"
        assert updated_bottle["year"] == 2024


class TestBottleApprovalAPI:
    """Test bottle approval (save to Obsidian) API endpoints."""

    @pytest.mark.asyncio
    async def test_approve_bottle_requires_valid_vault(
        self,
        test_client,
        wine_manifest_file
    ):
        """Test that approving bottle requires valid vault path."""
        # Upload
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {"upload_type": "manifest", "beverage_type": "wine"}
            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        extraction_id = upload_response.json()["extraction_id"]

        # Try to approve (may fail if vault not configured)
        approve_response = test_client.post(
            f"/api/v1/bottles/{extraction_id}/approve/0"
        )

        # Either succeeds or fails with vault error
        assert approve_response.status_code in [200, 500]

        if approve_response.status_code == 500:
            # Should mention vault or template directory in error (configuration issue)
            error = approve_response.json()
            error_msg = error["detail"].lower()
            assert "vault" in error_msg or "not configured" in error_msg or "template" in error_msg


class TestBottleReviewPage:
    """Test bottle review page."""

    @pytest.mark.asyncio
    async def test_review_page_loads(self, test_client, wine_manifest_file):
        """Test that review page loads with extraction data."""
        # Upload
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {"upload_type": "manifest", "beverage_type": "wine"}
            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        extraction_id = upload_response.json()["extraction_id"]

        # Load review page
        response = test_client.get(f"/review-bottles/{extraction_id}")

        assert response.status_code == 200
        assert "Review Bottle" in response.text or "review" in response.text.lower()


class TestBottleWorkflowIntegration:
    """Test complete bottle upload workflow (integration tests)."""

    @pytest.mark.asyncio
    async def test_complete_workflow_manifest_to_review(
        self,
        test_client,
        wine_manifest_file
    ):
        """Test complete workflow from upload to review."""
        # Step 1: Upload manifest
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {"upload_type": "manifest", "beverage_type": "wine"}
            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        assert upload_response.status_code == 200
        extraction_id = upload_response.json()["extraction_id"]
        bottles_count = upload_response.json()["bottles_count"]

        # Step 2: Get extraction for review
        get_response = test_client.get(f"/api/v1/bottles/{extraction_id}")
        assert get_response.status_code == 200
        extraction_data = get_response.json()
        assert len(extraction_data["bottles"]) == bottles_count

        # Step 3: Enrich first bottle
        enrich_response = test_client.post(
            f"/api/v1/bottles/{extraction_id}/enrich/0"
        )
        assert enrich_response.status_code == 200

        # Step 4: Get current bottle data and update it
        get_response = test_client.get(f"/api/v1/bottles/{extraction_id}")
        extraction_data = get_response.json()
        bottle_data = extraction_data["bottles"][0]
        bottle_data["notes"] = "Test notes"

        update_response = test_client.put(
            f"/api/v1/bottles/{extraction_id}/update/0",
            json={"bottle": bottle_data}
        )
        assert update_response.status_code == 200

        # Workflow complete (approval would require valid vault)

    @pytest.mark.asyncio
    async def test_reject_bottles_workflow(self, test_client, wine_manifest_file):
        """Test rejecting bottles workflow."""
        # Upload
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {"upload_type": "manifest", "beverage_type": "wine"}
            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        extraction_id = upload_response.json()["extraction_id"]

        # Reject
        reject_response = test_client.post(f"/api/v1/bottles/{extraction_id}/reject")

        assert reject_response.status_code == 200
        result = reject_response.json()
        assert result["status"] == "rejected"

        # Session should be cleared - getting extraction should fail
        get_response = test_client.get(f"/api/v1/bottles/{extraction_id}")
        assert get_response.status_code == 404


class TestSessionPersistence:
    """Test session persistence across requests."""

    @pytest.mark.asyncio
    async def test_session_persists_across_requests(
        self,
        test_client,
        wine_manifest_file
    ):
        """Test that session data persists across multiple requests."""
        # Upload with session
        with open(wine_manifest_file, "rb") as f:
            files = {"file": ("wine_manifest.pdf", f, "application/pdf")}
            data = {"upload_type": "manifest", "beverage_type": "wine"}
            upload_response = test_client.post("/api/v1/bottles/upload", files=files, data=data)

        extraction_id = upload_response.json()["extraction_id"]

        # Make multiple requests with same session
        for _ in range(3):
            get_response = test_client.get(f"/api/v1/bottles/{extraction_id}")
            assert get_response.status_code == 200

            data = get_response.json()
            assert data["extraction_id"] == extraction_id
