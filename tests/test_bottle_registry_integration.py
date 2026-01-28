"""Test bottle registry integration with vault reader."""

import os
import pytest
from pathlib import Path

# Set required env var before imports
os.environ.setdefault("WEB_SECRET_KEY", "test123")

from reserve_automation.core.bottle_registry import BottleRegistry
from reserve_automation.utils.vault_reader import VaultReader
from reserve_automation.web.config import load_web_config


class TestBottleRegistryIntegration:
    """Test that bottles are properly registered when read from vault."""

    @pytest.fixture
    def config(self):
        """Load config."""
        core_config, web_config = load_web_config()
        return core_config

    @pytest.fixture
    def registry(self):
        """Create a fresh registry."""
        return BottleRegistry()

    def test_registry_populated_when_reading_bottles(self, config, registry):
        """Bottles should be registered when read via VaultReader."""
        # Create reader with registry
        reader = VaultReader(config.vault_path, registry=registry)

        # Read bottles
        bottles = reader.read_all_bottles()

        # Should have read some bottles
        assert len(bottles) > 0, "Expected to read at least one bottle"

        # Registry should have same number of entries as bottles
        assert len(registry) == len(bottles), (
            f"Registry has {len(registry)} entries but read {len(bottles)} bottles"
        )

        # Each bottle should have an ID
        for bottle in bottles:
            assert bottle.id is not None, f"Bottle {bottle.producer} - {bottle.name} has no ID"

        # Each bottle's ID should be in the registry
        for bottle in bottles:
            path = registry.get_path(bottle.id)
            assert path is not None, (
                f"Bottle ID {bottle.id} not found in registry. "
                f"Registry has {len(registry._id_to_path)} entries."
            )
            assert path == bottle.vault_path, (
                f"Registry path mismatch: expected {bottle.vault_path}, got {path}"
            )

    def test_registry_empty_without_passing_to_reader(self, config):
        """Without registry, bottles still get IDs but registry stays empty."""
        registry = BottleRegistry()

        # Create reader WITHOUT registry
        reader = VaultReader(config.vault_path, registry=None)

        # Read bottles
        bottles = reader.read_all_bottles()

        # Should have read some bottles with IDs
        assert len(bottles) > 0
        assert all(b.id is not None for b in bottles)

        # But registry should still be empty
        assert len(registry) == 0, "Registry should be empty when not passed to VaultReader"

    def test_reader_registry_attribute(self, config, registry):
        """VaultReader should store the registry attribute correctly."""
        reader = VaultReader(config.vault_path, registry=registry)

        assert reader.registry is registry, "reader.registry should be the same object"
        assert reader.registry is not None, "reader.registry should not be None"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
