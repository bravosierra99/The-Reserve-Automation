"""Tests for BottleMatcher utility.

Tests fuzzy matching, substring matching, caching, and bottle name matching logic.
"""

from pathlib import Path

import pytest

from reserve_automation.core.models import BottleMetadata
from reserve_automation.utils.bottle_matcher import BottleMatch, BottleMatcher

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_vault(tmp_path):
    """Create temporary vault with sample bottles."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Create wine bottles
    wines_dir = vault / "1_Wines"
    wines_dir.mkdir()

    # Wine 1: Caymus - Cabernet Sauvignon - 2019
    caymus_dir = wines_dir / "Caymus - Cabernet Sauvignon - 2019"
    caymus_dir.mkdir()
    (caymus_dir / "Caymus - Cabernet Sauvignon - 2019.md").write_text("""---
fileClass: Wine
Winemaker: Caymus
WineName: Cabernet Sauvignon
Vintage: 2019
Inventory: 1
Buy: 0
---
""")

    # Wine 2: Chateau Margaux - Pavillon Rouge - 2015
    chateau_dir = wines_dir / "Chateau Margaux - Pavillon Rouge - 2015"
    chateau_dir.mkdir()
    (chateau_dir / "Chateau Margaux - Pavillon Rouge - 2015.md").write_text("""---
fileClass: Wine
Winemaker: Chateau Margaux
WineName: Pavillon Rouge
Vintage: 2015
Inventory: 1
Buy: 0
---
""")

    # Create whiskey bottles
    whiskeys_dir = vault / "1_Whiskeys"
    whiskeys_dir.mkdir()

    # Whiskey 1: Buffalo Trace - George T Stagg - 2022
    stagg_dir = whiskeys_dir / "Buffalo Trace - George T Stagg - 2022"
    stagg_dir.mkdir()
    (stagg_dir / "Buffalo Trace - George T Stagg - 2022.md").write_text("""---
fileClass: Whiskey
Distiller: Buffalo Trace
WhiskeyName: George T Stagg
Year: 2022
Proof: 130.4
Inventory: 1
Buy: 0
---
""")

    # Whiskey 2: Buffalo Trace - Bourbon
    bt_dir = whiskeys_dir / "Buffalo Trace - Bourbon"
    bt_dir.mkdir()
    (bt_dir / "Buffalo Trace - Bourbon.md").write_text("""---
fileClass: Whiskey
Distiller: Buffalo Trace
WhiskeyName: Bourbon
Proof: 90
Inventory: 1
Buy: 0
---
""")

    return vault


@pytest.fixture
def matcher(temp_vault):
    """Create BottleMatcher with temp vault."""
    return BottleMatcher(temp_vault)


# ============================================================================
# Fuzzy Matching Tests
# ============================================================================

class TestFuzzyMatching:
    """Test fuzzy string matching."""

    def test_exact_match_returns_high_score(self, matcher):
        """Exact match should return score close to 1.0."""
        matches = matcher.find_matches("Caymus - Cabernet Sauvignon - 2019", "wine")

        assert len(matches) > 0
        assert matches[0].score >= 0.9  # Should be very high

    def test_partial_match_returns_moderate_score(self, matcher):
        """Partial match should return moderate score."""
        matches = matcher.find_matches("Caymus Cabernet", "wine")

        assert len(matches) > 0
        # Should match but not perfect
        assert 0.5 <= matches[0].score < 1.0

    def test_typo_tolerance(self, matcher):
        """Fuzzy matching should tolerate small typos."""
        # "Caymis" instead of "Caymus" (one char diff)
        matches = matcher.find_matches("Caymis Cabernet", "wine")

        assert len(matches) > 0
        # Should still match despite typo
        assert matches[0].bottle.producer == "Caymus"

    def test_case_insensitive_matching(self, matcher):
        """Matching should be case-insensitive."""
        matches = matcher.find_matches("caymus cabernet", "wine")

        assert len(matches) > 0
        assert matches[0].bottle.producer == "Caymus"

    def test_min_score_threshold(self, matcher):
        """min_score should filter out low-scoring matches."""
        # Very different name
        matches = matcher.find_matches("Totally Different Wine", "wine", min_score=0.8)

        # Should not match anything with score >= 0.8
        assert all(m.score >= 0.8 for m in matches)

    def test_top_n_limit(self, matcher):
        """top_n should limit number of results."""
        matches = matcher.find_matches("Buffalo", "whiskey", top_n=1)

        assert len(matches) <= 1

    def test_matches_sorted_by_score(self, matcher):
        """Results should be sorted by score (highest first)."""
        matches = matcher.find_matches("Buffalo", "whiskey", top_n=10)

        # Check descending order
        for i in range(len(matches) - 1):
            assert matches[i].score >= matches[i + 1].score


# ============================================================================
# Substring Matching Tests
# ============================================================================

class TestSubstringMatching:
    """Test strict substring matching."""

    def test_substring_match_finds_partial(self, matcher):
        """Substring matching should find partial matches."""
        matches = matcher.find_matches("Stagg", "whiskey", strict_substring=True)

        assert len(matches) > 0
        assert "Stagg" in matches[0].bottle.name

    def test_substring_match_case_insensitive(self, matcher):
        """Substring matching should be case-insensitive."""
        matches = matcher.find_matches("stagg", "whiskey", strict_substring=True)

        assert len(matches) > 0

    def test_substring_exact_match_highest_score(self, matcher):
        """Exact substring match should get score 1.0."""
        matches = matcher.find_matches(
            "Buffalo Trace - George T Stagg - 2022",
            "whiskey",
            strict_substring=True
        )

        if len(matches) > 0:
            # Check if any match has perfect score
            exact_match = [m for m in matches if m.score == 1.0]
            assert len(exact_match) > 0

    def test_substring_no_match_returns_empty(self, matcher):
        """No substring match should return empty list."""
        matches = matcher.find_matches(
            "NonExistentBottle",
            "wine",
            strict_substring=True
        )

        assert len(matches) == 0


# ============================================================================
# Caching Tests
# ============================================================================

class TestCaching:
    """Test bottle caching behavior."""

    def test_cache_populated_on_first_search(self, matcher):
        """Cache should be populated after first search."""
        assert "wine" not in matcher._cache

        matcher.find_matches("Caymus", "wine")

        # Cache should now have wine bottles
        assert "wine" in matcher._cache
        assert len(matcher._cache["wine"]) > 0

    def test_cache_used_on_second_search(self, matcher):
        """Second search should use cached bottles."""
        # First search - populates cache
        matches1 = matcher.find_matches("Caymus", "wine")
        cached_bottles_count = len(matcher._cache["wine"])

        # Second search - uses cache
        matches2 = matcher.find_matches("Chateau", "wine")

        # Cache should still have same bottles
        assert len(matcher._cache["wine"]) == cached_bottles_count

    def test_invalidate_cache_specific_type(self, matcher):
        """invalidate_cache should clear specific beverage type."""
        # Populate cache for both types
        matcher.find_matches("Caymus", "wine")
        matcher.find_matches("Stagg", "whiskey")

        assert "wine" in matcher._cache
        assert "whiskey" in matcher._cache

        # Invalidate wine cache
        matcher.invalidate_cache("wine")

        assert "wine" not in matcher._cache
        assert "whiskey" in matcher._cache  # Should still be there

    def test_invalidate_cache_all_types(self, matcher):
        """invalidate_cache() with no args should clear all caches."""
        # Populate cache
        matcher.find_matches("Caymus", "wine")
        matcher.find_matches("Stagg", "whiskey")

        # Invalidate all
        matcher.invalidate_cache()

        assert len(matcher._cache) == 0


# ============================================================================
# Best Match Tests
# ============================================================================

class TestBestMatch:
    """Test find_best_match method."""

    def test_find_best_match_returns_single_result(self, matcher):
        """find_best_match should return single best match."""
        match = matcher.find_best_match("Caymus Cabernet", "wine")

        assert match is not None
        assert isinstance(match, BottleMatch)

    def test_find_best_match_auto_accept_threshold(self, matcher):
        """High confidence match should be auto-accepted."""
        # Exact match should exceed threshold
        match = matcher.find_best_match(
            "Caymus - Cabernet Sauvignon - 2019",
            "wine",
            auto_accept_threshold=0.8
        )

        assert match is not None
        assert match.score >= 0.8

    def test_find_best_match_no_matches_returns_none(self, matcher):
        """No matches should return None."""
        match = matcher.find_best_match(
            "NonExistentBottle12345",
            "wine",
            auto_accept_threshold=0.8
        )

        # Should either return None or a very low score match
        if match is not None:
            assert match.score < 0.8


# ============================================================================
# BottleMatch Tests
# ============================================================================

class TestBottleMatchObject:
    """Test BottleMatch object."""

    def test_bottle_match_has_required_attributes(self):
        """BottleMatch should have bottle, score, folder_path."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            source="test"
        )
        folder_path = Path("/vault/1_Wines/Test")

        match = BottleMatch(bottle, 0.95, folder_path)

        assert match.bottle == bottle
        assert match.score == 0.95
        assert match.folder_path == folder_path

    def test_bottle_match_repr(self):
        """BottleMatch repr should show name and score."""
        bottle = BottleMetadata(
            producer="Caymus",
            name="Cabernet",
            type="wine",
            source="test"
        )
        match = BottleMatch(bottle, 0.85, Path("/vault/1_Wines/Test"))

        repr_str = repr(match)

        assert "Caymus" in repr_str
        assert "Cabernet" in repr_str
        assert "0.85" in repr_str


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_bottle_name_returns_empty(self, matcher):
        """Empty bottle name should return no matches."""
        matches = matcher.find_matches("", "wine")

        # Should return empty or very low confidence
        assert len(matches) == 0 or matches[0].score < 0.3

    def test_unicode_characters_handled(self, temp_vault):
        """Unicode characters in names should be handled."""
        # Create bottle with unicode
        wines_dir = temp_vault / "1_Wines"
        unicode_dir = wines_dir / "Château Margaux - Merlot - 2020"
        unicode_dir.mkdir()
        (unicode_dir / "Château Margaux - Merlot - 2020.md").write_text("""---
fileClass: Wine
Winemaker: Château Margaux
WineName: Merlot
Vintage: 2020
Inventory: 1
Buy: 0
---
""")

        matcher = BottleMatcher(temp_vault)

        # Should match even with plain ASCII
        matches = matcher.find_matches("Chateau Margaux", "wine")

        # Should find the unicode bottle (fuzzy matching should handle it)
        assert len(matches) > 0

    def test_multiple_years_same_bottle(self, temp_vault):
        """Multiple vintages of same bottle should all match."""
        wines_dir = temp_vault / "1_Wines"

        # Add another Caymus vintage
        caymus2 = wines_dir / "Caymus - Cabernet Sauvignon - 2020"
        caymus2.mkdir()
        (caymus2 / "Caymus - Cabernet Sauvignon - 2020.md").write_text("""---
fileClass: Wine
Winemaker: Caymus
WineName: Cabernet Sauvignon
Vintage: 2020
Inventory: 1
Buy: 0
---
""")

        matcher = BottleMatcher(temp_vault)
        matches = matcher.find_matches("Caymus Cabernet", "wine", top_n=10)

        # Should find both vintages
        assert len(matches) >= 2
