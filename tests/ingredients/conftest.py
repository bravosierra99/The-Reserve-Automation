"""
Shared fixtures for ingredient system tests.

Uses in-memory SQLite database for test isolation.
"""

import pytest

from reserve_automation.core.ingredient import Ingredient


@pytest.fixture(scope="module")
def test_db():
    """Get a fresh database session and seed ingredient test data."""
    from reserve_automation.db.engine import get_db

    db = next(get_db())

    # Clean any existing ingredient data
    from reserve_automation.db.models.ingredient import IngredientModel
    db.query(IngredientModel).delete()
    db.commit()

    # Seed ingredient tree via repo
    from reserve_automation.db.repositories.ingredient_repo import SQLiteIngredientRepository
    repo = SQLiteIngredientRepository(db)

    # Root nodes
    spirit = repo.create(Ingredient(name="Spirit"))
    mixer = repo.create(Ingredient(name="Mixer"))
    garnish = repo.create(Ingredient(name="Garnish"))

    # Spirit subtree
    vodka = repo.create(Ingredient(name="Vodka", parent="Spirit"))
    repo.create(Ingredient(name="Gin", parent="Spirit"))
    flavored = repo.create(Ingredient(name="Flavored Vodka", parent="Vodka"))
    vanilla = repo.create(Ingredient(name="Vanilla Vodka", parent="Flavored Vodka"))
    repo.create(Ingredient(
        name="Svedka Vanilla Vodka",
        parent="Vanilla Vodka",
        cost=12.99,
        volume_ml=750,
        abv=35.0,
    ))

    # Mixer subtree
    tonic = repo.create(Ingredient(name="Tonic Water", parent="Mixer"))
    repo.create(Ingredient(
        name="Fever-Tree Indian Tonic",
        parent="Tonic Water",
        cost=6.99,
        volume_ml=500,
    ))
    repo.create(Ingredient(name="Simple Syrup", parent="Mixer"))

    # Garnish subtree
    repo.create(Ingredient(name="Lime", parent="Garnish"))

    yield db

    # Clean up after tests
    db.query(IngredientModel).delete()
    db.commit()


@pytest.fixture(scope="module")
def test_client(test_db):
    """Create test client with in-memory database."""
    from fastapi.testclient import TestClient

    from reserve_automation.web import app as web_app
    from reserve_automation.web.app import app
    from reserve_automation.web.config import load_web_config
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
