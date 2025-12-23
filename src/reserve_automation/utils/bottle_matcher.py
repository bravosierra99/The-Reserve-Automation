#CLAUDE_REQ: Bottle matching uses folder names from vault structure (see vault_reader.py)
#CLAUDE_REQ: folder_path is used for LinkedBottle field in tastings - MUST be folder name, not full path
#CLAUDE_REQ: Bottle names follow convention: "{Producer} - {Name} - {Year}" for wines, "{Distiller} - {WhiskeyName} - {Year}" for whiskeys
#CLAUDE_REQ: When generating tastings, LinkedBottle must use [[FolderName]] syntax matching the bottle folder
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
        self._cache = {}  # Cache bottles by beverage_type

    def invalidate_cache(self, beverage_type: Optional[str] = None):
        """
        Invalidate bottle cache for a specific beverage type or all types.

        Args:
            beverage_type: Optional beverage type to invalidate. If None, clears entire cache.
        """
        if beverage_type:
            if beverage_type in self._cache:
                logger.info(f"Invalidating bottle cache for {beverage_type}")
                del self._cache[beverage_type]
        else:
            logger.info("Invalidating entire bottle cache")
            self._cache.clear()

    def find_matches(
        self,
        bottle_name: str,
        beverage_type: str,
        top_n: int = 5,
        min_score: float = 0.3,
        strict_substring: bool = False,
    ) -> list[BottleMatch]:
        """
        Find matching bottles in the vault using fuzzy or substring matching.

        Args:
            bottle_name: Name from tasting card (e.g., "Stagg Jr Batch 24D")
            beverage_type: "wine" or "whiskey"
            top_n: Return top N matches
            min_score: Minimum similarity score (0.0-1.0) - ignored if strict_substring=True
            strict_substring: If True, use strict substring matching instead of fuzzy matching

        Returns:
            List of BottleMatch objects, sorted by score (highest first)
        """
        logger.info(f"Searching for bottle: '{bottle_name}' (type: {beverage_type}, strict={strict_substring})")

        # Get bottles from cache or read from vault
        if beverage_type in self._cache:
            logger.debug(f"Using cached bottles for {beverage_type}")
            vault_bottles = self._cache[beverage_type]
        else:
            logger.debug(f"Reading bottles from vault for {beverage_type}")
            vault_bottles = self.vault_reader.read_all_bottles(beverage_type=beverage_type)
            self._cache[beverage_type] = vault_bottles

        if strict_substring:
            # Use strict substring matching
            matches = self._substring_matches(bottle_name, vault_bottles)
        else:
            # Use fuzzy matching
            matches = self._fuzzy_matches(bottle_name, vault_bottles, min_score)

        # Sort by score (highest first)
        matches.sort(key=lambda m: m.score, reverse=True)

        # Return top N
        result = matches[:top_n]

        logger.info(f"Found {len(result)} matches (strict={strict_substring})")
        for match in result:
            logger.info(f"  {match}")

        return result

    def _fuzzy_matches(
        self,
        bottle_name: str,
        vault_bottles: list,
        min_score: float
    ) -> list[BottleMatch]:
        """Find matches using fuzzy string matching."""
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

            # Score 4: Folder name (most reliable) - use vault_path if available
            folder_path = None
            if bottle.vault_path:
                folder_path = self.vault_path / bottle.vault_path
                folder_name = bottle.vault_path.split('/')[-1]  # Last component
                scores.append(self._similarity(bottle_name, folder_name))

            # Use best score
            best_score = max(scores)

            if best_score >= min_score:
                matches.append(BottleMatch(bottle, best_score, folder_path))

        return matches

    def _substring_matches(
        self,
        query: str,
        vault_bottles: list
    ) -> list[BottleMatch]:
        """Find matches using strict substring matching."""
        query_lower = query.lower().strip()
        matches = []

        for bottle in vault_bottles:
            # Use vault_path if available, otherwise None
            folder_path = None
            folder_name = ""
            if bottle.vault_path:
                folder_path = self.vault_path / bottle.vault_path
                folder_name = bottle.vault_path.split('/')[-1]  # Last component

            # Check if query appears in any of these fields
            full_name = self._get_full_name(bottle)
            producer_name = f"{bottle.producer} {bottle.name}"

            # Check all possible name variants
            searchable_texts = [
                full_name.lower(),
                producer_name.lower(),
                bottle.name.lower(),
                folder_name.lower(),
            ]

            # Find if substring matches any field
            match_found = any(query_lower in text for text in searchable_texts)

            if match_found:
                # Calculate score based on match quality
                # Exact match = 1.0, contains at start = 0.9, contains elsewhere = 0.7
                score = 0.7  # Default for substring match

                for text in searchable_texts:
                    if text == query_lower:
                        score = 1.0
                        break
                    elif text.startswith(query_lower):
                        score = max(score, 0.9)
                    elif query_lower in text:
                        # Calculate score based on position (earlier is better)
                        position = text.find(query_lower)
                        position_score = 0.7 + (0.2 * (1 - position / len(text)))
                        score = max(score, position_score)

                matches.append(BottleMatch(bottle, score, folder_path))

        return matches

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

    def _similarity(self, a: str, b: str) -> float:
        """
        Calculate similarity score between two strings (0.0 to 1.0).

        Uses SequenceMatcher for fuzzy string matching.
        Case-insensitive.
        """
        a_clean = a.lower().strip()
        b_clean = b.lower().strip()

        return SequenceMatcher(None, a_clean, b_clean).ratio()
