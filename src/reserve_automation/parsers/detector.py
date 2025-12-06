"""Auto-detect and route to correct parser."""

from pathlib import Path
from typing import Optional

from loguru import logger

from ..core.exceptions import UnsupportedFileTypeError
from ..core.models import ParserResult
from .image import ImageParser
from .pdf import PDFParser


class ParserDetector:
    """
    Auto-detect file type and route to appropriate parser.

    Tries all registered parsers and uses the first one that can handle the file.
    """

    def __init__(self, config: Optional[dict] = None, llm_gateway=None):
        """
        Initialize parser detector.

        Args:
            config: Optional parser configuration
            llm_gateway: Optional LLM Gateway for vision-based OCR
        """
        config = config or {}

        # Initialize parsers with config
        pdf_config = config.get("pdf", {})
        image_config = config.get("image", {})

        self.parsers = [
            PDFParser(use_ocr_fallback=pdf_config.get("use_ocr_fallback", True)),
            ImageParser(
                preprocess=image_config.get("preprocess", True),
                deskew=image_config.get("deskew", True),
                denoise=image_config.get("denoise", True),
                enhance_contrast=image_config.get("enhance_contrast", True),
                language=image_config.get("ocr_language", "eng"),
                ocr_method=image_config.get("ocr_method", "auto"),
                llm_gateway=llm_gateway,
            ),
        ]

        logger.debug(f"Initialized parser detector with {len(self.parsers)} parsers")

    async def parse(self, input_file: Path) -> ParserResult:
        """
        Auto-detect file type and parse.

        Args:
            input_file: Path to file to parse

        Returns:
            ParserResult with extracted content

        Raises:
            UnsupportedFileTypeError: If no parser can handle the file
        """
        if not input_file.exists():
            raise FileNotFoundError(f"File not found: {input_file}")

        logger.debug(f"Auto-detecting parser for: {input_file.name}")

        # Try each parser in order
        for parser in self.parsers:
            if parser.can_parse(input_file):
                logger.info(f"Using {parser.__class__.__name__} for {input_file.name}")
                return await parser.parse(input_file)

        # No parser found
        raise UnsupportedFileTypeError(
            f"No parser available for file type: {input_file.suffix}. "
            f"Supported types: PDF, images (JPG, PNG, etc.)"
        )

    def detect_type(self, input_file: Path) -> Optional[str]:
        """
        Detect file type without parsing.

        Args:
            input_file: Path to file

        Returns:
            Type string ('pdf', 'image', etc.) or None if unsupported
        """
        for parser in self.parsers:
            if parser.can_parse(input_file):
                return parser.__class__.__name__.replace("Parser", "").lower()

        return None
