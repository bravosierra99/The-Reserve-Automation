"""Tests for the ``/no_think`` system-prompt prepend in LMStudioProvider.

When ``config["reasoning_effort"] == "none"``, the provider must prepend
``/no_think\\n\\n`` to the system message so qwen3-series models skip their
``<think>`` block. The provider must NOT prepend it again if the system
message already starts with ``/no_think``, and must NOT prepend it at all
when ``reasoning_effort`` is anything else (including absent).

See ``src/reserve_automation/llm/providers/lm_studio.py`` around line 194.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from reserve_automation.core.models import LLMRequest
from reserve_automation.llm.providers.lm_studio import LMStudioProvider


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_provider(reasoning_effort=None) -> LMStudioProvider:
    """Build an LMStudioProvider with a fake httpx client."""
    config = {
        "model": "qwen3-test",
        "base_url": "http://localhost:1234/v1",
        "timeout": 5,
        "max_iterations": 1,
    }
    if reasoning_effort is not None:
        config["reasoning_effort"] = reasoning_effort

    provider = LMStudioProvider(config)
    return provider


def _fake_chat_response():
    """A minimal LM Studio /chat/completions response payload."""
    fake_response = Mock()
    fake_response.raise_for_status = Mock()
    fake_response.json = Mock(
        return_value={
            "choices": [
                {
                    "message": {"content": "ok"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"total_tokens": 5},
        }
    )
    return fake_response


def _patch_provider_io(provider: LMStudioProvider):
    """Patch model-load + httpx so ``complete`` returns a captured payload."""
    captured = {}

    async def fake_post(path, json):
        captured["path"] = path
        captured["payload"] = json
        return _fake_chat_response()

    fake_client = Mock()
    fake_client.post = AsyncMock(side_effect=fake_post)
    provider.client = fake_client
    provider._client_loop = None  # _ensure_client recreates if loop differs;
    # we patch _ensure_client instead so the fake survives.

    # Skip httpx client construction entirely
    provider._ensure_client = Mock(return_value=None)
    # Skip model-load probing
    provider._ensure_model_loaded = AsyncMock(return_value=True)

    return captured


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNoThinkPrepend:
    """Behaviour of the ``/no_think`` prepend logic."""

    async def test_prepends_when_reasoning_effort_none_and_no_existing_marker(self):
        provider = _build_provider(reasoning_effort="none")
        captured = _patch_provider_io(provider)

        await provider.complete(
            LLMRequest(prompt="Hello", system="You are a helpful assistant.")
        )

        system_msg = next(
            m for m in captured["payload"]["messages"] if m["role"] == "system"
        )
        assert system_msg["content"].startswith("/no_think\n\n")
        assert system_msg["content"] == "/no_think\n\nYou are a helpful assistant."

    async def test_does_not_double_prepend_when_marker_already_present(self):
        provider = _build_provider(reasoning_effort="none")
        captured = _patch_provider_io(provider)

        original = "/no_think\n\nYou are a helpful assistant."
        await provider.complete(LLMRequest(prompt="Hi", system=original))

        system_msg = next(
            m for m in captured["payload"]["messages"] if m["role"] == "system"
        )
        assert system_msg["content"] == original
        # Sanity: only one occurrence
        assert system_msg["content"].count("/no_think") == 1

    async def test_does_not_prepend_when_reasoning_effort_is_low(self):
        provider = _build_provider(reasoning_effort="low")
        captured = _patch_provider_io(provider)

        await provider.complete(
            LLMRequest(prompt="Hi", system="You are a helpful assistant.")
        )

        system_msg = next(
            m for m in captured["payload"]["messages"] if m["role"] == "system"
        )
        assert "/no_think" not in system_msg["content"]
        assert system_msg["content"] == "You are a helpful assistant."

    async def test_does_not_prepend_when_reasoning_effort_absent(self):
        provider = _build_provider(reasoning_effort=None)
        captured = _patch_provider_io(provider)

        await provider.complete(
            LLMRequest(prompt="Hi", system="You are a helpful assistant.")
        )

        system_msg = next(
            m for m in captured["payload"]["messages"] if m["role"] == "system"
        )
        assert "/no_think" not in system_msg["content"]

    async def test_handles_empty_system_with_reasoning_none(self):
        """Empty system + reasoning none -> system message becomes just ``/no_think``."""
        provider = _build_provider(reasoning_effort="none")
        captured = _patch_provider_io(provider)

        await provider.complete(LLMRequest(prompt="Hi", system=""))

        # When system was empty, the code sets it to just "/no_think"
        system_messages = [
            m for m in captured["payload"]["messages"] if m["role"] == "system"
        ]
        assert len(system_messages) == 1
        assert system_messages[0]["content"] == "/no_think"

    async def test_handles_none_system_with_reasoning_none(self):
        """No system at all + reasoning none -> ``/no_think`` is still injected."""
        provider = _build_provider(reasoning_effort="none")
        captured = _patch_provider_io(provider)

        await provider.complete(LLMRequest(prompt="Hi"))  # system defaults to None

        system_messages = [
            m for m in captured["payload"]["messages"] if m["role"] == "system"
        ]
        assert len(system_messages) == 1
        assert system_messages[0]["content"] == "/no_think"

    async def test_no_system_message_when_no_marker_and_no_system(self):
        """No system + reasoning_effort != none -> no system message at all."""
        provider = _build_provider(reasoning_effort="low")
        captured = _patch_provider_io(provider)

        await provider.complete(LLMRequest(prompt="Hi"))

        system_messages = [
            m for m in captured["payload"]["messages"] if m["role"] == "system"
        ]
        assert system_messages == []

    async def test_reasoning_effort_payload_still_sent(self):
        """The legacy ``reasoning_effort`` payload key is sent alongside the prepend."""
        provider = _build_provider(reasoning_effort="none")
        captured = _patch_provider_io(provider)

        await provider.complete(LLMRequest(prompt="Hi", system="Sys"))

        assert captured["payload"].get("reasoning_effort") == "none"

    async def test_marker_check_is_strict_startswith(self):
        """A marker that appears later in the prompt must NOT prevent prepending."""
        provider = _build_provider(reasoning_effort="none")
        captured = _patch_provider_io(provider)

        # Marker mentioned in the *body* but not at the very start
        original = "Use /no_think when reasoning is unwanted."
        await provider.complete(LLMRequest(prompt="Hi", system=original))

        system_msg = next(
            m for m in captured["payload"]["messages"] if m["role"] == "system"
        )
        # Should be prepended because the original didn't *start* with /no_think
        assert system_msg["content"] == f"/no_think\n\n{original}"
        assert system_msg["content"].count("/no_think") == 2
