"""Bottle Registry - Bidirectional mapping between opaque IDs and vault paths."""

import hashlib
from typing import Optional

from loguru import logger


class BottleRegistry:
    """
    Bidirectional mapping between opaque IDs and vault paths.

    This registry allows the system to:
    - Generate deterministic opaque IDs from vault paths (hiding filesystem details from frontend)
    - Look up vault paths from IDs (for internal file operations)
    - Look up IDs from vault paths (for API responses)

    IDs are deterministic: same vault_path always produces same ID, even across server restarts.
    """

    def __init__(self):
        """Initialize empty registry."""
        self._path_to_id: dict[str, str] = {}
        self._id_to_path: dict[str, str] = {}

    @staticmethod
    def generate_id(vault_path: str) -> str:
        """
        Generate a deterministic opaque ID from a vault path.

        Uses SHA-256 hash of the path, truncated to 12 characters.
        This provides ~48 bits of entropy which is more than enough
        to avoid collisions in a personal bottle collection.

        Args:
            vault_path: Relative path in vault (e.g., "1_Whiskeys/Distiller - Name - Year")

        Returns:
            12-character hex string ID
        """
        # Normalize path (strip trailing slashes, use forward slashes)
        normalized = vault_path.rstrip('/').replace('\\', '/')

        # Generate SHA-256 hash and take first 12 hex characters
        hash_bytes = hashlib.sha256(normalized.encode('utf-8')).hexdigest()
        return hash_bytes[:12]

    def register(self, vault_path: str) -> str:
        """
        Register a vault path and return its opaque ID.

        If already registered, returns existing ID (which will be the same
        due to deterministic generation).

        Args:
            vault_path: Relative path in vault

        Returns:
            Opaque ID for this bottle
        """
        bottle_id = self.generate_id(vault_path)

        # Store bidirectional mapping
        self._path_to_id[vault_path] = bottle_id
        self._id_to_path[bottle_id] = vault_path

        logger.debug(f"Registered bottle: {bottle_id} -> {vault_path}")
        return bottle_id

    def get_path(self, bottle_id: str) -> Optional[str]:
        """
        Look up vault path from opaque ID.

        Args:
            bottle_id: Opaque bottle ID

        Returns:
            Vault path or None if not found
        """
        return self._id_to_path.get(bottle_id)

    def get_id(self, vault_path: str) -> Optional[str]:
        """
        Look up opaque ID from vault path.

        Note: If the bottle hasn't been registered yet, this returns None.
        Use generate_id() if you need to compute the ID without registration.

        Args:
            vault_path: Relative path in vault

        Returns:
            Opaque ID or None if not registered
        """
        return self._path_to_id.get(vault_path)

    def unregister(self, vault_path: str) -> bool:
        """
        Remove a bottle from the registry.

        Args:
            vault_path: Relative path in vault

        Returns:
            True if removed, False if not found
        """
        bottle_id = self._path_to_id.pop(vault_path, None)
        if bottle_id:
            self._id_to_path.pop(bottle_id, None)
            logger.debug(f"Unregistered bottle: {bottle_id}")
            return True
        return False

    def clear(self) -> None:
        """Clear all registrations."""
        self._path_to_id.clear()
        self._id_to_path.clear()
        logger.debug("Registry cleared")

    def __len__(self) -> int:
        """Return number of registered bottles."""
        return len(self._path_to_id)

    def __contains__(self, vault_path: str) -> bool:
        """Check if a vault path is registered."""
        return vault_path in self._path_to_id
