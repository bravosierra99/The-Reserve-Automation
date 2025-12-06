"""Custom exceptions for The Reserve Automation."""


class ReserveAutomationError(Exception):
    """Base exception for all Reserve Automation errors."""

    pass


class ConfigurationError(ReserveAutomationError):
    """Raised when configuration is invalid or missing."""

    pass


class ParserError(ReserveAutomationError):
    """Raised when parsing fails."""

    pass


class UnsupportedFileTypeError(ParserError):
    """Raised when file type is not supported."""

    pass


class ExtractionError(ReserveAutomationError):
    """Raised when LLM extraction fails."""

    pass


class LLMError(ReserveAutomationError):
    """Raised when LLM provider fails."""

    pass


class LLMProviderNotFoundError(LLMError):
    """Raised when requested LLM provider is not configured."""

    pass


class GenerationError(ReserveAutomationError):
    """Raised when Obsidian file generation fails."""

    pass


class GitError(ReserveAutomationError):
    """Raised when git operations fail."""

    pass
