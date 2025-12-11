"""LM Studio provider using OpenAI-compatible API."""

import asyncio
import base64
import json
import time
from typing import Optional

import httpx
from loguru import logger

from ...core.exceptions import LLMError
from ...core.models import LLMRequest, LLMResponse
from ..tool_executor import ToolExecutor
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
        self.client = None
        self._client_loop = None
        self.tool_executor = ToolExecutor()

    def _ensure_client(self):
        """Ensure httpx client is using the current event loop."""
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop yet, will be created when async context starts
            current_loop = None

        # Recreate client if loop changed or client doesn't exist
        if self.client is None or self._client_loop != current_loop:
            # Don't try to close old client - just replace it
            # The old client will be garbage collected
            self.client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
            self._client_loop = current_loop

    def supports_vision(self) -> bool:
        """LM Studio supports vision if a vision model is loaded."""
        # Check if model name suggests vision capability
        vision_indicators = ["llava", "bakllava", "vision", "vl", "qwen3-vl"]
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
        # Ensure client is using the current event loop
        self._ensure_client()

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
                "frequency_penalty": 0.5,  # Reduce repetition (OpenAI-compatible param)
                "presence_penalty": 0.5,   # Encourage diversity
            }

            # Add tools if provided
            if hasattr(request, 'tools') and request.tools:
                payload["tools"] = request.tools
                logger.debug(f"Sending {len(request.tools)} tools to LM Studio")

            # Note: LM Studio has inconsistent support for response_format
            # Some versions support {"type": "json_object"}, others don't
            # We rely on prompt engineering instead (safer for compatibility)

            # Tool calling loop - keep going until LLM returns content (not tool calls)
            max_iterations = 10  # Allow more iterations for complex searches
            iteration = 0
            total_tokens = 0

            while iteration < max_iterations:
                iteration += 1

                # Make API request
                logger.debug(f"LM Studio request #{iteration} to {self.base_url}/chat/completions")
                response = await self.client.post("/chat/completions", json=payload)
                response.raise_for_status()

                data = response.json()
                total_tokens += data.get("usage", {}).get("total_tokens", 0)

                message = data["choices"][0]["message"]
                finish_reason = data["choices"][0].get("finish_reason")

                # Check if LLM wants to call tools
                tool_calls = message.get("tool_calls", [])

                if tool_calls and finish_reason == "tool_calls":
                    logger.info(f"LLM calling {len(tool_calls)} tool(s)")

                    # Add assistant message with tool calls to conversation
                    payload["messages"].append({
                        "role": "assistant",
                        "content": message.get("content", ""),
                        "tool_calls": tool_calls
                    })

                    # Execute each tool and add results
                    for tool_call in tool_calls:
                        tool_name = tool_call["function"]["name"]
                        tool_args = json.loads(tool_call["function"]["arguments"])

                        # Execute tool
                        tool_result = self.tool_executor.execute(tool_name, tool_args)

                        # Add tool result to conversation
                        payload["messages"].append({
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": json.dumps(tool_result)
                        })

                    # Continue loop to get LLM's response to tool results
                    continue

                # No tool calls - this is the final response
                content = message.get("content", "")
                latency_ms = (time.time() - start_time) * 1000

                logger.debug(
                    f"LM Studio complete: {total_tokens} tokens, {latency_ms:.0f}ms, {iteration} iterations"
                )

                return LLMResponse(
                    content=content,
                    provider="lm_studio",
                    model=self.model,
                    tokens_used=total_tokens,
                    cost=0.0,  # Local model, no cost
                    latency_ms=latency_ms,
                )

            # Max iterations reached
            raise LLMError(f"Tool calling exceeded max iterations ({max_iterations})")

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
