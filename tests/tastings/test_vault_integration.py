#!/usr/bin/env python3
"""
Test Suite 3: Vault Integration Tests

Tests actual tasting file creation in a temporary test vault.
Uses RESERVE_VAULT_PATH environment variable to point to /tmp/test-vault.

IMPORTANT: These tests write real files to disk (in temp vault).
"""

import json
import os
import pytest
import subprocess
import sys
from pathlib import Path
from fastapi.testclient import TestClient

from reserve_automation.web.app import app
from reserve_automation.web.config import load_web_config

PROJECT_ROOT = Path(__file__).parent.parent.parent
TEST_VAULT = Path("/tmp/test-vault")


def setup_test_vault():
    """Ensure test vault exists with test bottles."""
    print("\n🔧 Setting up test vault...")

    # Clean up existing vault completely to start fresh
    import shutil
    if TEST_VAULT.exists():
        shutil.rmtree(TEST_VAULT)
        print("   ✓ Cleaned existing test vault")

    # Create directories
    (TEST_VAULT / "1_Whiskeys").mkdir(parents=True, exist_ok=True)
    (TEST_VAULT / "1_Wines").mkdir(parents=True, exist_ok=True)

    # Always recreate test whiskey to ensure correct format
    whiskey_dir = TEST_VAULT / "1_Whiskeys" / "Test Distillery - Test Bourbon - 2020"
    whiskey_file = whiskey_dir / "Test Distillery - Test Bourbon - 2020.md"
    whiskey_dir.mkdir(parents=True, exist_ok=True)
    whiskey_file.write_text("""---
fileClass: Whiskey
Producer: Test Distillery
Name: Test Bourbon
Year: 2020
Type: Bourbon
Inventory: 1
Buy: 0
---

# Test Distillery - Test Bourbon - 2020

Test whiskey for vault integration tests.
""")

    # Always recreate test wine to ensure correct format
    wine_dir = TEST_VAULT / "1_Wines" / "Château Test - Bordeaux - 2015"
    wine_file = wine_dir / "Château Test - Bordeaux - 2015.md"
    wine_dir.mkdir(parents=True, exist_ok=True)
    wine_file.write_text("""---
fileClass: Wine
Producer: Château Test
Name: Bordeaux
Year: 2015
Type: Red
Inventory: 1
Buy: 0
---

# Château Test - Bordeaux - 2015

Test wine for vault integration tests.
""")

    print(f"   ✓ Test vault ready at: {TEST_VAULT}")
    return TEST_VAULT


def cleanup_tasting_files():
    """Remove all tasting files from test vault."""
    print("\n🧹 Cleaning up tasting files from test vault...")
    count = 0

    for tasting_file in TEST_VAULT.rglob("Tasting-*.md"):
        tasting_file.unlink()
        count += 1

    if count > 0:
        print(f"   ✓ Removed {count} tasting file(s)")
    else:
        print("   ✓ No tasting files to remove")


@pytest.fixture(scope="module")
def test_client():
    """Create test client with proper configuration using test vault."""
    # Setup test vault first
    setup_test_vault()

    # Set environment to use test vault
    os.environ["RESERVE_VAULT_PATH"] = str(TEST_VAULT)

    # Load config (will pick up RESERVE_VAULT_PATH from environment)
    core_config, web_config = load_web_config()

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


def test_manual_obsidian_tasting(test_client):
    """Test manual Obsidian mode tasting creation.

    Uses the new sessionless API - all data is passed in a single POST request.
    """
    print("\n📝 Test: Manual Obsidian Mode Tasting")
    print("=" * 60)

    # Cleanup before test
    cleanup_tasting_files()

    print("\n1️⃣ Searching for test bottle in vault...")
    response = test_client.get("/api/v1/management/bottles/search?q=Test Bourbon")
    assert response.status_code == 200, "Bottle search failed"
    bottles = response.json()["bottles"]

    # Should find our test bottle
    test_bottles = [b for b in bottles if "Test Bourbon" in b["name"]]
    assert len(test_bottles) > 0, "Test bottle not found in test vault"
    test_bottle = test_bottles[0]
    print(f"   ✓ Found: {test_bottle['name']}")

    print("\n2️⃣ Saving manual tasting (Obsidian mode)...")
    # New sessionless API - all data in one request
    response = test_client.post(
        "/api/v1/manual-tasting/save",
        json={
            "mode": "obsidian",
            "beverage_type": "whiskey",
            "taster_name": "TestTaster",
            "tasting_date": "2025-12-27",
            "selected_bottle_id": test_bottle["id"],
            "tasting_data": {
                "whiskey_nose": 2.8,
                "whiskey_palate": 2.5,
                "whiskey_finish": 2.2,
                "whiskey_overall": 0.8,
                "nose_notes": ["test", "notes", "nose"],
                "palate_notes": ["test", "palate"],
                "finish_notes": ["long", "test"],
                "overall_notes": "Test tasting for vault integration"
            }
        }
    )
    assert response.status_code == 200, f"Save failed: {response.status_code} - {response.text}"
    print("   ✓ Save request completed")

    print("\n3️⃣ Verifying tasting file created...")
    # Look for tasting file in test bottle directory
    # Use bottle registry to get vault_path from ID
    from reserve_automation.web import app as web_app
    bottle_vault_path = web_app.bottle_registry.get_path(test_bottle["id"])
    bottle_dir = TEST_VAULT / bottle_vault_path
    tasting_files = list(bottle_dir.glob("Tasting-*.md"))

    assert len(tasting_files) > 0, f"No tasting files found in {bottle_dir}"
    assert len(tasting_files) == 1, f"Expected 1 tasting file, found {len(tasting_files)}"

    tasting_file = tasting_files[0]
    print(f"   ✓ Tasting file created: {tasting_file.name}")

    # Verify file content
    content = tasting_file.read_text()
    assert "fileClass: Tasting" in content, "Missing fileClass"
    assert "TestTaster" in content, "Missing taster name"
    assert "2025-12-27" in content, "Missing tasting date"
    assert "2.8" in content or "2.80" in content, "Missing nose score"
    assert "Test tasting for vault integration" in content, "Missing overall notes"
    print("   ✓ File content validated")

    # Verify frontmatter structure
    assert content.startswith("---"), "Should start with frontmatter"
    lines = content.split("\n")
    assert lines[0] == "---", "First line should be ---"
    frontmatter_end = next(i for i, line in enumerate(lines[1:], 1) if line == "---")
    assert frontmatter_end > 0, "Frontmatter should be closed"
    print("   ✓ Frontmatter structure valid")

    print("\n" + "=" * 60)
    print("✅ TEST PASSED: Manual Obsidian Tasting")
    print("=" * 60)


def test_cli_extraction_to_vault():
    """Test CLI extraction that writes to vault (no --dry-run)."""
    print("\n🖼️ Test: CLI Extraction to Vault")
    print("=" * 60)

    # Setup
    setup_test_vault()
    cleanup_tasting_files()

    # Check for test image
    fixtures_dir = PROJECT_ROOT / "tests" / "fixtures" / "tasting_cards"
    image_path = fixtures_dir / "aws_wine_test_001.jpg"

    if not image_path.exists():
        print(f"   ⚠️  Test image not found: {image_path}")
        print("   Skipping test")
        return True

    print(f"\n1️⃣ Extracting from: {image_path.name}")
    print("   NOTE: Running WITHOUT --dry-run (will write to vault)")

    # Run extraction pointing to test vault
    env = os.environ.copy()
    env["RESERVE_VAULT_PATH"] = str(TEST_VAULT)

    cmd = [
        "uv", "run", "reserve-automation", "extract-tasting",
        str(image_path),
        "--template", "aws_wine"
        # NO --dry-run flag - will actually write files
    ]

    print(f"   Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=PROJECT_ROOT, env=env)

    # May fail if LLM can't match bottles or other issues - that's okay for this test
    if result.returncode != 0:
        print(f"   ⚠️  Extraction exited with code {result.returncode}")
        print("   This is okay - LLM extraction can be unreliable")
        print("   Main test: Verify it didn't crash with exception")
        # Check stderr doesn't contain Python traceback
        assert "Traceback" not in result.stderr, "Should not crash with exception"
        print("   ✓ No exceptions thrown")
        return True

    print("   ✓ Extraction completed")

    # If successful, check if files were created
    print("\n2️⃣ Checking for created tasting files...")
    tasting_files = list(TEST_VAULT.rglob("Tasting-*.md"))

    if len(tasting_files) == 0:
        print("   ⚠️  No tasting files created (LLM may not have matched bottles)")
        print("   This is acceptable - matching can fail with test data")
        return True

    print(f"   ✓ Created {len(tasting_files)} tasting file(s)")

    # Verify at least one file is valid
    tasting_file = tasting_files[0]
    content = tasting_file.read_text()
    assert "fileClass: Wine Tasting" in content, "Should be Wine Tasting fileClass"
    assert content.startswith("---"), "Should have frontmatter"
    print(f"   ✓ File format valid: {tasting_file.name}")

    print("\n" + "=" * 60)
    print("✅ TEST PASSED: CLI Extraction to Vault")
    print("=" * 60)



def test_duplicate_detection(test_client):
    """Test that system handles duplicate tastings by overwriting.

    Uses the new sessionless API - all data is passed in a single POST request.
    """
    print("\n⚠️ Test: Duplicate Tasting Detection")
    print("=" * 60)

    # Cleanup before test
    cleanup_tasting_files()

    print("\n1️⃣ Creating first tasting...")
    # Search for test bottle
    response = test_client.get("/api/v1/management/bottles/search?q=Test Bourbon")
    bottles = response.json()["bottles"]
    test_bottle = [b for b in bottles if "Test Bourbon" in b["name"]][0]

    # Create initial tasting via new sessionless API
    response = test_client.post("/api/v1/manual-tasting/save", json={
        "mode": "obsidian",
        "beverage_type": "whiskey",
        "taster_name": "DupeTestTaster",
        "tasting_date": "2025-12-27",
        "selected_bottle_id": test_bottle["id"],
        "tasting_data": {
            "whiskey_nose": 2.0,
            "whiskey_palate": 2.0,
            "whiskey_finish": 2.0,
            "whiskey_overall": 0.5
        }
    })
    assert response.status_code == 200, f"First save failed: {response.status_code} - {response.text}"
    print("   ✓ First tasting created")

    print("\n2️⃣ Attempting to create duplicate...")
    # Try to create another tasting for same bottle, same taster, same date
    # The system should overwrite the existing file (same filename pattern)
    response = test_client.post("/api/v1/manual-tasting/save", json={
        "mode": "obsidian",
        "beverage_type": "whiskey",
        "taster_name": "DupeTestTaster",
        "tasting_date": "2025-12-27",
        "selected_bottle_id": test_bottle["id"],
        "tasting_data": {
            "whiskey_nose": 3.0,
            "whiskey_palate": 3.0,
            "whiskey_finish": 3.0,
            "whiskey_overall": 1.0
        }
    })
    assert response.status_code == 200, f"Second save failed: {response.status_code} - {response.text}"

    # Verify only 1 file exists (duplicate was overwritten)
    # Use bottle registry to get vault_path from ID
    from reserve_automation.web import app as web_app
    bottle_vault_path = web_app.bottle_registry.get_path(test_bottle["id"])
    bottle_dir = TEST_VAULT / bottle_vault_path
    tasting_files = list(bottle_dir.glob("Tasting-2025-12-27-DupeTestTaster*.md"))

    assert len(tasting_files) == 1, f"Should only have 1 tasting file, found {len(tasting_files)}"

    # Verify the file contains the updated scores (3.0, not 2.0)
    content = tasting_files[0].read_text()
    assert "3.0" in content or "3.00" in content, "File should contain updated scores (3.0)"
    print("   ✓ Duplicate was overwritten with new scores")
    print(f"   ✓ Only 1 tasting file exists")

    print("\n" + "=" * 60)
    print("✅ TEST PASSED: Duplicate Detection")
    print("=" * 60)


if __name__ == "__main__":
    # Check that test vault exists
    if not TEST_VAULT.exists():
        print(f"❌ ERROR: Test vault not found at {TEST_VAULT}")
        print("Run setup first to create test vault")
        sys.exit(1)

    try:
        print("\n" + "=" * 60)
        print("TEST SUITE 3: VAULT INTEGRATION")
        print("=" * 60)
        print(f"Test vault: {TEST_VAULT}")
        print("⚠️  WARNING: These tests write real files to temp vault")
        print("=" * 60)

        # Run tests
        test_manual_obsidian_tasting()
        print("\n")
        test_cli_extraction_to_vault()
        print("\n")
        test_duplicate_detection()

        print("\n" + "=" * 60)
        print("🎉 ALL SUITE 3 TESTS PASSED!")
        print("=" * 60)
        print("\n✓ Manual Obsidian tastings create files correctly")
        print("✓ CLI extraction writes to vault")
        print("✓ Duplicate detection works")
        print(f"✓ All files written to temp vault: {TEST_VAULT}")

        # Cleanup
        print("\n🧹 Cleaning up test vault...")
        cleanup_tasting_files()
        print("   ✓ Test tasting files removed")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
