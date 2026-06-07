"""Anthropic Claude provider."""

import base64
import os
import time

from anthropic import AsyncAnthropic
from loguru import logger

from ...core.exceptions import LLMError
from ...core.models import LLMRequest, LLMResponse
from .base import BaseLLMProvider


class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic Claude provider.

    Uses the official Anthropic SDK to interact with Claude models.
    Requires ANTHROPIC_API_KEY environment variable or api_key in config.
    """

    # Cost per million tokens (as of 2025)
    COSTS = {
        "claude-opus-4": {"input": 15.0, "output": 75.0},
        "claude-sonnet-4": {"input": 3.0, "output": 15.0},
        "claude-sonnet-3-5": {"input": 3.0, "output": 15.0},
        "claude-haiku-3-5": {"input": 0.80, "output": 4.0},
    }

    def __init__(self, config: dict):
        super().__init__(config)

        # Get API key from config or environment
        api_key_env = config.get("api_key_env", "ANTHROPIC_API_KEY")
        api_key = config.get("api_key") or os.getenv(api_key_env)

        if not api_key:
            raise LLMError(
                f"Anthropic API key not found. Set {api_key_env} environment variable "
                "or provide api_key in config."
            )

        self.client = AsyncAnthropic(api_key=api_key, timeout=self.timeout)

    def supports_vision(self) -> bool:
        """All modern Claude models support vision."""
        return True

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """
        Execute completion using Anthropic Claude API.

        Args:
            request: LLM request with prompt and optional images

        Returns:
            LLM response with content and metadata

        Raises:
            LLMError: If request fails
        """
        start_time = time.time()

        try:
            # Build message content
            if request.images:
                # Vision request with images
                content = [{"type": "text", "text": request.prompt}]

                for image_bytes in request.images:
                    # Detect image type (assume JPEG if not specified)
                    media_type = "image/jpeg"
                    if image_bytes[:4] == b"\x89PNG":
                        media_type = "image/png"
                    elif image_bytes[:4] == b"RIFF":
                        media_type = "image/webp"

                    b64_image = base64.standard_b64encode(image_bytes).decode("utf-8")
                    content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64_image,
                        },
                    })
            else:
                # Text-only request
                content = request.prompt

            # Make API request
            logger.debug(f"Anthropic request to {self.model}")

            response = await self.client.messages.create(
                model=self.model,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                system=request.system if request.system else None,
                messages=[{"role": "user", "content": content}],
            )

            latency_ms = (time.time() - start_time) * 1000

            # Extract content
            content_text = response.content[0].text

            # Calculate tokens and cost
            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            total_tokens = input_tokens + output_tokens

            cost = self._calculate_cost(self.model, input_tokens, output_tokens)

            logger.debug(
                f"Anthropic response: {total_tokens} tokens "
                f"(${cost:.4f}), {latency_ms:.0f}ms"
            )

            return LLMResponse(
                content=content_text,
                provider="anthropic",
                model=self.model,
                tokens_used=total_tokens,
                cost=cost,
                latency_ms=latency_ms,
            )

        except Exception as e:
            logger.error(f"Anthropic error: {e}")
            raise LLMError(f"Anthropic request failed: {e}")

    async def web_search(self, query: str, max_tokens: int = 500) -> str:
        """
        Perform a web search and summarize results.

        Uses Anthropic's extended thinking with web search capabilities.

        Args:
            query: Search query
            max_tokens: Maximum tokens for response

        Returns:
            Summary of search results

        Raises:
            LLMError: If search fails
        """
        try:
            logger.debug(f"Anthropic web search: {query}")

            # Use extended thinking mode with web search
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                temperature=0.1,  # Low temperature for factual responses
                thinking={
                    "type": "enabled",
                    "budget_tokens": 2000
                },
                messages=[{
                    "role": "user",
                    "content": f"Search the web and answer this question concisely: {query}"
                }]
            )

            # Extract content from response
            content = ""
            for block in response.content:
                if hasattr(block, 'text'):
                    content += block.text

            logger.debug(f"Web search completed: {len(content)} chars")
            return content.strip()

        except Exception as e:
            logger.error(f"Anthropic web search error: {e}")
            raise LLMError(f"Web search failed: {e}")

    async def health_check(self) -> bool:
        """
        Check if Anthropic API is accessible.

        Returns:
            True if API key is valid and accessible
        """
        try:
            # Make a minimal request to test connectivity
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=10,
                messages=[{"role": "user", "content": "Hi"}],
            )
            logger.debug("Anthropic health check: OK")
            return True
        except Exception as e:
            logger.warning(f"Anthropic health check failed: {e}")
            return False

    def _calculate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        """
        Calculate cost based on token usage.

        Args:
            model: Model name
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Cost in USD
        """
        # Find matching cost tier (handle versioned model names)
        costs = None
        for key in self.COSTS:
            if key in model:
                costs = self.COSTS[key]
                break

        if not costs:
            # Default to Sonnet pricing if model not found
            logger.warning(f"Unknown model {model}, using Sonnet pricing")
            costs = self.COSTS["claude-sonnet-4"]

        # Calculate cost per million tokens
        input_cost = (input_tokens / 1_000_000) * costs["input"]
        output_cost = (output_tokens / 1_000_000) * costs["output"]

        return input_cost + output_cost

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close client."""
        await self.client.close()
