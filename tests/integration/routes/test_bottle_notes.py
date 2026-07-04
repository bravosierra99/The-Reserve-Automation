"""Integration tests for shared bottle notes and the update-fields save contract.

Covers two things:
1. PUT /api/v1/bottles/{id}/notes — the ONE path that updates notes on
   existing bottles (admin + family).
2. Regression for the silent-save bug: update-fields only persists fields sent
   in `updates` (the frontend used to send edits only inside `bottle`, which
   the route ignores — every management-mode edit was dropped while the UI
   showed a success toast).
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from reserve_automation.core.models import BottleMetadata
from reserve_automation.db.engine import get_db
from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository


@pytest.fixture
def client(tmp_path):
    """Test client plus a seeded bottle in the shared in-memory SQLite DB."""
    from reserve_automation.core.config import Config
    from reserve_automation.web import app as app_module
    from reserve_automation.web.app import app

    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)
    app_module.core_config = Config(paths={"vault": str(vault_path), "templates_dir": "templates"})

    web_config = Mock()
    web_config.sessions.secret_key = "test-secret"
    web_config.sessions.max_age_hours = 24
    app_module.web_config = web_config

    db = next(get_db())
    repo = SQLiteBottleRepository(db)
    bottle = repo.create(BottleMetadata(
        producer="NotesCo",
        name="Test Rye",
        type="whiskey",
        source="test",
        price=25,
        proof=90,
    ))

    with TestClient(app) as test_client:
        yield test_client, repo, bottle

    repo.delete(int(bottle.id))
    db.close()


class TestBottleNotesEndpoint:
    def test_put_notes_persists(self, client):
        tc, repo, bottle = client
        r = tc.put(f"/api/v1/bottles/{bottle.id}/notes",
                   json={"notes": "Better after decanting for a day."})
        assert r.status_code == 200, r.text
        assert r.json()["notes"] == "Better after decanting for a day."

        fresh = repo.get_by_id(int(bottle.id))
        assert fresh.notes == "Better after decanting for a day."

    def test_put_notes_does_not_touch_other_fields(self, client):
        tc, repo, bottle = client
        tc.put(f"/api/v1/bottles/{bottle.id}/notes", json={"notes": "hello"})
        fresh = repo.get_by_id(int(bottle.id))
        assert fresh.price == 25
        assert fresh.proof == 90
        assert fresh.producer == "NotesCo"

    def test_put_empty_notes_stores_null(self, client):
        tc, repo, bottle = client
        tc.put(f"/api/v1/bottles/{bottle.id}/notes", json={"notes": "something"})
        r = tc.put(f"/api/v1/bottles/{bottle.id}/notes", json={"notes": "   "})
        assert r.status_code == 200
        assert r.json()["notes"] is None
        assert repo.get_by_id(int(bottle.id)).notes is None

    def test_put_notes_unknown_bottle_404(self, client):
        tc, _, _ = client
        r = tc.put("/api/v1/bottles/99999999/notes", json={"notes": "x"})
        assert r.status_code == 404


class TestUpdateFieldsSaveContract:
    def test_edits_in_updates_persist(self, client):
        """The exact payload shape saveManagement() sends must persist."""
        tc, repo, bottle = client
        payload = bottle.model_dump(mode="json")
        payload["id"] = bottle.id
        r = tc.post(
            "/api/v1/management/bottles/update-fields",
            json={
                "bottle": payload,
                # editableBottle shape: form values, numerics may be strings/empty
                "updates": {"price": 99.0, "proof": "", "region": "Kentucky"},
            },
        )
        assert r.status_code == 200, r.text
        fresh = repo.get_by_id(int(bottle.id))
        assert fresh.price == 99.0
        assert fresh.proof is None  # cleared via empty string
        assert fresh.region == "Kentucky"

    def test_edits_only_inside_bottle_are_ignored(self, client):
        """Documents the route contract: `bottle` is for identity only."""
        tc, repo, bottle = client
        payload = bottle.model_dump(mode="json")
        payload["id"] = bottle.id
        payload["price"] = 1234.0  # edit hidden inside `bottle` — not persisted
        r = tc.post(
            "/api/v1/management/bottles/update-fields",
            json={"bottle": payload, "updates": {}},
        )
        assert r.status_code == 200
        assert repo.get_by_id(int(bottle.id)).price == 25
