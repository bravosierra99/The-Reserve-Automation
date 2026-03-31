#!/usr/bin/env python3
"""
Test Suite 3: Vault Integration Tests (OBSOLETE)

These tests previously tested tasting file creation in a temporary vault.
Since the migration to SQLite, tastings are stored in the database, not as
vault files. These tests are skipped.

For DB-based tasting tests, see test_event_tastings.py.
"""

import pytest


@pytest.mark.skip(reason="Vault integration tests obsolete - tastings now stored in SQLite, not vault files")
class TestVaultIntegration:
    """Previously tested vault file creation for tastings."""

    def test_manual_obsidian_tasting(self):
        """Test manual Obsidian mode tasting creation - now handled by DB."""
        pass

    def test_cli_extraction_to_vault(self):
        """Test CLI extraction that writes to vault - now handled by DB."""
        pass

    def test_duplicate_detection(self):
        """Test duplicate tasting detection - now handled by DB constraints."""
        pass
