"""Tests for auth configuration."""

import tempfile
from pathlib import Path

import pytest
import yaml

from reserve_automation.web.auth.config import (
    AuthConfig,
    CloudflareConfig,
    DevConfig,
    RoleConfig,
    load_auth_config,
)


class TestAuthConfig:
    """Test AuthConfig model."""

    def test_resolve_role_admin(self):
        config = AuthConfig(
            roles={
                "admin": RoleConfig(emails=["admin@test.com"]),
                "family": RoleConfig(emails=["family@test.com"]),
            }
        )
        assert config.resolve_role("admin@test.com") == "admin"

    def test_resolve_role_family(self):
        config = AuthConfig(
            roles={
                "admin": RoleConfig(emails=["admin@test.com"]),
                "family": RoleConfig(emails=["family@test.com"]),
            }
        )
        assert config.resolve_role("family@test.com") == "family"

    def test_resolve_role_guest_fallback(self):
        config = AuthConfig(
            roles={
                "admin": RoleConfig(emails=["admin@test.com"]),
            }
        )
        assert config.resolve_role("stranger@test.com") == "guest"

    def test_resolve_role_case_insensitive(self):
        config = AuthConfig(
            roles={
                "admin": RoleConfig(emails=["Admin@Test.com"]),
            }
        )
        assert config.resolve_role("admin@test.com") == "admin"
        assert config.resolve_role("ADMIN@TEST.COM") == "admin"

    def test_has_permission(self):
        config = AuthConfig(
            permissions={
                "bottles.view": ["admin", "family", "guest"],
                "bottles.create": ["admin"],
            }
        )
        assert config.has_permission("admin", "bottles.view") is True
        assert config.has_permission("guest", "bottles.view") is True
        assert config.has_permission("admin", "bottles.create") is True
        assert config.has_permission("guest", "bottles.create") is False
        assert config.has_permission("family", "bottles.create") is False

    def test_has_permission_unknown(self):
        config = AuthConfig(permissions={})
        assert config.has_permission("admin", "unknown.perm") is False

    def test_get_permissions_dict(self):
        config = AuthConfig(
            permissions={
                "bottles.view": ["admin", "guest"],
                "bottles.create": ["admin"],
            }
        )
        perms = config.get_permissions_dict("admin")
        assert perms["bottles_view"] is True
        assert perms["bottles_create"] is True

        perms = config.get_permissions_dict("guest")
        assert perms["bottles_view"] is True
        assert perms["bottles_create"] is False


class TestLoadAuthConfig:
    """Test YAML config loading."""

    def test_load_from_file(self, tmp_path):
        config_data = {
            "cloudflare": {
                "team_domain": "myteam.cloudflareaccess.com",
                "audience_tag": "my-audience",
            },
            "dev": {
                "enabled": True,
                "mock_user_email": "dev@test.com",
                "mock_user_role": "admin",
            },
            "roles": {
                "admin": {"emails": ["a@test.com"]},
                "family": {"emails": ["f@test.com"]},
            },
            "permissions": {
                "bottles.view": ["admin", "family", "guest"],
                "bottles.create": ["admin"],
            },
        }

        config_path = tmp_path / "auth.yaml"
        with open(config_path, "w") as f:
            yaml.dump(config_data, f)

        config = load_auth_config(config_path)
        assert config.cloudflare.team_domain == "myteam.cloudflareaccess.com"
        assert config.dev.enabled is True
        assert config.resolve_role("a@test.com") == "admin"
        assert config.resolve_role("f@test.com") == "family"
        assert config.resolve_role("x@test.com") == "guest"
        assert config.has_permission("admin", "bottles.view") is True
        assert config.has_permission("guest", "bottles.create") is False

    def test_load_missing_file_returns_default(self):
        config = load_auth_config(Path("/nonexistent/auth.yaml"))
        assert config.dev.enabled is False  # Fail closed: dev mode off by default

    def test_load_empty_file(self, tmp_path):
        config_path = tmp_path / "auth.yaml"
        config_path.write_text("")
        config = load_auth_config(config_path)
        assert config.dev.enabled is False  # Fail closed: dev mode off by default


class TestDevConfig:
    """Test DevConfig defaults."""

    def test_defaults(self):
        dev = DevConfig()
        assert dev.enabled is False
        assert dev.mock_user_email == "admin@localhost"
        assert dev.mock_user_role == "admin"
        assert len(dev.toolbar_subnets) == 4
