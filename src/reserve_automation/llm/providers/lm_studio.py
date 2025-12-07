"""LM Studio provider using OpenAI-compatible API."""

import base64
import time
from typing import Optional

import httpx
from loguru import logger

from ...core.exceptions import LLMError
from ...core.models import LLMRequest, LLMResponse
from .base import BaseLLMProvider


class LMStudioProvider(BaseLLMProvider):
    """
    LM Studio provider using OpenAI-compatible API.

    LM Studio exposes a local API compatible with OpenAI's format,
    making it easy to use local models.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.base_url = config.get("base_url", "http://localhost:1234/v1")
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout,
        )

    def supports_vision(self) -> bool:
        """LM Studio supports vision if a vision model is loaded."""
        # Check if model name suggests vision capability
        vision_indicators = ["llava", "bakllava", "vision"]
        return any(ind in self.model.lower() for ind in vision_indicators)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """
        Execute completion using LM Studio's OpenAI-compatible API.

        Args:
            request: LLM request with prompt and optional images

        Returns:
            LLM response with content and metadata

        Raises:
            LLMError: If request fails
        """
        start_time = time.time()

        try:
            # Build messages in OpenAI format
            messages = []

            # Add system message if provided
            if request.system:
                messages.append({"role": "system", "content": request.system})

            # Handle vision requests (images)
            if request.images:
                content = [{"type": "text", "text": request.prompt}]

                # Add images as base64 data URLs
                for image_bytes in request.images:
                    b64_image = base64.b64encode(image_bytes).decode("utf-8")
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}
                    })

                messages.append({"role": "user", "content": content})
            else:
                # Text-only request
                messages.append({"role": "user", "content": request.prompt})

            # Build request payload
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
            }

            # Note: LM Studio has inconsistent support for response_format
            # Some versions support {"type": "json_object"}, others don't
            # We rely on prompt engineering instead (safer for compatibility)

            # Make API request
            logger.debug(f"LM Studio request to {self.base_url}/chat/completions")
            response = await self.client.post("/chat/completions", json=payload)
            response.raise_for_status()

            data = response.json()
            latency_ms = (time.time() - start_time) * 1000

            # Extract content from response
            content = data["choices"][0]["message"]["content"]
            tokens_used = data.get("usage", {}).get("total_tokens", 0)

            logger.debug(
                f"LM Studio response: {tokens_used} tokens, {latency_ms:.0f}ms"
            )

            return LLMResponse(
                content=content,
                provider="lm_studio",
                model=self.model,
                tokens_used=tokens_used,
                cost=0.0,  # Local model, no cost
                latency_ms=latency_ms,
            )

        except httpx.HTTPStatusError as e:
            logger.error(f"LM Studio HTTP error: {e.response.status_code} - {e.response.text}")
            raise LLMError(f"LM Studio request failed: {e.response.status_code}")

        except httpx.RequestError as e:
            logger.error(f"LM Studio connection error: {e}")
            raise LLMError(f"Cannot connect to LM Studio at {self.base_url}: {e}")

        except Exception as e:
            logger.error(f"LM Studio unexpected error: {e}")
            raise LLMError(f"LM Studio error: {e}")

    async def health_check(self) -> bool:
        """
        Check if LM Studio is accessible.

        Returns:
            True if LM Studio API is responding
        """
        try:
            response = await self.client.get("/models", timeout=5.0)
            if response.status_code == 200:
                logger.debug("LM Studio health check: OK")
                return True
            else:
                logger.warning(f"LM Studio health check failed: {response.status_code}")
                return False
        except Exception as e:
            logger.warning(f"LM Studio health check failed: {e}")
            return False

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close client."""
        await self.client.aclose()
