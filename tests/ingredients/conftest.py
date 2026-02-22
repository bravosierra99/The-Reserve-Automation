"""
Shared fixtures for ingredient system tests.

CRITICAL: These tests MUST use an isolated test vault, NEVER the real vault.
The test vault is created fresh for each test module and destroyed after.
"""

import shutil
import uuid
from pathlib import Path

import pytest


# Test vault path - completely isolated from real data
TEST_VAULT_PATH = Path(f"/tmp/test-vault-ingredients-{uuid.uuid4().hex[:8]}")


def _create_ingredient_file(base_dir: Path, name: str, parent: str = None, **kwargs):
    """Helper to create an ingredient markdown file in the test vault."""
    item_dir = base_dir / name
    item_dir.mkdir(parents=True, exist_ok=True)

    # Build frontmatter
    fields = {
        "fileClass": "Ingredient",
        "IngredientName": name,
        "Parent": parent or "",
        "Cost": kwargs.get("cost", ""),
        "VolumeMl": kwargs.get("volume_ml", ""),
        "ABV": kwargs.get("abv", ""),
        "Notes": kwargs.get("notes", ""),
    }

    lines = ["---"]
    for key, value in fields.items():
        lines.append(f"{key}: {value}")
    lines.append("---")
    lines.append("")
    lines.append(f"## {name}")
    lines.append("")

    (item_dir / f"{name}.md").write_text("\n".join(lines))
    return item_dir


@pytest.fixture(scope="module")
def test_vault():
    """
    Create an isolated test vault with sample ingredient tree.

    Tree structure:
        Spirit (root)
          Vodka
            Flavored Vodka
              Vanilla Vodka
                Svedka Vanilla Vodka (product)
          Gin
        Mixer (root)
          Tonic Water
            Fever-Tree Indian Tonic (product)
          Simple Syrup
        Garnish (root)
          Lime
    """
    # Clean up any existing test vault
    if TEST_VAULT_PATH.exists():
        shutil.rmtree(TEST_VAULT_PATH)

    # Create vault directory structure
    TEST_VAULT_PATH.mkdir(parents=True)
    ingredients_dir = TEST_VAULT_PATH / "2_Ingredients"
    ingredients_dir.mkdir()

    # Also create other directories that might be checked
    (TEST_VAULT_PATH / "1_Whiskeys").mkdir()
    (TEST_VAULT_PATH / "1_Wines").mkdir()

    # Root nodes
    _create_ingredient_file(ingredients_dir, "Spirit")
    _create_ingredient_file(ingredients_dir, "Mixer")
    _create_ingredient_file(ingredients_dir, "Garnish")

    # Spirit subtree
    _create_ingredient_file(ingredients_dir, "Vodka", parent="Spirit")
    _create_ingredient_file(ingredients_dir, "Gin", parent="Spirit")
    _create_ingredient_file(ingredients_dir, "Flavored Vodka", parent="Vodka")
    _create_ingredient_file(ingredients_dir, "Vanilla Vodka", parent="Flavored Vodka")
    _create_ingredient_file(
        ingredients_dir, "Svedka Vanilla Vodka",
        parent="Vanilla Vodka",
        cost="12.99",
        volume_ml="750",
        abv="35.0",
    )

    # Mixer subtree
    _create_ingredient_file(ingredients_dir, "Tonic Water", parent="Mixer")
    _create_ingredient_file(
        ingredients_dir, "Fever-Tree Indian Tonic",
        parent="Tonic Water",
        cost="6.99",
        volume_ml="500",
    )
    _create_ingredient_file(ingredients_dir, "Simple Syrup", parent="Mixer")

    # Garnish subtree
    _create_ingredient_file(ingredients_dir, "Lime", parent="Garnish")

    yield TEST_VAULT_PATH

    # Cleanup after all tests in module
    if TEST_VAULT_PATH.exists():
        shutil.rmtree(TEST_VAULT_PATH)


@pytest.fixture(scope="module")
def test_client(test_vault):
    """
    Create test client with proper configuration using ISOLATED test vault.

    CRITICAL: This sets RESERVE_VAULT_PATH to the test vault, ensuring
    tests NEVER touch the real vault.
    """
    import os
    from fastapi.testclient import TestClient

    # CRITICAL: Override vault path BEFORE importing app
    os.environ["RESERVE_VAULT_PATH"] = str(test_vault)

    # Now import and configure
    from reserve_automation.web.app import app
    from reserve_automation.web.config import load_web_config

    core_config, web_config = load_web_config()

    # Verify we're using the test vault
    assert str(test_vault) in str(core_config.vault_path), \
        f"SAFETY CHECK FAILED: Not using test vault! Got {core_config.vault_path}"

    # Override dependencies
    from reserve_automation.web import app as web_app
    from reserve_automation.core.bottle_registry import BottleRegistry
    web_app.core_config = core_config
    web_app.web_config = web_config

    # Initialize fresh bottle registry for ID lookups
    web_app.bottle_registry = BottleRegistry()

    # Initialize fresh event store
    web_app.event_store = {}

    # Create services
    from reserve_automation.web.services.upload_service import UploadService
    web_app.upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions
    )

    with TestClient(app, follow_redirects=False) as client:
        yield client
