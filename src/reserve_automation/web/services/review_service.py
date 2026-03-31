"""Review and approval service for extracted tastings."""

from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from loguru import logger

from reserve_automation.core.config import Config
from reserve_automation.core.tasting_note import TastingExtractionResult, TastingNote


class ReviewService:
    """Service for reviewing and approving extracted tastings."""

    def __init__(self, config_or_bottle_repo, tasting_repo=None):
        """
        Initialize review service.

        Supports two modes:
        1. Legacy: ReviewService(core_config) - vault-based matching/generation
        2. DB mode: ReviewService(bottle_repo, tasting_repo) - SQLite operations

        Args:
            config_or_bottle_repo: Either Config or SQLiteBottleRepository
            tasting_repo: Optional SQLiteTastingRepository (if first arg is a repo)
        """
        from ...db.repositories.bottle_repo import SQLiteBottleRepository

        if isinstance(config_or_bottle_repo, SQLiteBottleRepository):
            self.bottle_repo = config_or_bottle_repo
            self.tasting_repo = tasting_repo
            self.config = None
            self.vault_path = None
        else:
            # Legacy mode - config passed
            self.config = config_or_bottle_repo
            self.vault_path = config_or_bottle_repo.vault_path
            self.bottle_repo = None
            self.tasting_repo = None

    async def approve_extraction(
        self,
        extraction_result: TastingExtractionResult
    ) -> dict:
        """
        Approve extraction and save tastings.

        In DB mode: matches bottles via search and saves tastings to DB.
        In vault mode: matches bottles via BottleMatcher and generates vault files.

        Args:
            extraction_result: Extraction result with tastings

        Returns:
            Dictionary with approval results:
            - files_created: List of created file paths (or "db:{tasting_id}" in DB mode)
            - bottles_matched: List of matched bottle info
            - unmatched: List of tastings that couldn't be matched
        """
        logger.info(f"Approving extraction with {len(extraction_result.tastings)} tastings")

        files_created = []
        bottles_matched = []
        unmatched = []

        if self.bottle_repo and self.tasting_repo:
            # DB mode
            for tasting in extraction_result.tastings:
                match = self._match_bottle(tasting)

                if match is None:
                    logger.warning(f"No bottle match found for: {tasting.bottle_name}")
                    unmatched.append({
                        "bottle_name": tasting.bottle_name,
                        "taster_name": tasting.taster_name
                    })
                    continue

                try:
                    bottle_id = match["bottle_id"]
                    created = self.tasting_repo.create(tasting, bottle_id)
                    tasting_id = getattr(created, "id", None) or str(created)

                    files_created.append(f"db:{tasting_id}")
                    bottles_matched.append({
                        "bottle_name": tasting.bottle_name,
                        "matched_to": match["matched_to"],
                        "confidence": match["confidence"]
                    })

                    logger.info(f"Saved tasting to DB: id={tasting_id}")

                except Exception as e:
                    logger.error(f"Failed to save tasting to DB: {e}", exc_info=True)
                    unmatched.append({
                        "bottle_name": tasting.bottle_name,
                        "taster_name": tasting.taster_name,
                        "error": str(e)
                    })
        else:
            # Vault fallback
            from reserve_automation.generators.tasting_generator import TastingGenerator
            from reserve_automation.utils.bottle_matcher import BottleMatcher

            bottle_matcher = BottleMatcher(self.vault_path)
            tasting_generator = TastingGenerator(
                vault_path=self.vault_path,
                templates_path=self.config.templates_dir if self.config else None
            )

            for tasting in extraction_result.tastings:
                matches = bottle_matcher.find_matches(
                    bottle_name=tasting.bottle_name,
                    beverage_type=tasting.beverage_type,
                    top_n=1
                )

                if not matches:
                    logger.warning(f"No bottle match found for: {tasting.bottle_name}")
                    unmatched.append({
                        "bottle_name": tasting.bottle_name,
                        "taster_name": tasting.taster_name
                    })
                    continue

                match = matches[0]

                try:
                    file_path = tasting_generator.generate_tasting_file(
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

    def _match_bottle(self, tasting: TastingNote) -> Optional[dict]:
        """
        Match a tasting to a bottle.

        In DB mode: uses bottle_repo.search() with SequenceMatcher confidence.
        In vault mode: uses BottleMatcher.find_matches().

        Args:
            tasting: Tasting note to match

        Returns:
            In DB mode: dict with bottle_id, matched_to, confidence; or None
            In vault mode: dict with bottle_id (None), matched_to, confidence,
                folder_path; or None
        """
        if self.bottle_repo:
            # DB mode
            bottles = self.bottle_repo.search(tasting.bottle_name)
            if not bottles:
                return None

            best_match = None
            best_confidence = 0.0

            for bottle in bottles:
                full_name = f"{bottle.producer} - {bottle.name}"
                confidence = SequenceMatcher(
                    None, tasting.bottle_name.lower(), full_name.lower()
                ).ratio()

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = {
                        "bottle_id": int(bottle.id),
                        "matched_to": full_name,
                        "confidence": best_confidence
                    }

            return best_match
        else:
            # Vault fallback
            from reserve_automation.utils.bottle_matcher import BottleMatcher

            bottle_matcher = BottleMatcher(self.vault_path)
            matches = bottle_matcher.find_matches(
                bottle_name=tasting.bottle_name,
                beverage_type=tasting.beverage_type,
                top_n=1
            )

            if not matches:
                return None

            match = matches[0]
            return {
                "bottle_id": None,
                "matched_to": match.folder_path.name,
                "confidence": match.score,
                "folder_path": match.folder_path,
                "bottle_match": match
            }

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
                    "matched_to": match["matched_to"],
                    "confidence": match["confidence"]
                })
            else:
                preview.update({
                    "matched": False,
                    "matched_to": None,
                    "confidence": 0.0
                })

            previews.append(preview)

        return previews
