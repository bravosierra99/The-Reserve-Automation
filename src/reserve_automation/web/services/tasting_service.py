"""Service for tasting extraction, matching, and management."""

from datetime import datetime
from typing import Optional

from loguru import logger

from reserve_automation.core.tasting_note import TastingExtractionResult, TastingNote

from ..schemas.tasting import (
    MatchCandidate,
    TastingData,
    TastingSession,
    TastingSessionItem,
    TastingStatus,
)

_AUTO_SELECT_THRESHOLD = 0.8
_PERFECT_MATCH_CONFIDENCE = 1.0
_PARTIAL_MATCH_CONFIDENCE = 0.8


class TastingService:
    """Service for managing tasting extraction and review workflow."""

    def __init__(self, config_or_bottle_repo, tasting_repo=None):
        """
        Initialize tasting service.

        Supports two modes:
        1. Legacy: TastingService(core_config) - for session/extraction workflow
        2. DB mode: TastingService(bottle_repo, tasting_repo) - for DB operations

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
            self.vault_path = config_or_bottle_repo.vault_path if config_or_bottle_repo else None
            self.bottle_repo = None
            self.tasting_repo = None

    def create_session_from_extraction(
        self,
        extraction_id: str,
        extraction_result: TastingExtractionResult,
        expected_count: Optional[int] = None,
        upload_filename: Optional[str] = None,
        event_id: Optional[str] = None
    ) -> TastingSession:
        """Create a TastingSession from an extraction result."""
        logger.info(f"Creating tasting session {extraction_id} with {len(extraction_result.tastings)} tastings")

        tastings = []
        for i, tasting in enumerate(extraction_result.tastings):
            try:
                logger.debug(f"Processing tasting {i}: {tasting.bottle_name}")
                tasting_data = self._tasting_note_to_data(tasting)
            except Exception as e:
                logger.error(f"Failed to convert tasting {i} to TastingData: {e}", exc_info=True)
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
            if match_candidates and match_candidates[0].confidence >= _AUTO_SELECT_THRESHOLD:
                selected_match = match_candidates[0].bottle_path

            # Check for duplicate tasting
            duplicate_warning = None
            if selected_match:
                duplicate_warning = self.check_duplicate_tasting(
                    bottle_path=selected_match,
                    taster=tasting.taster_name,
                    tasting_date=tasting.tasting_date
                )

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
        """Get potential bottle matches for a tasting using DB search."""
        logger.debug(f"Finding matches for: {bottle_name} ({beverage_type}, event_id={event_id})")

        # If event_id provided, search event bottles
        if event_id:
            return self._search_event_bottles(bottle_name, beverage_type, event_id, limit)

        # Use bottle_repo for DB search
        if self.bottle_repo:
            bottles = self.bottle_repo.search(bottle_name)
            candidates = []
            for bottle in bottles[:limit]:
                # Simple confidence based on name similarity
                from difflib import SequenceMatcher
                full_name = f"{bottle.producer} - {bottle.name}"
                confidence = SequenceMatcher(None, bottle_name.lower(), full_name.lower()).ratio()

                thumbnail_url = f"/api/v1/bottle-label/{bottle.id}" if bottle.label_image_url else None

                candidate = MatchCandidate(
                    bottle_path=str(bottle.id),  # Use DB ID as path
                    bottle_name=full_name,
                    producer=bottle.producer or "",
                    vintage=bottle.year,
                    confidence=confidence,
                    thumbnail_url=thumbnail_url,
                    beverage_type=bottle.type or beverage_type
                )
                candidates.append(candidate)

            candidates.sort(key=lambda x: x.confidence, reverse=True)
            return candidates[:limit]

        # Fallback to vault-based matching if no repo
        if self.vault_path:
            from reserve_automation.utils.bottle_matcher import BottleMatcher
            bottle_matcher = BottleMatcher(self.vault_path)
            matches = bottle_matcher.find_matches(
                bottle_name=bottle_name,
                beverage_type=beverage_type,
                top_n=limit,
                min_score=0.3
            )

            candidates = []
            for match in matches:
                bottle_path = match.bottle.vault_path or ""
                if not bottle_path:
                    continue

                thumbnail_url = None
                label_path = self.vault_path / bottle_path / "labels" / "label.jpg"
                if label_path.exists():
                    thumbnail_url = f"/api/v1/vault-images/{beverage_type}/{bottle_path.split('/')[-1]}/label.jpg"

                candidate = MatchCandidate(
                    bottle_path=bottle_path,
                    bottle_name=self._get_full_name_from_match(match),
                    producer=match.bottle.producer or "",
                    vintage=match.bottle.year,
                    confidence=match.score,
                    thumbnail_url=thumbnail_url,
                    beverage_type=beverage_type
                )
                candidates.append(candidate)

            return candidates

        return []

    def _search_event_bottles(self, bottle_name, beverage_type, event_id, limit):
        """Search for bottles within an event."""
        from ...db.engine import get_db

        # Try to get event from DB
        try:
            db = next(get_db())
            from ...db.repositories.event_repo import SQLiteEventRepository
            event_repo = SQLiteEventRepository(db)
            event = event_repo.get_by_id(event_id)
            if not event:
                return []

            event_bottles = event.get("bottles", [])
            candidates = []
            for bottle in event_bottles:
                if bottle_name.lower() in bottle.get("bottle_name", "").lower():
                    display_name = bottle["bottle_name"]
                    if event.get("is_blind") and event.get("status") == "open" and bottle.get("blind_number"):
                        display_name = f"Bottle #{bottle['blind_number']}"

                    candidate = MatchCandidate(
                        bottle_path=bottle.get("bottle_id", bottle.get("bottle_path", "")),
                        bottle_name=display_name,
                        producer="",
                        confidence=_PERFECT_MATCH_CONFIDENCE if bottle_name.lower() == bottle.get("bottle_name", "").lower() else _PARTIAL_MATCH_CONFIDENCE,
                        thumbnail_url=None,
                        beverage_type=beverage_type
                    )
                    candidates.append(candidate)

            candidates.sort(key=lambda x: x.confidence, reverse=True)
            return candidates[:limit]
        except Exception as e:
            logger.warning(f"Failed to search event bottles: {e}")
            return []

    def search_bottles(
        self,
        query: str,
        beverage_type: Optional[str] = None,
        limit: int = 10,
        strict: bool = True,
        event_id: Optional[str] = None
    ) -> list[MatchCandidate]:
        """Search for bottles by name using DB."""
        logger.info(f"Searching bottles: '{query}' (type={beverage_type}, event_id={event_id})")

        if event_id:
            return self._search_event_bottles(query, beverage_type or "unknown", event_id, limit)

        if self.bottle_repo:
            bottles = self.bottle_repo.search(query)
            results = []
            for bottle in bottles[:limit]:
                from difflib import SequenceMatcher
                full_name = f"{bottle.producer} - {bottle.name}"
                confidence = SequenceMatcher(None, query.lower(), full_name.lower()).ratio()

                thumbnail_url = f"/api/v1/bottle-label/{bottle.id}" if bottle.label_image_url else None

                candidate = MatchCandidate(
                    bottle_path=str(bottle.id),
                    bottle_name=full_name,
                    producer=bottle.producer or "",
                    vintage=bottle.year,
                    confidence=confidence,
                    thumbnail_url=thumbnail_url,
                    beverage_type=bottle.type or beverage_type or "unknown"
                )
                results.append(candidate)

            results.sort(key=lambda x: x.confidence, reverse=True)
            return results[:limit]

        # Fallback to vault
        if self.vault_path:
            from reserve_automation.utils.bottle_matcher import BottleMatcher
            bottle_matcher = BottleMatcher(self.vault_path)
            results = []
            types_to_search = [beverage_type] if beverage_type else ["wine", "whiskey"]
            for bev_type in types_to_search:
                matches = bottle_matcher.find_matches(
                    bottle_name=query, beverage_type=bev_type,
                    top_n=limit, min_score=0.2, strict_substring=strict
                )
                for match in matches:
                    bottle_path = match.bottle.vault_path or ""
                    if not bottle_path:
                        continue
                    thumbnail_url = None
                    label_path = self.vault_path / bottle_path / "labels" / "label.jpg"
                    if label_path.exists():
                        thumbnail_url = f"/api/v1/bottle-label/{bottle_path}"
                    candidate = MatchCandidate(
                        bottle_path=bottle_path,
                        bottle_name=self._get_full_name_from_match(match),
                        producer=match.bottle.producer or "",
                        vintage=match.bottle.year,
                        confidence=match.score,
                        thumbnail_url=thumbnail_url,
                        beverage_type=bev_type
                    )
                    results.append(candidate)
            results.sort(key=lambda x: x.confidence, reverse=True)
            return results[:limit]

        return []

    def check_duplicate_tasting(
        self,
        bottle_path: str,
        taster: str,
        tasting_date: datetime
    ) -> Optional[str]:
        """Check if a tasting already exists for this bottle/taster/date combo."""
        if self.tasting_repo:
            try:
                bottle_id = int(bottle_path)
                date_str = tasting_date.strftime("%Y-%m-%d") if isinstance(tasting_date, datetime) else str(tasting_date)[:10]
                if self.tasting_repo.check_duplicate(bottle_id, taster, date_str):
                    return f"A tasting by {taster} on {date_str} may already exist"
            except (ValueError, TypeError):
                pass
            return None

        # Fallback to vault check
        if self.vault_path:
            full_path = self.vault_path / bottle_path
            if not full_path.exists():
                return None

            date_str = tasting_date.strftime("%Y-%m-%d") if isinstance(tasting_date, datetime) else str(tasting_date)[:10]
            for tasting_file in full_path.glob("tasting-*.md"):
                content = tasting_file.read_text()
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
        """Save a single tasting to the DB or event store."""
        logger.info(f"Saving tasting to {bottle_path} (event_id={event_id})")

        # If event_id provided, save to event store
        if event_id:
            return await self._save_to_event(tasting_item, bottle_path, event_id, participant_id)

        # Save to DB via tasting_repo
        if self.tasting_repo and self.bottle_repo:
            try:
                bottle_id = int(bottle_path)
                bottle = self.bottle_repo.get_by_id(bottle_id)
                if not bottle:
                    return False, None, f"Bottle not found: {bottle_path}"

                tasting_note = self._data_to_tasting_note(tasting_item.tasting_data)
                tasting_note.bottle_name = f"{bottle.producer} - {bottle.name}"

                created = self.tasting_repo.create(tasting_note, bottle_id)
                logger.info(f"Saved tasting to DB: id={created.id}")
                return True, str(created.id), None

            except Exception as e:
                logger.error(f"Failed to save tasting to DB: {e}", exc_info=True)
                return False, None, str(e)

        # Fallback to vault
        if self.vault_path:
            try:
                from reserve_automation.core.models import BottleMetadata
                from reserve_automation.generators.tasting_generator import TastingGenerator
                from reserve_automation.utils.bottle_matcher import BottleMatch, BottleMatcher

                tasting_note = self._data_to_tasting_note(tasting_item.tasting_data)
                full_bottle_path = self.vault_path / bottle_path
                if not full_bottle_path.exists():
                    return False, None, f"Bottle folder not found: {bottle_path}"

                bottle_matcher = BottleMatcher(self.vault_path)
                matches = bottle_matcher.find_matches(
                    bottle_name=full_bottle_path.name,
                    beverage_type=tasting_item.tasting_data.beverage_type,
                    top_n=1, min_score=0.0
                )

                if matches:
                    match = matches[0]
                    match.folder_path = full_bottle_path
                else:
                    bottle_meta = BottleMetadata(
                        producer="", name=full_bottle_path.name,
                        type=tasting_item.tasting_data.beverage_type
                    )
                    match = BottleMatch(bottle_meta, 1.0, full_bottle_path)

                tasting_generator = TastingGenerator(
                    vault_path=self.vault_path,
                    templates_path=self.config.templates_dir if self.config else None
                )
                file_path = tasting_generator.generate_tasting_file(
                    tasting=tasting_note, bottle_match=match, dry_run=False
                )
                rel_path = str(file_path.relative_to(self.vault_path))
                return True, rel_path, None

            except Exception as e:
                logger.error(f"Failed to save tasting: {e}", exc_info=True)
                return False, None, str(e)

        return False, None, "No storage backend available"

    async def _save_to_event(self, tasting_item, bottle_path, event_id, participant_id):
        """Save tasting to event store."""
        try:
            from ...db.engine import get_db
            from ...db.repositories.event_repo import SQLiteEventRepository

            db = next(get_db())
            event_repo = SQLiteEventRepository(db)
            event = event_repo.get_by_id(event_id)

            if not event:
                return False, None, "Event not found"
            if not participant_id:
                return False, None, "Participant ID required for event tastings"
            if participant_id not in event.get("participants", {}):
                return False, None, "Participant not found in event"

            participant = event["participants"][participant_id]
            if any(t.get("bottle_path") == bottle_path for t in participant.get("tastings", [])):
                return False, None, "You have already tasted this bottle"

            participant.setdefault("tastings", []).append({
                "bottle_path": bottle_path,
                "tasting_data": tasting_item.tasting_data.dict()
            })
            event_repo.update(event_id, event)

            logger.info(f"Saved tasting to event {event_id} for participant {participant_id}")
            return True, f"event:{event_id}", None

        except Exception as e:
            logger.error(f"Failed to save event tasting: {e}", exc_info=True)
            return False, None, str(e)

    async def save_manual_tasting_direct(
        self,
        taster_name: str,
        tasting_date: str,
        beverage_type: str,
        selected_bottle_path: str,
        tasting_data: dict,
    ) -> tuple[bool, Optional[str], Optional[str]]:
        """Save a manual tasting directly (no session required)."""
        from ..schemas.tasting import TastingData as TastingDataSchema

        if not taster_name:
            return False, None, "Missing taster name"
        if not tasting_date:
            return False, None, "Missing tasting date"
        if not selected_bottle_path:
            return False, None, "No bottle selected"

        # DB mode
        if self.bottle_repo and self.tasting_repo:
            try:
                bottle_id = int(selected_bottle_path)
                bottle = self.bottle_repo.get_by_id(bottle_id)
                if not bottle:
                    return False, None, f"Bottle not found: {selected_bottle_path}"

                bottle_name = f"{bottle.producer} - {bottle.name}"

                tasting_data_dict = {
                    'bottle_name': bottle_name,
                    'taster_name': taster_name,
                    'tasting_date': tasting_date,
                    'beverage_type': beverage_type,
                    **(tasting_data or {})
                }
                tasting_data_obj = TastingDataSchema(**tasting_data_dict)
                tasting_date_parsed = datetime.fromisoformat(tasting_date)

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

                created = self.tasting_repo.create(tasting_note, bottle_id)
                logger.info(f"Saved manual tasting to DB: id={created.id}")
                return True, str(created.id), None

            except Exception as e:
                logger.error(f"Failed to save manual tasting to DB: {e}", exc_info=True)
                return False, None, str(e)

        # Fallback to vault
        if self.vault_path:
            from reserve_automation.core.models import BottleMetadata
            from reserve_automation.generators.tasting_generator import TastingGenerator
            from reserve_automation.utils.bottle_matcher import BottleMatch, BottleMatcher

            full_bottle_path = self.vault_path / selected_bottle_path
            if not full_bottle_path.exists():
                return False, None, f"Bottle folder not found: {selected_bottle_path}"

            bottle_name = full_bottle_path.name
            tasting_data_dict = {
                'bottle_name': bottle_name,
                'taster_name': taster_name,
                'tasting_date': tasting_date,
                'beverage_type': beverage_type,
                **(tasting_data or {})
            }
            tasting_data_obj = TastingDataSchema(**tasting_data_dict)
            tasting_date_parsed = datetime.fromisoformat(tasting_date)

            tasting_note = TastingNote(
                bottle_name=bottle_name, taster_name=taster_name,
                tasting_date=tasting_date_parsed, beverage_type=beverage_type,
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
                color=tasting_data_obj.color, place=tasting_data_obj.place,
                theme=tasting_data_obj.theme,
                appearance_notes=tasting_data_obj.appearance_notes or [],
                nose_notes=tasting_data_obj.nose_notes or [],
                palate_notes=tasting_data_obj.palate_notes or [],
                finish_notes=tasting_data_obj.finish_notes or [],
                overall_notes=tasting_data_obj.overall_notes
            )

            bottle_matcher = BottleMatcher(self.vault_path)
            matches = bottle_matcher.find_matches(
                bottle_name=bottle_name, beverage_type=beverage_type,
                top_n=1, min_score=0.0
            )
            if matches:
                match = matches[0]
                match.folder_path = full_bottle_path
            else:
                bottle_meta = BottleMetadata(
                    producer="", name=bottle_name,
                    type=beverage_type, source="manual_tasting"
                )
                match = BottleMatch(bottle_meta, 1.0, full_bottle_path)

            try:
                tasting_generator = TastingGenerator(
                    vault_path=self.vault_path,
                    templates_path=self.config.templates_dir if self.config else None
                )
                file_path = tasting_generator.generate_tasting_file(
                    tasting=tasting_note, bottle_match=match, dry_run=False
                )
                rel_path = str(file_path.relative_to(self.vault_path))
                return True, rel_path, None
            except Exception as e:
                logger.error(f"Failed to generate tasting file: {e}", exc_info=True)
                return False, None, str(e)

        return False, None, "No storage backend available"

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
            appearance_notes=tasting.appearance_notes or [],
            nose_notes=tasting.nose_notes or [],
            palate_notes=tasting.palate_notes or [],
            finish_notes=tasting.finish_notes or [],
            overall_notes=tasting.overall_notes
        )

    def _data_to_tasting_note(self, data: TastingData) -> TastingNote:
        """Convert TastingData back to TastingNote for saving."""
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

    def _get_full_name_from_match(self, match) -> str:
        """Get full bottle name from a BottleMatch."""
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
