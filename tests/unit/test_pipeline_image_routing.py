"""Tests for the ``parser_result.source_type == "image"`` branch in the pipeline.

When the parser identifies the input as an image, the pipeline must use
``ImageMetadataExtractor.extract_from_image`` (vision LLM directly) rather
than running OCR text through the generic ``BottleExtractor``. See
``src/reserve_automation/pipeline.py`` around line 83.
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from reserve_automation.core.models import (
    BottleMetadata,
    ParserResult,
)
from reserve_automation.pipeline import extraction_pipeline


def _bottle(name="Test Wine"):
    return BottleMetadata(
        producer="Test Producer",
        name=name,
        type="wine",
        beverage_type="Red wine",
        source="test",
    )


@pytest.fixture
def fake_image_file(tmp_path):
    f = tmp_path / "label.jpg"
    f.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")  # minimal JPEG-ish bytes
    return f


@pytest.fixture
def fake_pdf_file(tmp_path):
    f = tmp_path / "list.pdf"
    f.write_bytes(b"%PDF-1.4 fake")
    return f


@pytest.fixture
def base_config():
    return {
        "llm": {},
        "parsers": {},
        "extraction": {"confidence_threshold": 0.7},
    }


class TestPipelineSourceTypeRouting:
    """Verify the routing decision at the source_type branch."""

    async def test_image_source_type_uses_image_extractor(self, fake_image_file, base_config):
        # Parser claims the input is an image
        parser_result = ParserResult(
            raw_text="(unused for image branch)",
            source_type="image",
            page_count=1,
            confidence=1.0,
        )

        with (
            patch(
                "reserve_automation.parsers.ParserDetector.parse",
                new=AsyncMock(return_value=parser_result),
            ),
            patch(
                "reserve_automation.extractors.image_extractor.ImageMetadataExtractor.extract_from_image",
                new=AsyncMock(return_value=(_bottle("Vision Wine"), {})),
            ) as mock_image_extract,
            patch(
                "reserve_automation.extractors.BottleExtractor.extract",
                new=AsyncMock(return_value=[_bottle("OCR Wine")]),
            ) as mock_text_extract,
        ):
            result = await extraction_pipeline(
                fake_image_file, base_config, input_type="auto", beverage_type="auto"
            )

        # Image extractor must be the one called
        mock_image_extract.assert_awaited_once()
        # And the text extractor must NOT be called
        mock_text_extract.assert_not_awaited()

        # And it received the actual file path
        called_args = mock_image_extract.await_args
        assert called_args.args[0] == fake_image_file
        # beverage_type=auto from the pipeline maps to None for the image extractor
        assert called_args.kwargs.get("beverage_type") is None

        # And the bottle from the image extractor is what flows through
        assert any(b.name == "Vision Wine" for b in result.bottles)

    async def test_image_source_type_passes_explicit_beverage_type(
        self, fake_image_file, base_config
    ):
        parser_result = ParserResult(
            raw_text="",
            source_type="image",
            page_count=1,
            confidence=1.0,
        )

        with (
            patch(
                "reserve_automation.parsers.ParserDetector.parse",
                new=AsyncMock(return_value=parser_result),
            ),
            patch(
                "reserve_automation.extractors.image_extractor.ImageMetadataExtractor.extract_from_image",
                new=AsyncMock(return_value=(_bottle(), {})),
            ) as mock_image_extract,
        ):
            await extraction_pipeline(
                fake_image_file, base_config, input_type="auto", beverage_type="wine"
            )

        # Explicit beverage_type must be forwarded (NOT None)
        assert mock_image_extract.await_args.kwargs.get("beverage_type") == "wine"

    async def test_pdf_source_type_uses_text_bottle_extractor(
        self, fake_pdf_file, base_config
    ):
        parser_result = ParserResult(
            raw_text="2019 Caymus Cabernet Sauvignon Napa Valley $85",
            source_type="pdf",
            page_count=1,
            confidence=1.0,
        )

        with (
            patch(
                "reserve_automation.parsers.ParserDetector.parse",
                new=AsyncMock(return_value=parser_result),
            ),
            patch(
                "reserve_automation.extractors.image_extractor.ImageMetadataExtractor.extract_from_image",
                new=AsyncMock(return_value=(_bottle(), {})),
            ) as mock_image_extract,
            patch(
                "reserve_automation.extractors.BottleExtractor.extract",
                new=AsyncMock(return_value=[_bottle("PDF Wine")]),
            ) as mock_text_extract,
        ):
            result = await extraction_pipeline(
                fake_pdf_file, base_config, input_type="auto", beverage_type="wine"
            )

        # The text extractor must be the one called for PDF
        mock_text_extract.assert_awaited_once()
        mock_image_extract.assert_not_awaited()
        assert any(b.name == "PDF Wine" for b in result.bottles)

    async def test_image_extractor_returning_none_yields_empty_bottles(
        self, fake_image_file, base_config
    ):
        """If the image extractor fails, the pipeline must produce an empty bottle list, not crash."""
        parser_result = ParserResult(
            raw_text="",
            source_type="image",
            page_count=1,
            confidence=1.0,
        )

        with (
            patch(
                "reserve_automation.parsers.ParserDetector.parse",
                new=AsyncMock(return_value=parser_result),
            ),
            patch(
                "reserve_automation.extractors.image_extractor.ImageMetadataExtractor.extract_from_image",
                new=AsyncMock(return_value=(None, {"error": "boom"})),
            ),
        ):
            result = await extraction_pipeline(
                fake_image_file, base_config, input_type="auto"
            )

        assert result.bottles == []
