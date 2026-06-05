"""Unit tests for input parsers."""

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from reserve_automation.core.exceptions import ParserError, UnsupportedFileTypeError
from reserve_automation.parsers import ImageParser, ParserDetector, PDFParser


@pytest.fixture
def temp_dir(tmp_path):
    """Create temporary directory for test files."""
    return tmp_path


@pytest.fixture
def sample_image_bytes():
    """Create a sample image as bytes."""
    img = Image.new("RGB", (100, 100), color="white")

    # Add some text-like patterns
    from PIL import ImageDraw

    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "Test Wine Label", fill="black")

    img_bytes = io.BytesIO()
    img.save(img_bytes, format="PNG")
    return img_bytes.getvalue()


@pytest.fixture
def sample_image_file(temp_dir, sample_image_bytes):
    """Create a sample image file."""
    image_path = temp_dir / "test_label.png"
    image_path.write_bytes(sample_image_bytes)
    return image_path


class TestImageParser:
    """Tests for ImageParser."""

    @pytest.mark.asyncio
    async def test_can_parse_image(self, sample_image_file):
        """Test that ImageParser recognizes image files."""
        parser = ImageParser()
        assert parser.can_parse(sample_image_file) is True

    @pytest.mark.asyncio
    async def test_can_parse_pdf_false(self, temp_dir):
        """Test that ImageParser rejects PDFs."""
        parser = ImageParser()
        pdf_path = temp_dir / "test.pdf"
        assert parser.can_parse(pdf_path) is False

    @pytest.mark.asyncio
    @patch("reserve_automation.parsers.image.pytesseract.image_to_string")
    async def test_parse_image(self, mock_ocr, sample_image_file):
        """Test parsing an image file."""
        mock_ocr.return_value = "Extracted text from image"

        parser = ImageParser(preprocess=False, ocr_method="tesseract")  # Use tesseract explicitly
        result = await parser.parse(sample_image_file)

        assert result.raw_text == "Extracted text from image"
        assert result.source_type == "image"
        assert len(result.images) == 1
        assert result.metadata["dimensions"] == (100, 100)

    @pytest.mark.asyncio
    async def test_parse_nonexistent_file(self):
        """Test error when file doesn't exist."""
        parser = ImageParser()

        with pytest.raises(ParserError, match="File not found"):
            await parser.parse(Path("/nonexistent/file.png"))

    @pytest.mark.asyncio
    async def test_parse_wrong_format(self, temp_dir):
        """Test error when file format is wrong."""
        parser = ImageParser()
        pdf_path = temp_dir / "test.pdf"
        pdf_path.write_text("fake pdf")

        with pytest.raises(ParserError, match="Unsupported image format"):
            await parser.parse(pdf_path)


class TestPDFParser:
    """Tests for PDFParser."""

    def test_can_parse_pdf(self, temp_dir):
        """Test that PDFParser recognizes PDF files."""
        parser = PDFParser()
        pdf_path = temp_dir / "test.pdf"
        assert parser.can_parse(pdf_path) is True

    def test_can_parse_image_false(self, sample_image_file):
        """Test that PDFParser rejects images."""
        parser = PDFParser()
        assert parser.can_parse(sample_image_file) is False

    @pytest.mark.asyncio
    @patch("pdfplumber.open")
    async def test_parse_pdf(self, mock_pdfplumber, temp_dir):
        """Test parsing a PDF file."""
        # Mock PDF with one page
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Wine list page 1\nChateau Example 2020"
        mock_page.images = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)

        mock_pdfplumber.return_value = mock_pdf

        # Create fake PDF file
        pdf_path = temp_dir / "wine_list.pdf"
        pdf_path.write_bytes(b"%PDF-1.4 fake content")

        parser = PDFParser(use_ocr_fallback=False)
        result = await parser.parse(pdf_path)

        assert "Wine list" in result.raw_text
        assert "Chateau Example" in result.raw_text
        assert result.source_type == "pdf"
        assert result.metadata["pages"] == 1

    @pytest.mark.asyncio
    async def test_parse_nonexistent_pdf(self):
        """Test error when PDF doesn't exist."""
        parser = PDFParser()

        with pytest.raises(ParserError, match="File not found"):
            await parser.parse(Path("/nonexistent/file.pdf"))


class TestParserDetector:
    """Tests for ParserDetector."""

    @pytest.mark.asyncio
    @patch("reserve_automation.parsers.image.pytesseract.image_to_string")
    async def test_auto_detect_image(self, mock_ocr, sample_image_file):
        """Test auto-detection of image files."""
        # Mock tesseract to return enough text to pass quality check
        mock_ocr.return_value = "Test text with enough characters to pass quality threshold for good OCR output"

        detector = ParserDetector()
        result = await detector.parse(sample_image_file)

        assert result.source_type == "image"

    @pytest.mark.asyncio
    @patch("pdfplumber.open")
    async def test_auto_detect_pdf(self, mock_pdfplumber, temp_dir):
        """Test auto-detection of PDF files."""
        # Mock PDF
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Test content"
        mock_page.images = []

        mock_pdf = MagicMock()
        mock_pdf.pages = [mock_page]
        mock_pdf.__enter__ = MagicMock(return_value=mock_pdf)
        mock_pdf.__exit__ = MagicMock(return_value=None)

        mock_pdfplumber.return_value = mock_pdf

        pdf_path = temp_dir / "test.pdf"
        pdf_path.write_bytes(b"%PDF-1.4")

        detector = ParserDetector()
        result = await detector.parse(pdf_path)

        assert result.source_type == "pdf"

    @pytest.mark.asyncio
    async def test_unsupported_file_type(self, temp_dir):
        """Test error for unsupported file types."""
        unsupported = temp_dir / "test.xyz"
        unsupported.write_text("unsupported content")

        detector = ParserDetector()

        with pytest.raises(UnsupportedFileTypeError, match="No parser available"):
            await detector.parse(unsupported)

    def test_detect_type_image(self, sample_image_file):
        """Test type detection for images."""
        detector = ParserDetector()
        assert detector.detect_type(sample_image_file) == "image"

    def test_detect_type_pdf(self, temp_dir):
        """Test type detection for PDFs."""
        pdf_path = temp_dir / "test.pdf"
        pdf_path.write_bytes(b"fake")

        detector = ParserDetector()
        assert detector.detect_type(pdf_path) == "pdf"

    def test_detect_type_unsupported(self, temp_dir):
        """Test type detection for unsupported files."""
        unknown = temp_dir / "test.xyz"
        unknown.write_text("unknown")

        detector = ParserDetector()
        assert detector.detect_type(unknown) is None
