"""Service for reviewing and improving label image quality."""

from pathlib import Path
from shutil import copyfile
from typing import List, Literal, Optional

from loguru import logger

from ...core.models import BottleMetadata
from ...llm.gateway import LLMGateway
from ...utils.label_processor import LabelImageProcessor
from ...utils.llm_label_finder import LLMLabelFinder
from ...utils.vault_reader import VaultReader


class LabelReviewCandidate:
    """Represents a label that needs review."""

    def __init__(
        self,
        bottle: BottleMetadata,
        original_path: Path,
        original_score: float,
        status: Literal["needs_replacement", "needs_cropping", "good"] = "good",
        shows_full_bottle: bool = False,
        search_results: Optional[List[dict]] = None
    ):
        self.bottle = bottle
        self.original_path = original_path
        self.original_score = original_score
        self.status = status
        self.shows_full_bottle = shows_full_bottle
        self.search_results = search_results or []

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "bottle": self.bottle.model_dump(mode='json'),
            "original_path": str(self.original_path),
            "original_score": self.original_score,
            "status": self.status,
            "shows_full_bottle": self.shows_full_bottle,
            "search_results": self.search_results,
            "priority": self._get_priority()
        }

    def _get_priority(self) -> int:
        """Get sort priority (lower = more urgent)."""
        if self.status == "needs_replacement":
            return 1
        elif self.status == "needs_cropping":
            return 2
        else:  # good
            return 3


class LabelReviewService:
    """Service for batch label quality review and improvement."""

    def __init__(self, llm_gateway: LLMGateway, vault_path: Path):
        """
        Initialize label review service.

        Args:
            llm_gateway: LLM gateway for vision tasks
            vault_path: Path to Obsidian vault
        """
        self.llm = llm_gateway
        self.vault_path = vault_path
        self.processor = LabelImageProcessor(llm_gateway)
        self.vault_reader = VaultReader(vault_path)
        self.label_finder = LLMLabelFinder(llm_gateway)

    async def scan_all_labels(
        self,
        show_all: bool = False,
        limit: Optional[int] = None
    ) -> List[LabelReviewCandidate]:
        """
        Scan all bottle labels and categorize them.

        Categorization rules:
        - needs_replacement: score < 5.0 (poor quality - search for new images)
        - needs_cropping: score >= 5.0 but shows full bottle (good image, just crop it)
        - good: score >= 8.0 or already well-cropped (no action needed)

        Args:
            show_all: If True, return all labels (not just ones needing action)
            limit: Optional limit on number of bottles to check

        Returns:
            Prioritized list of label review candidates
        """
        logger.info(f"Starting label quality scan (show_all: {show_all})")

        # Get all bottles from vault
        bottles = self.vault_reader.read_all_bottles()
        logger.info(f"Found {len(bottles)} bottles in vault")

        if limit:
            bottles = bottles[:limit]
            logger.info(f"Limiting scan to first {limit} bottles")

        candidates = []

        for bottle in bottles:
            try:
                # Check if bottle has a label
                label_path = self._get_label_path(bottle)
                if not label_path or not label_path.exists():
                    logger.debug(f"No label for {bottle.producer} {bottle.name}, skipping")
                    continue

                logger.info(f"Analyzing: {bottle.producer} {bottle.name}")

                # Read label image
                with open(label_path, 'rb') as f:
                    label_bytes = f.read()

                # Score label quality and detect if it shows full bottle
                score = await self.processor.score_label_quality(label_bytes, bottle)
                shows_full_bottle = await self._detect_full_bottle(label_bytes, bottle)

                if score is None:
                    logger.warning("Failed to score, skipping")
                    continue

                logger.info(f"  Score: {score:.1f}/10, Full bottle: {shows_full_bottle}")

                # Categorize
                if score < 5.0:
                    status = "needs_replacement"
                    logger.info("  🔴 Needs replacement (poor quality)")
                elif shows_full_bottle and score < 8.0:
                    status = "needs_cropping"
                    logger.info("  🟡 Needs cropping (full bottle detected)")
                else:
                    status = "good"
                    logger.info("  ✅ Good quality")

                # Add to candidates if needs action or showing all
                if status != "good" or show_all:
                    candidate = LabelReviewCandidate(
                        bottle=bottle,
                        original_path=label_path,
                        original_score=score,
                        status=status,
                        shows_full_bottle=shows_full_bottle
                    )
                    candidates.append(candidate)

            except Exception as e:
                logger.error(f"Error processing {bottle.producer} {bottle.name}: {e}")
                continue

        # Sort by priority (needs_replacement first, then needs_cropping, then good)
        candidates.sort(key=lambda c: c._get_priority())

        logger.info(f"Scan complete: {len(candidates)} labels in queue")
        logger.info(f"  Needs replacement: {sum(1 for c in candidates if c.status == 'needs_replacement')}")
        logger.info(f"  Needs cropping: {sum(1 for c in candidates if c.status == 'needs_cropping')}")
        logger.info(f"  Good: {sum(1 for c in candidates if c.status == 'good')}")

        return candidates

    async def _detect_full_bottle(self, image_bytes: bytes, bottle: BottleMetadata) -> bool:
        """
        Detect if image shows a full bottle vs just the label.

        Uses vision LLM to analyze the image composition.

        Args:
            image_bytes: Image to analyze
            bottle: Bottle metadata for context

        Returns:
            True if image shows full bottle, False if just label/closeup
        """
        try:
            prompt = f"""Analyze this {bottle.type} bottle image.

Is this image showing:
A) A full bottle (you can see the whole bottle from top to bottom)
B) Just the label (close-up crop of the label area)

Answer with only "full_bottle" or "just_label".
"""

            response = await self.llm.complete(
                task_type="ocr",
                prompt=prompt,
                images=[image_bytes]
            )

            result = response.content.lower().strip()
            is_full_bottle = "full" in result or "bottle" in result.replace("just_label", "")

            return is_full_bottle

        except Exception as e:
            logger.error(f"Full bottle detection failed: {e}")
            # Default to assuming it's full bottle (safer to crop)
            return True

    async def search_replacement_images(self, candidate: LabelReviewCandidate) -> List[dict]:
        """
        Search the web for replacement label images.

        Args:
            candidate: Label review candidate needing replacement

        Returns:
            List of image search results with URLs
        """
        try:
            logger.info(f"Searching for replacement images: {candidate.bottle.producer} {candidate.bottle.name}")

            # Use label finder to search (same as upload flow)
            results = await self.label_finder.find_label_images(candidate.bottle)

            logger.info(f"Found {len(results)} replacement image candidates")
            return results

        except Exception as e:
            logger.error(f"Image search failed: {e}")
            return []

    async def generate_improved_crop(self, candidate: LabelReviewCandidate) -> bool:
        """
        Generate improved crop for a candidate label.

        Args:
            candidate: Label review candidate

        Returns:
            True if improved crop was generated successfully
        """
        try:
            logger.info(f"Generating improved crop for {candidate.bottle.producer} {candidate.bottle.name}")

            # Create temp path for improved version
            original_path = candidate.original_path
            improved_path = original_path.parent / f"{original_path.stem}_improved{original_path.suffix}"

            # Copy original to temp location
            copyfile(original_path, improved_path)

            # Apply improved cropping (EXIF + LLM label detection)
            result = await self.processor.crop_to_label(improved_path)

            if not result:
                logger.warning("Crop processing failed")
                return False

            # Score the improved version
            with open(improved_path, 'rb') as f:
                improved_bytes = f.read()

            improved_score = await self.processor.score_label_quality(
                improved_bytes, candidate.bottle
            )

            if improved_score is None:
                logger.warning("Failed to score improved version")
                # Keep it anyway - user can decide
                improved_score = 0.0

            # Update candidate
            candidate.improved_path = improved_path
            candidate.improved_score = improved_score

            logger.info(f"  Original: {candidate.original_score:.1f} → Improved: {improved_score:.1f}")

            return True

        except Exception as e:
            logger.error(f"Failed to generate improved crop: {e}")
            return False

    async def accept_improved_label(self, bottle: BottleMetadata) -> bool:
        """
        Accept the improved label crop and replace original.

        Args:
            bottle: Bottle to update

        Returns:
            True if successful
        """
        try:
            label_path = self._get_label_path(bottle)
            if not label_path:
                return False

            improved_path = label_path.parent / f"{label_path.stem}_improved{label_path.suffix}"

            if not improved_path.exists():
                logger.error(f"Improved version not found: {improved_path}")
                return False

            # Backup original
            backup_path = label_path.parent / f"{label_path.stem}_original_backup{label_path.suffix}"
            copyfile(label_path, backup_path)

            # Replace with improved
            copyfile(improved_path, label_path)

            # Clean up
            improved_path.unlink()

            logger.info(f"✅ Accepted improved label for {bottle.producer} {bottle.name}")
            return True

        except Exception as e:
            logger.error(f"Failed to accept improved label: {e}")
            return False

    async def keep_original_label(self, bottle: BottleMetadata) -> bool:
        """
        Keep the original label and discard improved version.

        Args:
            bottle: Bottle to keep original for

        Returns:
            True if successful
        """
        try:
            label_path = self._get_label_path(bottle)
            if not label_path:
                return False

            improved_path = label_path.parent / f"{label_path.stem}_improved{label_path.suffix}"

            # Just delete improved version if it exists
            if improved_path.exists():
                improved_path.unlink()
                logger.info(f"Kept original label for {bottle.producer} {bottle.name}")

            return True

        except Exception as e:
            logger.error(f"Failed to clean up improved label: {e}")
            return False

    def _get_label_path(self, bottle: BottleMetadata) -> Optional[Path]:
        """Get path to bottle's label image."""
        if not bottle.vault_path:
            return None

        bottle_folder = self.vault_path / bottle.vault_path
        label_path = bottle_folder / "labels" / "label.jpg"

        # Also check for .png
        if not label_path.exists():
            label_path = bottle_folder / "labels" / "label.png"

        return label_path if label_path.exists() else None
