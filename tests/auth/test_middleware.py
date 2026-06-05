"""Tests for auth middleware."""

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from reserve_automation.web.auth.config import AuthConfig, DevConfig, RoleConfig
from reserve_automation.web.auth.middleware import AuthMiddleware
from reserve_automation.web.auth.models import AuthenticatedUser


def _create_test_app(auth_config: AuthConfig) -> FastAPI:
    """Create a minimal test app with auth middleware."""
    app = FastAPI()
    app.state.auth_config = auth_config
    app.add_middleware(AuthMiddleware, auth_config=auth_config)

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/protected")
    async def protected(request: Request):
        user = request.state.user
        return {"email": user.email, "role": user.role}

    @app.get("/page")
    async def page(request: Request):
        user = request.state.user
        return {"user": user.email}

    return app


class TestDevMode:
    """Test dev mode authentication."""

    def test_dev_mode_sets_user(self):
        config = AuthConfig(
            dev=DevConfig(enabled=True, mock_user_email="dev@test.com", mock_user_role="admin", require_local_subnet=False),
        )
        app = _create_test_app(config)
        client = TestClient(app)

        resp = client.get("/api/v1/protected")
        assert resp.status_code == 200
        assert resp.json()["email"] == "dev@test.com"
        assert resp.json()["role"] == "admin"

    def test_dev_mode_role_override_cookie(self):
        config = AuthConfig(
            dev=DevConfig(enabled=True, mock_user_email="dev@test.com", mock_user_role="admin", require_local_subnet=False),
            roles={
                "admin": RoleConfig(emails=["admin@test.com"]),
                "family": RoleConfig(emails=["family@test.com"]),
            },
        )
        app = _create_test_app(config)
        client = TestClient(app)

        # Override to family
        resp = client.get("/api/v1/protected", cookies={"dev_role_override": "family"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "family"

        # Override to guest
        resp = client.get("/api/v1/protected", cookies={"dev_role_override": "guest"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "guest"

    def test_dev_mode_invalid_role_override_uses_default(self):
        config = AuthConfig(
            dev=DevConfig(enabled=True, mock_user_email="dev@test.com", mock_user_role="admin", require_local_subnet=False),
        )
        app = _create_test_app(config)
        client = TestClient(app)

        # Invalid role override falls back to default
        resp = client.get("/api/v1/protected", cookies={"dev_role_override": "superadmin"})
        assert resp.status_code == 200
        assert resp.json()["role"] == "admin"


class TestPublicPaths:
    """Test that public paths bypass auth."""

    def test_health_is_public(self):
        # Even in prod mode (dev disabled), health should work
        config = AuthConfig(dev=DevConfig(enabled=False))
        app = _create_test_app(config)
        client = TestClient(app)

        resp = client.get("/api/v1/health")
        assert resp.status_code == 200


class TestProdMode:
    """Test production mode (Cloudflare Access)."""

    def test_no_jwt_returns_401(self):
        config = AuthConfig(dev=DevConfig(enabled=False))
        app = _create_test_app(config)
        client = TestClient(app)

        resp = client.get("/api/v1/protected")
        assert resp.status_code == 401

    def test_page_no_jwt_returns_401(self):
        config = AuthConfig(dev=DevConfig(enabled=False))
        app = _create_test_app(config)
        client = TestClient(app)

        resp = client.get("/page")
        assert resp.status_code == 401


class TestDevModeSubnetGate:
    """Regression: dev mode must not grant auth to non-local clients.

    This guards the bypass chain where dev.enabled was true *and* the app
    port was reachable outside Cloudflare — without an IP gate, any direct
    hit landed on admin via the mock user.
    """

    def test_dev_mode_with_subnet_check_rejects_non_local(self):
        # TestClient's peer host is "testclient" — not in any real subnet.
        config = AuthConfig(
            dev=DevConfig(
                enabled=True,
                mock_user_email="dev@test.com",
                mock_user_role="admin",
                require_local_subnet=True,
            ),
        )
        app = _create_test_app(config)
        client = TestClient(app)

        resp = client.get("/api/v1/protected")
        assert resp.status_code == 401

    def test_dev_mode_role_override_rejected_when_off_subnet(self):
        config = AuthConfig(
            dev=DevConfig(
                enabled=True,
                mock_user_email="dev@test.com",
                mock_user_role="admin",
                require_local_subnet=True,
            ),
        )
        app = _create_test_app(config)
        client = TestClient(app)

        # Even with the override cookie, off-subnet clients must not be authed.
        resp = client.get("/api/v1/protected", cookies={"dev_role_override": "admin"})
        assert resp.status_code == 401


class TestAuthenticatedUser:
    """Test the AuthenticatedUser model."""

    def test_display_name_derived_from_email(self):
        user = AuthenticatedUser(email="john.doe@example.com", role="admin")
        assert user.display_name == "John Doe"

    def test_display_name_explicit(self):
        user = AuthenticatedUser(email="a@b.com", role="admin", display_name="Alice")
        assert user.display_name == "Alice"
