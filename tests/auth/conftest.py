"""Auth test fixtures."""

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def test_auth_yaml(tmp_path_factory):
    """Create a test auth.yaml config."""
    auth_dir = tmp_path_factory.mktemp("auth-config")
    auth_path = auth_dir / "auth.yaml"

    config = {
        "cloudflare": {
            "team_domain": "test.cloudflareaccess.com",
            "audience_tag": "test-audience-tag",
            "jwt_header": "Cf-Access-Jwt-Assertion",
        },
        "dev": {
            "enabled": True,
            "mock_user_email": "admin@localhost",
            "mock_user_role": "admin",
            "toolbar_subnets": ["127.0.0.0/8", "10.0.0.0/8"],
        },
        "roles": {
            "admin": {"emails": ["admin@test.com", "admin2@test.com"]},
            "family": {"emails": ["family@test.com"]},
        },
        "permissions": {
            "bottles.view": ["admin", "family", "guest"],
            "bottles.create": ["admin"],
            "bottles.edit": ["admin"],
            "bottles.delete": ["admin"],
            "tastings.view": ["admin", "family", "guest"],
            "tastings.submit": ["admin", "family"],
            "management.access": ["admin"],
            "upload.access": ["admin"],
            "events.view": ["admin", "family", "guest"],
            "events.create": ["admin", "family"],
            "events.manage": ["admin"],
            "events.participate": ["admin", "family", "guest"],
            "ingredients.view": ["admin", "family", "guest"],
            "ingredients.create": ["admin"],
            "cocktails.view": ["admin", "family", "guest"],
            "cocktails.create": ["admin", "family"],
            "cocktails.delete": ["admin"],
            "labels.view": ["admin", "family", "guest"],
            "labels.edit": ["admin"],
        },
    }

    with open(auth_path, "w") as f:
        yaml.dump(config, f)

    return auth_path


@pytest.fixture(scope="module")
def test_vault():
    """Create a minimal test vault for auth tests."""
    vault_path = Path(f"/tmp/test-vault-auth-{uuid.uuid4().hex[:8]}")
    vault_path.mkdir(parents=True, exist_ok=True)

    # Create minimal vault structure
    for subdir in ["1_Wines", "1_Whiskeys", "2_Ingredients", "3_Cocktails"]:
        (vault_path / subdir).mkdir(exist_ok=True)

    yield vault_path

    # Cleanup
    import shutil
    if vault_path.exists():
        shutil.rmtree(vault_path)


@pytest.fixture(scope="module")
def auth_test_client(test_auth_yaml, test_vault):
    """Create a test client with auth middleware enabled."""
    # Set env vars before import
    os.environ["RESERVE_VAULT_PATH"] = str(test_vault)
    os.environ["WEB_SECRET_KEY"] = "test_secret_key_for_testing_only_not_secure_32_chars_min"

    from reserve_automation.web.auth.config import load_auth_config
    from reserve_automation.web.app import app

    auth_config = load_auth_config(test_auth_yaml)
    app.state.auth_config = auth_config

    # Ensure middleware is registered (only add once)
    from reserve_automation.web.auth.middleware import AuthMiddleware
    has_auth_middleware = any(
        isinstance(getattr(m, "cls", None), type) and issubclass(getattr(m, "cls", type), AuthMiddleware)
        for m in getattr(app, "user_middleware", [])
    )
    if not has_auth_middleware:
        app.add_middleware(AuthMiddleware, auth_config=auth_config)

    client = TestClient(app)
    yield client
