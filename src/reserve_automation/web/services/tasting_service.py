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

    def invalidate_bottle_cache(self, beverage_type: Optional[str] = None):
        """
        Invalidate bottle cache after new bottles are added.

        Args:
            beverage_type: Optional beverage type to invalidate. If None, clears entire cache.
        """
        self.bottle_matcher.invalidate_cache(beverage_type)

    def create_session_from_extraction(
        self,
        extraction_id: str,
        extraction_result: TastingExtractionResult,
        expected_count: Optional[int] = None,
        upload_filename: Optional[str] = None,
        event_id: Optional[str] = None
    ) -> TastingSession:
        """
        Create a TastingSession from an extraction result.

        Args:
            extraction_id: Unique ID for this extraction
            extraction_result: Raw extraction result from LLM
            expected_count: User-specified expected tasting count
            upload_filename: Original uploaded filename
            event_id: Optional event ID to restrict matches to event bottles

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
                limit=5,
                event_id=event_id
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
            upload_filename=upload_filename,
            event_id=event_id
        )

        return session

    def get_match_candidates(
        self,
        bottle_name: str,
        beverage_type: str,
        limit: int = 5,
        event_id: Optional[str] = None
    ) -> list[MatchCandidate]:
        """
        Get potential bottle matches for a tasting.

        Args:
            bottle_name: Bottle name from tasting card
            beverage_type: "wine" or "whiskey"
            limit: Maximum candidates to return
            event_id: Optional event ID to restrict matches to event bottles

        Returns:
            List of MatchCandidate objects sorted by confidence
        """
        logger.debug(f"Finding matches for: {bottle_name} ({beverage_type}, event_id={event_id})")

        # If event_id provided, filter to event bottles only
        if event_id:
            from ..app import event_store
            if event_store and event_id in event_store:
                event = event_store[event_id]
                event_bottles = event["bottles"]

                candidates = []
                for bottle in event_bottles:
                    # Simple string matching for event bottles
                    if bottle_name.lower() in bottle["bottle_name"].lower():
                        # Build thumbnail URL
                        thumbnail_url = None
                        label_path = self.vault_path / bottle["bottle_path"] / "labels" / "label.jpg"
                        if label_path.exists():
                            thumbnail_url = f"/api/v1/bottle-label/{bottle['bottle_path']}"

                        # Display name depends on event status
                        display_name = bottle["bottle_name"]
                        if event["is_blind"] and event["status"] == "open" and bottle.get("blind_number"):
                            display_name = f"Bottle #{bottle['blind_number']}"

                        candidate = MatchCandidate(
                            bottle_path=bottle["bottle_path"],
                            bottle_name=display_name,
                            producer="",
                            confidence=1.0 if bottle_name.lower() == bottle["bottle_name"].lower() else 0.8,
                            thumbnail_url=thumbnail_url,
                            beverage_type=beverage_type
                        )
                        candidates.append(candidate)

                candidates.sort(key=lambda x: x.confidence, reverse=True)
                return candidates[:limit]

            # Event not found, return empty
            return []

        matches = self.bottle_matcher.find_matches(
            bottle_name=bottle_name,
            beverage_type=beverage_type,
            top_n=limit,
            min_score=0.3
        )

        candidates = []
        for match in matches:
            # Use vault_path directly from bottle metadata
            bottle_path = match.bottle.vault_path or ""

            if not bottle_path:
                logger.warning(f"Bottle has no vault_path: {self._get_full_name(match)}")
                continue

            # Build thumbnail URL (if label exists)
            thumbnail_url = None
            bottle_folder_name = bottle_path.split('/')[-1]  # Last component
            label_path = self.vault_path / bottle_path / "labels" / "label.jpg"
            if label_path.exists():
                thumbnail_url = f"/api/v1/vault-images/{beverage_type}/{bottle_folder_name}/label.jpg"

            candidate = MatchCandidate(
                bottle_path=bottle_path,
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
        strict: bool = True,
        event_id: Optional[str] = None
    ) -> list[MatchCandidate]:
        """
        Search for bottles in the vault by name.

        Args:
            query: Search query
            beverage_type: Optional filter (wine/whiskey)
            limit: Maximum results
            strict: Use strict substring matching (default True)
            event_id: Optional event ID to restrict search to event bottles

        Returns:
            List of matching bottles as MatchCandidate objects
        """
        logger.info(f"Searching bottles: '{query}' (type={beverage_type}, strict={strict}, event_id={event_id})")

        # If event_id provided, search only event bottles
        if event_id:
            from ..app import event_store
            if event_store and event_id in event_store:
                event = event_store[event_id]
                event_bottles = event["bottles"]

                results = []
                for bottle in event_bottles:
                    # Match query against bottle name or blind number
                    matches_name = query.lower() in bottle["bottle_name"].lower()
                    matches_number = bottle.get("blind_number") and query in str(bottle["blind_number"])

                    if matches_name or matches_number:
                        # Build thumbnail URL
                        thumbnail_url = None
                        label_path = self.vault_path / bottle["bottle_path"] / "labels" / "label.jpg"
                        if label_path.exists():
                            thumbnail_url = f"/api/v1/bottle-label/{bottle['bottle_path']}"

                        # Display name depends on event status
                        display_name = bottle["bottle_name"]
                        if event["is_blind"] and event["status"] == "open" and bottle.get("blind_number"):
                            display_name = f"Bottle #{bottle['blind_number']}"

                        candidate = MatchCandidate(
                            bottle_path=bottle["bottle_path"],
                            bottle_name=display_name,
                            producer="",
                            confidence=1.0 if matches_name else 0.9,
                            thumbnail_url=thumbnail_url,
                            beverage_type=event["beverage_type"]
                        )
                        results.append(candidate)

                results.sort(key=lambda x: x.confidence, reverse=True)
                return results[:limit]

            # Event not found, return empty
            return []

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
                # Use vault_path directly from bottle metadata (no reconstruction needed!)
                bottle_path = match.bottle.vault_path or ""

                if not bottle_path:
                    logger.warning(f"Bottle has no vault_path: {self._get_full_name(match)}")
                    continue

                logger.debug(f"Processing match: bottle={self._get_full_name(match)}, vault_path={bottle_path}")

                # Build thumbnail URL from vault_path
                thumbnail_url = None
                # Check for label in bottle's labels folder
                label_path = self.vault_path / bottle_path / "labels" / "label.jpg"
                if label_path.exists():
                    thumbnail_url = f"/api/v1/bottle-label/{bottle_path}"

                candidate = MatchCandidate(
                    bottle_path=bottle_path,
                    bottle_name=self._get_full_name(match),
                    producer=match.bottle.producer or "",
                    vintage=match.bottle.year,
                    confidence=match.score,
                    thumbnail_url=thumbnail_url,
                    beverage_type=bev_type
                )
                logger.debug(f"  -> Created MatchCandidate with bottle_path='{candidate.bottle_path}'")
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
        bottle_path: str,
        event_id: Optional[str] = None,
        participant_id: Optional[str] = None
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Save a single tasting to the vault or event store.

        Args:
            tasting_item: The tasting session item to save
            bottle_path: Path to bottle folder in vault
            event_id: Optional event ID for event-based tastings
            participant_id: Optional participant ID for event-based tastings

        Returns:
            Tuple of (success, file_path, error_message)
        """
        logger.info(f"Saving tasting to {bottle_path} (event_id={event_id})")

        # If event_id provided, save to event_store instead of vault
        if event_id:
            try:
                from ..app import event_store
                if event_store is None or event_id not in event_store:
                    return False, None, "Event not found"

                if not participant_id:
                    return False, None, "Participant ID required for event tastings"

                event = event_store[event_id]

                # Check if participant exists
                if participant_id not in event["participants"]:
                    return False, None, "Participant not found in event"

                participant = event["participants"][participant_id]

                # Check for duplicate (one tasting per bottle per participant)
                if any(t["bottle_path"] == bottle_path for t in participant["tastings"]):
                    return False, None, "You have already tasted this bottle"

                # Add tasting to participant
                participant["tastings"].append({
                    "bottle_path": bottle_path,
                    "tasting_data": tasting_item.tasting_data.dict()
                })

                logger.info(f"Saved tasting to event {event_id} for participant {participant_id}")
                return True, f"event:{event_id}", None

            except Exception as e:
                logger.error(f"Failed to save event tasting: {e}", exc_info=True)
                return False, None, str(e)

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
            appearance_notes=tasting.appearance_notes or [],  # Wine-specific
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
            appearance_notes=data.appearance_notes,
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

    # ========================================================================
    # Manual Tasting Methods
    # ========================================================================

    async def save_manual_tasting_to_obsidian(
        self,
        manual_session
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Save a manual tasting session to Obsidian vault.

        Args:
            manual_session: ManualTastingSession object

        Returns:
            Tuple of (success, file_path, error_message)
        """
        # Import here to avoid circular imports
        from ..schemas.tasting import ManualTastingSession

        # Convert to proper type if dict
        if isinstance(manual_session, dict):
            manual_session = ManualTastingSession(**manual_session)

        # Validate all required fields are present
        if not manual_session.taster_name or not manual_session.tasting_date:
            return False, None, "Missing required taster info"

        if not manual_session.selected_bottle_path:
            return False, None, "No bottle selected"

        if not manual_session.tasting_data:
            return False, None, "No tasting data provided"

        # Convert to TastingNote
        tasting_note = self._manual_session_to_tasting_note(manual_session)

        # Find bottle folder
        full_bottle_path = self.vault_path / manual_session.selected_bottle_path
        if not full_bottle_path.exists():
            return False, None, f"Bottle folder not found: {manual_session.selected_bottle_path}"

        # Create bottle match from path
        from reserve_automation.core.models import BottleMetadata
        from reserve_automation.utils.bottle_matcher import BottleMatch

        # Get bottle name from folder
        bottle_name = full_bottle_path.name

        # Try to find existing match for metadata
        matches = self.bottle_matcher.find_matches(
            bottle_name=bottle_name,
            beverage_type=manual_session.beverage_type,
            top_n=1,
            min_score=0.0
        )

        if matches and len(matches) > 0:
            match = matches[0]
            match.folder_path = full_bottle_path
        else:
            # Create synthetic match if bottle not found in cache
            bottle_meta = BottleMetadata(
                producer="",
                name=bottle_name,
                type=manual_session.beverage_type,
                source="manual_tasting"
            )
            match = BottleMatch(bottle_meta, 1.0, full_bottle_path)

        # Generate and save tasting file
        try:
            file_path = self.tasting_generator.generate_tasting_file(
                tasting=tasting_note,
                bottle_match=match,
                dry_run=False
            )

            rel_path = str(file_path.relative_to(self.vault_path))
            logger.info(f"Saved manual tasting to: {rel_path}")

            # Invalidate bottle cache after saving
            self.invalidate_bottle_cache(manual_session.beverage_type)

            return True, rel_path, None
        except Exception as e:
            logger.error(f"Failed to generate tasting file: {e}", exc_info=True)
            return False, None, str(e)

    async def save_manual_tasting_direct(
        self,
        taster_name: str,
        tasting_date: str,
        beverage_type: str,
        selected_bottle_path: str,
        tasting_data: dict,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """
        Save a manual tasting directly (no session required).

        This is the sessionless version - all data is passed directly.

        Args:
            taster_name: Name of the taster
            tasting_date: Date of tasting (YYYY-MM-DD)
            beverage_type: "wine" or "whiskey"
            selected_bottle_path: Relative path to bottle folder in vault
            tasting_data: Dict containing scores and notes

        Returns:
            Tuple of (success, file_path, error_message)
        """
        from ..schemas.tasting import TastingData

        # Validate required fields
        if not taster_name:
            return False, None, "Missing taster name"
        if not tasting_date:
            return False, None, "Missing tasting date"
        if not selected_bottle_path:
            return False, None, "No bottle selected"

        # Find bottle folder
        full_bottle_path = self.vault_path / selected_bottle_path
        if not full_bottle_path.exists():
            return False, None, f"Bottle folder not found: {selected_bottle_path}"

        # Get bottle name from path
        bottle_name = full_bottle_path.name

        # Build TastingData
        tasting_data_dict = {
            'bottle_name': bottle_name,
            'taster_name': taster_name,
            'tasting_date': tasting_date,
            'beverage_type': beverage_type,
            **(tasting_data or {})
        }
        tasting_data_obj = TastingData(**tasting_data_dict)

        # Parse date
        tasting_date_parsed = datetime.fromisoformat(tasting_date)

        # Create TastingNote
        tasting_note = TastingNote(
            bottle_name=bottle_name,
            taster_name=taster_name,
            tasting_date=tasting_date_parsed,
            beverage_type=beverage_type,
            wine_appearance=tasting_data_obj.wine_appearance,
            wine_aroma=tasting_data_obj.wine_aroma,
            wine_taste=tasting_data_obj.wine_taste,
            wine_aftertaste=tasting_data_obj.wine_aftertaste,
            wine_overall=tasting_data_obj.wine_overall,
            whiskey_nose=tasting_data_obj.whiskey_nose,
            whiskey_palate=tasting_data_obj.whiskey_palate,
            whiskey_finish=tasting_data_obj.whiskey_finish,
            whiskey_overall=tasting_data_obj.whiskey_overall,
            days_from_crack=tasting_data_obj.days_from_crack,
            fill_level=tasting_data_obj.fill_level,
            color=tasting_data_obj.color,
            place=tasting_data_obj.place,
            theme=tasting_data_obj.theme,
            appearance_notes=tasting_data_obj.appearance_notes or [],
            nose_notes=tasting_data_obj.nose_notes or [],
            palate_notes=tasting_data_obj.palate_notes or [],
            finish_notes=tasting_data_obj.finish_notes or [],
            overall_notes=tasting_data_obj.overall_notes
        )

        # Create bottle match for file generation
        from reserve_automation.core.models import BottleMetadata
        from reserve_automation.utils.bottle_matcher import BottleMatch

        # Try to find existing match for metadata
        matches = self.bottle_matcher.find_matches(
            bottle_name=bottle_name,
            beverage_type=beverage_type,
            top_n=1,
            min_score=0.0
        )

        if matches and len(matches) > 0:
            match = matches[0]
            match.folder_path = full_bottle_path
        else:
            # Create synthetic match if bottle not found in cache
            bottle_meta = BottleMetadata(
                producer="",
                name=bottle_name,
                type=beverage_type,
                source="manual_tasting"
            )
            match = BottleMatch(bottle_meta, 1.0, full_bottle_path)

        # Generate and save tasting file
        try:
            file_path = self.tasting_generator.generate_tasting_file(
                tasting=tasting_note,
                bottle_match=match,
                dry_run=False
            )

            rel_path = str(file_path.relative_to(self.vault_path))
            logger.info(f"Saved manual tasting to: {rel_path}")

            # Invalidate bottle cache after saving
            self.invalidate_bottle_cache(beverage_type)

            return True, rel_path, None
        except Exception as e:
            logger.error(f"Failed to generate tasting file: {e}", exc_info=True)
            return False, None, str(e)

    def _manual_session_to_tasting_note(self, manual_session) -> TastingNote:
        """
        Convert ManualTastingSession to TastingNote.

        Args:
            manual_session: ManualTastingSession object

        Returns:
            TastingNote object
        """
        from ..schemas.tasting import TastingData

        # Get tasting data
        tasting_data = manual_session.tasting_data
        if isinstance(tasting_data, dict):
            # Merge session-level fields with form data
            bottle_name = manual_session.selected_bottle_path.split('/')[-1] if manual_session.selected_bottle_path else ""
            tasting_data_dict = {
                'bottle_name': bottle_name,
                'taster_name': manual_session.taster_name,
                'tasting_date': manual_session.tasting_date,
                'beverage_type': manual_session.beverage_type,
                **tasting_data  # Add the form fields (scores, notes, etc.)
            }
            tasting_data = TastingData(**tasting_data_dict)

        # Parse date
        if isinstance(manual_session.tasting_date, str):
            tasting_date = datetime.fromisoformat(manual_session.tasting_date)
        else:
            tasting_date = manual_session.tasting_date

        # Get bottle name from path
        bottle_name = manual_session.selected_bottle_path.split('/')[-1]

        return TastingNote(
            bottle_name=bottle_name,
            taster_name=manual_session.taster_name,
            tasting_date=tasting_date,
            beverage_type=manual_session.beverage_type,
            wine_appearance=tasting_data.wine_appearance,
            wine_aroma=tasting_data.wine_aroma,
            wine_taste=tasting_data.wine_taste,
            wine_aftertaste=tasting_data.wine_aftertaste,
            wine_overall=tasting_data.wine_overall,
            whiskey_nose=tasting_data.whiskey_nose,
            whiskey_palate=tasting_data.whiskey_palate,
            whiskey_finish=tasting_data.whiskey_finish,
            whiskey_overall=tasting_data.whiskey_overall,
            days_from_crack=tasting_data.days_from_crack,
            fill_level=tasting_data.fill_level,
            color=tasting_data.color,
            place=tasting_data.place,
            theme=tasting_data.theme,
            appearance_notes=tasting_data.appearance_notes or [],
            nose_notes=tasting_data.nose_notes or [],
            palate_notes=tasting_data.palate_notes or [],
            finish_notes=tasting_data.finish_notes or [],
            overall_notes=tasting_data.overall_notes
        )
