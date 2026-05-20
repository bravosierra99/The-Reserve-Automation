"""Cloudflare Access JWT validation with key caching."""

import time
from typing import Optional

import httpx
import jwt
from loguru import logger

from .config import CloudflareConfig


class CloudflareJWTValidator:
    """Validates Cloudflare Access JWTs using the team's public keys."""

    def __init__(self, config: CloudflareConfig):
        self.config = config
        self._jwks: Optional[dict] = None
        self._jwks_fetched_at: float = 0
        self._cache_ttl: int = 3600      # 1 hour: refresh interval
        self._cache_max_age: int = 14400  # 4 hours: hard cap on stale cache use.
                                         # Was 24h — that gave a forged-token
                                         # window of up to a day if CF rotated a
                                         # compromised signing key during a JWKS
                                         # fetch outage. 4h keeps the availability
                                         # benefit (JWKS hiccup tolerance) while
                                         # bounding the worst case.

    @property
    def certs_url(self) -> str:
        return f"https://{self.config.team_domain}/cdn-cgi/access/certs"

    async def _fetch_jwks(self) -> dict:
        """Fetch JWKS from Cloudflare Access."""
        async with httpx.AsyncClient() as client:
            response = await client.get(self.certs_url, timeout=10)
            response.raise_for_status()
            return response.json()

    async def _get_jwks(self) -> dict:
        """Get JWKS, using cache if fresh."""
        now = time.time()
        if self._jwks is None or (now - self._jwks_fetched_at) > self._cache_ttl:
            try:
                self._jwks = await self._fetch_jwks()
                self._jwks_fetched_at = now
                logger.debug("Refreshed Cloudflare Access JWKS")
            except Exception as e:
                logger.error(f"Failed to fetch JWKS: {e}")
                if self._jwks is None:
                    raise
                # Use stale cache on transient failures, but not indefinitely.
                # If the cache is older than _cache_max_age, refuse to serve it —
                # a key rotation may have occurred and continuing with old keys
                # could allow forged tokens to pass validation.
                cache_age = now - self._jwks_fetched_at
                if cache_age > self._cache_max_age:
                    logger.error(
                        f"JWKS cache is {cache_age:.0f}s old (max {self._cache_max_age}s) "
                        "and refresh failed — refusing stale keys"
                    )
                    raise
                logger.warning(f"Using stale JWKS cache ({cache_age:.0f}s old)")
        return self._jwks

    async def validate_token(self, token: str) -> Optional[dict]:
        """Validate a Cloudflare Access JWT.

        Args:
            token: The JWT string from Cf-Access-Jwt-Assertion header.

        Returns:
            Decoded token claims if valid, None if invalid.
        """
        try:
            jwks_data = await self._get_jwks()
            public_keys = jwt.PyJWKSet.from_dict(jwks_data)

            # Decode the token header to find the key ID
            unverified_header = jwt.get_unverified_header(token)
            kid = unverified_header.get("kid")

            # Find the matching key
            signing_key = None
            for key in public_keys.keys:
                if key.key_id == kid:
                    signing_key = key
                    break

            if signing_key is None:
                logger.warning(f"No matching key found for kid={kid}")
                return None

            # Decode and verify against any configured audience tag
            for aud in self.config.audience_tags:
                try:
                    claims = jwt.decode(
                        token,
                        signing_key.key,
                        algorithms=["RS256"],
                        audience=aud,
                    )
                    return claims
                except jwt.InvalidAudienceError:
                    continue

            logger.debug("JWT audience did not match any configured audience tags")
            return None

        except jwt.ExpiredSignatureError:
            logger.debug("JWT token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.debug(f"Invalid JWT token: {e}")
            return None
        except Exception as e:
            logger.error(f"JWT validation error: {e}")
            return None
