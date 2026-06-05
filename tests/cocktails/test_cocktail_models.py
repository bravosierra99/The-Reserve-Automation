"""Tests for cocktail recipe data models."""

import yaml

from reserve_automation.core.cocktail import (
    CocktailRecipe,
    RecipeIngredient,
)


class TestRecipeIngredient:
    """Test RecipeIngredient model."""

    def test_basic_ingredient(self):
        ing = RecipeIngredient(ingredient="Vodka", amount=2, unit="oz")
        assert ing.ingredient == "Vodka"
        assert ing.amount == 2
        assert ing.unit == "oz"
        assert ing.optional is False

    def test_optional_ingredient(self):
        ing = RecipeIngredient(ingredient="Simple Syrup", amount=0.5, unit="oz", optional=True)
        assert ing.optional is True

    def test_ingredient_with_notes(self):
        ing = RecipeIngredient(ingredient="Lime Juice", amount=0.75, unit="oz", notes="freshly squeezed")
        assert ing.notes == "freshly squeezed"


class TestCocktailRecipe:
    """Test CocktailRecipe model."""

    def test_basic_recipe(self):
        recipe = CocktailRecipe(
            name="Moscow Mule",
            ingredients=[
                RecipeIngredient(ingredient="Vodka", amount=2, unit="oz"),
                RecipeIngredient(ingredient="Ginger Beer", amount=4, unit="oz"),
            ],
            instructions=["Fill mug with ice", "Add vodka", "Top with ginger beer"],
            method="built",
        )
        assert recipe.name == "Moscow Mule"
        assert len(recipe.ingredients) == 2
        assert len(recipe.instructions) == 3
        assert recipe.method == "built"
        assert recipe.serving_size == 1

    def test_to_frontmatter_dict(self):
        recipe = CocktailRecipe(
            name="Test",
            ingredients=[
                RecipeIngredient(ingredient="Vodka", amount=2, unit="oz"),
                RecipeIngredient(ingredient="Syrup", amount=0.5, unit="oz", optional=True),
            ],
            instructions=["Step 1", "Step 2"],
            method="shaken",
            garnish="lime",
        )
        d = recipe.to_frontmatter_dict()
        assert d["name"] == "Test"
        assert d["method"] == "shaken"
        assert d["garnish"] == "lime"
        assert len(d["ingredients"]) == 2
        assert d["ingredients"][0]["ingredient"] == "Vodka"
        assert d["ingredients"][1]["optional"] is True
        assert d["instructions"] == ["Step 1", "Step 2"]

    def test_vault_path_excluded(self):
        recipe = CocktailRecipe(name="Test", vault_path="3_Cocktails/Test")
        d = recipe.model_dump()
        assert "vault_path" not in d

    def test_yaml_roundtrip(self):
        """Ingredients survive YAML serialization/deserialization."""
        recipe = CocktailRecipe(
            name="Test",
            ingredients=[
                RecipeIngredient(ingredient="Vodka", amount=2, unit="oz"),
                RecipeIngredient(ingredient="Lime", amount=0.75, unit="oz", notes="fresh"),
            ],
            instructions=["Shake", "Strain"],
        )
        fm = recipe.to_frontmatter_dict()

        # Serialize to YAML and back
        yaml_str = yaml.dump(fm, default_flow_style=False)
        loaded = yaml.safe_load(yaml_str)

        # Verify ingredients survive
        assert len(loaded["ingredients"]) == 2
        assert loaded["ingredients"][0]["ingredient"] == "Vodka"
        assert loaded["ingredients"][0]["amount"] == 2
        assert loaded["ingredients"][1]["notes"] == "fresh"
        assert loaded["instructions"] == ["Shake", "Strain"]
