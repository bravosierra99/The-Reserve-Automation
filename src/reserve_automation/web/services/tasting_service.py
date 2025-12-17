"""Service for tasting extraction, matching, and management."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from reserve_automation.core.config import Config
from reserve_automation.core.tasting_note import TastingExtractionResult, TastingNote
from reserve_automation.generators.tasting_generator import TastingGenerator
from reserve_automation.utils.bottle_matcher import BottleMatcher, BottleMatch

from ..schemas.tasting import (
    MatchCandidate,
    TastingData,
    TastingSession,
    TastingSessionItem,
    TastingStatus,
)


class TastingService:
    """Service for managing tasting extraction and review workflow."""

    def __init__(self, core_config: Config):
        """
        Initialize tasting service.

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

    def create_session_from_extraction(
        self,
        extraction_id: str,
        extraction_result: TastingExtractionResult,
        expected_count: Optional[int] = None,
        upload_filename: Optional[str] = None
    ) -> TastingSession:
        """
        Create a TastingSession from an extraction result.

        Args:
            extraction_id: Unique ID for this extraction
            extraction_result: Raw extraction result from LLM
            expected_count: User-specified expected tasting count
            upload_filename: Original uploaded filename

        Returns:
            TastingSession with match candidates populated
        """
        logger.info(f"Creating tasting session {extraction_id} with {len(extraction_result.tastings)} tastings")

        tastings = []
        for i, tasting in enumerate(extraction_result.tastings):
            try:
                logger.debug(f"Processing tasting {i}: {tasting.bottle_name}")
                # Convert raw tasting to TastingData
                tasting_data = self._tasting_note_to_data(tasting)
                logger.debug(f"Successfully converted tasting {i} to TastingData")
            except Exception as e:
                logger.error(f"Failed to convert tasting {i} to TastingData: {e}", exc_info=True)
                logger.error(f"Tasting data: {tasting.model_dump()}")
                raise

            # Get match candidates for this tasting
            match_candidates = self.get_match_candidates(
                bottle_name=tasting.bottle_name,
                beverage_type=tasting.beverage_type,
                limit=5
            )

            # Auto-select best match if confidence is high
            selected_match = None
            if match_candidates and match_candidates[0].confidence >= 0.8:
                selected_match = match_candidates[0].bottle_path

            # Check for duplicate tasting
            duplicate_warning = None
            if selected_match:
                duplicate_warning = self.check_duplicate_tasting(
                    bottle_path=selected_match,
                    taster=tasting.taster_name,
                    tasting_date=tasting.tasting_date
                )

            # Determine initial status
            status = TastingStatus.MATCHED if selected_match else TastingStatus.EXTRACTED

            session_item = TastingSessionItem(
                index=i,
                status=status,
                tasting_data=tasting_data,
                match_candidates=match_candidates,
                selected_match=selected_match,
                duplicate_warning=duplicate_warning
            )
            tastings.append(session_item)

        actual_count = len(tastings)
        count_mismatch = expected_count is not None and expected_count != actual_count

        if count_mismatch:
            logger.warning(f"Count mismatch: expected {expected_count}, got {actual_count}")

        # Infer beverage_type from template_type or first tasting
        beverage_type = "unknown"
        if extraction_result.template_type == "aws_wine":
            beverage_type = "wine"
        elif extraction_result.template_type == "bourbon":
            beverage_type = "whiskey"
        elif tastings and tastings[0].tasting_data.beverage_type:
            beverage_type = tastings[0].tasting_data.beverage_type

        session = TastingSession(
            extraction_id=extraction_id,
            beverage_type=beverage_type,
            template_type=extraction_result.template_type or "unknown",
            expected_count=expected_count,
            actual_count=actual_count,
            count_mismatch=count_mismatch,
            tastings=tastings,
            upload_filename=upload_filename
        )

        return session

    def get_match_candidates(
        self,
        bottle_name: str,
        beverage_type: str,
        limit: int = 5
    ) -> list[MatchCandidate]:
        """
        Get potential bottle matches for a tasting.

        Args:
            bottle_name: Bottle name from tasting card
            beverage_type: "wine" or "whiskey"
            limit: Maximum candidates to return

        Returns:
            List of MatchCandidate objects sorted by confidence
        """
        logger.debug(f"Finding matches for: {bottle_name} ({beverage_type})")

        matches = self.bottle_matcher.find_matches(
            bottle_name=bottle_name,
            beverage_type=beverage_type,
            top_n=limit,
            min_score=0.3
        )

        candidates = []
        for match in matches:
            # Build thumbnail URL (if label exists)
            thumbnail_url = None
            if match.folder_path:
                label_path = match.folder_path / "label.jpg"
                if label_path.exists():
                    # Construct URL for serving this image
                    rel_path = match.folder_path.relative_to(self.vault_path)
                    thumbnail_url = f"/api/v1/vault-images/{beverage_type}/{rel_path.name}/label.jpg"

            candidate = MatchCandidate(
                bottle_path=str(match.folder_path.relative_to(self.vault_path)) if match.folder_path else "",
                bottle_name=self._get_full_name(match),
                producer=match.bottle.producer or "",
                vintage=match.bottle.year,
                confidence=match.score,
                thumbnail_url=thumbnail_url,
                beverage_type=beverage_type
            )
            candidates.append(candidate)

        logger.debug(f"Found {len(candidates)} candidates")
        return candidates

    def search_bottles(
        self,
        query: str,
        beverage_type: Optional[str] = None,
        limit: int = 10,
        strict: bool = True
    ) -> list[MatchCandidate]:
        """
        Search for bottles in the vault by name.

        Args:
            query: Search query
            beverage_type: Optional filter (wine/whiskey)
            limit: Maximum results
            strict: Use strict substring matching (default True)

        Returns:
            List of matching bottles as MatchCandidate objects
        """
        logger.info(f"Searching bottles: '{query}' (type={beverage_type}, strict={strict})")

        results = []

        # Search both wine and whiskey if no type specified
        types_to_search = [beverage_type] if beverage_type else ["wine", "whiskey"]

        for bev_type in types_to_search:
            matches = self.bottle_matcher.find_matches(
                bottle_name=query,
                beverage_type=bev_type,
                top_n=limit,
                min_score=0.2,  # Lower threshold for fuzzy search
                strict_substring=strict
            )

            for match in matches:
                # Build thumbnail URL
                thumbnail_url = None
                if match.folder_path:
                    label_path = match.folder_path / "label.jpg"
                    if label_path.exists():
                        rel_path = match.folder_path.relative_to(self.vault_path)
                        thumbnail_url = f"/api/v1/vault-images/{bev_type}/{rel_path.name}/label.jpg"

                candidate = MatchCandidate(
                    bottle_path=str(match.folder_path.relative_to(self.vault_path)) if match.folder_path else "",
                    bottle_name=self._get_full_name(match),
                    producer=match.bottle.producer or "",
                    vintage=match.bottle.year,
                    confidence=match.score,
                    thumbnail_url=thumbnail_url,
                    beverage_type=bev_type
                )
                results.append(candidate)

        # Sort by confidence and limit
        results.sort(key=lambda x: x.confidence, reverse=True)
        return results[:limit]

    def check_duplicate_tasting(
        self,
        bottle_path: str,
        taster: str,
        tasting_date: datetime
    ) -> Optional[str]:
        """
        Check if a tasting already exists for this bottle/taster/date combo.

        Args:
            bottle_path: Relative path to bottle folder
            taster: Taster name
            tasting_date: Date of tasting

        Returns:
            Warning message if duplicate found, None otherwise
        """
        full_path = self.vault_path / bottle_path

        if not full_path.exists():
            return None

        # Look for existing tasting files
        date_str = tasting_date.strftime("%Y-%m-%d") if isinstance(tasting_date, datetime) else str(tasting_date)[:10]

        for tasting_file in full_path.glob("tasting-*.md"):
            # Check if file matches this taster and date
            content = tasting_file.read_text()

            # Simple check - look for taster name and date in content
            if taster.lower() in content.lower() and date_str in content:
                return f"A tasting by {taster} on {date_str} may already exist: {tasting_file.name}"

        return None

    async def save_tasting(
        self,
        tasting_item: TastingSessionItem,
        bottle_path: str
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Save a single tasting to the vault.

        Args:
            tasting_item: The tasting session item to save
            bottle_path: Path to bottle folder in vault

        Returns:
            Tuple of (success, file_path, error_message)
        """
        logger.info(f"Saving tasting to {bottle_path}")

        try:
            # Convert TastingData back to TastingNote
            tasting_note = self._data_to_tasting_note(tasting_item.tasting_data)

            # Get the bottle match
            full_bottle_path = self.vault_path / bottle_path
            if not full_bottle_path.exists():
                return False, None, f"Bottle folder not found: {bottle_path}"

            # Create a minimal BottleMatch for the generator
            # We need to find the actual bottle metadata
            matches = self.bottle_matcher.find_matches(
                bottle_name=full_bottle_path.name,
                beverage_type=tasting_item.tasting_data.beverage_type,
                top_n=1,
                min_score=0.0
            )

            if not matches:
                # Create a synthetic match
                from reserve_automation.core.models import BottleMetadata
                bottle_meta = BottleMetadata(
                    producer="",
                    name=full_bottle_path.name,
                    type=tasting_item.tasting_data.beverage_type
                )
                match = BottleMatch(bottle_meta, 1.0, full_bottle_path)
            else:
                match = matches[0]
                match.folder_path = full_bottle_path  # Ensure correct path

            # Generate tasting file
            file_path = self.tasting_generator.generate_tasting_file(
                tasting=tasting_note,
                bottle_match=match,
                dry_run=False
            )

            rel_path = str(file_path.relative_to(self.vault_path))
            logger.info(f"Created tasting file: {rel_path}")

            return True, rel_path, None

        except Exception as e:
            logger.error(f"Failed to save tasting: {e}", exc_info=True)
            return False, None, str(e)

    def _tasting_note_to_data(self, tasting: TastingNote) -> TastingData:
        """Convert a TastingNote to TastingData for editing."""
        return TastingData(
            bottle_name=tasting.bottle_name,
            taster_name=tasting.taster_name,
            tasting_date=tasting.tasting_date.isoformat() if isinstance(tasting.tasting_date, datetime) else str(tasting.tasting_date),
            beverage_type=tasting.beverage_type,
            wine_appearance=tasting.wine_appearance,
            wine_aroma=tasting.wine_aroma,
            wine_taste=tasting.wine_taste,
            wine_aftertaste=tasting.wine_aftertaste,
            wine_overall=tasting.wine_overall,
            whiskey_nose=tasting.whiskey_nose,
            whiskey_palate=tasting.whiskey_palate,
            whiskey_finish=tasting.whiskey_finish,
            whiskey_overall=tasting.whiskey_overall,
            days_from_crack=tasting.days_from_crack,
            fill_level=tasting.fill_level,
            color=tasting.color,
            place=tasting.place,
            theme=tasting.theme,
            nose_notes=tasting.nose_notes or [],
            palate_notes=tasting.palate_notes or [],
            finish_notes=tasting.finish_notes or [],
            overall_notes=tasting.overall_notes
        )

    def _data_to_tasting_note(self, data: TastingData) -> TastingNote:
        """Convert TastingData back to TastingNote for saving."""
        # Parse date
        if isinstance(data.tasting_date, str):
            tasting_date = datetime.fromisoformat(data.tasting_date)
        else:
            tasting_date = data.tasting_date

        return TastingNote(
            bottle_name=data.bottle_name,
            taster_name=data.taster_name,
            tasting_date=tasting_date,
            beverage_type=data.beverage_type,
            wine_appearance=data.wine_appearance,
            wine_aroma=data.wine_aroma,
            wine_taste=data.wine_taste,
            wine_aftertaste=data.wine_aftertaste,
            wine_overall=data.wine_overall,
            whiskey_nose=data.whiskey_nose,
            whiskey_palate=data.whiskey_palate,
            whiskey_finish=data.whiskey_finish,
            whiskey_overall=data.whiskey_overall,
            days_from_crack=data.days_from_crack,
            fill_level=data.fill_level,
            color=data.color,
            place=data.place,
            theme=data.theme,
            nose_notes=data.nose_notes,
            palate_notes=data.palate_notes,
            finish_notes=data.finish_notes,
            overall_notes=data.overall_notes
        )

    def _get_full_name(self, match: BottleMatch) -> str:
        """Get full bottle name from a match."""
        parts = [match.bottle.producer, match.bottle.name]
        if match.bottle.year:
            parts.append(str(match.bottle.year))
        return " - ".join(filter(None, parts))

    def get_session_stats(self, session: TastingSession) -> dict:
        """Get statistics for a tasting session."""
        approved = sum(1 for t in session.tastings if t.status == TastingStatus.APPROVED)
        skipped = sum(1 for t in session.tastings if t.status == TastingStatus.SKIPPED)
        remaining = session.actual_count - approved - skipped

        return {
            "total": session.actual_count,
            "approved": approved,
            "skipped": skipped,
            "remaining": remaining,
            "all_done": remaining == 0
        }
