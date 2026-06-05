"""Integration tests for bottle management routes (SQLite-backed).

These tests verify the management API workflow against an in-memory SQLite database:
1. Load bottles from DB
2. Search bottles
3. Update bottle fields and verify persistence
4. Verify/enrich bottle metadata (async task pattern)
5. Tasting summary from DB-seeded tasting notes
"""

from datetime import date
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from reserve_automation.core.models import BottleMetadata
from reserve_automation.core.tasting_note import TastingNote
from reserve_automation.db.engine import get_db
from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
from reserve_automation.db.repositories.tasting_repo import SQLiteTastingRepository


@pytest.fixture
def client(tmp_path):
    """Create test client and seed test bottles into the in-memory SQLite database."""
    from reserve_automation.core.config import Config
    from reserve_automation.web import app as app_module
    from reserve_automation.web.app import app

    # Config validator requires the vault path to exist, even though management
    # routes no longer use vault files. Create an empty directory to satisfy it.
    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)

    config = Config(paths={"vault": str(vault_path), "templates_dir": "templates"})
    app_module.core_config = config

    web_config = Mock()
    web_config.sessions.secret_key = "test-secret"
    web_config.sessions.max_age_hours = 24
    app_module.web_config = web_config

    db = next(get_db())
    bottle_repo = SQLiteBottleRepository(db)

    stagg = bottle_repo.create(BottleMetadata(
        producer="Buffalo Trace",
        name="GEORGE T. STAGG",
        year=2024,
        type="whiskey",
        beverage_type="Bourbon",
        source="test",
        proof=130.4,
        region="Kentucky",
        price=125,
        inventory=1,
    ))

    margaux = bottle_repo.create(BottleMetadata(
        producer="Chateau Margaux",
        name="Grand Vin",
        year=2015,
        type="wine",
        beverage_type="Red",
        source="test",
        variety="Cabernet Sauvignon Blend",
        region="France - Bordeaux",
        abv=13.5,
        price=450,
        inventory=1,
    ))

    with TestClient(app) as test_client:
        yield test_client

    # Cleanup seeded rows so the shared in-memory DB stays clean between test runs
    bottle_repo.delete(int(stagg.id))
    bottle_repo.delete(int(margaux.id))
    db.close()


class TestManagementBottleList:
    """Test loading bottles from the database."""

    def test_get_all_bottles(self, client):
        """GET /api/v1/management/bottles should return DB-backed bottles."""
        response = client.get("/api/v1/management/bottles")

        assert response.status_code == 200
        data = response.json()

        assert "bottles" in data
        assert "count" in data
        assert data["count"] >= 2

        bottles = data["bottles"]
        stagg = next((b for b in bottles if "STAGG" in b.get("name", "")), None)
        assert stagg is not None
        assert stagg["producer"] == "Buffalo Trace"
        assert stagg["beverage_type"] == "Bourbon"

    def test_search_bottles(self, client):
        """GET /api/v1/management/bottles/search should find bottles by query."""
        response = client.get("/api/v1/management/bottles/search?q=Stagg")

        assert response.status_code == 200
        data = response.json()

        assert data["count"] >= 1
        assert "STAGG" in data["bottles"][0]["name"]


class TestManagementBottleUpdate:
    """Test updating bottle metadata via the management API."""

    def test_update_bottle_fields_saves_to_db(self, client):
        """POST /api/v1/management/bottles/update-fields should persist changes to DB."""
        # Get the Stagg bottle from the list endpoint
        list_response = client.get("/api/v1/management/bottles")
        bottles = list_response.json()["bottles"]

        stagg = next((b for b in bottles if "STAGG" in b.get("name", "")), None)
        assert stagg is not None, "Test bottle not found"

        update_data = {
            "bottle": stagg,
            "updates": {
                "proof": 131.2,
                "price": 150,
            },
        }

        response = client.post(
            "/api/v1/management/bottles/update-fields",
            json=update_data,
        )

        assert response.status_code == 200, f"Update failed: {response.json()}"
        result = response.json()
        assert result["status"] == "success"

        # Verify changes are persisted by fetching fresh from API
        list_response2 = client.get("/api/v1/management/bottles")
        updated_bottles = list_response2.json()["bottles"]
        updated_stagg = next((b for b in updated_bottles if "STAGG" in b.get("name", "")), None)
        assert updated_stagg is not None
        assert updated_stagg["proof"] == 131.2
        assert updated_stagg["price"] == 150

    def test_verify_bottle_metadata(self, client):
        """POST /api/v1/management/bottles/{id}/verify starts async task,
        GET /api/v1/management/tasks/{task_id}/status returns the result.

        Starlette's TestClient runs BackgroundTasks synchronously, so the
        task is complete by the time we poll.
        """
        list_response = client.get("/api/v1/management/bottles")
        bottles = list_response.json()["bottles"]
        stagg = next((b for b in bottles if "STAGG" in b.get("name", "")), None)
        assert stagg is not None

        # Start async verification using bottle data (index param is ignored by logic)
        response = client.post(
            "/api/v1/management/bottles/0/verify",
            json={"bottle": stagg},
        )
        assert response.status_code == 200, f"Verify failed: {response.json()}"

        start_result = response.json()
        assert "task_id" in start_result
        assert start_result["status"] == "queued"

        # Poll for result (task already completed — TestClient runs bg tasks sync)
        task_id = start_result["task_id"]
        status_response = client.get(f"/api/v1/management/tasks/{task_id}/status")
        assert status_response.status_code == 200, f"Status poll failed: {status_response.json()}"

        result = status_response.json()
        assert result["status"] == "complete"
        assert "original" in result
        assert "updated" in result
        assert "changes" in result

    def test_update_year_persists_to_db(self, client):
        """Updating the year field should be saved to the DB and visible via API."""
        list_response = client.get("/api/v1/management/bottles")
        bottles = list_response.json()["bottles"]
        margaux = next((b for b in bottles if "Margaux" in b.get("producer", "")), None)
        assert margaux is not None

        update_data = {
            "bottle": margaux,
            "updates": {"year": 2016},
        }

        response = client.post(
            "/api/v1/management/bottles/update-fields",
            json=update_data,
        )

        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "success"
        assert result["bottle"]["year"] == 2016


class TestManagementTastingsSummary:
    """Test tasting statistics endpoints."""

    def test_get_tastings_summary(self, client):
        """POST /api/v1/management/bottles/tastings-summary should return DB-backed stats."""
        list_response = client.get("/api/v1/management/bottles")
        bottles = list_response.json()["bottles"]
        stagg = next((b for b in bottles if "STAGG" in b.get("name", "")), None)
        assert stagg is not None

        # Seed a tasting note for the Stagg bottle
        db = next(get_db())
        tasting_repo = SQLiteTastingRepository(db)
        tasting_repo.create(
            TastingNote(
                bottle_name="Buffalo Trace - GEORGE T. STAGG - 2024",
                taster_name="TestTaster",
                tasting_date=date(2024, 12, 30),
                beverage_type="whiskey",
                whiskey_nose=3.0,
                whiskey_palate=2.5,
                whiskey_finish=3.0,
                whiskey_overall=1.0,
            ),
            bottle_id=int(stagg["id"]),
        )
        db.close()

        response = client.post(
            "/api/v1/management/bottles/tastings-summary",
            json={"bottle": stagg},
        )

        assert response.status_code == 200
        result = response.json()
        assert result["tasting_count"] >= 1
        assert result["avg_score"] is not None
        assert result["max_score"] == 10  # Whiskey 10-point scale
        assert "TestTaster" in result["tasters"]

        # Cleanup tasting
        tastings = tasting_repo.get_by_bottle_id(int(stagg["id"]))
        for t in tastings:
            # TastingNote objects don't have id; fetch from DB model
            pass
        # Use DB session directly to clean up
        from sqlalchemy.orm import Session

        from reserve_automation.db.engine import get_engine
        from reserve_automation.db.models.bottle import TastingNoteModel
        engine = get_engine()
        with Session(engine) as session:
            session.query(TastingNoteModel).filter(
                TastingNoteModel.bottle_id == int(stagg["id"]),
                TastingNoteModel.taster_name == "TestTaster",
            ).delete()
            session.commit()
