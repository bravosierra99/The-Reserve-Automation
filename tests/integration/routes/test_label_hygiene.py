"""Integration tests for label hygiene across the upload/save/download paths.

Covers the fixes for docs/GROUND_TRUTH.md #4:
1. Manifest uploads must NOT stage the manifest document as a temp label
   (it used to become every imported bottle's label.jpg).
2. /api/v1/bottles/save must not attach a non-image temp label to a bottle.
3. /api/v1/management/labels/download-image must reject non-images and
   tiny web thumbnails before saving anything.
"""

import shutil
import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from reserve_automation.core.config import Config
from reserve_automation.core.models import BottleMetadata
from reserve_automation.db.engine import get_db
from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF\n"


def _jpeg_bytes(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color="white")
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture
def client(tmp_path):
    """Test client that bypasses the app lifespan (same pattern as
    test_bottle_save_route.py)."""
    from reserve_automation.web import app as app_module
    from reserve_automation.web.services.upload_service import UploadService

    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)

    app_module.core_config = Config(
        paths={"vault": str(vault_path), "templates_dir": "templates"}
    )

    web_config = Mock()
    web_config.sessions.secret_key = "test-secret"
    web_config.sessions.max_age_hours = 24
    app_module.web_config = web_config

    app_module.upload_service = UploadService(
        temp_dir=str(tmp_path / "uploads"),
        max_file_size_mb=10,
        allowed_extensions=["jpg", "jpeg", "png", "pdf"],
    )

    return TestClient(app_module.app)


@pytest.fixture
def bottle_repo():
    gen = get_db()
    db = next(gen)
    repo = SQLiteBottleRepository(db)
    yield repo
    try:
        next(gen)
    except StopIteration:
        pass


@pytest.fixture
def temp_upload(request):
    """Create a /tmp/reserve_uploads/{id}/labels dir (the hardcoded path
    save.py reads temp labels from) and clean it up afterwards."""
    upload_id = f"test-{uuid.uuid4()}"
    labels_dir = Path("/tmp/reserve_uploads") / upload_id / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    yield upload_id, labels_dir
    shutil.rmtree(Path("/tmp/reserve_uploads") / upload_id, ignore_errors=True)


BOTTLE_PAYLOAD = {
    "producer": "Hygiene Test Winery",
    "name": "Label Hygiene Cuvee",
    "type": "wine",
    "year": 2021,
    "beverage_type": "Red wine",
    "source": "manual",
}


# ---------------------------------------------------------------------------
# 1. Upload staging: manifests must not stage a temp label
# ---------------------------------------------------------------------------

class TestUploadTempLabelStaging:
    def _mock_extraction_service(self):
        svc = Mock()
        bottle = BottleMetadata(
            producer="P", name="N", type="wine", beverage_type="Red wine", source="test"
        )
        svc.extract_bottle_from_image = AsyncMock(return_value=(bottle, {}))
        svc.extract_bottles_from_manifest = AsyncMock(return_value=[bottle, bottle])
        svc.bottle_to_dict = lambda b: b.model_dump(mode="json")
        return svc

    def test_manifest_upload_does_not_stage_temp_label(self, client):
        from reserve_automation.web import app as app_module

        with patch(
            "reserve_automation.web.routes.bottles.extraction.ExtractionService",
            return_value=self._mock_extraction_service(),
        ):
            response = client.post(
                "/api/v1/bottles/upload",
                files={"file": ("manifest.pdf", BytesIO(PDF_BYTES), "application/pdf")},
                data={"upload_type": "manifest", "beverage_type": "wine"},
            )

        assert response.status_code == 200
        upload_id = response.json()["upload_id"]
        temp_label = app_module.upload_service.temp_dir / upload_id / "labels" / "label.jpg"
        assert not temp_label.exists(), (
            "Manifest document was staged as a temp label — it would become "
            "every imported bottle's label.jpg on save"
        )

    def test_bottle_image_upload_still_stages_temp_label(self, client):
        from reserve_automation.web import app as app_module

        with patch(
            "reserve_automation.web.routes.bottles.extraction.ExtractionService",
            return_value=self._mock_extraction_service(),
        ):
            response = client.post(
                "/api/v1/bottles/upload",
                files={"file": ("bottle.jpg", BytesIO(_jpeg_bytes(800, 1200)), "image/jpeg")},
                data={"upload_type": "bottle_image", "beverage_type": "wine"},
            )

        assert response.status_code == 200
        upload_id = response.json()["upload_id"]
        temp_label = app_module.upload_service.temp_dir / upload_id / "labels" / "label.jpg"
        assert temp_label.exists()


# ---------------------------------------------------------------------------
# 2. Save: non-image temp label must not be attached to the bottle
# ---------------------------------------------------------------------------

class TestSaveLabelValidation:
    def test_save_skips_pdf_temp_label(self, client, bottle_repo, temp_upload, tmp_path, monkeypatch):
        from reserve_automation.web.routes.bottles import save as save_module

        media_dir = tmp_path / "media"
        monkeypatch.setattr(save_module, "MEDIA_DIR", media_dir)

        upload_id, labels_dir = temp_upload
        (labels_dir / "label.jpg").write_bytes(PDF_BYTES)

        response = client.post(
            "/api/v1/bottles/save",
            json={"bottle": BOTTLE_PAYLOAD, "upload_id": upload_id},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        bottle_id = response.json()["id"]
        dest = media_dir / "bottles" / bottle_id / "label.jpg"
        assert not dest.exists(), "PDF was attached as the bottle's label"

        saved = bottle_repo.get_by_id(int(bottle_id))
        assert not getattr(saved, "label_path", None)
        bottle_repo.delete(int(bottle_id))

    def test_save_attaches_real_image_temp_label(self, client, bottle_repo, temp_upload, tmp_path, monkeypatch):
        from reserve_automation.web.routes.bottles import save as save_module

        media_dir = tmp_path / "media"
        monkeypatch.setattr(save_module, "MEDIA_DIR", media_dir)

        upload_id, labels_dir = temp_upload
        (labels_dir / "label.jpg").write_bytes(_jpeg_bytes(800, 1200))

        payload = dict(BOTTLE_PAYLOAD, name="Label Hygiene Cuvee Real Image")
        response = client.post(
            "/api/v1/bottles/save",
            json={"bottle": payload, "upload_id": upload_id},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        bottle_id = response.json()["id"]
        dest = media_dir / "bottles" / bottle_id / "label.jpg"
        assert dest.exists()
        bottle_repo.delete(int(bottle_id))


# ---------------------------------------------------------------------------
# 3. Download: tiny thumbnails and non-images are rejected with a 400
# ---------------------------------------------------------------------------

class TestDownloadImageValidation:
    def _download(self, client, bottle_id, body_bytes):
        class _Resp:
            content = body_bytes

            def raise_for_status(self):
                pass

        class _Client:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url):
                return _Resp()

        with patch(
            "reserve_automation.utils.url_validation.validate_url_not_internal_async",
            new=AsyncMock(return_value=None),
        ), patch("httpx.AsyncClient", return_value=_Client()):
            return client.post(
                "/api/v1/management/labels/download-image",
                json={"bottle_id": bottle_id, "image_url": "https://example.com/img.jpg"},
            )

    @pytest.fixture
    def saved_bottle(self, bottle_repo):
        bottle = BottleMetadata(
            producer="Hygiene Test Winery",
            name="Download Validation Bottle",
            type="wine",
            beverage_type="Red wine",
            source="test",
        )
        created = bottle_repo.create(bottle)
        yield created
        bottle_repo.delete(int(created.id))

    def test_rejects_tiny_thumbnail(self, client, saved_bottle):
        response = self._download(client, str(saved_bottle.id), _jpeg_bytes(160, 160))
        assert response.status_code == 400
        assert "too small" in response.json()["detail"]

    def test_rejects_non_image_body(self, client, saved_bottle):
        response = self._download(client, str(saved_bottle.id), PDF_BYTES)
        assert response.status_code == 400
        assert "not a readable image" in response.json()["detail"]

    def test_accepts_full_size_image(self, client, saved_bottle):
        response = self._download(client, str(saved_bottle.id), _jpeg_bytes(900, 1300))
        assert response.status_code == 200
        assert response.json()["status"] == "success"
