"""Unit tests for LLM Gateway."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from reserve_automation.core.exceptions import LLMError, LLMProviderNotFoundError
from reserve_automation.core.models import LLMRequest, LLMResponse
from reserve_automation.llm import LLMGateway
from reserve_automation.llm.providers.base import BaseLLMProvider


class MockProvider(BaseLLMProvider):
    """Mock LLM provider for testing."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.complete_called = False
        self.health_check_called = False

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.complete_called = True
        return LLMResponse(
            content="Mock response",
            provider="mock",
            model=self.model,
            tokens_used=100,
            cost=0.0,
            latency_ms=50.0,
        )

    async def health_check(self) -> bool:
        self.health_check_called = True
        return True


@pytest.fixture
def mock_config():
    """Mock LLM configuration."""
    return {
        "providers": {
            "mock_local": {
                "provider": "mock",
                "model": "mock-model-1",
            },
            "mock_cloud": {
                "provider": "mock",
                "model": "mock-model-2",
            },
        },
        "routing": {
            "extraction": "mock_local",
            "ocr": "mock_local",
        },
        "fallback": {
            "enabled": True,
            "rules": {
                "mock_local": ["mock_cloud"],
            },
        },
    }


@pytest.fixture
def gateway(mock_config):
    """Create LLM gateway with mock providers."""
    with patch.dict(LLMGateway.PROVIDER_CLASSES, {"mock": MockProvider}):
        return LLMGateway(mock_config)


@pytest.mark.asyncio
async def test_gateway_initialization(gateway):
    """Test that gateway initializes providers correctly."""
    assert len(gateway.providers) == 2
    assert "mock_local" in gateway.providers
    assert "mock_cloud" in gateway.providers
    assert isinstance(gateway.providers["mock_local"], MockProvider)


@pytest.mark.asyncio
async def test_gateway_routing(gateway):
    """Test that requests are routed to correct provider."""
    response = await gateway.complete(
        task_type="extraction",
        prompt="Test prompt"
    )

    assert response.content == "Mock response"
    assert response.provider == "mock"
    assert gateway.providers["mock_local"].complete_called


@pytest.mark.asyncio
async def test_gateway_missing_routing():
    """Test error when task type has no routing rule."""
    config = {
        "providers": {"mock": {"provider": "mock", "model": "test"}},
        "routing": {},
    }

    with patch.dict(LLMGateway.PROVIDER_CLASSES, {"mock": MockProvider}):
        gateway = LLMGateway(config)

        with pytest.raises(LLMProviderNotFoundError, match="No routing rule"):
            await gateway.complete(task_type="unknown", prompt="test")


@pytest.mark.asyncio
async def test_gateway_fallback(mock_config):
    """Test automatic fallback when primary provider fails."""

    class FailingProvider(BaseLLMProvider):
        async def complete(self, request: LLMRequest) -> LLMResponse:
            raise LLMError("Primary provider failed")

        async def health_check(self) -> bool:
            return False

    with patch.dict(
        LLMGateway.PROVIDER_CLASSES,
        {"failing": FailingProvider, "mock": MockProvider}
    ):
        config = {
            "providers": {
                "primary": {"provider": "failing", "model": "fail"},
                "backup": {"provider": "mock", "model": "backup"},
            },
            "routing": {"test": "primary"},
            "fallback": {
                "enabled": True,
                "rules": {"primary": ["backup"]},
            },
        }

        gateway = LLMGateway(config)
        response = await gateway.complete(task_type="test", prompt="test")

        # Should succeed with fallback
        assert response.content == "Mock response"
        assert gateway.providers["backup"].complete_called


@pytest.mark.asyncio
async def test_health_check_all(gateway):
    """Test checking health of all providers."""
    results = await gateway.health_check_all()

    assert len(results) == 2
    assert results["mock_local"] is True
    assert results["mock_cloud"] is True
    assert gateway.providers["mock_local"].health_check_called


@pytest.mark.asyncio
async def test_health_check_single(gateway):
    """Test checking health of specific provider."""
    result = await gateway.health_check("mock_local")

    assert result is True
    assert gateway.providers["mock_local"].health_check_called


@pytest.mark.asyncio
async def test_list_providers(gateway):
    """Test listing configured providers."""
    providers = gateway.list_providers()

    assert len(providers) == 2
    assert "mock_local" in providers
    assert providers["mock_local"]["model"] == "mock-model-1"


@pytest.mark.asyncio
async def test_get_routing_info(gateway):
    """Test getting routing configuration."""
    routing = gateway.get_routing_info()

    assert routing["extraction"] == "mock_local"
    assert routing["ocr"] == "mock_local"
