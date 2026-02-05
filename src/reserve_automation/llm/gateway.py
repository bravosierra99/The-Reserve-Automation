"""LLM Gateway - unified interface to multiple LLM providers."""

from typing import Dict, Optional

from loguru import logger

from ..core.exceptions import LLMError, LLMProviderNotFoundError
from ..core.models import LLMRequest, LLMResponse
from .providers.anthropic_provider import AnthropicProvider
from .providers.base import BaseLLMProvider
from .providers.lm_studio import LMStudioProvider


class LLMGateway:
    """
    Central LLM abstraction layer.

    Routes requests to appropriate providers based on task type.
    Supports automatic fallback to backup providers.
    """

    # Map provider type strings to classes
    PROVIDER_CLASSES = {
        "lm_studio": LMStudioProvider,
        "anthropic": AnthropicProvider,
        # Add more providers here as needed
        # "openai": OpenAIProvider,
        # "ollama": OllamaProvider,
    }

    def __init__(self, config: dict):
        """
        Initialize LLM Gateway with configuration.

        Args:
            config: LLM configuration dictionary (from llm.yaml)

        Raises:
            LLMError: If configuration is invalid
        """
        self.config = config
        self.providers: Dict[str, BaseLLMProvider] = {}
        self.routing = config.get("routing", {})
        self.fallback_config = config.get("fallback", {})

        # Initialize all configured providers
        self._initialize_providers()

        logger.info(f"LLM Gateway initialized with {len(self.providers)} providers")

    def _initialize_providers(self) -> None:
        """Initialize all configured providers."""
        providers_config = self.config.get("providers", {})

        for name, provider_config in providers_config.items():
            provider_type = provider_config.get("provider")

            if not provider_type:
                logger.warning(f"Provider {name} missing 'provider' type, skipping")
                continue

            if provider_type not in self.PROVIDER_CLASSES:
                logger.warning(f"Unknown provider type: {provider_type}, skipping {name}")
                continue

            try:
                ProviderClass = self.PROVIDER_CLASSES[provider_type]
                self.providers[name] = ProviderClass(provider_config)
                logger.debug(f"Initialized provider: {name} ({provider_type})")

            except Exception as e:
                logger.error(f"Failed to initialize provider {name}: {e}")
                # Continue initializing other providers

    async def complete(
        self,
        task_type: str,
        prompt: str,
        system: Optional[str] = None,
        images: Optional[list[bytes]] = None,
        tools: Optional[list[dict]] = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Execute LLM completion with automatic routing.

        Args:
            task_type: Task identifier for routing (e.g., 'extraction', 'ocr')
            prompt: User prompt
            system: Optional system prompt
            images: Optional images for vision tasks
            **kwargs: Additional arguments (max_tokens, temperature, etc.)

        Returns:
            LLM response with content and metadata

        Raises:
            LLMProviderNotFoundError: If no provider configured for task
            LLMError: If request fails and no fallback succeeds
        """
        # 1. Determine provider from routing rules
        provider_name = self.routing.get(task_type)

        if not provider_name:
            raise LLMProviderNotFoundError(
                f"No routing rule for task type: {task_type}. "
                f"Add to config/llm.yaml routing section."
            )

        if provider_name not in self.providers:
            raise LLMProviderNotFoundError(
                f"Provider {provider_name} not initialized. "
                f"Check config/llm.yaml providers section."
            )

        # 2. Build request
        request = LLMRequest(
            prompt=prompt,
            system=system,
            images=images,
            max_tokens=kwargs.get("max_tokens", 2000),
            temperature=kwargs.get("temperature", 0.2),
            response_format=kwargs.get("response_format"),
        )

        # Add tools if provided
        if tools:
            request.tools = tools

        # 3. Execute with primary provider
        try:
            provider = self.providers[provider_name]
            logger.debug(f"Routing {task_type} → {provider_name}")

            response = await provider.complete(request)
            logger.info(f"✓ {task_type} via {provider_name} ({response.tokens_used} tokens)")

            return response

        except Exception as e:
            logger.error(f"✗ {provider_name} failed for {task_type}: {e}")

            # 4. Try fallback if configured
            fallback_provider = None
            if self.fallback_config.get("enabled", False):
                fallback_provider = self._get_fallback(provider_name)

                if fallback_provider:
                    logger.info(f"↻ Retrying {task_type} with fallback: {fallback_provider}")

                    try:
                        provider = self.providers[fallback_provider]
                        response = await provider.complete(request)

                        logger.info(
                            f"✓ {task_type} via {fallback_provider} (fallback) "
                            f"({response.tokens_used} tokens)"
                        )
                        return response

                    except Exception as fallback_error:
                        logger.error(f"✗ Fallback {fallback_provider} also failed: {fallback_error}")

            # No fallback or fallback failed
            raise LLMError(
                f"Task {task_type} failed with {provider_name}"
                + (f" and fallback" if fallback_provider else "")
            ) from e

    def _get_fallback(self, provider_name: str) -> Optional[str]:
        """
        Get fallback provider for a given provider.

        Args:
            provider_name: Name of provider that failed

        Returns:
            Name of fallback provider, or None if not configured
        """
        rules = self.fallback_config.get("rules", {})
        fallback_list = rules.get(provider_name, [])

        # Return first available fallback provider
        for fallback_name in fallback_list:
            if fallback_name in self.providers:
                return fallback_name

        return None

    async def health_check_all(self) -> Dict[str, bool]:
        """
        Check health of all configured providers.

        Returns:
            Dictionary mapping provider names to health status
        """
        results = {}

        for name, provider in self.providers.items():
            try:
                is_healthy = await provider.health_check()
                results[name] = is_healthy
                status = "✓" if is_healthy else "✗"
                logger.debug(f"{status} {name} health check")
            except Exception as e:
                results[name] = False
                logger.error(f"✗ {name} health check error: {e}")

        return results

    async def health_check(self, provider_name: str) -> bool:
        """
        Check health of a specific provider.

        Args:
            provider_name: Name of provider to check

        Returns:
            True if healthy, False otherwise

        Raises:
            LLMProviderNotFoundError: If provider not found
        """
        if provider_name not in self.providers:
            raise LLMProviderNotFoundError(f"Provider not found: {provider_name}")

        provider = self.providers[provider_name]
        return await provider.health_check()

    def list_providers(self) -> Dict[str, dict]:
        """
        List all configured providers with metadata.

        Returns:
            Dictionary mapping provider names to their info
        """
        info = {}

        for name, provider in self.providers.items():
            info[name] = {
                "type": provider.__class__.__name__,
                "model": provider.model,
                "supports_vision": provider.supports_vision(),
            }

        return info

    def get_routing_info(self) -> dict:
        """
        Get current routing configuration.

        Returns:
            Dictionary of task types to provider names
        """
        return self.routing.copy()

    async def web_search(self, query: str, max_tokens: int = 500) -> str:
        """
        Perform a web search and get results.

        Uses the provider configured for 'web_search' task type, or looks for
        a provider that supports web search (typically Anthropic).

        Args:
            query: Search query
            max_tokens: Maximum tokens for response

        Returns:
            Search results summary

        Raises:
            LLMError: If search fails or no suitable provider found
        """
        # Try to find web search provider - check routing first
        provider_name = self.routing.get("web_search")

        # If not explicitly routed, look for a provider that supports web search
        if not provider_name:
            logger.debug("No explicit web_search routing, searching for capable provider...")
            for name, provider in self.providers.items():
                if hasattr(provider, 'web_search'):
                    provider_name = name
                    logger.debug(f"Found web search capable provider: {provider_name}")
                    break

        if not provider_name or provider_name not in self.providers:
            logger.warning(
                "No provider supports web search. "
                "Web search requires AnthropicProvider. Falling back to keyword matching."
            )
            raise LLMError(
                "Web search not available - no provider supports it. "
                "Add Anthropic provider to config/llm.yaml to enable web search."
            )

        provider = self.providers[provider_name]

        # Double-check provider supports web search
        if not hasattr(provider, 'web_search'):
            logger.warning(f"Provider {provider_name} does not support web search")
            raise LLMError(
                f"Provider {provider_name} does not support web search. "
                f"Add AnthropicProvider to config/llm.yaml to enable web search."
            )

        try:
            logger.info(f"Web search via {provider_name}: {query}")
            result = await provider.web_search(query, max_tokens)
            logger.info(f"✓ Web search completed via {provider_name}")
            return result

        except Exception as e:
            logger.error(f"Web search failed: {e}")
            raise LLMError(f"Web search failed: {e}") from e
