"""Unit tests for ImageMetadataExtractor._normalize_wine_beverage_type and proof sanity check."""

import io
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest
from PIL import Image

from reserve_automation.extractors.image_extractor import ImageMetadataExtractor


class TestNormalizeWineBeverageType:
    """Tests for _normalize_wine_beverage_type static method."""

    def test_empty_string_returns_none(self):
        assert ImageMetadataExtractor._normalize_wine_beverage_type("") is None

    def test_none_input_returns_none(self):
        assert ImageMetadataExtractor._normalize_wine_beverage_type(None) is None

    def test_bare_wine_returns_none(self):
        # "wine" alone has no keyword match in _WINE_TYPE_MAP
        assert ImageMetadataExtractor._normalize_wine_beverage_type("wine") is None

    def test_case_insensitive_red(self):
        for val in ["RED", "Red", "red"]:
            assert ImageMetadataExtractor._normalize_wine_beverage_type(val) == "Red wine", val

    def test_case_insensitive_white(self):
        for val in ["WHITE", "White", "white"]:
            assert ImageMetadataExtractor._normalize_wine_beverage_type(val) == "White wine", val

    def test_rose_accent_returns_rosé(self):
        assert ImageMetadataExtractor._normalize_wine_beverage_type("rosé") == "Rosé"

    def test_rose_no_accent_returns_rosé(self):
        assert ImageMetadataExtractor._normalize_wine_beverage_type("rose") == "Rosé"

    def test_rosé_champagne_precedence(self):
        # First entry in map — must win over Rosé and Sparkling entries
        assert ImageMetadataExtractor._normalize_wine_beverage_type("rosé champagne") == "Rosé Champagne"

    def test_champagne_returns_sparkling(self):
        # "champagne" matches second entry, not first (no "rosé")
        assert ImageMetadataExtractor._normalize_wine_beverage_type("champagne") == "Sparkling wine"

    def test_unknown_variety_name_returns_none(self):
        # Wine variety names should not match any keyword
        assert ImageMetadataExtractor._normalize_wine_beverage_type("Cabernet Sauvignon") is None

    def test_all_canonical_labels(self):
        cases = [
            ("rosé champagne", "Rosé Champagne"),
            ("sparkling",      "Sparkling wine"),
            ("port",           "Fortified wine"),
            ("dessert",        "Dessert wine"),
            ("rosé",           "Rosé"),
            ("white",          "White wine"),
            ("red",            "Red wine"),
        ]
        for raw, expected in cases:
            assert ImageMetadataExtractor._normalize_wine_beverage_type(raw) == expected, raw


class TestNormalizeSpiritBeverageType:
    """Tests for _normalize_spirit_beverage_type static method."""

    def test_empty_string_returns_none(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("") is None

    def test_none_input_returns_none(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type(None) is None

    def test_bourbon_variants(self):
        cases = ["Bourbon", "Bourbon Whiskey", "Kentucky Straight Bourbon Whiskey", "straight bourbon"]
        for v in cases:
            assert ImageMetadataExtractor._normalize_spirit_beverage_type(v) == "Bourbon", v

    def test_scotch_variants(self):
        cases = ["Scotch", "Scotch Whisky", "Single Malt Scotch Whisky", "Blended Scotch"]
        for v in cases:
            assert ImageMetadataExtractor._normalize_spirit_beverage_type(v) == "Scotch Whisky", v

    def test_irish_whiskey(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Irish Whiskey") == "Irish Whiskey"
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Irish") == "Irish Whiskey"

    def test_tennessee_whiskey(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Tennessee Whiskey") == "Tennessee Whiskey"

    def test_rye_whiskey(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Rye Whiskey") == "Rye Whiskey"
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("American Rye") == "Rye Whiskey"

    def test_japanese_whisky(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Japanese Whisky") == "Japanese Whisky"
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Japanese") == "Japanese Whisky"

    def test_canadian_whisky(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Canadian Whisky") == "Canadian Whisky"

    def test_bourbon_takes_precedence_over_tennessee(self):
        # "bourbon" keyword should win before "tennessee" is checked
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Bourbon") == "Bourbon"

    def test_tennessee_takes_precedence_over_scotch(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Tennessee") == "Tennessee Whiskey"

    def test_unknown_spirit_returns_none(self):
        # Unrecognized values fall back to sanitize_string in caller
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Grappa") is None
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Aquavit") is None

    def test_case_insensitive(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("BOURBON") == "Bourbon"
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("scotch whisky") == "Scotch Whisky"

    def test_rum_types(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Dark Rum") == "Dark Rum"
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Spiced Rum") == "Spiced Rum"
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Light Rum") == "Light Rum"

    def test_tequila_types(self):
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Reposado") == "Reposado Tequila"
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Extra Añejo Tequila") == "Extra Añejo Tequila"
        assert ImageMetadataExtractor._normalize_spirit_beverage_type("Mezcal") == "Mezcal"


class TestNormalizeCountry:
    """Tests for _normalize_country static method."""

    def test_empty_string_returns_none(self):
        assert ImageMetadataExtractor._normalize_country("") is None

    def test_none_returns_none(self):
        assert ImageMetadataExtractor._normalize_country(None) is None

    def test_usa_variants(self):
        cases = ["USA", "US", "U.S.", "U.S.A.", "United States of America", "America"]
        for v in cases:
            assert ImageMetadataExtractor._normalize_country(v) == "United States", v

    def test_uk_variants(self):
        cases = ["UK", "U.K.", "Great Britain", "GB", "England"]
        for v in cases:
            assert ImageMetadataExtractor._normalize_country(v) == "United Kingdom", v

    def test_case_insensitive_lookup(self):
        assert ImageMetadataExtractor._normalize_country("usa") == "United States"
        assert ImageMetadataExtractor._normalize_country("Usa") == "United States"
        assert ImageMetadataExtractor._normalize_country("uk") == "United Kingdom"

    def test_already_canonical_passes_through(self):
        assert ImageMetadataExtractor._normalize_country("United States") == "United States"
        assert ImageMetadataExtractor._normalize_country("United Kingdom") == "United Kingdom"

    def test_other_countries_pass_through(self):
        for country in ["France", "Italy", "Spain", "Scotland", "Japan", "Australia"]:
            assert ImageMetadataExtractor._normalize_country(country) == country, country

    def test_scotland_not_remapped(self):
        # Scotland is a valid country for spirits purposes — should not become "United Kingdom"
        assert ImageMetadataExtractor._normalize_country("Scotland") == "Scotland"


class TestProofSanityCheck:
    """Tests for wine proof > 50 discard in _create_bottle_from_extraction."""

    @pytest.fixture
    def extractor(self):
        mock_llm = Mock()
        mock_llm.complete = AsyncMock()
        mock_llm.web_search = AsyncMock(return_value="wine")
        return ImageMetadataExtractor(mock_llm)

    @pytest.fixture
    def image_path(self):
        return Path("/tmp/test_label.jpg")

    @pytest.mark.asyncio
    async def test_wine_proof_75_discarded(self, extractor, image_path):
        """alcohol='75 CL' → proof=75 for wine → both proof and abv discarded."""
        data = {
            "producer": "Test Winery",
            "name": "Test Wine",
            "beverage_type": "wine",
            "alcohol": "75 CL",
        }
        with patch.object(extractor, "_infer_beverage_type", AsyncMock(return_value="wine")):
            bottle = await extractor._create_bottle_from_extraction(data, image_path)
        assert bottle.proof is None
        assert bottle.abv is None

    @pytest.mark.asyncio
    async def test_whiskey_proof_75_preserved(self, extractor, image_path):
        """proof=75 for whiskey is NOT discarded — sanity check only applies to wine."""
        data = {
            "producer": "Test Distillery",
            "name": "Test Bourbon",
            "beverage_type": "whiskey",
            "alcohol": "75 PROOF",
        }
        with patch.object(extractor, "_infer_beverage_type", AsyncMock(return_value="whiskey")):
            bottle = await extractor._create_bottle_from_extraction(data, image_path)
        assert bottle.proof == 75.0

    @pytest.mark.asyncio
    async def test_wine_proof_at_boundary_preserved(self, extractor, image_path):
        """Wine with proof ≤ 50 is preserved (fortified wine range)."""
        data = {
            "producer": "Test Winery",
            "name": "Test Sherry",
            "beverage_type": "wine",
            "alcohol": "40 PROOF",
        }
        with patch.object(extractor, "_infer_beverage_type", AsyncMock(return_value="wine")):
            bottle = await extractor._create_bottle_from_extraction(data, image_path)
        assert bottle.proof == 40.0
        assert bottle.abv == 20.0


class TestImageReencodedAsJpeg:
    """Vision LLM must receive a plain JPEG — see extract_from_image comment about MPO."""

    @pytest.fixture
    def extractor_with_captured_images(self):
        captured = {}

        async def fake_complete(*args, **kwargs):
            captured["images"] = kwargs.get("images")
            response = Mock()
            response.content = '{"producer": "x", "name": "y", "beverage_type": "whiskey", "confidence": "high"}'
            return response

        mock_llm = Mock()
        mock_llm.complete = AsyncMock(side_effect=fake_complete)
        mock_llm.web_search = AsyncMock(return_value="whiskey")
        return ImageMetadataExtractor(mock_llm), captured

    @pytest.mark.asyncio
    async def test_png_input_sent_as_jpeg(self, extractor_with_captured_images, tmp_path):
        """A PNG on disk must be re-encoded to JPEG before being handed to the LLM."""
        extractor, captured = extractor_with_captured_images
        png_path = tmp_path / "label.png"
        Image.new("RGB", (32, 32), (200, 100, 50)).save(png_path, format="PNG")

        with patch.object(extractor, "_infer_beverage_type", AsyncMock(return_value="whiskey")):
            await extractor.extract_from_image(png_path)

        assert captured["images"], "LLM gateway received no images"
        sent_bytes = captured["images"][0]
        assert sent_bytes[:2] == b"\xff\xd8", "Bytes sent to LLM do not start with JPEG SOI marker"
        roundtrip = Image.open(io.BytesIO(sent_bytes))
        assert roundtrip.format == "JPEG"

    @pytest.mark.asyncio
    async def test_rgba_input_flattened_and_sent_as_jpeg(self, extractor_with_captured_images, tmp_path):
        """RGBA inputs would raise on JPEG save without RGB conversion — must be handled."""
        extractor, captured = extractor_with_captured_images
        png_path = tmp_path / "label_rgba.png"
        Image.new("RGBA", (32, 32), (200, 100, 50, 128)).save(png_path, format="PNG")

        with patch.object(extractor, "_infer_beverage_type", AsyncMock(return_value="whiskey")):
            await extractor.extract_from_image(png_path)

        sent_bytes = captured["images"][0]
        assert sent_bytes[:2] == b"\xff\xd8"
        roundtrip = Image.open(io.BytesIO(sent_bytes))
        assert roundtrip.format == "JPEG"
        assert roundtrip.mode == "RGB"
