"""Tests for JWT validation."""

import json
import time
from unittest.mock import AsyncMock, patch

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from reserve_automation.web.auth.config import CloudflareConfig
from reserve_automation.web.auth.jwt import CloudflareJWTValidator


def _generate_test_rsa_keypair():
    """Generate an RSA key pair for testing."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    return private_key, public_key


def _make_jwks(public_key, kid="test-kid-1"):
    """Create a JWKS dict from a public key."""
    from jwt.algorithms import RSAAlgorithm
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_dict["kid"] = kid
    jwk_dict["use"] = "sig"
    return {"keys": [jwk_dict]}


def _make_token(private_key, claims, kid="test-kid-1"):
    """Create a signed JWT token."""
    return pyjwt.encode(
        claims,
        private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )


class TestCloudflareJWTValidator:
    """Test JWT validation logic."""

    @pytest.fixture
    def config(self):
        return CloudflareConfig(
            team_domain="test.cloudflareaccess.com",
            audience_tag="test-audience",
        )

    @pytest.fixture
    def keypair(self):
        return _generate_test_rsa_keypair()

    @pytest.mark.asyncio
    async def test_valid_token(self, config, keypair):
        private_key, public_key = keypair
        jwks = _make_jwks(public_key)
        claims = {
            "email": "user@test.com",
            "aud": "test-audience",
            "iss": f"https://test.cloudflareaccess.com",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(private_key, claims)

        validator = CloudflareJWTValidator(config)
        validator._jwks = jwks
        validator._jwks_fetched_at = time.time()

        result = await validator.validate_token(token)
        assert result is not None
        assert result["email"] == "user@test.com"

    @pytest.mark.asyncio
    async def test_expired_token(self, config, keypair):
        private_key, public_key = keypair
        jwks = _make_jwks(public_key)
        claims = {
            "email": "user@test.com",
            "aud": "test-audience",
            "iat": int(time.time()) - 7200,
            "exp": int(time.time()) - 3600,  # Expired 1 hour ago
        }
        token = _make_token(private_key, claims)

        validator = CloudflareJWTValidator(config)
        validator._jwks = jwks
        validator._jwks_fetched_at = time.time()

        result = await validator.validate_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_audience(self, config, keypair):
        private_key, public_key = keypair
        jwks = _make_jwks(public_key)
        claims = {
            "email": "user@test.com",
            "aud": "wrong-audience",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(private_key, claims)

        validator = CloudflareJWTValidator(config)
        validator._jwks = jwks
        validator._jwks_fetched_at = time.time()

        result = await validator.validate_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_wrong_kid(self, config, keypair):
        private_key, public_key = keypair
        jwks = _make_jwks(public_key, kid="different-kid")
        claims = {
            "email": "user@test.com",
            "aud": "test-audience",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(private_key, claims, kid="unknown-kid")

        validator = CloudflareJWTValidator(config)
        validator._jwks = jwks
        validator._jwks_fetched_at = time.time()

        result = await validator.validate_token(token)
        assert result is None

    @pytest.mark.asyncio
    async def test_invalid_token_string(self, config):
        validator = CloudflareJWTValidator(config)
        validator._jwks = {"keys": []}
        validator._jwks_fetched_at = time.time()

        result = await validator.validate_token("not-a-jwt-token")
        assert result is None

    @pytest.mark.asyncio
    async def test_jwks_cache(self, config, keypair):
        private_key, public_key = keypair
        jwks = _make_jwks(public_key)

        validator = CloudflareJWTValidator(config)
        # Pre-fill cache
        validator._jwks = jwks
        validator._jwks_fetched_at = time.time()

        claims = {
            "email": "user@test.com",
            "aud": "test-audience",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(private_key, claims)

        # Should use cache (no HTTP call)
        result = await validator.validate_token(token)
        assert result is not None
        assert result["email"] == "user@test.com"

    @pytest.mark.asyncio
    async def test_stale_cache_triggers_refresh(self, config, keypair):
        private_key, public_key = keypair
        jwks = _make_jwks(public_key)

        validator = CloudflareJWTValidator(config)
        validator._jwks = jwks
        # Set cache as very old
        validator._jwks_fetched_at = time.time() - 7200

        # Mock the fetch to return the same JWKS
        validator._fetch_jwks = AsyncMock(return_value=jwks)

        claims = {
            "email": "user@test.com",
            "aud": "test-audience",
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        token = _make_token(private_key, claims)

        result = await validator.validate_token(token)
        assert result is not None
        validator._fetch_jwks.assert_called_once()
