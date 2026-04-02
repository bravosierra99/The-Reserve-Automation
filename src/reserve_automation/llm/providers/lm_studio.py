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
        self.max_iterations = config.get("max_iterations", 10)
        self.tool_executor = ToolExecutor(max_results=config.get("max_results", 10))
        self._model_load_attempted = False  # Track if we've tried loading the model

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

    async def _is_model_loaded(self) -> bool:
        """
        Check if the configured model is currently loaded in LM Studio.

        Returns:
            True if model is loaded, False otherwise
        """
        try:
            # Ensure client is using the current event loop
            self._ensure_client()

            logger.debug(f"Checking if model {self.model} is loaded at {self.base_url}/models")
            response = await self.client.get("/models", timeout=10.0)
            logger.debug(f"Got response: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                loaded_models = data.get("data", [])
                logger.debug(f"Loaded models: {[m.get('id') for m in loaded_models]}")

                # Check if our model is in the list of loaded models
                for model_info in loaded_models:
                    model_id = model_info.get("id", "")
                    if self.model in model_id or model_id in self.model:
                        logger.info(f"✓ Model {self.model} is loaded in LM Studio")
                        return True

                logger.warning(f"Model {self.model} not in loaded models: {[m.get('id') for m in loaded_models]}")
                return False

            logger.warning(f"Failed to get models list: HTTP {response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Could not check loaded models: {type(e).__name__}: {e}")
            import traceback
            logger.debug(f"Traceback: {traceback.format_exc()}")
            return False

    async def _load_model(self) -> bool:
        """
        Attempt to load the configured model in LM Studio.

        Note: LM Studio doesn't support auto-loading models via API.
        Models must be manually loaded in the LM Studio UI.

        Returns:
            False - auto-loading not supported
        """
        logger.warning(
            f"Model {self.model} is not loaded. "
            f"LM Studio does not support auto-loading models via API. "
            f"Please load the model manually in the LM Studio application."
        )
        return False

    async def _ensure_model_loaded(self) -> None:
        """
        Ensure the model is loaded, attempting to load it if necessary.

        Raises:
            LLMError: If model cannot be loaded
        """
        # Only try loading once per session to avoid repeated failures
        if self._model_load_attempted:
            return

        self._model_load_attempted = True

        # Check if model is already loaded
        if await self._is_model_loaded():
            logger.debug(f"Model {self.model} already loaded")
            return

        # Try to load the model
        logger.info(f"Model {self.model} not loaded, attempting to load...")
        if not await self._load_model():
            raise LLMError(
                f"Failed to load model {self.model} in LM Studio. "
                f"Please load the model manually in LM Studio."
            )

        # Wait a moment for model to initialize
        await asyncio.sleep(2)

    def supports_vision(self) -> bool:
        """LM Studio supports vision if a vision model is loaded."""
        # Check if model name suggests vision capability
        vision_indicators = ["llava", "bakllava", "vision", "vl", "qwen3-vl"]
        return any(ind in self.model.lower() for ind in vision_indicators)

    async def complete(self, request: LLMRequest, _retry: bool = False) -> LLMResponse:
        """
        Execute completion using LM Studio's OpenAI-compatible API.

        Args:
            request: LLM request with prompt and optional images
            _retry: Internal parameter to track retry attempts

        Returns:
            LLM response with content and metadata

        Raises:
            LLMError: If request fails
        """
        # Ensure client is using the current event loop
        self._ensure_client()

        # Ensure model is loaded (will auto-load if needed)
        await self._ensure_model_loaded()

        start_time = time.time()

        try:
            # Build messages in OpenAI format
            messages = []

            # Add system message if provided
            if request.system:
                messages.append({"role": "system", "content": request.system})

            # Handle vision requests (images)
            if request.images:
                logger.debug(f"Vision request: {len(request.images)} image(s), total {sum(len(img) for img in request.images)} bytes")
                content = [{"type": "text", "text": request.prompt}]

                # Add images as base64 data URLs
                for idx, image_bytes in enumerate(request.images):
                    b64_image = base64.b64encode(image_bytes).decode("utf-8")
                    logger.debug(f"Image {idx+1}: {len(image_bytes)} bytes -> {len(b64_image)} base64 chars")
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64_image}"}
                    })

                messages.append({"role": "user", "content": content})
            else:
                # Text-only request
                logger.debug("Text-only request (NO IMAGES)")
                messages.append({"role": "user", "content": request.prompt})

            # Build request payload
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": request.max_tokens,
                "temperature": request.temperature,
                # NOTE: Penalties removed for LM Studio 0.4.1+ compatibility
                # LM Studio 0.4.1 handles these more aggressively, causing vision models
                # to generate garbage tokens. If repetition becomes an issue again,
                # use lower values (0.1-0.2) or make them conditional based on task type.
                # "frequency_penalty": 0.5,
                # "presence_penalty": 0.5,
            }

            # Request larger context if configured (some backends support this)
            context_length = self.config.get("context_length")
            if context_length:
                payload["num_ctx"] = context_length  # Ollama-style
                payload["n_ctx"] = context_length    # llama.cpp-style

            # Disable reasoning/thinking for models that default it on (e.g. Qwen3.5).
            # Without this, reasoning models consume all tokens thinking and return empty content.
            reasoning_effort = self.config.get("reasoning_effort")
            if reasoning_effort:
                payload["reasoning_effort"] = reasoning_effort

            # Add tools if provided
            if hasattr(request, 'tools') and request.tools:
                payload["tools"] = request.tools
                logger.debug(f"Sending {len(request.tools)} tools to LM Studio")

            # Note: LM Studio has inconsistent support for response_format
            # Some versions support {"type": "json_object"}, others don't
            # We rely on prompt engineering instead (safer for compatibility)

            # Tool calling loop - keep going until LLM returns content (not tool calls)
            max_iterations = self.max_iterations
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
                    # Log what tools are being called with what arguments
                    tool_summary = []
                    for tc in tool_calls:
                        args_preview = json.loads(tc["function"]["arguments"])
                        tool_summary.append(f"{tc['function']['name']}({list(args_preview.values())[0] if args_preview else ''})")
                    logger.info(f"LLM calling {len(tool_calls)} tool(s): {', '.join(tool_summary)}")

                    # Add assistant message with tool calls to conversation
                    payload["messages"].append({
                        "role": "assistant",
                        "content": message.get("content") or "",  # Ensure it's always a string, not None
                        "tool_calls": tool_calls
                    })

                    # Execute each tool and add results
                    for tool_call in tool_calls:
                        tool_name = tool_call["function"]["name"]
                        tool_args = json.loads(tool_call["function"]["arguments"])

                        # Execute tool
                        tool_result = self.tool_executor.execute(tool_name, tool_args)

                        # Log tool result for debugging
                        if "error" in tool_result:
                            logger.error(f"Tool {tool_name} returned error: {tool_result['error']}")
                        else:
                            result_preview = str(tool_result)[:200] + "..." if len(str(tool_result)) > 200 else str(tool_result)
                            logger.debug(f"Tool {tool_name} result preview: {result_preview}")

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

            # If we haven't retried yet, try loading the model and retry once
            if not _retry:
                logger.info("Retrying after attempting to reload model...")
                self._model_load_attempted = False  # Reset to allow reload attempt

                try:
                    await self._ensure_model_loaded()
                    # Retry the request by calling complete recursively with retry flag
                    return await self.complete(request, _retry=True)
                except Exception as retry_error:
                    logger.error(f"Retry failed: {retry_error}")

            raise LLMError(f"LM Studio request failed: {e.response.status_code}")

        except httpx.RequestError as e:
            logger.error(f"LM Studio connection error: {e}")

            # If we haven't retried yet, try loading the model and retry once
            if not _retry:
                logger.info("Connection failed - retrying after attempting to reload model...")
                self._model_load_attempted = False  # Reset to allow reload attempt

                try:
                    await self._ensure_model_loaded()
                    # Retry the request by calling complete recursively with retry flag
                    return await self.complete(request, _retry=True)
                except Exception as retry_error:
                    logger.error(f"Retry failed: {retry_error}")

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
