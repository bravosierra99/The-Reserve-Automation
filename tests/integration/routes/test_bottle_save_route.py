"""Integration tests for POST /api/v1/bottles/save and /api/v1/bottles/check-duplicates.

These tests exercise the save route directly with pre-built bottle payloads — no LLM
upload step required. They specifically cover the find_duplicates call path that was
previously untested and caused a production 500 error
(SQLiteBottleRepository.find_duplicates() got an unexpected keyword argument 'threshold').

Coverage:
- Save a new bottle (no duplicates) → status: success
- Save a bottle that matches an existing one → status: duplicate_found
- force_save bypasses duplicate detection
- replace_bottle_id updates an existing bottle
- /check-duplicates endpoint returns correct matches
- Bad requests rejected with 422
"""

import pytest
from unittest.mock import Mock
from fastapi.testclient import TestClient

from reserve_automation.core.config import Config
from reserve_automation.db.engine import get_db
from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client(tmp_path):
    """Test client that bypasses the app lifespan.

    Sets core_config and web_config directly to avoid vault-path validation
    in Config.load(). Auth works because the session-scoped conftest fixture
    already enabled dev mode on _startup_auth_config / app.state.auth_config.
    """
    from reserve_automation.web import app as app_module

    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)

    app_module.core_config = Config(
        paths={"vault": str(vault_path), "templates_dir": "templates"}
    )

    web_config = Mock()
    web_config.sessions.secret_key = "test-secret"
    web_config.sessions.max_age_hours = 24
    app_module.web_config = web_config

    return TestClient(app_module.app)


@pytest.fixture
def bottle_repo():
    """Repository backed by the shared in-memory SQLite DB."""
    gen = get_db()
    db = next(gen)
    repo = SQLiteBottleRepository(db)
    yield repo
    try:
        next(gen)
    except StopIteration:
        pass


# ---------------------------------------------------------------------------
# Payloads
# ---------------------------------------------------------------------------

CABERNET_PAYLOAD = {
    "producer": "Vineyard 29",
    "name": "The Essentials",
    "type": "wine",
    "year": 2022,
    "beverage_type": "Red wine",
    "country": "USA",
    "region": "Napa Valley",
    "source": "manual",
}

DIFFERENT_BOTTLE_PAYLOAD = {
    "producer": "Opus One Winery",
    "name": "Opus One Reserve",
    "type": "wine",
    "year": 2019,
    "beverage_type": "Red wine",
    "country": "USA",
    "source": "manual",
}


# ---------------------------------------------------------------------------
# Save route — happy path (no existing bottles)
# ---------------------------------------------------------------------------

class TestSaveBottleNoDuplicates:
    """Save succeeds when no similar bottle exists in the DB."""

    def test_save_new_bottle_returns_success(self, client):
        response = client.post(
            "/api/v1/bottles/save",
            json={"bottle": DIFFERENT_BOTTLE_PAYLOAD, "upload_id": None},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "success"
        assert "id" in data

    def test_save_creates_retrievable_bottle(self, client, bottle_repo):
        unique_payload = {**DIFFERENT_BOTTLE_PAYLOAD, "producer": "Unique Winery XYZ"}
        response = client.post(
            "/api/v1/bottles/save",
            json={"bottle": unique_payload, "upload_id": None},
        )
        assert response.status_code == 200, response.text
        bottle_id = int(response.json()["id"])
        saved = bottle_repo.get_by_id(bottle_id)
        assert saved is not None
        assert saved.producer == "Unique Winery XYZ"


# ---------------------------------------------------------------------------
# Save route — duplicate detection
# ---------------------------------------------------------------------------

class TestSaveBottleDuplicateDetection:
    """Duplicate detection fires correctly and can be bypassed."""

    @pytest.fixture(autouse=True)
    def seed_existing_bottle(self, bottle_repo):
        from reserve_automation.core.models import BottleMetadata
        created = bottle_repo.create(BottleMetadata(**CABERNET_PAYLOAD))
        self._existing_id = str(created.id)
        yield
        bottle_repo.delete(created.id)

    def test_save_matching_bottle_returns_duplicate_found(self, client):
        response = client.post(
            "/api/v1/bottles/save",
            json={"bottle": CABERNET_PAYLOAD, "upload_id": None, "force_save": False},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "duplicate_found"
        assert len(data["duplicates"]) >= 1

    def test_force_save_bypasses_duplicate_detection_different_year(self, client):
        """force_save with a similar-but-different vintage creates a new bottle."""
        similar_but_different = {**CABERNET_PAYLOAD, "year": 2020}
        response = client.post(
            "/api/v1/bottles/save",
            json={"bottle": similar_but_different, "upload_id": None, "force_save": True},
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "success"

    def test_force_save_identical_bottle_upserts(self, client):
        """force_save with an exactly identical bottle updates the existing record (upsert)."""
        response = client.post(
            "/api/v1/bottles/save",
            json={"bottle": CABERNET_PAYLOAD, "upload_id": None, "force_save": True},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "success"
        # Should return the same ID as the seeded bottle
        assert data["id"] == self._existing_id

    def test_replace_bottle_id_bypasses_duplicate_detection(self, client):
        response = client.post(
            "/api/v1/bottles/save",
            json={
                "bottle": CABERNET_PAYLOAD,
                "upload_id": None,
                "replace_bottle_id": self._existing_id,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "success"


# ---------------------------------------------------------------------------
# Save route — replace existing bottle
# ---------------------------------------------------------------------------

class TestSaveBottleReplace:
    """replace_bottle_id updates an existing record."""

    @pytest.fixture(autouse=True)
    def seed_existing_bottle(self, bottle_repo):
        from reserve_automation.core.models import BottleMetadata
        created = bottle_repo.create(BottleMetadata(**CABERNET_PAYLOAD))
        self._existing_id = str(created.id)
        yield
        try:
            bottle_repo.delete(created.id)
        except Exception:
            pass

    def test_replace_updates_existing_bottle(self, client, bottle_repo):
        updated_payload = {**CABERNET_PAYLOAD, "year": 2021}
        response = client.post(
            "/api/v1/bottles/save",
            json={
                "bottle": updated_payload,
                "upload_id": None,
                "replace_bottle_id": self._existing_id,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "success"
        refreshed = bottle_repo.get_by_id(int(self._existing_id))
        assert refreshed.year == 2021


# ---------------------------------------------------------------------------
# /check-duplicates endpoint
# ---------------------------------------------------------------------------

class TestCheckDuplicatesEndpoint:
    """The manual check-duplicates endpoint returns correct matches."""

    @pytest.fixture(autouse=True)
    def seed_existing_bottle(self, bottle_repo):
        from reserve_automation.core.models import BottleMetadata
        created = bottle_repo.create(BottleMetadata(**CABERNET_PAYLOAD))
        self._existing_id = created.id
        yield
        bottle_repo.delete(created.id)

    def test_check_duplicates_finds_match(self, client):
        response = client.post(
            "/api/v1/bottles/check-duplicates",
            json=CABERNET_PAYLOAD,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "checked"
        assert data["count"] >= 1

    def test_check_duplicates_no_match(self, client):
        response = client.post(
            "/api/v1/bottles/check-duplicates",
            json=DIFFERENT_BOTTLE_PAYLOAD,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["status"] == "checked"
        assert isinstance(data["count"], int)

    def test_check_duplicates_returns_required_fields(self, client):
        response = client.post(
            "/api/v1/bottles/check-duplicates",
            json=CABERNET_PAYLOAD,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "status" in data
        assert "duplicates" in data
        assert "count" in data


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestSaveBottleValidation:
    """Bad requests are rejected before touching the DB."""

    def test_missing_bottle_key_returns_422(self, client):
        response = client.post("/api/v1/bottles/save", json={"upload_id": "abc"})
        assert response.status_code == 422

    def test_empty_body_returns_422(self, client):
        response = client.post("/api/v1/bottles/save", json={})
        assert response.status_code == 422
