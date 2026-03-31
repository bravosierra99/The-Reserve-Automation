"""
Shared fixtures for event system tests.

Uses in-memory SQLite database for test isolation.
"""

import pytest

from reserve_automation.core.models import BottleMetadata


@pytest.fixture(scope="module")
def test_db():
    """Get a fresh database session and seed event test data (bottles)."""
    from reserve_automation.db.engine import get_db

    db = next(get_db())

    # Clean existing data
    from reserve_automation.db.models.bottle import BottleModel, TastingNoteModel
    from reserve_automation.db.models.event import (
        EventModel, EventBottleModel, EventCocktailModel,
        EventParticipantModel, EventTastingModel, EventCocktailRatingModel,
    )
    db.query(EventCocktailRatingModel).delete()
    db.query(EventTastingModel).delete()
    db.query(EventParticipantModel).delete()
    db.query(EventCocktailModel).delete()
    db.query(EventBottleModel).delete()
    db.query(EventModel).delete()
    db.query(TastingNoteModel).delete()
    db.query(BottleModel).delete()
    db.commit()

    # Seed test bottles
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
    repo = SQLiteBottleRepository(db)

    repo.create(BottleMetadata(
        producer="Buffalo Trace",
        name="Weller Special Reserve",
        type="whiskey",
        source="test",
        proof=90,
        region="Kentucky",
        inventory=1,
    ))
    repo.create(BottleMetadata(
        producer="Buffalo Trace",
        name="Blantons Original",
        type="whiskey",
        source="test",
        proof=93,
        region="Kentucky",
        inventory=1,
    ))
    repo.create(BottleMetadata(
        producer="Caymus Vineyards",
        name="Cabernet Sauvignon",
        type="wine",
        source="test",
        year=2021,
        variety="Cabernet Sauvignon",
        region="USA - Napa Valley",
        abv=14.5,
        inventory=1,
    ))
    repo.create(BottleMetadata(
        producer="Opus One",
        name="Opus One",
        type="wine",
        source="test",
        year=2019,
        variety="Bordeaux Blend",
        region="USA - Napa Valley",
        abv=14.5,
        inventory=1,
    ))

    yield db

    # Clean up
    db.query(EventCocktailRatingModel).delete()
    db.query(EventTastingModel).delete()
    db.query(EventParticipantModel).delete()
    db.query(EventCocktailModel).delete()
    db.query(EventBottleModel).delete()
    db.query(EventModel).delete()
    db.query(TastingNoteModel).delete()
    db.query(BottleModel).delete()
    db.commit()


@pytest.fixture(scope="module")
def test_client(test_db):
    """Create test client with in-memory database."""
    from fastapi.testclient import TestClient
    from reserve_automation.web.app import app
    from reserve_automation.web.config import load_web_config
    from reserve_automation.web import app as web_app
    from reserve_automation.web.services.upload_service import UploadService

    core_config, web_config = load_web_config()
    web_app.core_config = core_config
    web_app.web_config = web_config
    web_app.upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions
    )

    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def weller_bottle(test_db):
    """Return info for the test Weller bottle."""
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
    repo = SQLiteBottleRepository(test_db)
    bottles = repo.search("Weller")
    assert bottles, "Weller bottle not found in test DB"
    bottle = bottles[0]
    return {
        "name": f"{bottle.producer} - {bottle.name}",
        "id": str(bottle.id),
        "beverage_type": "whiskey"
    }


@pytest.fixture
def blantons_bottle(test_db):
    """Return info for the test Blanton's bottle."""
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
    repo = SQLiteBottleRepository(test_db)
    bottles = repo.search("Blantons")
    assert bottles, "Blantons bottle not found in test DB"
    bottle = bottles[0]
    return {
        "name": f"{bottle.producer} - {bottle.name}",
        "id": str(bottle.id),
        "beverage_type": "whiskey"
    }


@pytest.fixture
def caymus_bottle(test_db):
    """Return info for the test Caymus bottle."""
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
    repo = SQLiteBottleRepository(test_db)
    bottles = repo.search("Caymus")
    assert bottles, "Caymus bottle not found in test DB"
    bottle = bottles[0]
    return {
        "name": f"{bottle.producer} - {bottle.name}",
        "id": str(bottle.id),
        "beverage_type": "wine"
    }


@pytest.fixture
def opus_bottle(test_db):
    """Return info for the test Opus One bottle."""
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
    repo = SQLiteBottleRepository(test_db)
    bottles = repo.search("Opus One")
    assert bottles, "Opus One bottle not found in test DB"
    bottle = bottles[0]
    return {
        "name": f"{bottle.producer} - {bottle.name}",
        "id": str(bottle.id),
        "beverage_type": "wine"
    }
