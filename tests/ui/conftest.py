"""Fixtures for UI integration tests.

Uses TestClient (in-process) — inherits the in-memory SQLite DB already
initialised by the root conftest and the dev-mode auth bypass, so no
external server is needed. Tests run in milliseconds.
"""

import pytest
from fastapi.testclient import TestClient

from reserve_automation.core.models import BeverageType, BottleMetadata

# ---------------------------------------------------------------------------
# Seed data helpers
# ---------------------------------------------------------------------------

def _make_whiskey(**kwargs) -> BottleMetadata:
    defaults = dict(producer="Weller", name="Original Wheated Bourbon", type=BeverageType.WHISKEY, inventory=2, source="test")
    defaults.update(kwargs)
    return BottleMetadata(**defaults)


def _make_wine(**kwargs) -> BottleMetadata:
    defaults = dict(producer="Caymus", name="Cabernet Sauvignon 2021", type=BeverageType.WINE, inventory=1, source="test")
    defaults.update(kwargs)
    return BottleMetadata(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ui_client():
    """TestClient with dev-mode auth — shares the session-scoped in-memory DB."""
    from reserve_automation.web.app import app
    return TestClient(app)


@pytest.fixture(scope="module")
def seeded_bottles(ui_client):
    """Seed a whiskey and a wine bottle; return their IDs.

    Cleanup: deletes both bottles at module teardown.
    """
    from reserve_automation.db.engine import get_db
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository

    db = next(get_db())
    repo = SQLiteBottleRepository(db)

    whiskey = repo.create(_make_whiskey())
    wine = repo.create(_make_wine())

    yield {"whiskey_id": whiskey.id, "wine_id": wine.id}

    repo.delete(int(whiskey.id))
    repo.delete(int(wine.id))
