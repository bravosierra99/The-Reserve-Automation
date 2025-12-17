"""Review and approval service for extracted tastings."""

from pathlib import Path
from typing import Optional

from loguru import logger

from reserve_automation.core.config import Config
from reserve_automation.core.tasting_note import TastingExtractionResult, TastingNote
from reserve_automation.generators.tasting_generator import TastingGenerator
from reserve_automation.utils.bottle_matcher import BottleMatcher, BottleMatch


class ReviewService:
    """Service for reviewing and approving extracted tastings."""

    def __init__(self, core_config: Config):
        """
        Initialize review service.

        Args:
            core_config: Core application configuration
        """
        self.config = core_config
        self.vault_path = core_config.vault_path
        self.templates_path = core_config.templates_dir

        # Initialize bottle matcher and tasting generator
        self.bottle_matcher = BottleMatcher(self.vault_path)
        self.tasting_generator = TastingGenerator(
            vault_path=self.vault_path,
            templates_path=self.templates_path
        )

    async def approve_extraction(
        self,
        extraction_result: TastingExtractionResult
    ) -> dict:
        """
        Approve extraction and save tastings to Obsidian vault.

        Args:
            extraction_result: Extraction result with tastings

        Returns:
            Dictionary with approval results:
            - files_created: List of created file paths
            - bottles_matched: List of matched bottle info
            - unmatched: List of tastings that couldn't be matched
        """
        logger.info(f"Approving extraction with {len(extraction_result.tastings)} tastings")

        files_created = []
        bottles_matched = []
        unmatched = []

        for tasting in extraction_result.tastings:
            # Match bottle in vault
            match = self._match_bottle(tasting)

            if match is None:
                logger.warning(f"No bottle match found for: {tasting.bottle_name}")
                unmatched.append({
                    "bottle_name": tasting.bottle_name,
                    "taster_name": tasting.taster_name
                })
                continue

            # Generate tasting file
            try:
                file_path = self.tasting_generator.generate_tasting_file(
                    tasting=tasting,
                    bottle_match=match,
                    dry_run=False
                )

                files_created.append(str(file_path.relative_to(self.vault_path)))
                bottles_matched.append({
                    "bottle_name": tasting.bottle_name,
                    "matched_to": match.folder_path.name,
                    "confidence": match.score
                })

                logger.info(f"Created tasting file: {file_path}")

            except Exception as e:
                logger.error(f"Failed to generate tasting file: {e}", exc_info=True)
                unmatched.append({
                    "bottle_name": tasting.bottle_name,
                    "taster_name": tasting.taster_name,
                    "error": str(e)
                })

        result = {
            "files_created": files_created,
            "bottles_matched": bottles_matched,
            "unmatched": unmatched
        }

        logger.info(
            f"Approval complete: {len(files_created)} files created, "
            f"{len(unmatched)} unmatched"
        )

        return result

    def _match_bottle(self, tasting: TastingNote) -> Optional[BottleMatch]:
        """
        Match a tasting to a bottle in the vault.

        Args:
            tasting: Tasting note to match

        Returns:
            BottleMatch if found, None otherwise
        """
        # Use bottle matcher to find best match
        matches = self.bottle_matcher.find_matches(
            bottle_name=tasting.bottle_name,
            beverage_type=tasting.beverage_type,
            top_n=1
        )

        if not matches:
            return None

        # Return best match (first one)
        return matches[0]

    def preview_matches(
        self,
        extraction_result: TastingExtractionResult
    ) -> list[dict]:
        """
        Preview bottle matches without saving.

        Args:
            extraction_result: Extraction result with tastings

        Returns:
            List of match previews
        """
        previews = []

        for tasting in extraction_result.tastings:
            match = self._match_bottle(tasting)

            preview = {
                "bottle_name": tasting.bottle_name,
                "taster_name": tasting.taster_name,
                "tasting_date": tasting.tasting_date.isoformat()
            }

            if match:
                preview.update({
                    "matched": True,
                    "matched_to": match.folder_path.name,
                    "confidence": match.score
                })
            else:
                preview.update({
                    "matched": False,
                    "matched_to": None,
                    "confidence": 0.0
                })

            previews.append(preview)

        return previews
