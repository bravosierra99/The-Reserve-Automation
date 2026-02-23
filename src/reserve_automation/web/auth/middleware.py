"""Auth middleware for FastAPI."""

import ipaddress
from typing import Optional

from fastapi import Request
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .config import AuthConfig
from .jwt import CloudflareJWTValidator
from .models import AuthenticatedUser


# Paths that don't require authentication
PUBLIC_PATHS = {
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/redoc",
}

# Path prefixes that don't require authentication
PUBLIC_PREFIXES = (
    "/static/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    """Middleware that authenticates requests via Cloudflare Access JWT or dev mode."""

    def __init__(self, app, auth_config: AuthConfig):
        super().__init__(app)
        self.auth_config = auth_config
        self.jwt_validator = CloudflareJWTValidator(auth_config.cloudflare)

    async def dispatch(self, request: Request, call_next):
        # Skip auth for public paths
        if self._is_public_path(request.url.path):
            return await call_next(request)

        user = None

        if self.auth_config.dev.enabled:
            user = self._get_dev_user(request)
        else:
            user = await self._get_cloudflare_user(request)

        if user is None:
            # No valid auth - return 401 for API, redirect for pages
            if request.url.path.startswith("/api/"):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Authentication required"},
                )
            # For page requests, Cloudflare Access handles the redirect
            # If we get here without a user, something is wrong
            return JSONResponse(
                status_code=401,
                content={"detail": "Authentication required"},
            )

        # Set user on request state
        request.state.user = user
        return await call_next(request)

    def _is_public_path(self, path: str) -> bool:
        """Check if path is public (no auth required)."""
        if path in PUBLIC_PATHS:
            return True
        for prefix in PUBLIC_PREFIXES:
            if path.startswith(prefix):
                return True
        return False

    def _get_dev_user(self, request: Request) -> AuthenticatedUser:
        """Get user from dev mode (cookie override or default mock)."""
        dev = self.auth_config.dev

        # Check for role override cookie
        role_override = request.cookies.get("dev_role_override")
        if role_override and role_override in ("admin", "family", "guest"):
            role = role_override
            # Use a mock email for the overridden role
            if role == "admin" and self.auth_config.roles.get("admin"):
                email = self.auth_config.roles["admin"].emails[0] if self.auth_config.roles["admin"].emails else dev.mock_user_email
            elif role == "family" and self.auth_config.roles.get("family"):
                email = self.auth_config.roles["family"].emails[0] if self.auth_config.roles["family"].emails else "family@localhost"
            else:
                email = "guest@localhost"
        else:
            email = dev.mock_user_email
            role = dev.mock_user_role

        return AuthenticatedUser(email=email, role=role)

    async def _get_cloudflare_user(self, request: Request) -> Optional[AuthenticatedUser]:
        """Get user from Cloudflare Access JWT."""
        jwt_header = self.auth_config.cloudflare.jwt_header
        token = request.headers.get(jwt_header)

        if not token:
            return None

        claims = await self.jwt_validator.validate_token(token)
        if not claims:
            return None

        email = claims.get("email", "")
        if not email:
            return None

        role = self.auth_config.resolve_role(email)

        return AuthenticatedUser(email=email, role=role)

    def _is_local_subnet(self, request: Request) -> bool:
        """Check if request comes from a local subnet (for dev toolbar visibility)."""
        client_ip = request.client.host if request.client else None
        if not client_ip:
            return False

        try:
            addr = ipaddress.ip_address(client_ip)
            for subnet_str in self.auth_config.dev.toolbar_subnets:
                if addr in ipaddress.ip_network(subnet_str):
                    return True
        except ValueError:
            pass
        return False
