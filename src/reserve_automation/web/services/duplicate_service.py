"""Duplicate bottle detection service."""

from pathlib import Path
from typing import List, Dict, Optional
from difflib import SequenceMatcher

from loguru import logger

from reserve_automation.core.models import BottleMetadata


class DuplicateDetectionService:
    """Service for detecting potential duplicate bottles in the vault."""

    def __init__(self, vault_path: Path):
        """
        Initialize duplicate detection service.

        Args:
            vault_path: Path to Obsidian vault
        """
        self.vault_path = vault_path
        self.wines_dir = vault_path / "1_Wines"
        self.whiskeys_dir = vault_path / "1_Whiskeys"

    def find_potential_duplicates(
        self,
        bottle: BottleMetadata,
        threshold: float = 0.7
    ) -> List[Dict]:
        """
        Find potential duplicate bottles in the vault.

        Args:
            bottle: Bottle to check
            threshold: Similarity threshold (0.0-1.0)

        Returns:
            List of potential duplicates with metadata and confidence scores
        """
        logger.info(f"Checking for duplicates: {bottle.producer} - {bottle.name} ({bottle.year})")
        logger.info(f"Bottle type field: {bottle.type}")
        logger.info(f"Bottle beverage_type field: {bottle.beverage_type}")
        logger.info(f"Threshold: {threshold}")

        potential_duplicates = []

        # Determine which directory to search based on 'type' field (not beverage_type)
        # bottle.type should be exactly "wine" or "whiskey"
        # bottle.beverage_type is the specific type like "Red wine", "Bourbon", etc.
        search_dir = self.wines_dir if bottle.type == "wine" else self.whiskeys_dir
        logger.info(f"Search directory: {search_dir}")

        if not search_dir.exists():
            logger.warning(f"Search directory does not exist: {search_dir}")
            return []

        # Get all markdown files (excluding subdirectories with tastings)
        bottle_files = [f for f in search_dir.glob("*/*.md") if f.is_file()]
        logger.info(f"Found {len(bottle_files)} bottle files to check")

        all_scores = []  # Track all scores for debugging

        for file_path in bottle_files:
            # Extract bottle info from filename
            # Format: "Producer - Name (Year).md" or "Producer - Name.md"
            filename = file_path.stem

            # Calculate similarity
            similarity = self._calculate_similarity(bottle, filename, file_path)
            all_scores.append((filename, similarity))

            if similarity >= threshold:
                duplicate_info = {
                    "file_path": str(file_path.relative_to(self.vault_path)),
                    "filename": filename,
                    "confidence": round(similarity, 2),
                    "reason": self._explain_match(bottle, filename)
                }
                potential_duplicates.append(duplicate_info)
                logger.info(f"Found potential duplicate: {filename} (confidence: {similarity:.2f})")

        # Log top 5 matches for debugging
        all_scores.sort(key=lambda x: x[1], reverse=True)
        logger.info("Top 5 similarity scores:")
        for filename, score in all_scores[:5]:
            logger.info(f"  {filename}: {score:.2f}")

        # Sort by confidence (highest first)
        potential_duplicates.sort(key=lambda x: x["confidence"], reverse=True)

        logger.info(f"Found {len(potential_duplicates)} duplicates above threshold {threshold}")
        return potential_duplicates

    def _calculate_similarity(
        self,
        bottle: BottleMetadata,
        filename: str,
        file_path: Path,
        debug: bool = False
    ) -> float:
        """
        Calculate similarity score between bottle and existing file.

        Uses multiple matching strategies to be robust against formatting variations.

        Args:
            bottle: Bottle metadata
            filename: Existing bottle filename (without .md)
            file_path: Path to existing file
            debug: Enable debug logging

        Returns:
            Similarity score (0.0-1.0)
        """
        # Normalize both strings for better matching
        bottle_producer = (bottle.producer or "").lower().strip()
        bottle_name = (bottle.name or "").lower().strip()
        bottle_year_str = str(bottle.year) if bottle.year else ""

        filename_lower = filename.lower()

        # Strategy 1: Parse structured format "Producer - Name (Year)" or "Producer - Name"
        structured_score = self._try_structured_match(
            bottle_producer, bottle_name, bottle_year_str, filename, filename_lower
        )

        # Strategy 2: Fuzzy match on whole filename (catches formatting variations)
        # Combine bottle info into searchable string
        bottle_str = f"{bottle_producer} {bottle_name} {bottle_year_str}".strip()
        whole_similarity = self._fuzzy_match(bottle_str, filename_lower)

        # Strategy 3: Check if key components appear anywhere in filename
        component_score = 0.0
        components_found = 0
        total_components = 0

        if bottle_producer:
            total_components += 1
            if bottle_producer in filename_lower or self._fuzzy_match(bottle_producer, filename_lower) > 0.8:
                components_found += 1

        if bottle_name:
            total_components += 1
            if bottle_name in filename_lower or self._fuzzy_match(bottle_name, filename_lower) > 0.8:
                components_found += 1

        if bottle_year_str:
            total_components += 1
            # Year should match exactly or be very close
            if bottle_year_str in filename_lower:
                components_found += 1

        if total_components > 0:
            component_score = components_found / total_components

        # Take the best score from all strategies
        best_score = max(structured_score, whole_similarity, component_score)

        if debug or best_score >= 0.4:  # Log anything promising
            logger.info(f"Similarity with '{filename}':")
            logger.info(f"  Bottle: '{bottle_producer} - {bottle_name} ({bottle_year_str})'")
            logger.info(f"  Structured: {structured_score:.2f}, Whole: {whole_similarity:.2f}, Component: {component_score:.2f}")
            logger.info(f"  Best: {best_score:.2f}")

        return best_score

    def _try_structured_match(
        self,
        bottle_producer: str,
        bottle_name: str,
        bottle_year_str: str,
        filename: str,
        filename_lower: str
    ) -> float:
        """Try to parse filename as structured format and compare."""
        scores = []

        # Try to parse "Producer - Name (Year)" or "Producer - Name"
        parts = filename.split(" - ", 1)
        if len(parts) < 2:
            # No " - " separator, try whole string comparison
            return 0.0

        existing_producer = parts[0].strip().lower()
        name_and_year = parts[1].strip()

        # Extract year if present (handle multiple formats)
        existing_year = None
        existing_name = name_and_year

        # Try (YYYY) format
        if "(" in name_and_year and ")" in name_and_year:
            import re
            year_match = re.search(r'\((\d{4})\)', name_and_year)
            if year_match:
                existing_year = year_match.group(1)
                # Remove the year part
                existing_name = name_and_year[:year_match.start()].strip()

        # Also check for bare year at end
        import re
        year_match = re.search(r'\s+(\d{4})$', existing_name)
        if year_match and not existing_year:
            existing_year = year_match.group(1)
            existing_name = existing_name[:year_match.start()].strip()

        existing_name = existing_name.lower()

        # Compare producer (weight: 0.4)
        producer_similarity = self._fuzzy_match(bottle_producer, existing_producer)
        producer_score = producer_similarity * 0.4
        scores.append(producer_score)

        # Compare name (weight: 0.4)
        name_similarity = self._fuzzy_match(bottle_name, existing_name)
        name_score = name_similarity * 0.4
        scores.append(name_score)

        # Compare year (weight: 0.2)
        year_score = 0.0
        if bottle_year_str and existing_year:
            year_match = 1.0 if bottle_year_str == existing_year else 0.0
            year_score = year_match * 0.2
            scores.append(year_score)
        elif not bottle_year_str and not existing_year:
            # Both missing year - slight bonus
            year_score = 0.1
            scores.append(year_score)

        return sum(scores)

    def _fuzzy_match(self, str1: str, str2: str) -> float:
        """
        Calculate fuzzy string similarity.

        Args:
            str1: First string
            str2: Second string

        Returns:
            Similarity score (0.0-1.0)
        """
        if not str1 or not str2:
            return 0.0

        return SequenceMatcher(None, str1, str2).ratio()

    def _explain_match(self, bottle: BottleMetadata, filename: str) -> str:
        """
        Generate explanation for why this is considered a potential duplicate.

        Args:
            bottle: Bottle metadata
            filename: Existing bottle filename

        Returns:
            Human-readable explanation
        """
        parts = filename.split(" - ", 1)
        if len(parts) < 2:
            return "Similar filename"

        existing_producer = parts[0].strip()
        name_and_year = parts[1].strip()

        reasons = []

        # Check producer match
        if bottle.producer and existing_producer:
            producer_sim = self._fuzzy_match(
                bottle.producer.lower(),
                existing_producer.lower()
            )
            if producer_sim > 0.8:
                reasons.append(f"Similar producer: '{existing_producer}'")

        # Check name match
        existing_name = name_and_year
        if name_and_year.endswith(")") and "(" in name_and_year:
            year_start = name_and_year.rfind("(")
            existing_name = name_and_year[:year_start].strip()

        if bottle.name and existing_name:
            name_sim = self._fuzzy_match(
                bottle.name.lower(),
                existing_name.lower()
            )
            if name_sim > 0.8:
                reasons.append(f"Similar name: '{existing_name}'")

        # Check year match
        if bottle.year and "(" in name_and_year:
            year_start = name_and_year.rfind("(")
            year_str = name_and_year[year_start + 1:-1].strip()
            try:
                existing_year = int(year_str)
                if bottle.year == existing_year:
                    reasons.append(f"Same year: {existing_year}")
            except ValueError:
                pass

        return "; ".join(reasons) if reasons else "Similar metadata"
