"""Unit tests for extraction components."""

import pytest
from unittest.mock import AsyncMock, Mock

from reserve_automation.core.exceptions import ExtractionError
from reserve_automation.core.models import BottleMetadata, ParserResult
from reserve_automation.extractors import BottleExtractor, ConfidenceAnalyzer
from reserve_automation.llm.gateway import LLMResponse


# ============================================================================
# BottleExtractor Tests
# ============================================================================


class TestBottleExtractor:
    """Tests for BottleExtractor."""

    @pytest.fixture
    def mock_llm(self):
        """Create mock LLM Gateway."""
        llm = Mock()
        llm.complete = AsyncMock()
        return llm

    @pytest.fixture
    def extractor(self, mock_llm):
        """Create BottleExtractor with mock LLM."""
        return BottleExtractor(mock_llm)

    @pytest.fixture
    def sample_parser_result(self):
        """Sample parser result."""
        return ParserResult(
            raw_text="2019 Caymus Cabernet Sauvignon Napa Valley $85",
            source_type="pdf",
            page_count=1,
            confidence=1.0,
        )

    @pytest.mark.asyncio
    async def test_extract_wine_success(self, extractor, mock_llm, sample_parser_result):
        """Test successful wine extraction."""
        # Mock LLM response
        mock_llm.complete.return_value = LLMResponse(
            content='[{"producer": "Caymus", "name": "Cabernet Sauvignon", "year": 2019, "type": "wine", "beverage_type": "Red wine", "region": "Napa Valley", "country": "United States", "price": 85.0}]',
            tokens_used=150,
            cost=0.01,
            model="test-model",
            provider="test",
            latency_ms=100.0,
        )

        # Extract bottles
        bottles = await extractor.extract(sample_parser_result, beverage_type="wine")

        # Verify results
        assert len(bottles) == 1
        bottle = bottles[0]
        assert bottle.producer == "Caymus"
        assert bottle.name == "Cabernet Sauvignon"
        assert bottle.year == 2019
        assert bottle.type == "wine"
        assert bottle.beverage_type == "Red wine"
        assert bottle.region == "Napa Valley"
        assert bottle.price == 85.0
        assert 0.0 <= bottle.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_extract_whiskey_success(self, extractor, mock_llm):
        """Test successful whiskey extraction."""
        parser_result = ParserResult(
            raw_text="Buffalo Trace Bourbon 90 Proof Kentucky $25",
            source_type="image",
            page_count=1,
            confidence=1.0,
        )

        mock_llm.complete.return_value = LLMResponse(
            content='[{"producer": "Buffalo Trace", "name": "Bourbon", "type": "whiskey", "beverage_type": "Bourbon", "proof": 90, "region": "Kentucky", "country": "United States", "price": 25.0}]',
            tokens_used=120,
            cost=0.008,
            model="test-model",
            provider="test",
            latency_ms=100.0,
        )

        bottles = await extractor.extract(parser_result, beverage_type="whiskey")

        assert len(bottles) == 1
        bottle = bottles[0]
        assert bottle.producer == "Buffalo Trace"
        assert bottle.type == "whiskey"
        assert bottle.beverage_type == "Bourbon"
        assert bottle.proof == 90
        assert bottle.price == 25.0

    @pytest.mark.asyncio
    async def test_extract_empty_text(self, extractor, mock_llm):
        """Test extraction with empty text."""
        parser_result = ParserResult(
            raw_text="",
            source_type="pdf",
            page_count=1,
            confidence=1.0,
        )

        bottles = await extractor.extract(parser_result)

        assert len(bottles) == 0
        # LLM should not be called
        mock_llm.complete.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_with_markdown_code_block(self, extractor, mock_llm, sample_parser_result):
        """Test JSON parsing with markdown code blocks."""
        # Mock LLM response with markdown code block
        mock_llm.complete.return_value = LLMResponse(
            content='```json\n[{"producer": "Test", "name": "Wine", "type": "wine"}]\n```',
            tokens_used=100,
            cost=0.005,
            model="test-model",
            provider="test",
            latency_ms=100.0,
        )

        bottles = await extractor.extract(sample_parser_result, beverage_type="wine")

        assert len(bottles) == 1
        assert bottles[0].producer == "Test"

    @pytest.mark.asyncio
    async def test_extract_invalid_json(self, extractor, mock_llm, sample_parser_result):
        """Test extraction with invalid JSON response."""
        mock_llm.complete.return_value = LLMResponse(
            content="This is not JSON at all!",
            tokens_used=50,
            cost=0.003,
            model="test-model",
            provider="test",
            latency_ms=100.0,
        )

        with pytest.raises(ExtractionError, match="valid JSON"):
            await extractor.extract(sample_parser_result, beverage_type="wine")

    @pytest.mark.asyncio
    async def test_extract_non_array_json(self, extractor, mock_llm, sample_parser_result):
        """Test extraction with non-array JSON."""
        mock_llm.complete.return_value = LLMResponse(
            content='{"producer": "Test", "name": "Wine"}',
            tokens_used=50,
            cost=0.003,
            model="test-model",
            provider="test",
            latency_ms=100.0,
        )

        with pytest.raises(ExtractionError, match="JSON array"):
            await extractor.extract(sample_parser_result, beverage_type="wine")

    @pytest.mark.asyncio
    async def test_extract_with_invalid_bottle_data(self, extractor, mock_llm, sample_parser_result):
        """Test extraction with invalid bottle data (should skip invalid entries)."""
        # One valid, one invalid (missing required fields)
        mock_llm.complete.return_value = LLMResponse(
            content='[{"producer": "Valid", "name": "Wine", "type": "wine"}, {"name": "Invalid"}]',
            tokens_used=100,
            cost=0.005,
            model="test-model",
            provider="test",
            latency_ms=100.0,
        )

        bottles = await extractor.extract(sample_parser_result, beverage_type="wine")

        # Should only get the valid bottle
        assert len(bottles) == 1
        assert bottles[0].producer == "Valid"

    @pytest.mark.asyncio
    async def test_extract_llm_failure(self, extractor, mock_llm, sample_parser_result):
        """Test extraction when LLM call fails."""
        mock_llm.complete.side_effect = Exception("LLM API error")

        with pytest.raises(ExtractionError, match="Failed to extract bottles"):
            await extractor.extract(sample_parser_result, beverage_type="wine")

    @pytest.mark.asyncio
    async def test_auto_detect_type_wine(self, extractor, mock_llm):
        """Test auto-detection of wine type."""
        parser_result = ParserResult(
            raw_text="2019 Caymus Cabernet Sauvignon Napa Valley vintage",
            source_type="pdf",
            page_count=1,
            confidence=1.0,
        )

        # Mock type detection response
        mock_llm.complete.side_effect = [
            LLMResponse(content="wine", tokens_used=5, cost=0.001, model="test", provider="test", latency_ms=50.0),
            LLMResponse(
                content='[{"producer": "Caymus", "name": "Cabernet Sauvignon", "year": 2019, "type": "wine"}]',
                tokens_used=100,
                cost=0.005,
                model="test",
                provider="test",
                latency_ms=100.0,
            ),
        ]

        bottles = await extractor.extract(parser_result, beverage_type="auto")

        # Should have called LLM twice (type detection + extraction)
        assert mock_llm.complete.call_count == 2
        assert len(bottles) == 1

    @pytest.mark.asyncio
    async def test_auto_detect_type_whiskey(self, extractor, mock_llm):
        """Test auto-detection of whiskey type."""
        parser_result = ParserResult(
            raw_text="Buffalo Trace Bourbon 90 proof distillery barrel",
            source_type="pdf",
            page_count=1,
            confidence=1.0,
        )

        mock_llm.complete.side_effect = [
            LLMResponse(content="whiskey", tokens_used=5, cost=0.001, model="test", provider="test", latency_ms=50.0),
            LLMResponse(
                content='[{"producer": "Buffalo Trace", "name": "Bourbon", "type": "whiskey"}]',
                tokens_used=100,
                cost=0.005,
                model="test",
                provider="test",
                latency_ms=100.0,
            ),
        ]

        bottles = await extractor.extract(parser_result, beverage_type="auto")

        assert mock_llm.complete.call_count == 2
        assert len(bottles) == 1

    @pytest.mark.asyncio
    async def test_auto_detect_type_fallback(self, extractor, mock_llm, sample_parser_result):
        """Test auto-detection fallback when detection fails."""
        # Type detection fails
        mock_llm.complete.side_effect = [
            Exception("Type detection failed"),
            LLMResponse(
                content='[{"producer": "Test", "name": "Wine", "type": "wine"}]',
                tokens_used=100,
                cost=0.005,
                model="test",
                provider="test",
            latency_ms=100.0,
            ),
        ]

        # Should still extract successfully
        bottles = await extractor.extract(sample_parser_result, beverage_type="auto")

        assert len(bottles) == 1


# ============================================================================
# Confidence Calculation Tests
# ============================================================================


class TestConfidenceCalculation:
    """Tests for confidence scoring algorithm."""

    @pytest.fixture
    def mock_llm(self):
        llm = Mock()
        llm.complete = AsyncMock()
        return llm

    @pytest.fixture
    def extractor(self, mock_llm):
        return BottleExtractor(mock_llm)

    def test_confidence_all_fields_present(self, extractor):
        """Test confidence with all fields present."""
        bottle = BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            type="wine",
            year=2019,
            beverage_type="Red wine",
            variety="Cabernet Sauvignon",
            region="Napa Valley",
            country="United States",
            price=85.0,
            source="test",
        )

        confidence = extractor._calculate_confidence(bottle)

        # 0.5 (producer+name) + 0.2 (year) + 0.15 (type/variety) + 0.1 (region/country) + 0.05 (price) = 1.0
        assert confidence == 1.0

    def test_confidence_required_fields_only(self, extractor):
        """Test confidence with only required fields."""
        bottle = BottleMetadata(
            producer="Test Producer",
            name="Test Wine",
            type="wine",
            source="test",
        )

        confidence = extractor._calculate_confidence(bottle)

        # Only 0.5 for producer+name
        assert confidence == 0.5

    def test_confidence_missing_producer(self, extractor):
        """Test confidence with missing producer."""
        # Use model_construct to bypass validation
        bottle = BottleMetadata.model_construct(
            producer="",
            name="Test Wine",
            type="wine",
            year=2020,
            source="test",
        )

        confidence = extractor._calculate_confidence(bottle)

        # 0.2 (year) only, no points for producer+name
        assert confidence == 0.2

    def test_confidence_invalid_year(self, extractor):
        """Test confidence with invalid year."""
        # Use model_construct to bypass validation
        bottle = BottleMetadata.model_construct(
            producer="Test",
            name="Wine",
            type="wine",
            year=1500,  # Too old
            source="test",
        )

        confidence = extractor._calculate_confidence(bottle)

        # 0.5 only, no points for invalid year
        assert confidence == 0.5

    def test_confidence_future_year(self, extractor):
        """Test confidence with future year."""
        # Use model_construct to bypass validation
        bottle = BottleMetadata.model_construct(
            producer="Test",
            name="Wine",
            type="wine",
            year=2050,  # Too far in future
            source="test",
        )

        confidence = extractor._calculate_confidence(bottle)

        assert confidence == 0.5

    def test_confidence_with_variety_no_beverage_type(self, extractor):
        """Test confidence with variety but no beverage_type."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            variety="Cabernet Sauvignon",
            source="test",
        )

        confidence = extractor._calculate_confidence(bottle)

        # 0.5 + 0.15 (variety counts for type/variety)
        assert confidence == 0.65

    def test_confidence_with_region_no_country(self, extractor):
        """Test confidence with region but no country."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            region="Napa Valley",
            source="test",
        )

        confidence = extractor._calculate_confidence(bottle)

        # 0.5 + 0.1 (region counts)
        assert confidence == 0.6

    def test_confidence_zero_price(self, extractor):
        """Test confidence with zero price (should not count)."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            price=0.0,
            source="test",
        )

        confidence = extractor._calculate_confidence(bottle)

        # No points for zero price
        assert confidence == 0.5

    def test_confidence_negative_price(self, extractor):
        """Test confidence with negative price (invalid)."""
        # Use model_construct to bypass validation
        bottle = BottleMetadata.model_construct(
            producer="Test",
            name="Wine",
            type="wine",
            price=-10.0,
            source="test",
        )

        confidence = extractor._calculate_confidence(bottle)

        # No points for negative price
        assert confidence == 0.5


# ============================================================================
# ConfidenceAnalyzer Tests
# ============================================================================


class TestConfidenceAnalyzer:
    """Tests for ConfidenceAnalyzer."""

    @pytest.fixture
    def analyzer(self):
        """Create analyzer with default threshold."""
        return ConfidenceAnalyzer(review_threshold=0.7)

    @pytest.fixture
    def sample_bottles(self):
        """Create sample bottles with varying confidence."""
        return [
            BottleMetadata(
                producer="High Confidence",
                name="Wine 1",
                type="wine",
                year=2019,
                beverage_type="Red wine",
                region="Napa",
                country="USA",
                price=100.0,
                confidence=0.95,
                source="test",
            ),
            BottleMetadata(
                producer="Medium Confidence",
                name="Wine 2",
                type="wine",
                year=2020,
                confidence=0.65,
                source="test",
            ),
            BottleMetadata(
                producer="Low Confidence",
                name="Wine 3",
                type="wine",
                confidence=0.45,
                source="test",
            ),
            BottleMetadata(
                producer="High Confidence 2",
                name="Wine 4",
                type="wine",
                year=2018,
                beverage_type="White wine",
                confidence=0.85,
                source="test",
            ),
        ]

    def test_analyzer_initialization(self):
        """Test analyzer initialization with valid threshold."""
        analyzer = ConfidenceAnalyzer(review_threshold=0.8)
        assert analyzer.review_threshold == 0.8

    def test_analyzer_invalid_threshold_low(self):
        """Test analyzer with threshold below 0."""
        with pytest.raises(ValueError, match="between 0 and 1"):
            ConfidenceAnalyzer(review_threshold=-0.1)

    def test_analyzer_invalid_threshold_high(self):
        """Test analyzer with threshold above 1."""
        with pytest.raises(ValueError, match="between 0 and 1"):
            ConfidenceAnalyzer(review_threshold=1.5)

    def test_analyze_split(self, analyzer, sample_bottles):
        """Test splitting bottles into high confidence and needs review."""
        high_conf, needs_review = analyzer.analyze(sample_bottles)

        # Threshold is 0.7, so:
        # High: 0.95, 0.85 (2 bottles)
        # Review: 0.65, 0.45 (2 bottles)
        assert len(high_conf) == 2
        assert len(needs_review) == 2

        # Verify correct categorization
        assert all(b.confidence >= 0.7 for b in high_conf)
        assert all(b.confidence < 0.7 for b in needs_review)

    def test_analyze_all_high_confidence(self, analyzer):
        """Test when all bottles have high confidence."""
        bottles = [
            BottleMetadata(producer="Test", name="Wine", type="wine", confidence=0.9, source="test"),
            BottleMetadata(producer="Test", name="Wine", type="wine", confidence=0.8, source="test"),
        ]

        high_conf, needs_review = analyzer.analyze(bottles)

        assert len(high_conf) == 2
        assert len(needs_review) == 0

    def test_analyze_all_low_confidence(self, analyzer):
        """Test when all bottles need review."""
        bottles = [
            BottleMetadata(producer="Test", name="Wine", type="wine", confidence=0.5, source="test"),
            BottleMetadata(producer="Test", name="Wine", type="wine", confidence=0.3, source="test"),
        ]

        high_conf, needs_review = analyzer.analyze(bottles)

        assert len(high_conf) == 0
        assert len(needs_review) == 2

    def test_analyze_empty_list(self, analyzer):
        """Test with empty bottle list."""
        high_conf, needs_review = analyzer.analyze([])

        assert len(high_conf) == 0
        assert len(needs_review) == 0

    def test_analyze_threshold_edge_case(self, analyzer):
        """Test bottle exactly at threshold."""
        bottles = [
            BottleMetadata(producer="Test", name="Wine", type="wine", confidence=0.7, source="test"),
        ]

        high_conf, needs_review = analyzer.analyze(bottles)

        # Exactly at threshold should be high confidence (>=)
        assert len(high_conf) == 1
        assert len(needs_review) == 0

    def test_get_statistics(self, analyzer, sample_bottles):
        """Test statistics calculation."""
        stats = analyzer.get_statistics(sample_bottles)

        assert stats["count"] == 4
        assert stats["mean"] == pytest.approx(0.725)  # (0.95 + 0.65 + 0.45 + 0.85) / 4
        assert stats["min"] == 0.45
        assert stats["max"] == 0.95
        assert stats["high_confidence_count"] == 2
        assert stats["needs_review_count"] == 2
        assert stats["threshold"] == 0.7

    def test_get_statistics_empty(self, analyzer):
        """Test statistics with empty list."""
        stats = analyzer.get_statistics([])

        assert stats["count"] == 0
        assert stats["mean"] == 0.0
        assert stats["min"] == 0.0
        assert stats["max"] == 0.0
        assert stats["high_confidence_count"] == 0
        assert stats["needs_review_count"] == 0

    def test_get_low_confidence_reasons_complete_bottle(self, analyzer):
        """Test reasons for complete bottle (should have no issues)."""
        bottle = BottleMetadata(
            producer="Test Producer",
            name="Test Wine",
            type="wine",
            year=2020,
            beverage_type="Red wine",
            variety="Cabernet",
            region="Napa",
            country="USA",
            price=50.0,
            source="test",
        )

        reasons = analyzer.get_low_confidence_reasons(bottle)

        assert len(reasons) == 0

    def test_get_low_confidence_reasons_missing_producer(self, analyzer):
        """Test reasons when producer is missing."""
        # Use model_construct to bypass validation
        bottle = BottleMetadata.model_construct(
            producer="",
            name="Wine",
            type="wine",
            source="test",
        )

        reasons = analyzer.get_low_confidence_reasons(bottle)

        assert "Missing producer or name" in reasons

    def test_get_low_confidence_reasons_missing_year(self, analyzer):
        """Test reasons when year is missing."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            source="test",
        )

        reasons = analyzer.get_low_confidence_reasons(bottle)

        assert "Missing year/vintage" in reasons

    def test_get_low_confidence_reasons_invalid_year(self, analyzer):
        """Test reasons for invalid year."""
        # Use model_construct to bypass validation
        bottle = BottleMetadata.model_construct(
            producer="Test",
            name="Wine",
            type="wine",
            year=1500,
            source="test",
        )

        reasons = analyzer.get_low_confidence_reasons(bottle)

        assert any("Invalid year" in r for r in reasons)

    def test_get_low_confidence_reasons_missing_type_and_variety(self, analyzer):
        """Test reasons when both type and variety are missing."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            source="test",
        )

        reasons = analyzer.get_low_confidence_reasons(bottle)

        assert "Missing beverage type or variety" in reasons

    def test_get_low_confidence_reasons_missing_location(self, analyzer):
        """Test reasons when region and country are missing."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            source="test",
        )

        reasons = analyzer.get_low_confidence_reasons(bottle)

        assert "Missing region and country" in reasons

    def test_get_low_confidence_reasons_missing_price(self, analyzer):
        """Test reasons when price is missing."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            source="test",
        )

        reasons = analyzer.get_low_confidence_reasons(bottle)

        assert "Missing price information" in reasons

    def test_get_low_confidence_reasons_multiple(self, analyzer):
        """Test multiple reasons for low confidence."""
        # Use model_construct to bypass validation
        bottle = BottleMetadata.model_construct(
            producer="",
            name="Wine",
            type="wine",
            year=3000,
            source="test",
        )

        reasons = analyzer.get_low_confidence_reasons(bottle)

        # Should have multiple reasons
        assert len(reasons) >= 2
        assert "Missing producer or name" in reasons
        assert any("Invalid year" in r for r in reasons)


# ============================================================================
# Integration-style Tests
# ============================================================================


class TestExtractionIntegration:
    """Integration-style tests for extraction workflow."""

    @pytest.fixture
    def mock_llm(self):
        llm = Mock()
        llm.complete = AsyncMock()
        return llm

    @pytest.fixture
    def extractor(self, mock_llm):
        return BottleExtractor(mock_llm)

    @pytest.fixture
    def analyzer(self):
        return ConfidenceAnalyzer(review_threshold=0.7)

    @pytest.mark.asyncio
    async def test_full_extraction_workflow(self, extractor, analyzer, mock_llm):
        """Test complete extraction and analysis workflow."""
        # Setup parser result
        parser_result = ParserResult(
            raw_text="2019 Caymus Cabernet $85\nBuffalo Trace Bourbon $25",
            source_type="pdf",
            page_count=1,
            confidence=1.0,
        )

        # Mock LLM to return multiple bottles
        mock_llm.complete.return_value = LLMResponse(
            content='[{"producer": "Caymus", "name": "Cabernet Sauvignon", "year": 2019, "type": "wine", "beverage_type": "Red wine", "region": "Napa Valley", "country": "United States", "price": 85.0}, {"producer": "Buffalo Trace", "name": "Bourbon", "type": "whiskey", "proof": 90, "price": 25.0}]',
            tokens_used=200,
            cost=0.01,
            model="test-model",
            provider="test",
            latency_ms=100.0,
        )

        # Extract bottles
        bottles = await extractor.extract(parser_result, beverage_type="auto")

        # Analyze confidence
        high_conf, needs_review = analyzer.analyze(bottles)

        # Verify workflow
        assert len(bottles) == 2
        assert bottles[0].type == "wine"
        assert bottles[1].type == "whiskey"

        # Wine should have higher confidence (more fields)
        # Whiskey should need review (fewer fields)
        assert len(high_conf) >= 1
        assert all(b.confidence >= 0.7 for b in high_conf)
