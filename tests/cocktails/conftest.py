"""
Shared fixtures for cocktail system tests.

Uses in-memory SQLite database for test isolation.
"""

import pytest

from reserve_automation.core.ingredient import Ingredient
from reserve_automation.core.cocktail import CocktailRecipe, RecipeIngredient
from reserve_automation.core.cocktail_tasting import CocktailTastingNote


@pytest.fixture(scope="module")
def test_db():
    """Get a fresh database session and seed cocktail test data."""
    from reserve_automation.db.engine import get_db

    db = next(get_db())

    # Clean existing data
    from reserve_automation.db.models.ingredient import IngredientModel
    from reserve_automation.db.models.cocktail import CocktailModel, RecipeIngredientModel, CocktailInstructionModel
    from reserve_automation.db.models.cocktail_tasting import CocktailTastingModel, CocktailTastingIngredientModel
    db.query(CocktailTastingIngredientModel).delete()
    db.query(CocktailTastingModel).delete()
    db.query(CocktailInstructionModel).delete()
    db.query(RecipeIngredientModel).delete()
    db.query(CocktailModel).delete()
    db.query(IngredientModel).delete()
    db.commit()

    # Seed ingredients
    from reserve_automation.db.repositories.ingredient_repo import SQLiteIngredientRepository
    ing_repo = SQLiteIngredientRepository(db)

    ing_repo.create(Ingredient(name="Spirit"))
    ing_repo.create(Ingredient(name="Vodka", parent="Spirit"))
    ing_repo.create(Ingredient(name="Bourbon", parent="Spirit"))
    ing_repo.create(Ingredient(name="Mixer"))
    ing_repo.create(Ingredient(name="Lime Juice", parent="Mixer"))
    ing_repo.create(Ingredient(name="Ginger Beer", parent="Mixer"))
    ing_repo.create(Ingredient(name="Simple Syrup", parent="Mixer"))

    # Seed cocktails
    from reserve_automation.db.repositories.cocktail_repo import SQLiteCocktailRepository
    cocktail_repo = SQLiteCocktailRepository(db)

    moscow_mule = CocktailRecipe(
        name="Moscow Mule",
        ingredients=[
            RecipeIngredient(ingredient="Vodka", amount=2, unit="oz"),
            RecipeIngredient(ingredient="Lime Juice", amount=0.75, unit="oz"),
            RecipeIngredient(ingredient="Ginger Beer", amount=4, unit="oz"),
        ],
        instructions=["Fill copper mug with ice", "Add vodka and lime juice", "Top with ginger beer", "Stir gently"],
        method="built",
        style="classic",
        glassware="copper mug",
        garnish="lime wedge",
    )
    created_mule = cocktail_repo.create(moscow_mule)

    old_fashioned = CocktailRecipe(
        name="Old Fashioned",
        ingredients=[
            RecipeIngredient(ingredient="Bourbon", amount=2, unit="oz"),
            RecipeIngredient(ingredient="Simple Syrup", amount=0.25, unit="oz"),
        ],
        instructions=["Add bourbon and syrup to glass", "Add ice and stir", "Express orange peel"],
        method="stirred",
        style="classic",
        glassware="rocks glass",
        garnish="orange peel",
    )
    cocktail_repo.create(old_fashioned)

    # Seed a tasting for Moscow Mule
    tasting = CocktailTastingNote(
        recipe_name="Moscow Mule",
        taster_name="Ben",
        tasting_date="2025-06-15",
        score=8.5,
        notes="Refreshing with nice ginger bite",
        bartender="Ben",
    )
    cocktail_repo.create_tasting(tasting, int(created_mule.id))

    yield db

    # Clean up
    db.query(CocktailTastingIngredientModel).delete()
    db.query(CocktailTastingModel).delete()
    db.query(CocktailInstructionModel).delete()
    db.query(RecipeIngredientModel).delete()
    db.query(CocktailModel).delete()
    db.query(IngredientModel).delete()
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
