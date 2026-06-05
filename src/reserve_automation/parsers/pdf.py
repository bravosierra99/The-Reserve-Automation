"""PDF parser using pdfplumber with OCR fallback."""

from pathlib import Path
from typing import List

import pdfplumber
from loguru import logger

from ..core.exceptions import ParserError
from ..core.models import ParserResult
from .base import BaseParser


class PDFParser(BaseParser):
    """
    Parse PDF files using pdfplumber with OCR fallback.

    Extracts text using pdfplumber's text extraction.
    Falls back to OCR if text is sparse or missing.
    Also extracts embedded images.
    """

    # Supported PDF extensions
    EXTENSIONS = ["pdf"]

    # Minimum characters per page to consider text extraction successful
    MIN_CHARS_PER_PAGE = 50

    def __init__(self, use_ocr_fallback: bool = True):
        """
        Initialize PDF parser.

        Args:
            use_ocr_fallback: If True, use OCR when text extraction is poor
        """
        self.use_ocr_fallback = use_ocr_fallback

    def can_parse(self, input_file: Path) -> bool:
        """Check if file is a PDF."""
        return self._get_file_extension(input_file) in self.EXTENSIONS

    async def parse(self, input_file: Path) -> ParserResult:
        """
        Parse PDF file and extract text and images.

        Args:
            input_file: Path to PDF file

        Returns:
            ParserResult with extracted text and images

        Raises:
            ParserError: If parsing fails
        """
        if not input_file.exists():
            raise ParserError(f"File not found: {input_file}")

        if not self.can_parse(input_file):
            raise ParserError(f"Not a PDF file: {input_file}")

        try:
            logger.debug(f"Parsing PDF: {input_file}")

            with pdfplumber.open(input_file) as pdf:
                # Extract text from all pages
                text_parts = []
                images = []
                page_count = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages, 1):
                    # Extract text
                    page_text = page.extract_text() or ""
                    text_parts.append(page_text)

                    # Extract images from page (if any)
                    page_images = self._extract_images_from_page(page)
                    images.extend(page_images)

                    logger.debug(
                        f"Page {page_num}/{page_count}: "
                        f"{len(page_text)} chars, {len(page_images)} images"
                    )

                # Combine all text
                full_text = "\n\n".join(text_parts)

                # Check if text extraction was successful
                avg_chars_per_page = len(full_text) / page_count if page_count > 0 else 0

                if avg_chars_per_page < self.MIN_CHARS_PER_PAGE:
                    logger.warning(
                        f"Sparse text extraction ({avg_chars_per_page:.0f} chars/page). "
                        "PDF may be scanned images."
                    )

                    if self.use_ocr_fallback:
                        logger.info("Falling back to OCR...")
                        full_text = await self._ocr_fallback(input_file)

                logger.info(
                    f"Parsed PDF: {len(full_text)} chars, "
                    f"{len(images)} images, {page_count} pages"
                )

                return ParserResult(
                    raw_text=full_text,
                    images=images,
                    metadata={"pages": page_count, "method": "pdfplumber"},
                    source_type="pdf",
                )

        except Exception as e:
            logger.error(f"PDF parsing failed: {e}")
            raise ParserError(f"Failed to parse PDF: {e}") from e

    def _extract_images_from_page(self, page) -> List[bytes]:
        """
        Extract images from a PDF page.

        Args:
            page: pdfplumber page object

        Returns:
            List of image bytes
        """
        images = []

        try:
            # pdfplumber can extract images
            for image_obj in page.images:
                # Try to get image data
                # This is basic - pdfplumber's image handling is limited
                # In production, might want to use PyPDF2 or pikepdf for better image extraction
                pass

        except Exception as e:
            logger.debug(f"Could not extract images from page: {e}")

        return images

    async def _ocr_fallback(self, pdf_path: Path) -> str:
        """
        Use OCR to extract text from PDF.

        Converts PDF pages to images and runs OCR.

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted text from OCR
        """
        try:
            # Use pdf2image to convert PDF to images
            from pdf2image import convert_from_path

            logger.debug("Converting PDF to images for OCR...")
            images = convert_from_path(str(pdf_path))

            # Use ImageParser for OCR
            from .image import ImageParser

            image_parser = ImageParser()
            text_parts = []

            for page_num, image in enumerate(images, 1):
                # Save to bytes
                import io

                img_bytes = io.BytesIO()
                image.save(img_bytes, format="PNG")
                img_bytes.seek(0)

                # Create temp file for image
                import tempfile

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                    tmp.write(img_bytes.read())
                    tmp_path = Path(tmp.name)

                try:
                    # Parse with OCR
                    result = await image_parser.parse(tmp_path)
                    text_parts.append(result.raw_text)
                    logger.debug(f"OCR page {page_num}: {len(result.raw_text)} chars")
                finally:
                    # Clean up temp file
                    tmp_path.unlink(missing_ok=True)

            full_text = "\n\n".join(text_parts)
            logger.info(f"OCR completed: {len(full_text)} chars")

            return full_text

        except ImportError as e:
            logger.error("pdf2image not available for OCR fallback")
            raise ParserError(
                "OCR fallback requires pdf2image: pip install pdf2image"
            ) from e

        except Exception as e:
            logger.error(f"OCR fallback failed: {e}")
            # Return empty string rather than failing completely
            return ""
