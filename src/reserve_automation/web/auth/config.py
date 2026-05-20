"""Auth configuration models and loader."""

import os
import re
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


class CloudflareConfig(BaseModel):
    """Cloudflare Access configuration."""
    team_domain: str = "yourteam.cloudflareaccess.com"
    audience_tag: str | list[str] = ""
    jwt_header: str = "Cf-Access-Jwt-Assertion"

    @property
    def audience_tags(self) -> list[str]:
        """Return audience tags as a list (supports single string or list)."""
        if isinstance(self.audience_tag, list):
            return self.audience_tag
        return [self.audience_tag] if self.audience_tag else []


class DevConfig(BaseModel):
    """Dev mode configuration."""
    enabled: bool = False
    mock_user_email: str = "admin@localhost"
    mock_user_role: str = "admin"
    toolbar_subnets: list[str] = Field(
        default=["192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12", "127.0.0.0/8"]
    )
    # When enabled is true, the middleware additionally requires the request's
    # source IP to fall inside toolbar_subnets. The test suite flips this to
    # False because Starlette's TestClient uses "testclient" as the peer host,
    # which isn't a valid IP. Never set this to False in a deployed config.
    require_local_subnet: bool = True


class RoleConfig(BaseModel):
    """Configuration for a single role."""
    emails: list[str] = Field(default_factory=list)


class AuthConfig(BaseModel):
    """Top-level auth configuration."""
    cloudflare: CloudflareConfig = Field(default_factory=CloudflareConfig)
    dev: DevConfig = Field(default_factory=DevConfig)
    roles: dict[str, RoleConfig] = Field(default_factory=dict)
    permissions: dict[str, list[str]] = Field(default_factory=dict)

    def resolve_role(self, email: str) -> str:
        """Resolve an email address to a role name.

        Checks admin, then family, falls back to 'guest'.
        """
        for role_name, role_config in self.roles.items():
            if email.lower() in [e.lower() for e in role_config.emails]:
                return role_name
        return "guest"

    def has_permission(self, role: str, permission: str) -> bool:
        """Check if a role has a specific permission."""
        allowed_roles = self.permissions.get(permission, [])
        return role in allowed_roles

    def get_permissions_dict(self, role: str) -> dict[str, bool]:
        """Get a dict of all permissions for a role (key format: bottles_view)."""
        result = {}
        for perm, allowed_roles in self.permissions.items():
            # Convert dots to underscores for JS-friendly keys
            key = perm.replace(".", "_")
            result[key] = role in allowed_roles
        return result


def load_auth_config(config_path: Optional[Path] = None) -> AuthConfig:
    """Load auth config from YAML file.

    Args:
        config_path: Path to auth.yaml. If None, searches in standard locations.

    Returns:
        AuthConfig instance.
    """
    if config_path is None:
        # Search in standard locations
        candidates = [
            Path(__file__).parent.parent.parent.parent.parent / "config" / "auth.yaml",
            Path("config/auth.yaml"),
        ]
        for candidate in candidates:
            if candidate.exists():
                config_path = candidate
                break

    if config_path is None or not config_path.exists():
        # Return default config (fail closed - dev mode disabled)
        return AuthConfig(dev=DevConfig(enabled=False))

    with open(config_path) as f:
        raw = f.read()

    # Expand ${VAR} references from environment
    raw = re.sub(r"\$\{(\w+)\}", lambda m: os.environ.get(m.group(1), m.group(0)), raw)
    data = yaml.safe_load(raw)

    if not data:
        return AuthConfig(dev=DevConfig(enabled=False))

    # Parse roles
    roles = {}
    for role_name, role_data in data.get("roles", {}).items():
        if isinstance(role_data, dict):
            roles[role_name] = RoleConfig(**role_data)
        else:
            roles[role_name] = RoleConfig()

    dev_data = data.get("dev", {})
    # AUTH_DEV_ENABLED env var overrides the committed dev.enabled value so the
    # checked-in config can stay false. Truthy values: 1/true/yes/on.
    dev_env = os.environ.get("AUTH_DEV_ENABLED")
    if dev_env is not None:
        dev_data = {**dev_data, "enabled": dev_env.strip().lower() in ("1", "true", "yes", "on")}

    config = AuthConfig(
        cloudflare=CloudflareConfig(**data.get("cloudflare", {})),
        dev=DevConfig(**dev_data),
        roles=roles,
        permissions=data.get("permissions", {}),
    )

    from loguru import logger
    for role_name, role_config in config.roles.items():
        logger.info(f"Auth config: role={role_name!r} emails={role_config.emails}")

    return config
