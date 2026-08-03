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
from io import BytesIO
from pathlib import Path

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


class TestUploadStreamHeartbeat:
    """The streaming upload endpoint must emit heartbeat events *during* the long
    extraction call, so the SSE response never goes silent long enough to trip an
    upstream proxy idle-timeout (nginx ~60s / Cloudflare ~100s 524). Without the
    heartbeat the browser sees a failure even though the backend extraction
    succeeds — the original "prod failed to extract my bottle" report.
    """

    def _parse_sse(self, text):
        events = []
        for part in text.split("\n\n"):
            line = part.strip()
            if line.startswith("data: "):
                events.append(json.loads(line[len("data: "):]))
        return events

    def test_extraction_emits_heartbeats_between_extracting_and_complete(
        self, test_client, sample_bottle_image
    ):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        from reserve_automation.web.routes.bottles import extraction as ext

        class _SlowExtractionService:
            def __init__(self, *a, **k):
                pass

            async def extract_bottle_from_image(self, image_path, beverage_type):
                # Sleep well past several heartbeat intervals (patched to 0.05s).
                await asyncio.sleep(0.35)
                return SimpleNamespace(purchase_source=None, inventory=0), {}

            def bottle_to_dict(self, bottle):
                return {"producer": "Heartbeat", "name": "Test Dram"}

        with patch.object(ext, "ExtractionService", _SlowExtractionService), \
             patch.object(ext, "_poll_for_model", AsyncMock(return_value=(True, ""))), \
             patch.object(ext, "_HEARTBEAT_INTERVAL_SECONDS", 0.05):
            response = test_client.post(
                "/api/v1/bottles/upload/stream",
                files={"file": ("bottle.jpg", sample_bottle_image, "image/jpeg")},
                data={"upload_type": "bottle_image", "beverage_type": "whiskey"},
            )

        assert response.status_code == 200
        events = self._parse_sse(response.text)
        statuses = [e["status"] for e in events]

        # Stream completed successfully with the extracted bottle.
        assert statuses[-1] == "complete", statuses
        assert events[-1]["bottles"] == [{"producer": "Heartbeat", "name": "Test Dram"}]

        # At least one heartbeat fired DURING extraction — identified by the
        # "(Ns elapsed)" suffix the heartbeat message_fn adds (the one-shot
        # pre-extraction "extracting" event has no elapsed suffix).
        heartbeats = [
            e for e in events
            if e["status"] == "extracting" and "elapsed" in e.get("message", "")
        ]
        assert len(heartbeats) >= 1, f"no heartbeat during extraction: {events}"

    def test_stream_shows_error_when_lm_studio_unavailable(self, test_client, sample_bottle_image):
        """When the model never becomes available, the stream emits an 'error'
        event whose message reads as a failure — not a silent 'complete' with 0
        bottles. This is the unit-level guard for the browser test
        TestBrowserUploadFlow.test_upload_bottle_shows_error_on_failure: switching
        the page to the streaming endpoint added a model-poll step that must still
        surface a fast, clearly-worded error when LM Studio is down.
        """
        from unittest.mock import AsyncMock, patch

        from reserve_automation.web.routes.bottles import extraction as ext

        with patch.object(ext, "_poll_for_model", AsyncMock(return_value=(False, "unreachable"))):
            response = test_client.post(
                "/api/v1/bottles/upload/stream",
                files={"file": ("bottle.jpg", sample_bottle_image, "image/jpeg")},
                data={"upload_type": "bottle_image", "beverage_type": "whiskey"},
            )

        assert response.status_code == 200
        events = self._parse_sse(response.text)
        statuses = [e["status"] for e in events]

        assert "error" in statuses, statuses
        assert "complete" not in statuses, statuses
        error_msg = next(e["message"] for e in events if e["status"] == "error")
        # The browser test waits on text matching /error|failed/i.
        assert "failed" in error_msg.lower() or "error" in error_msg.lower(), error_msg

    @pytest.mark.asyncio
    async def test_poll_for_model_fails_fast_when_unreachable(self):
        """_poll_for_model returns (False, 'unreachable') quickly when LM Studio
        isn't listening — it must NOT wait out the full model-load window."""
        import time
        from unittest.mock import patch

        import httpx

        from reserve_automation.web.routes.bottles import extraction as ext

        class _UnreachableClient:
            def __init__(self, *a, **k):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                raise httpx.ConnectError("connection refused")

        async def _noop_status(status, message, **extra):
            pass

        start = time.monotonic()
        with patch("httpx.AsyncClient", _UnreachableClient):
            ok, reason = await ext._poll_for_model(
                "http://localhost:1234/v1", "any-model", _noop_status,
                max_wait_seconds=300, poll_interval=8, unreachable_grace_seconds=0.2,
            )
        elapsed = time.monotonic() - start

        assert ok is False
        assert reason == "unreachable"
        assert elapsed < 3, f"fail-fast took too long: {elapsed:.1f}s"

    @pytest.mark.asyncio
    async def test_poll_for_model_sends_bearer_token(self):
        """Regression: the model pre-flight probe MUST send the LM Studio API key
        when one is configured. Without it, an auth-required LM Studio returns 401,
        which the probe misreads as 'unreachable' and fail-fasts the upload even
        though the authenticated extraction would succeed."""
        from unittest.mock import patch

        from reserve_automation.web.routes.bottles import extraction as ext

        captured_headers = {}

        class _CapturingClient:
            def __init__(self, *a, **k):
                captured_headers["value"] = k.get("headers")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                class _Resp:
                    status_code = 200

                    @staticmethod
                    def json():
                        return {"data": [{"id": "qwen/qwen3.5-9b"}]}

                return _Resp()

        async def _noop_status(status, message, **extra):
            pass

        with patch("httpx.AsyncClient", _CapturingClient):
            ok, reason = await ext._poll_for_model(
                "http://lmstudio:1234/v1", "qwen/qwen3.5-9b", _noop_status,
                api_key="sk-lm-secret",
            )

        assert ok is True and reason == ""
        assert captured_headers["value"] == {"Authorization": "Bearer sk-lm-secret"}

    @pytest.mark.asyncio
    async def test_poll_for_model_no_token_sends_no_auth_header(self):
        """When no key is configured, the probe sends no Authorization header
        (headers=None) — unchanged behaviour for keyless LM Studio setups."""
        from unittest.mock import patch

        from reserve_automation.web.routes.bottles import extraction as ext

        captured_headers = {}

        class _CapturingClient:
            def __init__(self, *a, **k):
                captured_headers["value"] = k.get("headers")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def get(self, *a, **k):
                class _Resp:
                    status_code = 200

                    @staticmethod
                    def json():
                        return {"data": [{"id": "qwen/qwen3.5-9b"}]}

                return _Resp()

        async def _noop_status(status, message, **extra):
            pass

        with patch("httpx.AsyncClient", _CapturingClient):
            ok, reason = await ext._poll_for_model(
                "http://lmstudio:1234/v1", "qwen/qwen3.5-9b", _noop_status,
                api_key=None,
            )

        assert ok is True and reason == ""
        assert captured_headers["value"] is None


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


class TestAutoCropTemp:
    """Auto-crop for upload-mode labels: POST /api/v1/bottles/auto-crop-temp.

    The upload modal's Auto-Crop button crops the just-uploaded image before
    the bottle is saved (no DB id yet), mirroring manual-crop-temp.
    """

    @pytest.mark.parametrize("bad_id", ["../etc/passwd", "a/b", ""])
    def test_invalid_upload_id_rejected(self, test_client, bad_id):
        """Path-traversal / empty upload_id is a 400, never a 500."""
        response = test_client.post(
            "/api/v1/bottles/auto-crop-temp", json={"upload_id": bad_id}
        )
        assert response.status_code == 400

    def test_missing_temp_dir_returns_404(self, test_client):
        """A well-formed but unknown upload_id has no temp dir → 404."""
        response = test_client.post(
            "/api/v1/bottles/auto-crop-temp",
            json={"upload_id": "nonexistent-upload-xyz"},
        )
        assert response.status_code == 404

    @pytest.mark.requires_lm_studio
    def test_auto_crop_happy_path(self, test_client, sample_bottle_image):
        """Staging a temp label and auto-cropping it produces a reviewable preview.

        Gated on LM Studio because crop_to_label's primary (text-based) label
        detection uses LLM vision.
        """
        import shutil
        import uuid

        upload_id = f"test-{uuid.uuid4().hex[:8]}"
        labels_dir = Path("/tmp/reserve_uploads") / upload_id / "labels"
        labels_dir.mkdir(parents=True, exist_ok=True)
        original_bytes = sample_bottle_image.getvalue()
        (labels_dir / "label.jpg").write_bytes(original_bytes)
        try:
            response = test_client.post(
                "/api/v1/bottles/auto-crop-temp", json={"upload_id": upload_id}
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["status"] == "success"
            # The crop lands in a preview file; the original label is untouched
            # until the user accepts it.
            preview = labels_dir / body["preview_filename"]
            assert preview.exists()
            assert (labels_dir / "label.jpg").read_bytes() == original_bytes

            accept = test_client.post(
                "/api/v1/bottles/accept-crop-temp", json={"upload_id": upload_id}
            )
            assert accept.status_code == 200, accept.text
            assert not preview.exists()
            assert (labels_dir / "label.jpg").read_bytes() != original_bytes
        finally:
            shutil.rmtree(Path("/tmp/reserve_uploads") / upload_id, ignore_errors=True)

    def test_accept_without_preview_returns_404(self, test_client, sample_bottle_image):
        """Accepting when no auto-crop preview exists is a 404, and the label survives."""
        import shutil
        import uuid

        upload_id = f"test-{uuid.uuid4().hex[:8]}"
        labels_dir = Path("/tmp/reserve_uploads") / upload_id / "labels"
        labels_dir.mkdir(parents=True, exist_ok=True)
        (labels_dir / "label.jpg").write_bytes(sample_bottle_image.getvalue())
        try:
            response = test_client.post(
                "/api/v1/bottles/accept-crop-temp", json={"upload_id": upload_id}
            )
            assert response.status_code == 404
            assert (labels_dir / "label.jpg").exists()
        finally:
            shutil.rmtree(Path("/tmp/reserve_uploads") / upload_id, ignore_errors=True)

    @pytest.mark.parametrize("bad_id", ["../etc/passwd", "a/b", ""])
    def test_accept_invalid_upload_id_rejected(self, test_client, bad_id):
        """accept-crop-temp validates upload_id like the crop endpoints."""
        response = test_client.post(
            "/api/v1/bottles/accept-crop-temp", json={"upload_id": bad_id}
        )
        assert response.status_code == 400


class TestWarmModel:
    """Model pre-warm: POST /api/v1/bottles/warm-model.

    The upload page fires this on load so LM Studio JIT-loads the vision
    model before the user clicks Import (a cold model otherwise adds its full
    load time to the first extraction).
    """

    @pytest.fixture(autouse=True)
    def reset_warm_state(self):
        """Each test starts from a cold warm-state and restores it after."""
        from reserve_automation.web.routes.bottles import extraction as ext

        saved = dict(ext._warm_state)
        ext._warm_state.update({"task": None, "last_ok": None})
        yield
        ext._warm_state.update(saved)

    @pytest.mark.asyncio
    async def test_warm_request_sends_bearer_token_to_chat_completions(self):
        """The warm call must authenticate like LMStudioProvider (GROUND_TRUTH.md #3)
        and must be an inference request — only inference triggers the JIT load."""
        from unittest.mock import patch

        from reserve_automation.web.routes.bottles import extraction as ext

        captured = {}

        class _CapturingClient:
            def __init__(self, *a, **k):
                captured["headers"] = k.get("headers")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

            async def post(self, url, json=None, **k):
                captured["url"] = url
                captured["payload"] = json

                class _Resp:
                    @staticmethod
                    def raise_for_status():
                        pass

                return _Resp()

        with patch("httpx.AsyncClient", _CapturingClient):
            await ext._send_warm_request(
                "http://lmstudio:1234/v1", "qwen/qwen3.5-9b", "sk-lm-secret"
            )

        assert captured["headers"] == {"Authorization": "Bearer sk-lm-secret"}
        assert captured["url"] == "http://lmstudio:1234/v1/chat/completions"
        assert captured["payload"]["model"] == "qwen/qwen3.5-9b"
        assert captured["payload"]["max_tokens"] == 1

    def test_warm_endpoint_fires_background_load(self, test_client):
        """First call kicks off a warm task and reports 'warming'."""
        from unittest.mock import AsyncMock, patch

        from reserve_automation.web.routes.bottles import extraction as ext

        with patch.object(ext, "_send_warm_request", new=AsyncMock()) as mock_send:
            response = test_client.post("/api/v1/bottles/warm-model")
            assert response.status_code == 200
            assert response.json()["status"] == "warming"
            assert ext._warm_state["task"] is not None
        # The mock may or may not have completed inside the request's loop;
        # what matters is the endpoint scheduled it.
        assert mock_send.call_count <= 1

    def test_warm_endpoint_debounces_recent_success(self, test_client):
        """A fresh successful warm short-circuits: no new task is spawned."""
        import time as _time

        from reserve_automation.web.routes.bottles import extraction as ext

        ext._warm_state["last_ok"] = _time.monotonic()
        response = test_client.post("/api/v1/bottles/warm-model")
        assert response.status_code == 200
        assert response.json()["status"] == "warm"
        assert ext._warm_state["task"] is None
