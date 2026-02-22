"""
Shared fixtures for cocktail system tests.

CRITICAL: These tests MUST use an isolated test vault, NEVER the real vault.
"""

import shutil
import uuid
from pathlib import Path

import yaml
import pytest


TEST_VAULT_PATH = Path(f"/tmp/test-vault-cocktails-{uuid.uuid4().hex[:8]}")


def _create_ingredient_file(base_dir: Path, name: str, parent: str = None, **kwargs):
    """Create an ingredient markdown file in the test vault."""
    item_dir = base_dir / name
    item_dir.mkdir(parents=True, exist_ok=True)
    fields = {
        "fileClass": "Ingredient",
        "IngredientName": name,
        "Parent": parent or "",
        "Brand": kwargs.get("brand", ""),
        "Cost": kwargs.get("cost", ""),
        "VolumeMl": kwargs.get("volume_ml", ""),
        "ABV": kwargs.get("abv", ""),
        "InStock": kwargs.get("in_stock", ""),
        "PurchaseLink": "",
        "Notes": "",
    }
    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    (item_dir / f"{name}.md").write_text("\n".join(lines))


def _create_cocktail_file(base_dir: Path, name: str, ingredients: list, instructions: list, **kwargs):
    """Create a cocktail markdown file in the test vault using proper YAML."""
    item_dir = base_dir / name
    item_dir.mkdir(parents=True, exist_ok=True)

    frontmatter = {
        "fileClass": "Cocktail",
        "CocktailName": name,
        "Description": kwargs.get("description", ""),
        "Method": kwargs.get("method", ""),
        "Glassware": kwargs.get("glassware", ""),
        "Garnish": kwargs.get("garnish", ""),
        "Style": kwargs.get("style", ""),
        "Ingredients": ingredients,
        "Instructions": instructions,
        "ServingSize": kwargs.get("serving_size", 1),
        "Stars": kwargs.get("stars", "--"),
        "Photo": "",
    }

    content = "---\n" + yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True) + "---\n\n## " + name + "\n"
    (item_dir / f"{name}.md").write_text(content)


def _create_cocktail_tasting_file(
    cocktail_dir: Path, cocktail_name: str, taster_name: str,
    tasting_date: str, score: float = None, notes: str = None,
    bartender: str = None, bottles_used: list = None,
):
    """Create a cocktail tasting markdown file in the test vault."""
    cocktail_dir.mkdir(parents=True, exist_ok=True)

    frontmatter = {
        "fileClass": "Cocktail Tasting",
        "Date": tasting_date,
        "TasterName": taster_name,
        "Bartender": bartender or "",
        "Score": score,
        "BottlesUsed": bottles_used or [],
        "LinkedCocktail": f"[[{cocktail_name}]]",
        "Notes": notes or "",
    }

    content = "---\n" + yaml.dump(frontmatter, default_flow_style=False, allow_unicode=True) + "---\n\n## Tasting Notes\n"
    filename = f"Tasting-{tasting_date}-{taster_name}.md"
    (cocktail_dir / filename).write_text(content)


@pytest.fixture(scope="module")
def test_vault():
    """Create an isolated test vault with sample ingredients and cocktails."""
    if TEST_VAULT_PATH.exists():
        shutil.rmtree(TEST_VAULT_PATH)

    TEST_VAULT_PATH.mkdir(parents=True)
    ingredients_dir = TEST_VAULT_PATH / "2_Ingredients"
    ingredients_dir.mkdir()
    cocktails_dir = TEST_VAULT_PATH / "3_Cocktails"
    cocktails_dir.mkdir()
    (TEST_VAULT_PATH / "1_Whiskeys").mkdir()
    (TEST_VAULT_PATH / "1_Wines").mkdir()

    # Create some ingredients
    _create_ingredient_file(ingredients_dir, "Spirit")
    _create_ingredient_file(ingredients_dir, "Vodka", parent="Spirit")
    _create_ingredient_file(ingredients_dir, "Bourbon", parent="Spirit")
    _create_ingredient_file(ingredients_dir, "Mixer")
    _create_ingredient_file(ingredients_dir, "Lime Juice", parent="Mixer")
    _create_ingredient_file(ingredients_dir, "Ginger Beer", parent="Mixer")
    _create_ingredient_file(ingredients_dir, "Simple Syrup", parent="Mixer")

    # Create sample cocktails
    _create_cocktail_file(
        cocktails_dir, "Moscow Mule",
        ingredients=[
            {"ingredient": "Vodka", "amount": 2, "unit": "oz"},
            {"ingredient": "Lime Juice", "amount": 0.75, "unit": "oz"},
            {"ingredient": "Ginger Beer", "amount": 4, "unit": "oz"},
        ],
        instructions=["Fill copper mug with ice", "Add vodka and lime juice", "Top with ginger beer", "Stir gently"],
        method="built",
        style="classic",
        glassware="copper mug",
        garnish="lime wedge",
    )

    # Create a sample tasting for Moscow Mule
    _create_cocktail_tasting_file(
        cocktails_dir / "Moscow Mule",
        cocktail_name="Moscow Mule",
        taster_name="Ben",
        tasting_date="2025-06-15",
        score=8.5,
        notes="Refreshing with nice ginger bite",
        bartender="Ben",
    )

    _create_cocktail_file(
        cocktails_dir, "Old Fashioned",
        ingredients=[
            {"ingredient": "Bourbon", "amount": 2, "unit": "oz"},
            {"ingredient": "Simple Syrup", "amount": 0.25, "unit": "oz"},
        ],
        instructions=["Add bourbon and syrup to glass", "Add ice and stir", "Express orange peel"],
        method="stirred",
        style="classic",
        glassware="rocks glass",
        garnish="orange peel",
    )

    yield TEST_VAULT_PATH

    if TEST_VAULT_PATH.exists():
        shutil.rmtree(TEST_VAULT_PATH)


@pytest.fixture(scope="module")
def test_client(test_vault):
    """Create test client with isolated test vault."""
    import os
    from fastapi.testclient import TestClient

    os.environ["RESERVE_VAULT_PATH"] = str(test_vault)

    from reserve_automation.web.app import app
    from reserve_automation.web.config import load_web_config

    core_config, web_config = load_web_config()

    assert str(test_vault) in str(core_config.vault_path), \
        f"SAFETY CHECK FAILED: Not using test vault! Got {core_config.vault_path}"

    from reserve_automation.web import app as web_app
    from reserve_automation.core.bottle_registry import BottleRegistry
    web_app.core_config = core_config
    web_app.web_config = web_config
    web_app.bottle_registry = BottleRegistry()
    web_app.event_store = {}

    from reserve_automation.web.services.upload_service import UploadService
    web_app.upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions
    )

    with TestClient(app, follow_redirects=False) as client:
        yield client
