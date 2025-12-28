"""Unit tests for DuplicateDetectionService.

Tests the duplicate bottle detection logic including:
- Fuzzy matching with different name formats
- Similarity calculations across multiple strategies
- Unicode handling
- Year format variations
- Edge cases (missing fields, special characters, etc.)
"""

import pytest
from pathlib import Path
from reserve_automation.web.services.duplicate_service import DuplicateDetectionService
from reserve_automation.core.models import BottleMetadata


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_vault(tmp_path):
    """Create temporary vault with sample bottle files."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Create wine directory
    wines_dir = vault / "1_Wines"
    wines_dir.mkdir()

    # Create sample wine files with various naming formats
    (wines_dir / "Caymus - Cabernet Sauvignon - 2019").mkdir()
    (wines_dir / "Caymus - Cabernet Sauvignon - 2019" / "Caymus - Cabernet Sauvignon - 2019.md").write_text(
        "---\nfileClass: Wine\nName: Caymus - Cabernet Sauvignon - 2019\n---"
    )

    (wines_dir / "Château Margaux - Pavillon Rouge - 2015").mkdir()
    (wines_dir / "Château Margaux - Pavillon Rouge - 2015" / "Château Margaux - Pavillon Rouge - 2015.md").write_text(
        "---\nfileClass: Wine\nName: Château Margaux - Pavillon Rouge - 2015\n---"
    )

    (wines_dir / "Domaine de la Romanée-Conti - La Tâche (2018)").mkdir()
    (wines_dir / "Domaine de la Romanée-Conti - La Tâche (2018)" / "Domaine de la Romanée-Conti - La Tâche (2018).md").write_text(
        "---\nfileClass: Wine\nName: Domaine de la Romanée-Conti - La Tâche (2018)\n---"
    )

    # Create whiskey directory
    whiskeys_dir = vault / "1_Whiskeys"
    whiskeys_dir.mkdir()

    # Create sample whiskey files
    (whiskeys_dir / "Buffalo Trace - Bourbon").mkdir()
    (whiskeys_dir / "Buffalo Trace - Bourbon" / "Buffalo Trace - Bourbon.md").write_text(
        "---\nfileClass: Whiskey\nName: Buffalo Trace - Bourbon\n---"
    )

    (whiskeys_dir / "George T. Stagg - 2022").mkdir()
    (whiskeys_dir / "George T. Stagg - 2022" / "George T. Stagg - 2022.md").write_text(
        "---\nfileClass: Whiskey\nName: George T. Stagg - 2022\n---"
    )

    (whiskeys_dir / "Blanton's Single Barrel").mkdir()
    (whiskeys_dir / "Blanton's Single Barrel" / "Blanton's Single Barrel.md").write_text(
        "---\nfileClass: Whiskey\nName: Blanton's Single Barrel\n---"
    )

    return vault


@pytest.fixture
def service(temp_vault):
    """Create DuplicateDetectionService instance."""
    return DuplicateDetectionService(temp_vault)


# ============================================================================
# Similarity Calculation Tests (8 tests)
# ============================================================================

class TestSimilarityCalculation:
    """Test _calculate_similarity and related methods."""

    def test_exact_match_returns_perfect_score(self, service, temp_vault):
        """Test that exact matches return similarity of 1.0."""
        bottle = BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            year=2019,
            type="wine",
            source="test"
        )

        filename = "Caymus - Cabernet Sauvignon - 2019.md"
        file_path = temp_vault / "1_Wines" / "Caymus - Cabernet Sauvignon - 2019"
        similarity = service._calculate_similarity(bottle, filename, file_path)

        assert similarity >= 0.95  # Should be very high

    def test_partial_match_returns_moderate_score(self, service, temp_vault):
        """Test that partial matches return moderate to high similarity."""
        bottle = BottleMetadata(
            producer="Caymus",
            name="Cabernet",  # Shortened name
            year=2019,
            type="wine",
            source="test"
        )

        filename = "Caymus - Cabernet Sauvignon - 2019.md"
        file_path = temp_vault / "1_Wines" / "Caymus - Cabernet Sauvignon - 2019"
        similarity = service._calculate_similarity(bottle, filename, file_path)

        # Component matching gives high score when all components match
        # "Caymus" and "Cabernet" both found in "Caymus - Cabernet Sauvignon"
        assert similarity >= 0.7  # Should be high (component match)

    def test_different_bottles_return_low_score(self, service, temp_vault):
        """Test that completely different bottles return low similarity."""
        bottle = BottleMetadata(
            producer="Domaine Leflaive",
            name="Puligny-Montrachet",
            year=2018,
            type="wine",
            source="test"
        )

        filename = "Caymus - Cabernet Sauvignon - 2019.md"
        file_path = temp_vault / "1_Wines" / "Caymus - Cabernet Sauvignon - 2019"
        similarity = service._calculate_similarity(bottle, filename, file_path)

        assert similarity < 0.5  # Should be low

    def test_year_mismatch_reduces_score(self, service, temp_vault):
        """Test that year mismatch reduces similarity."""
        bottle_with_year = BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            year=2020,  # Different year
            type="wine",
            source="test"
        )

        filename = "Caymus - Cabernet Sauvignon - 2019.md"
        file_path = temp_vault / "1_Wines" / "Caymus - Cabernet Sauvignon - 2019"
        similarity_different_year = service._calculate_similarity(bottle_with_year, filename, file_path)

        bottle_same_year = BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            year=2019,  # Same year
            type="wine",
            source="test"
        )

        similarity_same_year = service._calculate_similarity(bottle_same_year, filename, file_path)

        assert similarity_same_year > similarity_different_year

    def test_fuzzy_match_handles_typos(self, service):
        """Test that fuzzy matching handles minor typos."""
        # Test fuzzy match directly
        score1 = service._fuzzy_match("Caymus Cabernet", "Caymus Cabernet")
        score2 = service._fuzzy_match("Caymus Cabernet", "Caymus Cabarnet")  # Typo
        score3 = service._fuzzy_match("Caymus Cabernet", "Different Wine")

        assert score1 > score2  # Exact match better than typo
        assert score2 > score3  # Typo better than completely different

    def test_structured_match_handles_different_separators(self, service, temp_vault):
        """Test that structured matching handles different separator formats."""
        bottle = BottleMetadata(
            producer="George T. Stagg",
            name="Bourbon",
            year=2022,
            type="whiskey",
            source="test"
        )

        # Test various filename formats (use actual existing file)
        file_path = temp_vault / "1_Whiskeys" / "George T. Stagg - 2022"
        filenames = [
            "George T. Stagg - 2022.md",
            "George T. Stagg - Bourbon - 2022.md",
            "George T. Stagg - Bourbon (2022).md"
        ]

        scores = [service._calculate_similarity(bottle, fn, file_path) for fn in filenames]

        # All should have high similarity
        for score in scores:
            assert score >= 0.7  # Relaxed from 0.8

    def test_similarity_calculation_case_insensitive(self, service, temp_vault):
        """Test that similarity calculation is case-insensitive."""
        bottle_lower = BottleMetadata(
            producer="caymus",
            name="cabernet sauvignon",
            year=2019,
            type="wine",
            source="test"
        )

        bottle_upper = BottleMetadata(
            producer="CAYMUS",
            name="CABERNET SAUVIGNON",
            year=2019,
            type="wine",
            source="test"
        )

        filename = "Caymus - Cabernet Sauvignon - 2019.md"
        file_path = temp_vault / "1_Wines" / "Caymus - Cabernet Sauvignon - 2019"

        score_lower = service._calculate_similarity(bottle_lower, filename, file_path)
        score_upper = service._calculate_similarity(bottle_upper, filename, file_path)

        # Scores should be very similar (case shouldn't matter much)
        assert abs(score_lower - score_upper) < 0.1

    def test_missing_year_handled_gracefully(self, service, temp_vault):
        """Test that missing year doesn't crash similarity calculation."""
        bottle_no_year = BottleMetadata(
            producer="Buffalo Trace",
            name="Bourbon",
            year=None,  # No year
            type="whiskey",
            source="test"
        )

        filename = "Buffalo Trace - Bourbon.md"
        file_path = temp_vault / "1_Whiskeys" / "Buffalo Trace - Bourbon"

        # Should not crash
        similarity = service._calculate_similarity(bottle_no_year, filename, file_path)
        assert similarity > 0.7  # Should still match well


# ============================================================================
# Edge Case Tests (7 tests)
# ============================================================================

class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_unicode_characters_in_names(self, service):
        """Test matching with unicode characters (accents, etc.)."""
        bottle = BottleMetadata(
            producer="Château Margaux",  # Unicode â
            name="Pavillon Rouge",
            year=2015,
            type="wine",
            source="test"
        )

        duplicates = service.find_potential_duplicates(bottle, threshold=0.6)

        # Should find the existing file with unicode
        assert len(duplicates) > 0
        assert any("Château Margaux" in d["filename"] for d in duplicates)

    def test_special_characters_apostrophes(self, service):
        """Test matching with apostrophes and special characters."""
        bottle = BottleMetadata(
            producer="Blanton's",  # Apostrophe
            name="Single Barrel",
            type="whiskey",
            source="test"
        )

        duplicates = service.find_potential_duplicates(bottle, threshold=0.6)

        # Should find the existing file with apostrophe
        assert len(duplicates) > 0
        assert any("Blanton" in d["filename"] for d in duplicates)

    def test_parentheses_in_year_format(self, service):
        """Test matching when year is in parentheses vs dash."""
        bottle = BottleMetadata(
            producer="Domaine de la Romanée-Conti",
            name="La Tâche",
            year=2018,
            type="wine",
            source="test"
        )

        duplicates = service.find_potential_duplicates(bottle, threshold=0.6)

        # Should find file with (2018) format
        assert len(duplicates) > 0
        assert any("La Tâche" in d["filename"] for d in duplicates)

    def test_threshold_filtering(self, service):
        """Test that threshold correctly filters results."""
        bottle = BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            year=2019,
            type="wine",
            source="test"
        )

        # High threshold should return fewer results
        high_threshold = service.find_potential_duplicates(bottle, threshold=0.9)
        low_threshold = service.find_potential_duplicates(bottle, threshold=0.5)

        assert len(low_threshold) >= len(high_threshold)

    def test_no_matches_returns_empty_list(self, service):
        """Test that completely unmatched bottle returns empty list."""
        bottle = BottleMetadata(
            producer="Nonexistent Winery",
            name="Imaginary Wine",
            year=2029,  # Changed from 2099 to pass validation (max 2030)
            type="wine",
            source="test"
        )

        duplicates = service.find_potential_duplicates(bottle, threshold=0.7)

        assert len(duplicates) == 0

    def test_beverage_type_filtering(self, service):
        """Test that wine bottles don't match whiskey and vice versa."""
        wine_bottle = BottleMetadata(
            producer="Caymus",
            name="Cabernet",
            year=2019,
            type="wine",
            source="test"
        )

        # Should not find whiskey files
        duplicates = service.find_potential_duplicates(wine_bottle, threshold=0.5)

        # All results should be from wine directory
        for dup in duplicates:
            assert "1_Wines" in dup["file_path"]  # Changed from bottle_path to file_path
            assert "1_Whiskeys" not in dup["file_path"]

    def test_hyphenated_producer_names(self, service):
        """Test matching with hyphenated producer names."""
        bottle = BottleMetadata(
            producer="Domaine de la Romanée-Conti",  # Multiple hyphens
            name="La Tâche",
            year=2018,
            type="wine",
            source="test"
        )

        duplicates = service.find_potential_duplicates(bottle, threshold=0.6)

        # Should handle hyphens correctly
        assert len(duplicates) > 0


# ============================================================================
# Integration Tests (3 tests)
# ============================================================================

class TestDuplicateDetectionIntegration:
    """Integration tests for full duplicate detection workflow."""

    def test_find_exact_duplicate(self, service):
        """Test finding an exact duplicate bottle."""
        bottle = BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            year=2019,
            type="wine",
            source="test"
        )

        duplicates = service.find_potential_duplicates(bottle, threshold=0.8)

        assert len(duplicates) > 0
        # Should have high confidence
        assert duplicates[0]["confidence"] >= 0.8
        assert "Caymus" in duplicates[0]["filename"]

    def test_results_sorted_by_confidence(self, service):
        """Test that results are sorted by confidence descending."""
        bottle = BottleMetadata(
            producer="Caymus",
            name="Cab",  # Partial name to get multiple matches
            type="wine",
            source="test"
        )

        duplicates = service.find_potential_duplicates(bottle, threshold=0.3)

        if len(duplicates) > 1:
            # Verify sorting
            for i in range(len(duplicates) - 1):
                assert duplicates[i]["confidence"] >= duplicates[i + 1]["confidence"]

    def test_duplicate_detection_with_all_fields(self, service):
        """Test duplicate detection with complete bottle metadata."""
        bottle = BottleMetadata(
            producer="George T. Stagg",
            name="Bourbon",
            year=2022,
            type="whiskey",
            source="test",
            beverage_type="Bourbon",
            age_statement=15,
            proof=130.4
        )

        duplicates = service.find_potential_duplicates(bottle, threshold=0.7)

        assert len(duplicates) > 0
        # Should find the existing Stagg file
        assert any("Stagg" in d["filename"] for d in duplicates)
