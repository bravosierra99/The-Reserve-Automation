"""Base LLM provider interface."""

from abc import ABC, abstractmethod
from typing import Optional

from ...core.models import LLMRequest, LLMResponse


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.

    All providers must implement the complete() and health_check() methods.
    """

    def __init__(self, config: dict):
        """
        Initialize provider with configuration.

        Args:
            config: Provider configuration dictionary
        """
        self.config = config
        self.model = config.get("model", "unknown")
        self.timeout = config.get("timeout", 120)
        self.max_retries = config.get("max_retries", 2)

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """
        Execute completion request.

        Args:
            request: Unified LLM request

        Returns:
            LLM response with content and metadata

        Raises:
            LLMError: If request fails
        """
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """
        Test provider connectivity.

        Returns:
            True if provider is accessible, False otherwise
        """
        pass

    def supports_vision(self) -> bool:
        """
        Check if provider supports vision/image inputs.

        Override in subclasses that support vision.

        Returns:
            True if vision is supported
        """
        return False

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(model={self.model})"
