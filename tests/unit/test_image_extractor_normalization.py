"""Tests for ImageMetadataExtractor wine-type normalization and wine-proof sanity checks.

Covers two recent changes in
``src/reserve_automation/extractors/image_extractor.py``:

1. ``ImageMetadataExtractor._normalize_wine_beverage_type`` — keyword map from
   raw LLM ``type`` strings to canonical wine sub-categories.
2. Wine proof sanity checks — when the inferred ``beverage_type == "wine"``
   and the parsed proof exceeds 50, both proof and abv are dropped (the
   number was almost certainly a bottle volume like ``75 CL``, not a proof).
   There are two such checks: one after the ``alcohol`` field parser and
   one inside the ``proof_raw`` block.
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from reserve_automation.extractors.image_extractor import ImageMetadataExtractor


# ---------------------------------------------------------------------------
# _normalize_wine_beverage_type — pure-function unit tests
# ---------------------------------------------------------------------------


class TestNormalizeWineBeverageType:
    """Unit tests for the static keyword-map normalizer."""

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Most-specific match wins (Rosé Champagne over Champagne over Rosé)
            ("Rosé Champagne", "Rosé Champagne"),
            ("rose champagne", "Rosé Champagne"),
            ("Pink Champagne", "Rosé Champagne"),
            # Sparkling family
            ("Champagne", "Sparkling wine"),
            ("Prosecco", "Sparkling wine"),
            ("Cava", "Sparkling wine"),
            ("Crémant de Bourgogne", "Sparkling wine"),
            ("cremant", "Sparkling wine"),
            ("Sparkling Wine", "Sparkling wine"),
            ("Pétillant Naturel", "Sparkling wine"),
            ("petillant", "Sparkling wine"),
            ("Mousseux", "Sparkling wine"),
            ("Frizzante", "Sparkling wine"),
            # Fortified family
            ("Port", "Fortified wine"),
            ("Porto", "Fortified wine"),
            ("Sherry", "Fortified wine"),
            ("Madeira", "Fortified wine"),
            ("Marsala", "Fortified wine"),
            ("Fortified Wine", "Fortified wine"),
            # Dessert family
            ("Dessert wine", "Dessert wine"),
            ("Ice Wine", "Dessert wine"),
            ("Icewine", "Dessert wine"),
            ("Sauternes", "Dessert wine"),
            ("Beerenauslese", "Dessert wine"),
            ("Trockenbeerenauslese", "Dessert wine"),
            # Rosé (without champagne)
            ("Rosé", "Rosé"),
            ("rose", "Rosé"),
            # White
            ("White Wine", "White wine"),
            ("Blanc de Blancs", "White wine"),
            ("Bianco", "White wine"),
            ("Weiss", "White wine"),
            ("Blanco", "White wine"),
            # Red
            ("Red Wine", "Red wine"),
            ("Rouge", "Red wine"),
            ("Tinto", "Red wine"),
            ("Rosso", "Red wine"),
            ("Rot", "Red wine"),
        ],
    )
    def test_keyword_match_returns_canonical_label(self, raw, expected):
        assert ImageMetadataExtractor._normalize_wine_beverage_type(raw) == expected

    @pytest.mark.parametrize("raw", ["", None])
    def test_empty_or_none_returns_none(self, raw):
        assert ImageMetadataExtractor._normalize_wine_beverage_type(raw) is None

    @pytest.mark.parametrize(
        "raw",
        [
            # "wine" alone is intentionally too generic — the map has no "wine" entry
            "wine",
            "Wine",
            # Variety / appellation strings the LLM sometimes shoves into `type`
            "Cabernet Sauvignon",
            "Pinot Noir",
            "Chardonnay",
            "Bordeaux",
            "Napa Valley",
            # Pure noise
            "asdf",
        ],
    )
    def test_unrecognizable_returns_none(self, raw):
        assert ImageMetadataExtractor._normalize_wine_beverage_type(raw) is None

    def test_specificity_order_rose_champagne_beats_champagne(self):
        # If the keyword order were wrong, "rose champagne" would hit the
        # plain "champagne" entry first and return "Sparkling wine".
        assert (
            ImageMetadataExtractor._normalize_wine_beverage_type("Rosé Champagne")
            == "Rosé Champagne"
        )

    def test_specificity_order_champagne_beats_rose(self):
        # Plain "Champagne" must still go to Sparkling wine, not Rosé.
        assert (
            ImageMetadataExtractor._normalize_wine_beverage_type("Champagne")
            == "Sparkling wine"
        )

    def test_case_and_whitespace_insensitive(self):
        assert (
            ImageMetadataExtractor._normalize_wine_beverage_type("   RED WINE   ")
            == "Red wine"
        )

    def test_substring_match_inside_phrase(self):
        # The map looks for keywords *inside* the lowered string, so noise
        # before/after a keyword still resolves correctly.
        assert (
            ImageMetadataExtractor._normalize_wine_beverage_type(
                "California Red Blend"
            )
            == "Red wine"
        )


# ---------------------------------------------------------------------------
# Wine proof sanity check — full _create_bottle_from_extraction path
# ---------------------------------------------------------------------------


def _make_extractor() -> ImageMetadataExtractor:
    """Build an ImageMetadataExtractor with a mocked LLM gateway."""
    gateway = Mock()
    gateway.complete = AsyncMock()
    return ImageMetadataExtractor(gateway)


class TestWineProofSanityCheck:
    """Verify the wine ``proof > 50`` discard rule fires in both code paths."""

    @pytest.fixture(autouse=True)
    def _patch_infer(self):
        """Force ``_infer_beverage_type`` to return a deterministic value.

        ``_create_bottle_from_extraction`` invokes web search inside
        ``_infer_beverage_type``; we bypass it entirely so each test
        controls the inferred beverage type directly.
        """
        with patch.object(
            ImageMetadataExtractor,
            "_infer_beverage_type",
            new=AsyncMock(),
        ) as mocked:
            self.mock_infer = mocked
            yield

    # ------- alcohol-field path (sanity check #1) -------

    async def test_wine_alcohol_field_with_volume_in_cl_is_discarded(self):
        """``alcohol="75 CL"`` parses to proof=150 — must be dropped for wine."""
        self.mock_infer.return_value = "wine"
        extractor = _make_extractor()

        bottle = await extractor._create_bottle_from_extraction(
            {
                "producer": "Château Test",
                "name": "Bordeaux 2019",
                "type": "Red Wine",
                "alcohol": "75 CL",  # bottle volume mistakenly placed in alcohol
            },
            Path("test.jpg"),
        )

        assert bottle.type == "wine"
        assert bottle.proof is None
        assert bottle.abv is None

    async def test_wine_alcohol_field_value_61_is_discarded(self):
        """Just above the 50-proof threshold — 61 -> abv 30.5 is implausible."""
        self.mock_infer.return_value = "wine"
        extractor = _make_extractor()

        bottle = await extractor._create_bottle_from_extraction(
            {
                "producer": "X",
                "name": "Y",
                "type": "White Wine",
                # Bare numeric > 60 with no % or "abv" hint -> assumed proof
                "alcohol": "61",
            },
            Path("test.jpg"),
        )

        assert bottle.proof is None
        assert bottle.abv is None

    async def test_wine_alcohol_field_legitimate_abv_is_kept(self):
        """13.5% ABV is plausible for wine — proof 27 is well below 50."""
        self.mock_infer.return_value = "wine"
        extractor = _make_extractor()

        bottle = await extractor._create_bottle_from_extraction(
            {
                "producer": "Château OK",
                "name": "Reserve",
                "type": "Red Wine",
                "alcohol": "13.5%",
            },
            Path("test.jpg"),
        )

        assert bottle.abv == pytest.approx(13.5)
        assert bottle.proof == pytest.approx(27.0)

    async def test_whiskey_high_proof_is_kept(self):
        """The sanity check is wine-only — 100-proof bourbon must survive."""
        self.mock_infer.return_value = "whiskey"
        extractor = _make_extractor()

        bottle = await extractor._create_bottle_from_extraction(
            {
                "producer": "Buffalo Trace",
                "name": "Bourbon",
                "type": "Bourbon",
                "alcohol": "100 proof",
            },
            Path("test.jpg"),
        )

        assert bottle.proof == pytest.approx(100.0)
        assert bottle.abv == pytest.approx(50.0)

    # ------- proof-field path (sanity check #2) -------

    async def test_wine_proof_field_above_50_is_discarded(self):
        """Same rule fires for the dedicated ``proof`` schema field."""
        self.mock_infer.return_value = "wine"
        extractor = _make_extractor()

        bottle = await extractor._create_bottle_from_extraction(
            {
                "producer": "Château Test",
                "name": "Bordeaux",
                "type": "Red Wine",
                # Empty alcohol so we land in the proof_raw branch
                "alcohol": "",
                "proof": "75",
            },
            Path("test.jpg"),
        )

        assert bottle.proof is None
        assert bottle.abv is None

    async def test_wine_proof_field_at_threshold_is_kept(self):
        """proof == 50 is the boundary; only ``> 50`` is discarded."""
        self.mock_infer.return_value = "wine"
        extractor = _make_extractor()

        bottle = await extractor._create_bottle_from_extraction(
            {
                "producer": "Fortified Co.",
                "name": "Port",
                "type": "Fortified",
                "alcohol": "",
                "proof": "50",
            },
            Path("test.jpg"),
        )

        assert bottle.proof == pytest.approx(50.0)
        # abv is derived from proof when only proof is provided
        assert bottle.abv == pytest.approx(25.0)

    async def test_whiskey_proof_field_above_50_is_kept(self):
        """The proof-field sanity check is also wine-only."""
        self.mock_infer.return_value = "whiskey"
        extractor = _make_extractor()

        bottle = await extractor._create_bottle_from_extraction(
            {
                "producer": "Wild Turkey",
                "name": "101",
                "type": "Bourbon",
                "alcohol": "",
                "proof": "101",
            },
            Path("test.jpg"),
        )

        assert bottle.proof == pytest.approx(101.0)
        assert bottle.abv == pytest.approx(50.5)

    # ------- beverage_type field is normalized only for wine -------

    async def test_wine_beverage_type_uses_normalizer(self):
        self.mock_infer.return_value = "wine"
        extractor = _make_extractor()

        bottle = await extractor._create_bottle_from_extraction(
            {
                "producer": "Test",
                "name": "X",
                "type": "Red Wine",  # raw -> "Red wine" via normalizer
            },
            Path("test.jpg"),
        )

        assert bottle.type == "wine"
        assert bottle.beverage_type == "Red wine"

    async def test_wine_unrecognizable_type_yields_none_beverage_type(self):
        """Unknown wine ``type`` strings must come out as ``None`` so enrichment can fill in."""
        self.mock_infer.return_value = "wine"
        extractor = _make_extractor()

        bottle = await extractor._create_bottle_from_extraction(
            {
                "producer": "Test",
                "name": "X",
                "type": "Cabernet Sauvignon",  # variety, not category
            },
            Path("test.jpg"),
        )

        assert bottle.type == "wine"
        assert bottle.beverage_type is None
