"""
Shared fixtures for tasting tests.

CRITICAL: These tests MUST use an isolated test vault, NEVER the real vault.
The test vault is created fresh for each test module and destroyed after.
"""

import shutil
from pathlib import Path

import pytest


# Test vault path - completely isolated from real data
TEST_VAULT_PATH = Path("/tmp/test-vault-tastings")


@pytest.fixture(scope="module")
def test_vault():
    """
    Create an isolated test vault with fixture bottles.

    This vault is completely separate from the real vault and contains
    only test data. It's created fresh for each test module.
    """
    # Clean up any existing test vault
    if TEST_VAULT_PATH.exists():
        shutil.rmtree(TEST_VAULT_PATH)

    # Create vault directory structure
    TEST_VAULT_PATH.mkdir(parents=True)
    (TEST_VAULT_PATH / "1_Whiskeys").mkdir()
    (TEST_VAULT_PATH / "1_Wines").mkdir()
    (TEST_VAULT_PATH / "1_Spirits").mkdir()

    # Create test whiskey bottle (Weller)
    weller_dir = TEST_VAULT_PATH / "1_Whiskeys" / "Buffalo Trace - Weller Special Reserve"
    weller_dir.mkdir(parents=True)
    (weller_dir / "Buffalo Trace - Weller Special Reserve.md").write_text("""---
fileClass: Whiskey
Name: Buffalo Trace - Weller Special Reserve
Distiller: Buffalo Trace
WhiskeyName: Weller Special Reserve
AgeStatement:
Year:
Type: Kentucky Straight Bourbon Whiskey
MashBill: Wheated
BarrelType:
Proof: 90
Region-State: Kentucky
BatchNumber:
BottleNumber:
Price:
PurchaseSource:
PurchaseLink:
Inventory: 1
Buy: 0
Stars: --
ValueForMoney:
BottleOpenedDate:
BottleImage:
---

## Test Fixture Bottle

This is a test fixture bottle for automated testing.
""")

    # Create test wine bottle (Caymus)
    caymus_dir = TEST_VAULT_PATH / "1_Wines" / "Caymus Vineyards - Cabernet Sauvignon - 2021"
    caymus_dir.mkdir(parents=True)
    (caymus_dir / "Caymus Vineyards - Cabernet Sauvignon - 2021.md").write_text("""---
fileClass: Wine
Name: Caymus Vineyards - Cabernet Sauvignon - 2021
Winemaker: Caymus Vineyards
WineName: Cabernet Sauvignon
Vintage: "2021"
Type: Red wine
Variety: Cabernet Sauvignon
Country-Region: USA - Napa Valley
Vineyard:
ABV: 14.5
Style:
Price:
PurchaseSource:
PurchaseLink:
Stars: --
ValueForMoney:
Points:
Inventory: 1
Buy: 0
---

## Test Fixture Bottle

This is a test fixture bottle for automated testing.
""")

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

    # Initialize bottle registry for ID lookups
    web_app.bottle_registry = BottleRegistry()

    # Create services
    from reserve_automation.web.services.upload_service import UploadService
    web_app.upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions
    )

    with TestClient(app, follow_redirects=False) as client:
        yield client


@pytest.fixture
def weller_bottle(test_vault, test_client):
    """Return path info for the test Weller bottle with opaque ID."""
    from reserve_automation.web import app as web_app
    vault_path = "1_Whiskeys/Buffalo Trace - Weller Special Reserve"
    # Register bottle and get ID
    bottle_id = web_app.bottle_registry.register(vault_path)
    return {
        "name": "Buffalo Trace - Weller Special Reserve",
        "vault_path": vault_path,  # Keep for internal test use (file operations)
        "id": bottle_id,  # Opaque ID for API calls
        "beverage_type": "whiskey"
    }


@pytest.fixture
def caymus_bottle(test_vault, test_client):
    """Return path info for the test Caymus bottle with opaque ID."""
    from reserve_automation.web import app as web_app
    vault_path = "1_Wines/Caymus Vineyards - Cabernet Sauvignon - 2021"
    # Register bottle and get ID
    bottle_id = web_app.bottle_registry.register(vault_path)
    return {
        "name": "Caymus Vineyards - Cabernet Sauvignon - 2021",
        "vault_path": vault_path,  # Keep for internal test use (file operations)
        "id": bottle_id,  # Opaque ID for API calls
        "beverage_type": "wine"
    }
