"""Image parser using OCR."""

from pathlib import Path
import io
import base64
from typing import Literal, Optional

from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
from loguru import logger

from ..core.exceptions import ParserError
from ..core.models import ParserResult
from .base import BaseParser


class ImageParser(BaseParser):
    """
    Parse images using OCR (tesseract or vision model).

    Supports multiple OCR methods with smart auto-fallback:
    - tesseract: Fast, local OCR (requires tesseract installed)
    - vision: Vision model OCR via LLM (slower but more accurate)
    - auto: Try tesseract first, fall back to vision if output is poor
    """

    # Supported image extensions
    EXTENSIONS = ["jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp"]

    # Minimum characters per image for "good" OCR quality
    MIN_CHARS_THRESHOLD = 50

    def __init__(
        self,
        preprocess: bool = True,
        deskew: bool = True,
        denoise: bool = True,
        enhance_contrast: bool = True,
        language: str = "eng",
        ocr_method: Literal["tesseract", "vision", "auto"] = "auto",
        llm_gateway=None,
    ):
        """
        Initialize image parser.

        Args:
            preprocess: Apply preprocessing for better OCR
            deskew: Attempt to deskew rotated images
            denoise: Apply denoising filter
            enhance_contrast: Enhance image contrast
            language: OCR language (default: English)
            ocr_method: OCR method to use (tesseract/vision/auto)
            llm_gateway: LLM Gateway instance for vision-based OCR
        """
        self.preprocess = preprocess
        self.deskew = deskew
        self.denoise = denoise
        self.enhance_contrast = enhance_contrast
        self.language = language
        self.ocr_method = ocr_method
        self.llm_gateway = llm_gateway

    def can_parse(self, input_file: Path) -> bool:
        """Check if file is a supported image format."""
        return self._get_file_extension(input_file) in self.EXTENSIONS

    async def parse(self, input_file: Path) -> ParserResult:
        """
        Parse image file using OCR.

        Args:
            input_file: Path to image file

        Returns:
            ParserResult with extracted text

        Raises:
            ParserError: If parsing fails
        """
        if not input_file.exists():
            raise ParserError(f"File not found: {input_file}")

        if not self.can_parse(input_file):
            raise ParserError(f"Unsupported image format: {input_file}")

        try:
            logger.debug(f"Parsing image: {input_file}")

            # Load image
            image = Image.open(input_file)
            original_size = image.size

            # Preprocess if enabled
            if self.preprocess and self.ocr_method != "vision":
                image = self._preprocess_image(image)

            # Convert image to bytes for storage
            img_bytes_io = io.BytesIO()
            image.save(img_bytes_io, format="PNG")
            img_bytes = img_bytes_io.getvalue()

            # Perform OCR based on method
            text = None
            ocr_method_used = None

            if self.ocr_method == "tesseract":
                text = await self._ocr_tesseract(image)
                ocr_method_used = "tesseract"

            elif self.ocr_method == "vision":
                text = await self._ocr_vision(img_bytes)
                ocr_method_used = "vision"

            elif self.ocr_method == "auto":
                # Try tesseract first
                try:
                    text = await self._ocr_tesseract(image)
                    ocr_method_used = "tesseract"

                    # Check if quality is poor
                    if self._is_poor_quality(text, image_size=original_size):
                        logger.warning(
                            f"Tesseract OCR produced poor quality output ({len(text)} chars). "
                            "Falling back to vision model..."
                        )
                        text = await self._ocr_vision(img_bytes)
                        ocr_method_used = "vision (fallback)"
                    else:
                        logger.info("Tesseract OCR quality acceptable, using result")

                except Exception as e:
                    logger.warning(f"Tesseract OCR failed: {e}. Falling back to vision model...")
                    text = await self._ocr_vision(img_bytes)
                    ocr_method_used = "vision (fallback)"

            logger.info(
                f"Parsed image: {len(text)} chars, "
                f"size: {original_size[0]}x{original_size[1]}, "
                f"method: {ocr_method_used}"
            )

            return ParserResult(
                raw_text=text,
                images=[img_bytes],
                metadata={
                    "dimensions": original_size,
                    "preprocessed": self.preprocess,
                    "ocr_method": ocr_method_used,
                },
                source_type="image",
            )

        except Exception as e:
            logger.error(f"Image parsing failed: {e}")
            raise ParserError(f"Failed to parse image: {e}") from e

    async def _ocr_tesseract(self, image: Image.Image) -> str:
        """
        Perform OCR using tesseract.

        Args:
            image: PIL Image to OCR

        Returns:
            Extracted text

        Raises:
            Exception: If tesseract fails
        """
        logger.debug("Running Tesseract OCR...")
        text = pytesseract.image_to_string(image, lang=self.language)
        return text

    async def _ocr_vision(self, img_bytes: bytes) -> str:
        """
        Perform OCR using vision model via LLM Gateway.

        Args:
            img_bytes: Image as bytes

        Returns:
            Extracted text

        Raises:
            ParserError: If vision model fails or not configured
        """
        if not self.llm_gateway:
            raise ParserError(
                "Vision model OCR requested but LLM Gateway not configured. "
                "Either install tesseract or configure LLM Gateway."
            )

        logger.debug("Running vision model OCR...")

        # Encode image to base64 for LLM
        # (Already in bytes, vision models typically expect this)

        # Create OCR prompt (keep short to save context tokens for output)
        ocr_prompt = """Extract all text from this image, top to bottom. Return only the text, preserving line breaks. Do not repeat lines."""

        try:
            response = await self.llm_gateway.complete(
                task_type="ocr",
                prompt=ocr_prompt,
                images=[img_bytes],
                temperature=0.0,  # Deterministic for OCR
                max_tokens=2000,  # Reserve context for output
            )

            text = response.content.strip()
            logger.info(f"Vision model extracted {len(text)} characters")
            return text

        except Exception as e:
            raise ParserError(f"Vision model OCR failed: {e}") from e

    def _is_poor_quality(self, text: str, image_size: tuple[int, int] = None) -> bool:
        """
        Detect if OCR output is poor quality or incomplete.

        Args:
            text: OCR extracted text
            image_size: Optional (width, height) of the image in pixels

        Returns:
            True if quality is poor, False otherwise
        """
        # Check if text is too sparse
        if len(text.strip()) < self.MIN_CHARS_THRESHOLD:
            return True

        # Check for excessive gibberish (high ratio of non-alphanumeric chars)
        if not text:
            return True

        alphanumeric = sum(c.isalnum() or c.isspace() for c in text)
        total = len(text)

        if total > 0:
            ratio = alphanumeric / total
            # If less than 60% alphanumeric+space, likely gibberish
            if ratio < 0.6:
                return True

        # Check for incomplete extraction based on image size
        # Large images (photos/scans) should produce more text
        if image_size:
            width, height = image_size
            total_pixels = width * height

            # For images > 1MP, expect at least 0.0001 chars/pixel
            # e.g., 3024x4032 (12MP) should have ~1200+ chars for a document
            if total_pixels > 1_000_000:  # 1 megapixel
                min_expected_chars = total_pixels * 0.0001
                if len(text) < min_expected_chars:
                    logger.debug(
                        f"Possible incomplete extraction: {len(text)} chars from {total_pixels/1_000_000:.1f}MP image "
                        f"(expected ~{int(min_expected_chars)}+ chars for document)"
                    )
                    return True

        return False

    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocess image to improve OCR accuracy.

        Args:
            image: PIL Image

        Returns:
            Preprocessed image
        """
        logger.debug("Preprocessing image for OCR...")

        # Convert to grayscale
        if image.mode != "L":
            image = image.convert("L")

        # Denoise
        if self.denoise:
            image = image.filter(ImageFilter.MedianFilter(size=3))

        # Enhance contrast
        if self.enhance_contrast:
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)

        # Sharpen
        image = image.filter(ImageFilter.SHARPEN)

        # Resize if very small (OCR works better on larger images)
        width, height = image.size
        if width < 1000 or height < 1000:
            scale = max(1000 / width, 1000 / height)
            new_size = (int(width * scale), int(height * scale))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
            logger.debug(f"Upscaled image to {new_size}")

        # Binarization (convert to black and white)
        # Use adaptive thresholding for better results
        import numpy as np
        from PIL import ImageOps

        # Simple thresholding
        threshold = 128
        image = image.point(lambda p: 255 if p > threshold else 0)

        return image
