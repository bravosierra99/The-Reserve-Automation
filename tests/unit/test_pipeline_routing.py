"""Unit tests for extraction_pipeline routing logic."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from reserve_automation.core.models import BottleMetadata, ParserResult


class TestPipelineRouting:
    """Tests verifying pipeline.py routes image vs non-image inputs to the right extractor."""

    @pytest.fixture
    def config(self):
        return {"llm": {}, "parsers": {}, "extraction": {}}

    @pytest.fixture
    def sample_bottle(self):
        return BottleMetadata(producer="Test Winery", name="Test Wine", type="wine", source="test")

    @pytest.mark.asyncio
    async def test_image_source_routes_to_image_extractor(self, config, sample_bottle):
        """source_type='image' calls ImageMetadataExtractor; BottleExtractor is never instantiated."""
        parser_result = ParserResult(source_type="image", raw_text="")

        with patch("reserve_automation.pipeline.LLMGateway"), \
             patch("reserve_automation.pipeline.ParserDetector") as mock_parser_cls, \
             patch("reserve_automation.extractors.image_extractor.ImageMetadataExtractor") as mock_img_cls, \
             patch("reserve_automation.pipeline.BottleExtractor") as mock_bottle_cls, \
             patch("reserve_automation.pipeline.ConfidenceAnalyzer") as mock_conf_cls:

            mock_parser_cls.return_value.parse = AsyncMock(return_value=parser_result)
            mock_img_cls.return_value.extract_from_image = AsyncMock(
                return_value=(sample_bottle, {"success": True})
            )
            mock_conf_cls.return_value.analyze = Mock(return_value=([sample_bottle], []))

            from reserve_automation.pipeline import extraction_pipeline
            await extraction_pipeline(Path("/tmp/test.jpg"), config, input_type="auto")

            mock_img_cls.assert_called_once()
            mock_bottle_cls.return_value.extract.assert_not_called()

    @pytest.mark.asyncio
    async def test_pdf_source_routes_to_bottle_extractor(self, config, sample_bottle):
        """source_type='pdf' calls BottleExtractor; ImageMetadataExtractor is never instantiated."""
        parser_result = ParserResult(source_type="pdf", raw_text="Test wine text")

        with patch("reserve_automation.pipeline.LLMGateway"), \
             patch("reserve_automation.pipeline.ParserDetector") as mock_parser_cls, \
             patch("reserve_automation.extractors.image_extractor.ImageMetadataExtractor") as mock_img_cls, \
             patch("reserve_automation.pipeline.BottleExtractor") as mock_bottle_cls, \
             patch("reserve_automation.pipeline.ConfidenceAnalyzer") as mock_conf_cls:

            mock_parser_cls.return_value.parse = AsyncMock(return_value=parser_result)
            mock_bottle_cls.return_value.extract = AsyncMock(return_value=[sample_bottle])
            mock_conf_cls.return_value.analyze = Mock(return_value=([sample_bottle], []))

            from reserve_automation.pipeline import extraction_pipeline
            await extraction_pipeline(Path("/tmp/test.pdf"), config, input_type="auto")

            mock_bottle_cls.return_value.extract.assert_called_once()
            mock_img_cls.assert_not_called()

    @pytest.mark.asyncio
    async def test_image_extractor_result_wrapped_in_list(self, config, sample_bottle):
        """Pipeline wraps the single bottle from ImageMetadataExtractor in a list."""
        parser_result = ParserResult(source_type="image", raw_text="")

        with patch("reserve_automation.pipeline.LLMGateway"), \
             patch("reserve_automation.pipeline.ParserDetector") as mock_parser_cls, \
             patch("reserve_automation.extractors.image_extractor.ImageMetadataExtractor") as mock_img_cls, \
             patch("reserve_automation.pipeline.ConfidenceAnalyzer") as mock_conf_cls:

            mock_parser_cls.return_value.parse = AsyncMock(return_value=parser_result)
            mock_img_cls.return_value.extract_from_image = AsyncMock(
                return_value=(sample_bottle, {"success": True})
            )
            mock_conf_cls.return_value.analyze = Mock(return_value=([sample_bottle], []))

            from reserve_automation.pipeline import extraction_pipeline
            result = await extraction_pipeline(Path("/tmp/test.jpg"), config, input_type="auto")

            assert result.total_extracted == 1
            assert result.bottles == [sample_bottle]

    @pytest.mark.asyncio
    async def test_image_extractor_none_result_produces_empty_list(self, config):
        """When ImageMetadataExtractor returns (None, ...), pipeline produces 0 bottles."""
        parser_result = ParserResult(source_type="image", raw_text="")

        with patch("reserve_automation.pipeline.LLMGateway"), \
             patch("reserve_automation.pipeline.ParserDetector") as mock_parser_cls, \
             patch("reserve_automation.extractors.image_extractor.ImageMetadataExtractor") as mock_img_cls, \
             patch("reserve_automation.pipeline.ConfidenceAnalyzer") as mock_conf_cls:

            mock_parser_cls.return_value.parse = AsyncMock(return_value=parser_result)
            mock_img_cls.return_value.extract_from_image = AsyncMock(
                return_value=(None, {"error": "extraction failed"})
            )
            mock_conf_cls.return_value.analyze = Mock(return_value=([], []))

            from reserve_automation.pipeline import extraction_pipeline
            result = await extraction_pipeline(Path("/tmp/test.jpg"), config, input_type="auto")

            assert result.total_extracted == 0
            assert result.bottles == []
