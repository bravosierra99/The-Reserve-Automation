"""Image parser using OCR."""

from pathlib import Path
import io

from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
from loguru import logger

from ..core.exceptions import ParserError
from ..core.models import ParserResult
from .base import BaseParser


class ImageParser(BaseParser):
    """
    Parse images using OCR (pytesseract).

    Supports common image formats and applies preprocessing
    to improve OCR accuracy.
    """

    # Supported image extensions
    EXTENSIONS = ["jpg", "jpeg", "png", "bmp", "tiff", "tif", "webp"]

    def __init__(
        self,
        preprocess: bool = True,
        deskew: bool = True,
        denoise: bool = True,
        enhance_contrast: bool = True,
        language: str = "eng",
    ):
        """
        Initialize image parser.

        Args:
            preprocess: Apply preprocessing for better OCR
            deskew: Attempt to deskew rotated images
            denoise: Apply denoising filter
            enhance_contrast: Enhance image contrast
            language: OCR language (default: English)
        """
        self.preprocess = preprocess
        self.deskew = deskew
        self.denoise = denoise
        self.enhance_contrast = enhance_contrast
        self.language = language

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
            if self.preprocess:
                image = self._preprocess_image(image)

            # Perform OCR
            logger.debug("Running OCR...")
            text = pytesseract.image_to_string(image, lang=self.language)

            # Convert image to bytes for storage
            img_bytes_io = io.BytesIO()
            image.save(img_bytes_io, format="PNG")
            img_bytes = img_bytes_io.getvalue()

            logger.info(
                f"Parsed image: {len(text)} chars, "
                f"size: {original_size[0]}x{original_size[1]}"
            )

            return ParserResult(
                raw_text=text,
                images=[img_bytes],
                metadata={
                    "dimensions": original_size,
                    "preprocessed": self.preprocess,
                },
                source_type="image",
            )

        except Exception as e:
            logger.error(f"Image parsing failed: {e}")
            raise ParserError(f"Failed to parse image: {e}") from e

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
