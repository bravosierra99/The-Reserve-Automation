"""Unit tests for ReviewService (DB mode).

ReviewService matches extracted tasting notes to stored bottles and persists
them. The DB-mode path (the live one, used by routes/review.py and
routes/management/labels.py) was previously at ~10% coverage despite carrying
real fuzzy-matching and save logic. These tests exercise that path against an
in-memory SQLite DB using the project's real repositories.
"""

from datetime import date

import pytest

from reserve_automation.core.models import BottleMetadata
from reserve_automation.core.tasting_note import (
    TastingExtractionResult,
    TastingNote,
)
from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
from reserve_automation.db.repositories.tasting_repo import SQLiteTastingRepository
from reserve_automation.web.services.review_service import ReviewService


@pytest.fixture
def repos():
    """Real bottle + tasting repositories over the in-memory test DB.

    Seeds two bottles and cleans the bottles/tastings tables on the way in so
    the fixture is independent of other modules' leftovers.
    """
    from reserve_automation.db.engine import get_db
    from reserve_automation.db.models.bottle import BottleModel, TastingNoteModel

    db = next(get_db())
    db.query(TastingNoteModel).delete()
    db.query(BottleModel).delete()
    db.commit()

    bottle_repo = SQLiteBottleRepository(db)
    tasting_repo = SQLiteTastingRepository(db)

    bottle_repo.create(
        BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            year=2019,
            type="wine",
            source="test",
            inventory=1,
        )
    )
    bottle_repo.create(
        BottleMetadata(
            producer="Buffalo Trace",
            name="Kentucky Straight Bourbon",
            year=2021,
            type="whiskey",
            source="test",
            inventory=1,
        )
    )

    yield bottle_repo, tasting_repo

    db.query(TastingNoteModel).delete()
    db.query(BottleModel).delete()
    db.commit()


@pytest.fixture
def service(repos):
    bottle_repo, tasting_repo = repos
    return ReviewService(bottle_repo, tasting_repo)


def _wine_tasting(bottle_name: str, taster: str = "Alice") -> TastingNote:
    return TastingNote(
        bottle_name=bottle_name,
        taster_name=taster,
        tasting_date=date(2026, 6, 7),
        beverage_type="wine",
    )


def test_init_enters_db_mode_with_repo(repos):
    """Passing a real SQLiteBottleRepository selects DB mode, not vault mode."""
    bottle_repo, tasting_repo = repos
    service = ReviewService(bottle_repo, tasting_repo)

    assert service.bottle_repo is bottle_repo
    assert service.tasting_repo is tasting_repo
    assert service.config is None
    assert service.vault_path is None


def test_match_bottle_finds_best_match(service):
    """A recognizable name resolves to the seeded bottle with a real id."""
    match = service._match_bottle(_wine_tasting("Caymus"))

    assert match is not None
    assert match["matched_to"] == "Caymus - Cabernet Sauvignon"
    assert isinstance(match["bottle_id"], int)
    assert 0.0 < match["confidence"] <= 1.0


def test_match_bottle_no_match_returns_none(service):
    """A name that matches no stored bottle returns None (not a crash)."""
    assert service._match_bottle(_wine_tasting("Nonexistent Chateau XYZ")) is None


def test_preview_matches_marks_matched_and_unmatched(service):
    """preview_matches reports matched/unmatched without persisting anything."""
    result = TastingExtractionResult(
        tastings=[
            _wine_tasting("Caymus", taster="Alice"),
            _wine_tasting("Nonexistent Chateau XYZ", taster="Bob"),
        ],
        template_type="aws_wine",
    )

    previews = service.preview_matches(result)

    assert len(previews) == 2
    matched = next(p for p in previews if p["taster_name"] == "Alice")
    unmatched = next(p for p in previews if p["taster_name"] == "Bob")
    assert matched["matched"] is True
    assert matched["matched_to"] == "Caymus - Cabernet Sauvignon"
    assert unmatched["matched"] is False
    assert unmatched["matched_to"] is None
    assert unmatched["confidence"] == 0.0


@pytest.mark.asyncio
async def test_approve_extraction_saves_matched_and_reports_unmatched(service, repos):
    """approve_extraction persists matched tastings and lists unmatched ones."""
    bottle_repo, tasting_repo = repos
    matched_bottle = bottle_repo.search("Caymus")[0]

    result = TastingExtractionResult(
        tastings=[
            _wine_tasting("Caymus", taster="Alice"),
            _wine_tasting("Nonexistent Chateau XYZ", taster="Bob"),
        ],
        template_type="aws_wine",
    )

    outcome = await service.approve_extraction(result)

    # One matched + saved, one unmatched.
    assert len(outcome["files_created"]) == 1
    assert outcome["files_created"][0].startswith("db:")
    assert len(outcome["bottles_matched"]) == 1
    assert outcome["bottles_matched"][0]["matched_to"] == "Caymus - Cabernet Sauvignon"
    assert len(outcome["unmatched"]) == 1
    assert outcome["unmatched"][0]["bottle_name"] == "Nonexistent Chateau XYZ"

    # The matched tasting is actually persisted against the bottle.
    saved = tasting_repo.get_by_bottle_id(int(matched_bottle.id))
    assert len(saved) == 1
    assert saved[0].taster_name == "Alice"
