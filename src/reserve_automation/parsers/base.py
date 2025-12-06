"""Base parser interface for input files."""

from abc import ABC, abstractmethod
from pathlib import Path

from ..core.models import ParserResult


class BaseParser(ABC):
    """
    Abstract base class for all input parsers.

    Parsers extract text and images from various input formats
    (PDF, images, screenshots, etc.)
    """

    @abstractmethod
    async def parse(self, input_file: Path) -> ParserResult:
        """
        Parse input file and extract text/images.

        Args:
            input_file: Path to input file

        Returns:
            ParserResult with extracted content

        Raises:
            ParserError: If parsing fails
        """
        pass

    @abstractmethod
    def can_parse(self, input_file: Path) -> bool:
        """
        Check if this parser can handle the given file.

        Args:
            input_file: Path to input file

        Returns:
            True if this parser can handle the file
        """
        pass

    def _get_file_extension(self, input_file: Path) -> str:
        """Get lowercase file extension without dot."""
        return input_file.suffix.lower().lstrip(".")

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}()"
