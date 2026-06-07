"""Unit tests for TastingService covering edge paths and mode-switching."""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_service_db_mode(bottle_repo=None, tasting_repo=None):
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
    from reserve_automation.web.services.tasting_service import TastingService

    bottle_repo = bottle_repo or MagicMock(spec=SQLiteBottleRepository)
    tasting_repo = tasting_repo or MagicMock()
    return TastingService(bottle_repo, tasting_repo)


def _make_service_legacy_mode(vault_path=None):
    from reserve_automation.web.services.tasting_service import TastingService

    config = MagicMock()
    config.vault_path = vault_path
    return TastingService(config)


def _make_extraction_result(bottle_name="Weller Special Reserve", taster="Tester"):
    from reserve_automation.core.tasting_note import TastingExtractionResult, TastingNote

    note = TastingNote(
        bottle_name=bottle_name,
        taster_name=taster,
        tasting_date=datetime(2025, 1, 1),
        beverage_type="whiskey",
    )
    return TastingExtractionResult(tastings=[note], template_type="bourbon")


def _make_session_item():
    from reserve_automation.web.schemas.tasting import (
        TastingData,
        TastingSessionItem,
        TastingStatus,
    )

    tasting_data = TastingData(
        bottle_name="Weller Special Reserve",
        taster_name="Tester",
        tasting_date="2025-01-01",
        beverage_type="whiskey",
    )
    return TastingSessionItem(
        index=0,
        status=TastingStatus.EXTRACTED,
        tasting_data=tasting_data,
        match_candidates=[],
        selected_match=None,
    )


# ---------------------------------------------------------------------------
# 1. Constructor modes
# ---------------------------------------------------------------------------

class TestTastingServiceInitModes:
    def test_db_mode(self):
        from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
        bottle_repo = MagicMock(spec=SQLiteBottleRepository)
        tasting_repo = MagicMock()
        svc = _make_service_db_mode(bottle_repo, tasting_repo)

        assert svc.bottle_repo is bottle_repo
        assert svc.tasting_repo is tasting_repo
        assert svc.config is None
        assert svc.vault_path is None

    def test_legacy_mode_vault_path_inherited(self):
        fake_vault = Path("/tmp/fake-vault")
        svc = _make_service_legacy_mode(vault_path=fake_vault)

        assert svc.config is not None
        assert svc.bottle_repo is None
        assert svc.vault_path == fake_vault

    def test_legacy_mode_no_vault(self):
        svc = _make_service_legacy_mode(vault_path=None)

        assert svc.config is not None
        assert svc.vault_path is None


# ---------------------------------------------------------------------------
# 2. create_session_from_extraction — conversion error propagates
# ---------------------------------------------------------------------------

class TestCreateSessionFromExtraction:
    def test_conversion_error_propagates(self):
        svc = _make_service_db_mode()
        extraction = _make_extraction_result()

        with patch.object(svc, "_tasting_note_to_data", side_effect=ValueError("bad data")):
            with pytest.raises(ValueError, match="bad data"):
                svc.create_session_from_extraction("xid", extraction)

    def test_auto_selects_high_confidence_match(self):
        from reserve_automation.web.schemas.tasting import MatchCandidate

        svc = _make_service_db_mode()
        extraction = _make_extraction_result()

        high_conf = MatchCandidate(
            bottle_path="42",
            bottle_name="Weller Special Reserve",
            producer="Buffalo Trace",
            confidence=0.95,
            beverage_type="whiskey",
        )
        with patch.object(svc, "get_match_candidates", return_value=[high_conf]):
            with patch.object(svc, "check_duplicate_tasting", return_value=None):
                session = svc.create_session_from_extraction("xid", extraction)

        assert session.tastings[0].selected_match == "42"

    def test_no_auto_select_below_threshold(self):
        from reserve_automation.web.schemas.tasting import MatchCandidate

        svc = _make_service_db_mode()
        extraction = _make_extraction_result()

        low_conf = MatchCandidate(
            bottle_path="42",
            bottle_name="Weller Special Reserve",
            producer="Buffalo Trace",
            confidence=0.5,
            beverage_type="whiskey",
        )
        with patch.object(svc, "get_match_candidates", return_value=[low_conf]):
            session = svc.create_session_from_extraction("xid", extraction)

        assert session.tastings[0].selected_match is None


# ---------------------------------------------------------------------------
# 3. _save_to_event — three error paths
# ---------------------------------------------------------------------------

class TestSaveToEventMode:
    @pytest.mark.asyncio
    async def test_event_not_found(self):
        svc = _make_service_db_mode()
        item = _make_session_item()

        with patch("reserve_automation.web.services.tasting_service.TastingService._save_to_event",
                   new_callable=AsyncMock) as mock_save:
            mock_save.return_value = (False, None, "Event not found")
            ok, path, err = await svc.save_tasting(item, "42", event_id="no-such-event", participant_id="pid")

        assert not ok
        assert err == "Event not found"

    @pytest.mark.asyncio
    async def test_participant_id_missing(self):
        svc = _make_service_db_mode()
        item = _make_session_item()

        mock_event = {"participants": {"pid": {"tastings": []}}, "bottles": []}

        with patch("reserve_automation.db.repositories.event_repo.SQLiteEventRepository") as MockRepo:
            MockRepo.return_value.get.return_value = mock_event
            with patch("reserve_automation.db.engine.get_db") as mock_get_db:
                mock_get_db.return_value = iter([MagicMock()])
                ok, path, err = await svc._save_to_event(item, "42", "evt-id", participant_id=None)

        assert not ok
        assert err == "Participant ID required for event tastings"

    @pytest.mark.asyncio
    async def test_participant_not_in_event(self):
        svc = _make_service_db_mode()
        item = _make_session_item()

        mock_event = {"participants": {"other-pid": {"tastings": []}}, "bottles": []}

        with patch("reserve_automation.db.repositories.event_repo.SQLiteEventRepository") as MockRepo:
            MockRepo.return_value.get.return_value = mock_event
            with patch("reserve_automation.db.engine.get_db") as mock_get_db:
                mock_get_db.return_value = iter([MagicMock()])
                ok, path, err = await svc._save_to_event(item, "42", "evt-id", participant_id="unknown-pid")

        assert not ok
        assert err == "Participant not found in event"


# ---------------------------------------------------------------------------
# 4. TastingExtractor.extract_from_image — template detection routing
# ---------------------------------------------------------------------------

class TestExtractFromImageTemplateDetection:
    @pytest.mark.asyncio
    async def test_aws_wine_template_routes_correctly(self, tmp_path):
        from reserve_automation.core.tasting_note import TastingExtractionResult
        from reserve_automation.extractors.tasting_extractor import TastingExtractor

        image = tmp_path / "card.jpg"
        image.write_bytes(b"fake")

        llm = MagicMock()
        llm.complete = AsyncMock(return_value=MagicMock(content="aws_wine"))
        extractor = TastingExtractor(llm)

        dummy_result = TastingExtractionResult(tastings=[], template_type="aws_wine")
        with patch.object(extractor, "_extract_aws_wine", new_callable=AsyncMock, return_value=dummy_result) as mock_aws:
            result = await extractor.extract_from_image(image)

        mock_aws.assert_called_once()
        assert result.template_type == "aws_wine"

    @pytest.mark.asyncio
    async def test_bourbon_template_routes_correctly(self, tmp_path):
        from reserve_automation.core.tasting_note import TastingExtractionResult
        from reserve_automation.extractors.tasting_extractor import TastingExtractor

        image = tmp_path / "card.jpg"
        image.write_bytes(b"fake")

        llm = MagicMock()
        llm.complete = AsyncMock(return_value=MagicMock(content="bourbon"))
        extractor = TastingExtractor(llm)

        dummy_result = TastingExtractionResult(tastings=[], template_type="bourbon")
        with patch.object(extractor, "_extract_bourbon", new_callable=AsyncMock, return_value=dummy_result) as mock_bourbon:
            result = await extractor.extract_from_image(image)

        mock_bourbon.assert_called_once()
        assert result.template_type == "bourbon"


# ---------------------------------------------------------------------------
# 5. TastingExtractor._extract_aws_wine — OCR failure fallback
# ---------------------------------------------------------------------------

class TestExtractAwsWineOcrFailure:
    @pytest.mark.asyncio
    async def test_ocr_failure_falls_back_to_llm(self, tmp_path):
        from reserve_automation.core.tasting_note import TastingExtractionResult
        from reserve_automation.extractors.tasting_extractor import TastingExtractor

        image = tmp_path / "card.jpg"
        image.write_bytes(b"fake")

        llm = MagicMock()
        extractor = TastingExtractor(llm)

        fallback_result = TastingExtractionResult(tastings=[], template_type="aws_wine")

        with patch("reserve_automation.extractors.tasting_extractor.detect_table_structure",
                   side_effect=RuntimeError("OCR failed")):
            with patch.object(extractor, "_extract_aws_wine_llm",
                              new_callable=AsyncMock, return_value=fallback_result) as mock_llm:
                result = await extractor._extract_aws_wine(image)

        mock_llm.assert_called_once_with(image)
        assert result is fallback_result


# ---------------------------------------------------------------------------
# 6. get_match_candidates — vault fallback when no bottle_repo
# ---------------------------------------------------------------------------

class TestGetMatchCandidatesVaultFallback:
    def test_uses_bottle_matcher_when_no_repo(self, tmp_path):
        svc = _make_service_legacy_mode(vault_path=tmp_path)

        mock_match = MagicMock()
        mock_match.bottle.vault_path = "whiskey/Weller"
        mock_match.bottle.producer = "Buffalo Trace"
        mock_match.bottle.year = None
        mock_match.score = 0.9

        with patch("reserve_automation.utils.bottle_matcher.BottleMatcher") as MockMatcher:
            MockMatcher.return_value.find_matches.return_value = [mock_match]
            with patch.object(svc, "_get_full_name_from_match", return_value="Buffalo Trace - Weller"):
                candidates = svc.get_match_candidates("Weller", "whiskey")

        MockMatcher.assert_called_once_with(tmp_path)
        assert len(candidates) == 1
        assert candidates[0].confidence == 0.9


# ---------------------------------------------------------------------------
# 7. search_bottles — routes through event search when event_id provided
# ---------------------------------------------------------------------------

class TestSearchBottlesWithEventId:
    def test_routes_to_event_search(self):
        svc = _make_service_db_mode()

        with patch.object(svc, "_search_event_bottles", return_value=[]) as mock_event_search:
            svc.search_bottles("Weller", beverage_type="whiskey", event_id="evt-123")

        mock_event_search.assert_called_once_with("Weller", "whiskey", "evt-123", 10)


# ---------------------------------------------------------------------------
# 8. check_duplicate_tasting — non-integer bottle_path is handled gracefully
# ---------------------------------------------------------------------------

class TestCheckDuplicateTastingExceptions:
    def test_non_integer_bottle_path_returns_none(self):
        svc = _make_service_db_mode()
        # Non-integer path triggers ValueError in int() — should be caught and return None
        result = svc.check_duplicate_tasting(
            bottle_path="some/vault/path",
            taster="Tester",
            tasting_date=datetime(2025, 1, 1),
        )
        assert result is None

    def test_valid_integer_path_checks_repo(self):
        tasting_repo = MagicMock()
        tasting_repo.check_duplicate.return_value = True
        svc = _make_service_db_mode(tasting_repo=tasting_repo)

        result = svc.check_duplicate_tasting(
            bottle_path="42",
            taster="Tester",
            tasting_date=datetime(2025, 1, 1),
        )

        tasting_repo.check_duplicate.assert_called_once()
        assert result is not None


# ---------------------------------------------------------------------------
# 9. save_manual_tasting_direct — input validation
# ---------------------------------------------------------------------------

class TestSaveManualTastingDirectValidation:
    @pytest.mark.asyncio
    async def test_missing_taster_name(self):
        svc = _make_service_db_mode()
        ok, _, err = await svc.save_manual_tasting_direct(
            taster_name="",
            tasting_date="2025-01-01",
            beverage_type="whiskey",
            selected_bottle_path="42",
            tasting_data={},
        )
        assert not ok
        assert err == "Missing taster name"

    @pytest.mark.asyncio
    async def test_missing_tasting_date(self):
        svc = _make_service_db_mode()
        ok, _, err = await svc.save_manual_tasting_direct(
            taster_name="Tester",
            tasting_date="",
            beverage_type="whiskey",
            selected_bottle_path="42",
            tasting_data={},
        )
        assert not ok
        assert err == "Missing tasting date"

    @pytest.mark.asyncio
    async def test_missing_bottle_path(self):
        svc = _make_service_db_mode()
        ok, _, err = await svc.save_manual_tasting_direct(
            taster_name="Tester",
            tasting_date="2025-01-01",
            beverage_type="whiskey",
            selected_bottle_path="",
            tasting_data={},
        )
        assert not ok
        assert err == "No bottle selected"
