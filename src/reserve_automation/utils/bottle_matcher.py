"""Fuzzy match tasting notes to bottles in the vault."""

import logging
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from ..core.models import BottleMetadata
from ..utils.vault_reader import VaultReader

logger = logging.getLogger(__name__)


class BottleMatch:
    """Represents a potential bottle match."""

    def __init__(self, bottle: BottleMetadata, score: float, folder_path: Path):
        self.bottle = bottle
        self.score = score  # 0.0 to 1.0
        self.folder_path = folder_path

    def __repr__(self):
        return f"BottleMatch(name={self.bottle.name}, producer={self.bottle.producer}, score={self.score:.2f})"


class BottleMatcher:
    """Fuzzy match tasting note bottle names to bottles in the vault."""

    def __init__(self, vault_path: Path):
        self.vault_path = Path(vault_path)
        self.vault_reader = VaultReader(vault_path)

    def find_matches(
        self,
        bottle_name: str,
        beverage_type: str,
        top_n: int = 5,
        min_score: float = 0.3,
    ) -> list[BottleMatch]:
        """
        Find matching bottles in the vault using fuzzy matching.

        Args:
            bottle_name: Name from tasting card (e.g., "Stagg Jr Batch 24D")
            beverage_type: "wine" or "whiskey"
            top_n: Return top N matches
            min_score: Minimum similarity score (0.0-1.0)

        Returns:
            List of BottleMatch objects, sorted by score (highest first)
        """
        logger.info(f"Searching for bottle: '{bottle_name}' (type: {beverage_type})")

        # Read all bottles of this type from vault
        vault_bottles = self.vault_reader.read_all_bottles(beverage_type=beverage_type)

        matches = []
        for bottle in vault_bottles:
            # Calculate similarity scores for different name combinations
            scores = []

            # Score 1: Full bottle name (producer + name + vintage)
            full_name = self._get_full_name(bottle)
            scores.append(self._similarity(bottle_name, full_name))

            # Score 2: Producer + name only
            producer_name = f"{bottle.producer} {bottle.name}"
            scores.append(self._similarity(bottle_name, producer_name))

            # Score 3: Name only
            scores.append(self._similarity(bottle_name, bottle.name))

            # Score 4: Folder name (most reliable)
            folder_path = self._get_bottle_folder(bottle)
            if folder_path:
                folder_name = folder_path.name
                scores.append(self._similarity(bottle_name, folder_name))

            # Use best score
            best_score = max(scores)

            if best_score >= min_score:
                matches.append(BottleMatch(bottle, best_score, folder_path))

        # Sort by score (highest first)
        matches.sort(key=lambda m: m.score, reverse=True)

        # Return top N
        result = matches[:top_n]

        logger.info(f"Found {len(result)} matches (min_score={min_score})")
        for match in result:
            logger.info(f"  {match}")

        return result

    def find_best_match(
        self,
        bottle_name: str,
        beverage_type: str,
        auto_accept_threshold: float = 0.8,
    ) -> Optional[BottleMatch]:
        """
        Find the single best match for a bottle.

        Args:
            bottle_name: Name from tasting card
            beverage_type: "wine" or "whiskey"
            auto_accept_threshold: Auto-accept if score >= this value

        Returns:
            BottleMatch if confident match found, else None
        """
        matches = self.find_matches(bottle_name, beverage_type, top_n=1)

        if not matches:
            logger.warning(f"No matches found for: {bottle_name}")
            return None

        best_match = matches[0]

        if best_match.score >= auto_accept_threshold:
            logger.info(f"Auto-accepted match: {best_match} (score >= {auto_accept_threshold})")
            return best_match
        else:
            logger.info(f"Best match below threshold: {best_match} (score < {auto_accept_threshold})")
            return best_match  # Return anyway for manual review

    def _get_full_name(self, bottle: BottleMetadata) -> str:
        """Get full bottle name: 'Producer - Name - Year'"""
        parts = [bottle.producer, bottle.name]
        if bottle.year:
            parts.append(str(bottle.year))
        return " - ".join(parts)

    def _get_bottle_folder(self, bottle: BottleMetadata) -> Optional[Path]:
        """Get the folder path for this bottle in the vault."""
        # Construct expected folder name
        folder_name = self._get_full_name(bottle)

        # Search in appropriate cellar directory
        if bottle.type == "wine":
            cellar_dir = self.vault_path / "Cellar" / "1_Wines"
        else:
            cellar_dir = self.vault_path / "Cellar" / "1_Whiskeys"

        # Find matching folder
        for folder in cellar_dir.glob("*"):
            if folder.is_dir() and folder.name == folder_name:
                return folder

        return None

    def _similarity(self, a: str, b: str) -> float:
        """
        Calculate similarity score between two strings (0.0 to 1.0).

        Uses SequenceMatcher for fuzzy string matching.
        Case-insensitive.
        """
        a_clean = a.lower().strip()
        b_clean = b.lower().strip()

        return SequenceMatcher(None, a_clean, b_clean).ratio()
