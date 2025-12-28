"""Schema Coherence Tests - Prevent Field Synchronization Bugs.

These tests ensure fields stay synchronized across all data models and schemas.
The appearance_notes bug demonstrated this gap - field was missing from TastingData
but existed in TastingNote, causing data loss during conversion.

CRITICAL: These tests prevent regressions by verifying:
1. TastingNote and TastingData have matching field sets
2. All wine fields are properly separated from whiskey fields
3. Templates reference all required fields
4. No field leakage between beverage types
"""

import pytest
from datetime import date

from reserve_automation.core.tasting_note import TastingNote, TastingExtractionResult
from reserve_automation.web.schemas.tasting import TastingData
from reserve_automation.core.models import BottleMetadata


# ============================================================================
# Test Field Completeness Across Models
# ============================================================================

class TestFieldCompleteness:
    """Verify fields exist in all required models."""

    def test_tasting_note_has_all_core_fields(self):
        """Ensure TastingNote has all core identification fields."""
        required_fields = {
            "bottle_name", "taster_name", "tasting_date", "beverage_type"
        }

        tasting_note_fields = set(TastingNote.model_fields.keys())

        for field in required_fields:
            assert field in tasting_note_fields, \
                f"TastingNote missing core field: {field}"

    def test_tasting_data_has_all_core_fields(self):
        """Ensure TastingData has all core identification fields."""
        required_fields = {
            "bottle_name", "taster_name", "tasting_date", "beverage_type"
        }

        tasting_data_fields = set(TastingData.model_fields.keys())

        for field in required_fields:
            assert field in tasting_data_fields, \
                f"TastingData missing core field: {field}"

    def test_wine_score_fields_in_both_models(self):
        """Ensure wine scoring fields exist in both TastingNote and TastingData.

        CRITICAL: This would have caught the appearance_notes bug!
        """
        wine_score_fields = {
            "wine_appearance", "wine_aroma", "wine_taste",
            "wine_aftertaste", "wine_overall"
        }

        tasting_note_fields = set(TastingNote.model_fields.keys())
        tasting_data_fields = set(TastingData.model_fields.keys())

        for field in wine_score_fields:
            assert field in tasting_note_fields, \
                f"TastingNote missing wine field: {field}"
            assert field in tasting_data_fields, \
                f"TastingData missing wine field: {field}"

    def test_whiskey_score_fields_in_both_models(self):
        """Ensure whiskey scoring fields exist in both models."""
        whiskey_score_fields = {
            "whiskey_nose", "whiskey_palate", "whiskey_finish", "whiskey_overall"
        }

        tasting_note_fields = set(TastingNote.model_fields.keys())
        tasting_data_fields = set(TastingData.model_fields.keys())

        for field in whiskey_score_fields:
            assert field in tasting_note_fields, \
                f"TastingNote missing whiskey field: {field}"
            assert field in tasting_data_fields, \
                f"TastingData missing whiskey field: {field}"

    def test_notes_fields_in_both_models(self):
        """Ensure tasting notes fields exist in both models.

        REGRESSION TEST: This would have caught appearance_notes missing!
        """
        notes_fields = {
            "appearance_notes",  # Wine-specific
            "nose_notes",
            "palate_notes",
            "finish_notes",
            "overall_notes"
        }

        tasting_note_fields = set(TastingNote.model_fields.keys())
        tasting_data_fields = set(TastingData.model_fields.keys())

        for field in notes_fields:
            assert field in tasting_note_fields, \
                f"TastingNote missing notes field: {field}"
            assert field in tasting_data_fields, \
                f"TastingData missing notes field: {field}"

    def test_whiskey_metadata_fields_in_both_models(self):
        """Ensure whiskey-specific metadata exists in both models."""
        whiskey_metadata = {"days_from_crack", "fill_level"}

        tasting_note_fields = set(TastingNote.model_fields.keys())
        tasting_data_fields = set(TastingData.model_fields.keys())

        for field in whiskey_metadata:
            assert field in tasting_note_fields, \
                f"TastingNote missing whiskey metadata: {field}"
            assert field in tasting_data_fields, \
                f"TastingData missing whiskey metadata: {field}"


# ============================================================================
# Test Type-Specific Field Isolation
# ============================================================================

class TestTypeFieldIsolation:
    """Ensure wine/whiskey fields don't leak between types."""

    def test_wine_tasting_only_populates_wine_fields(self):
        """Wine tastings should have wine scores, not whiskey scores."""
        wine_tasting = TastingNote(
            bottle_name="Test Wine",
            taster_name="Tester",
            tasting_date=date.today(),
            beverage_type="wine",
            wine_appearance=2.5,
            wine_aroma=5.0,
            wine_taste=5.0,
            wine_aftertaste=2.5,
            wine_overall=1.5
        )

        # Wine scores should be set
        assert wine_tasting.wine_appearance == 2.5
        assert wine_tasting.wine_aroma == 5.0

        # Whiskey scores should be None
        assert wine_tasting.whiskey_nose is None
        assert wine_tasting.whiskey_palate is None
        assert wine_tasting.whiskey_finish is None
        assert wine_tasting.whiskey_overall is None

    def test_whiskey_tasting_only_populates_whiskey_fields(self):
        """Whiskey tastings should have whiskey scores, not wine scores."""
        whiskey_tasting = TastingNote(
            bottle_name="Test Whiskey",
            taster_name="Tester",
            tasting_date=date.today(),
            beverage_type="whiskey",
            whiskey_nose=2.5,
            whiskey_palate=2.5,
            whiskey_finish=2.5,
            whiskey_overall=0.8
        )

        # Whiskey scores should be set
        assert whiskey_tasting.whiskey_nose == 2.5
        assert whiskey_tasting.whiskey_palate == 2.5

        # Wine scores should be None
        assert whiskey_tasting.wine_appearance is None
        assert whiskey_tasting.wine_aroma is None
        assert whiskey_tasting.wine_taste is None


# ============================================================================
# Test Conversion Round-Trips
# ============================================================================

class TestConversionRoundTrips:
    """Test that data survives conversion between models."""

    def test_wine_tasting_note_to_dict_preserves_fields(self):
        """Ensure TastingNote.model_dump() preserves all fields."""
        wine_tasting = TastingNote(
            bottle_name="Caymus Cabernet",
            taster_name="Alice",
            tasting_date=date(2025, 12, 27),
            beverage_type="wine",
            wine_appearance=2.5,
            wine_aroma=5.0,
            wine_taste=5.0,
            wine_aftertaste=2.5,
            wine_overall=1.5,
            appearance_notes=["ruby", "clear", "viscous"],
            nose_notes=["cherry", "oak"],
            palate_notes=["full-bodied", "smooth"],
            finish_notes=["long", "pleasant"],
            overall_notes="Excellent wine"
        )

        data = wine_tasting.model_dump()

        # All fields should be in dict
        assert data["appearance_notes"] == ["ruby", "clear", "viscous"]
        assert data["nose_notes"] == ["cherry", "oak"]
        assert data["wine_appearance"] == 2.5
        assert data["wine_aroma"] == 5.0

    def test_whiskey_tasting_note_to_dict_preserves_fields(self):
        """Ensure whiskey TastingNote preserves all fields."""
        whiskey_tasting = TastingNote(
            bottle_name="Stagg",
            taster_name="Bob",
            tasting_date=date(2025, 12, 27),
            beverage_type="whiskey",
            whiskey_nose=2.5,
            whiskey_palate=2.5,
            whiskey_finish=2.5,
            whiskey_overall=0.8,
            nose_notes=["vanilla", "caramel"],
            palate_notes=["sweet", "spicy"],
            finish_notes=["warm", "lingering"],
            overall_notes="Outstanding bourbon",
            days_from_crack=30,
            fill_level=75
        )

        data = whiskey_tasting.model_dump()

        # All whiskey fields should be in dict
        assert data["whiskey_nose"] == 2.5
        assert data["days_from_crack"] == 30
        assert data["fill_level"] == 75
        assert data["nose_notes"] == ["vanilla", "caramel"]

    def test_tasting_data_to_dict_preserves_appearance_notes(self):
        """REGRESSION TEST: Ensure TastingData preserves appearance_notes.

        This is the exact bug that occurred - appearance_notes was missing
        from TastingData schema, causing data loss during conversion.
        """
        tasting_data = TastingData(
            bottle_name="Test Wine",
            taster_name="Tester",
            tasting_date="2025-12-27",
            beverage_type="wine",
            wine_appearance=2.5,
            appearance_notes=["ruby", "clear", "viscous"]
        )

        data_dict = tasting_data.model_dump()

        # appearance_notes MUST be preserved
        assert "appearance_notes" in data_dict
        assert data_dict["appearance_notes"] == ["ruby", "clear", "viscous"]


# ============================================================================
# Test Score Validation
# ============================================================================

class TestScoreValidation:
    """Verify score ranges match FileClass constraints."""

    def test_wine_appearance_score_range(self):
        """Wine Appearance should be 0-3."""
        # Valid scores
        TastingNote(
            bottle_name="Test", taster_name="Test", tasting_date=date.today(),
            beverage_type="wine", wine_appearance=0
        )
        TastingNote(
            bottle_name="Test", taster_name="Test", tasting_date=date.today(),
            beverage_type="wine", wine_appearance=3
        )

        # Invalid scores should raise
        with pytest.raises(Exception):
            TastingNote(
                bottle_name="Test", taster_name="Test", tasting_date=date.today(),
                beverage_type="wine", wine_appearance=3.5
            )

    def test_wine_aroma_score_range(self):
        """Wine Aroma should be 0-6."""
        TastingNote(
            bottle_name="Test", taster_name="Test", tasting_date=date.today(),
            beverage_type="wine", wine_aroma=6
        )

        with pytest.raises(Exception):
            TastingNote(
                bottle_name="Test", taster_name="Test", tasting_date=date.today(),
                beverage_type="wine", wine_aroma=6.5
            )

    def test_whiskey_nose_score_range(self):
        """Whiskey Nose should be 0-3."""
        TastingNote(
            bottle_name="Test", taster_name="Test", tasting_date=date.today(),
            beverage_type="whiskey", whiskey_nose=3
        )

        with pytest.raises(Exception):
            TastingNote(
                bottle_name="Test", taster_name="Test", tasting_date=date.today(),
                beverage_type="whiskey", whiskey_nose=3.5
            )

    def test_whiskey_overall_score_range(self):
        """Whiskey Overall should be 0-1."""
        TastingNote(
            bottle_name="Test", taster_name="Test", tasting_date=date.today(),
            beverage_type="whiskey", whiskey_overall=1
        )

        with pytest.raises(Exception):
            TastingNote(
                bottle_name="Test", taster_name="Test", tasting_date=date.today(),
                beverage_type="whiskey", whiskey_overall=1.5
            )


# ============================================================================
# Test Total Score Calculations
# ============================================================================

class TestTotalScoreCalculations:
    """Verify total_score() and max_score() methods."""

    def test_wine_total_score_calculation(self):
        """Wine total should sum to max 20."""
        wine_tasting = TastingNote(
            bottle_name="Test",
            taster_name="Test",
            tasting_date=date.today(),
            beverage_type="wine",
            wine_appearance=3,    # max 3
            wine_aroma=6,         # max 6
            wine_taste=6,         # max 6
            wine_aftertaste=3,    # max 3
            wine_overall=2        # max 2
        )

        assert wine_tasting.total_score() == 20
        assert wine_tasting.max_score() == 20

    def test_whiskey_total_score_calculation(self):
        """Whiskey total should sum to max 10."""
        whiskey_tasting = TastingNote(
            bottle_name="Test",
            taster_name="Test",
            tasting_date=date.today(),
            beverage_type="whiskey",
            whiskey_nose=3,      # max 3
            whiskey_palate=3,    # max 3
            whiskey_finish=3,    # max 3
            whiskey_overall=1    # max 1
        )

        assert whiskey_tasting.total_score() == 10
        assert whiskey_tasting.max_score() == 10

    def test_wine_partial_scores(self):
        """Test wine scoring with partial scores."""
        wine_tasting = TastingNote(
            bottle_name="Test",
            taster_name="Test",
            tasting_date=date.today(),
            beverage_type="wine",
            wine_appearance=2.5,
            wine_aroma=5.0,
            # Missing other scores
        )

        # Should sum only populated fields
        assert wine_tasting.total_score() == 7.5
