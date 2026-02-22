"""Tests for cocktail tasting data models."""

import yaml
import pytest

from reserve_automation.core.cocktail_tasting import (
    CocktailTastingNote,
    CocktailTastingIngredient,
    CreateCocktailTastingRequest,
)


class TestCocktailTastingIngredient:
    """Test CocktailTastingIngredient model."""

    def test_basic_ingredient(self):
        ing = CocktailTastingIngredient(
            recipe_ingredient="Vodka",
            actual_product="Svedka Vanilla Vodka",
        )
        assert ing.recipe_ingredient == "Vodka"
        assert ing.actual_product == "Svedka Vanilla Vodka"


class TestCocktailTastingNote:
    """Test CocktailTastingNote model."""

    def test_basic_tasting(self):
        tasting = CocktailTastingNote(
            recipe_name="Moscow Mule",
            taster_name="Ben",
            tasting_date="2025-06-15",
            score=8.5,
            notes="Great cocktail",
            bartender="Ben",
        )
        assert tasting.recipe_name == "Moscow Mule"
        assert tasting.taster_name == "Ben"
        assert tasting.tasting_date == "2025-06-15"
        assert tasting.score == 8.5
        assert tasting.notes == "Great cocktail"
        assert tasting.bartender == "Ben"
        assert tasting.bottles_used == []

    def test_tasting_with_bottles_used(self):
        tasting = CocktailTastingNote(
            recipe_name="Moscow Mule",
            taster_name="Ben",
            tasting_date="2025-06-15",
            bottles_used=[
                CocktailTastingIngredient(
                    recipe_ingredient="Vodka",
                    actual_product="Svedka",
                ),
                CocktailTastingIngredient(
                    recipe_ingredient="Ginger Beer",
                    actual_product="Fever-Tree",
                ),
            ],
        )
        assert len(tasting.bottles_used) == 2
        assert tasting.bottles_used[0].recipe_ingredient == "Vodka"
        assert tasting.bottles_used[0].actual_product == "Svedka"

    def test_tasting_minimal(self):
        tasting = CocktailTastingNote(
            recipe_name="Old Fashioned",
            taster_name="Alice",
            tasting_date="2025-07-01",
        )
        assert tasting.score is None
        assert tasting.notes is None
        assert tasting.bartender is None
        assert tasting.bottles_used == []

    def test_vault_path_excluded(self):
        tasting = CocktailTastingNote(
            recipe_name="Test",
            taster_name="Test",
            tasting_date="2025-01-01",
            vault_path="3_Cocktails/Test/Tasting-2025-01-01-Test.md",
        )
        d = tasting.model_dump()
        assert "vault_path" not in d

    def test_score_validation_min(self):
        with pytest.raises(Exception):
            CocktailTastingNote(
                recipe_name="Test",
                taster_name="Test",
                tasting_date="2025-01-01",
                score=0.5,  # Below minimum of 1
            )

    def test_score_validation_max(self):
        with pytest.raises(Exception):
            CocktailTastingNote(
                recipe_name="Test",
                taster_name="Test",
                tasting_date="2025-01-01",
                score=11,  # Above maximum of 10
            )


class TestCreateCocktailTastingRequest:
    """Test CreateCocktailTastingRequest model."""

    def test_basic_request(self):
        req = CreateCocktailTastingRequest(
            taster_name="Ben",
            score=7.5,
            notes="Nice",
            bartender="Alice",
        )
        assert req.taster_name == "Ben"
        assert req.score == 7.5
        assert req.notes == "Nice"
        assert req.bartender == "Alice"
        assert req.bottles_used == []

    def test_empty_name_fails(self):
        with pytest.raises(Exception):
            CreateCocktailTastingRequest(taster_name="")

    def test_request_with_bottles(self):
        req = CreateCocktailTastingRequest(
            taster_name="Ben",
            bottles_used=[
                CocktailTastingIngredient(
                    recipe_ingredient="Vodka",
                    actual_product="Svedka",
                ),
            ],
        )
        assert len(req.bottles_used) == 1
