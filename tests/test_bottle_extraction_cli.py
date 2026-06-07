"""Tests for bottle extraction via CLI (manifest processing)."""

import json
from pathlib import Path

import pytest

from reserve_automation.core.config import Config
from reserve_automation.core.models import BottleMetadata
from reserve_automation.extractors.bottle import BottleExtractor
from reserve_automation.llm.gateway import LLMGateway
from reserve_automation.parsers.pdf import PDFParser


@pytest.fixture
def config():
    """Load test configuration."""
    return Config.load()


@pytest.fixture
def llm_gateway(config):
    """Create LLM gateway for testing."""
    return LLMGateway(config.llm)


@pytest.fixture
def pdf_parser():
    """Create PDF parser."""
    return PDFParser()


@pytest.fixture
def bottle_extractor(llm_gateway):
    """Create bottle extractor."""
    return BottleExtractor(llm_gateway)


@pytest.fixture
def wine_manifest_path():
    """Path to test wine manifest PDF."""
    return Path(__file__).parent / "fixtures" / "manifests" / "wine_manifest_sample.pdf"


@pytest.fixture
def expected_results_path():
    """Path to expected extraction results."""
    return Path(__file__).parent / "fixtures" / "manifests" / "wine_manifest_expected.json"


@pytest.fixture
def expected_bottles(expected_results_path):
    """Load expected bottle extraction results."""
    if not expected_results_path.exists():
        pytest.skip("Expected results file not found")

    data = json.loads(expected_results_path.read_text())
    return [BottleMetadata(**bottle) for bottle in data]


class TestPDFParsing:
    """Test PDF parsing functionality."""

    @pytest.mark.asyncio
    async def test_parse_wine_manifest(self, pdf_parser, wine_manifest_path):
        """Test parsing wine manifest PDF."""
        result = await pdf_parser.parse(wine_manifest_path)

        assert result is not None
        assert len(result.raw_text) > 0
        assert result.source_type == "pdf"
        assert "Forge Cellars" in result.raw_text
        assert "Willow Vineyard" in result.raw_text

    @pytest.mark.asyncio
    async def test_parse_extracts_text_from_all_pages(self, pdf_parser, wine_manifest_path):
        """Test that parser extracts text from all pages."""
        result = await pdf_parser.parse(wine_manifest_path)

        # Check for wines on different pages
        assert "Forge Cellars" in result.raw_text  # Page 1
        assert "Cava Reserva" in result.raw_text  # Page 2


@pytest.mark.requires_lm_studio
class TestBottleExtraction:
    """Test bottle extraction from manifests."""

    @pytest.mark.asyncio
    async def test_extract_bottles_from_manifest(
        self,
        bottle_extractor,
        pdf_parser,
        wine_manifest_path
    ):
        """Test extracting bottles from wine manifest."""
        # Parse the PDF
        parser_result = await pdf_parser.parse(wine_manifest_path)

        # Extract bottles
        bottles = await bottle_extractor.extract(
            parser_result=parser_result,
            beverage_type="wine"
        )

        assert len(bottles) > 0
        assert all(isinstance(b, BottleMetadata) for b in bottles)

    @pytest.mark.asyncio
    async def test_extracted_bottle_count(
        self,
        bottle_extractor,
        pdf_parser,
        wine_manifest_path,
        expected_bottles
    ):
        """Test that extraction finds expected number of bottles."""
        parser_result = await pdf_parser.parse(wine_manifest_path)
        bottles = await bottle_extractor.extract(parser_result, beverage_type="wine")

        # Allow ±1 tolerance for slight variations
        assert abs(len(bottles) - len(expected_bottles)) <= 1, \
            f"Expected ~{len(expected_bottles)} bottles, got {len(bottles)}"

    @pytest.mark.asyncio
    async def test_extracted_bottles_have_required_fields(
        self,
        bottle_extractor,
        pdf_parser,
        wine_manifest_path
    ):
        """Test that extracted bottles have required fields."""
        parser_result = await pdf_parser.parse(wine_manifest_path)
        bottles = await bottle_extractor.extract(parser_result, beverage_type="wine")

        for bottle in bottles:
            # Every bottle should have at minimum:
            assert bottle.producer, f"Bottle missing producer: {bottle}"
            assert bottle.name, f"Bottle missing name: {bottle}"
            # Type should be wine (beverage_type can be "Red wine", "White wine", "Sparkling", etc.)
            assert bottle.type == "wine", f"Expected type='wine', got: {bottle.type}"

    @pytest.mark.asyncio
    async def test_extraction_matches_expected_bottles(
        self,
        bottle_extractor,
        pdf_parser,
        wine_manifest_path,
        expected_bottles
    ):
        """Test that extraction matches expected results (regression test)."""
        parser_result = await pdf_parser.parse(wine_manifest_path)
        bottles = await bottle_extractor.extract(parser_result, beverage_type="wine")

        # Check that we find the key bottles from the manifest
        bottle_names = {f"{b.producer} - {b.name}" for b in bottles}

        # Key bottles that should be found
        expected_names = [
            "Forge Cellars - Willow Vineyard",
            "Jax Vineyards - Y3 Taureau Napa Valley Red",
            "Trimbach - Riesling Alsace",
            "Sandhi - Chardonnay Sta. Rita Hills",
        ]

        found = [name for name in expected_names if any(name in bn for bn in bottle_names)]

        # Should find at least 75% of key bottles
        assert len(found) >= len(expected_names) * 0.75, \
            f"Only found {len(found)}/{len(expected_names)} key bottles: {found}"

    @pytest.mark.asyncio
    async def test_bottles_have_correct_years(
        self,
        bottle_extractor,
        pdf_parser,
        wine_manifest_path
    ):
        """Test that bottles extract years correctly."""
        parser_result = await pdf_parser.parse(wine_manifest_path)
        bottles = await bottle_extractor.extract(parser_result, beverage_type="wine")

        # Find specific bottles and check their years
        forge = next((b for b in bottles if "Forge Cellars" in b.producer), None)
        assert forge is not None
        assert forge.year == 2023

        trimbach = next((b for b in bottles if "Trimbach" in b.producer), None)
        assert trimbach is not None
        assert trimbach.year == 2022

    @pytest.mark.asyncio
    async def test_bottles_extract_regions(
        self,
        bottle_extractor,
        pdf_parser,
        wine_manifest_path
    ):
        """Test that bottles extract region information."""
        parser_result = await pdf_parser.parse(wine_manifest_path)
        bottles = await bottle_extractor.extract(parser_result, beverage_type="wine")

        # Check that at least some bottles have region info
        # Note: LLM extraction quality can vary, so we use a lenient threshold
        bottles_with_regions = [b for b in bottles if b.region]
        assert len(bottles_with_regions) >= 1, \
            "Expected at least 1 bottle with region information (LLM extraction can vary)"


@pytest.mark.requires_lm_studio
class TestBottleDataQuality:
    """Test the quality of extracted bottle data."""

    @pytest.mark.asyncio
    async def test_no_duplicate_bottles(
        self,
        bottle_extractor,
        pdf_parser,
        wine_manifest_path
    ):
        """Test that extraction doesn't create duplicate bottles."""
        parser_result = await pdf_parser.parse(wine_manifest_path)
        bottles = await bottle_extractor.extract(parser_result, beverage_type="wine")

        # Create unique identifiers for each bottle
        bottle_ids = [f"{b.producer}|{b.name}|{b.year}" for b in bottles]

        # Check for duplicates
        unique_ids = set(bottle_ids)
        assert len(bottle_ids) == len(unique_ids), \
            f"Found duplicate bottles: {len(bottle_ids)} total, {len(unique_ids)} unique"

    @pytest.mark.asyncio
    async def test_confidence_scores_reasonable(
        self,
        bottle_extractor,
        pdf_parser,
        wine_manifest_path
    ):
        """Test that confidence scores are in reasonable range."""
        parser_result = await pdf_parser.parse(wine_manifest_path)
        bottles = await bottle_extractor.extract(parser_result, beverage_type="wine")

        for bottle in bottles:
            if bottle.confidence is not None:
                assert 0.0 <= bottle.confidence <= 1.0, \
                    f"Confidence out of range: {bottle.confidence} for {bottle.producer}"


@pytest.mark.requires_lm_studio
class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_empty_pdf_returns_no_bottles(
        self,
        bottle_extractor,
        pdf_parser,
        tmp_path
    ):
        """Test that an empty PDF returns no bottles."""
        # Create an empty PDF would require a PDF library
        # For now, test with empty parser result
        from reserve_automation.core.models import ParserResult

        empty_result = ParserResult(
            raw_text="",
            source_type="pdf",
            images=[]
        )

        bottles = await bottle_extractor.extract(empty_result, beverage_type="wine")
        assert len(bottles) == 0

    @pytest.mark.asyncio
    async def test_auto_detect_beverage_type(
        self,
        bottle_extractor,
        pdf_parser,
        wine_manifest_path
    ):
        """Test auto-detection of beverage type."""
        parser_result = await pdf_parser.parse(wine_manifest_path)
        bottles = await bottle_extractor.extract(parser_result, beverage_type="auto")

        # Should detect wine (type field should be "wine", beverage_type can vary)
        assert len(bottles) > 0
        assert all(b.type == "wine" for b in bottles), \
            f"Expected all bottles to have type='wine', got: {[b.type for b in bottles]}"
