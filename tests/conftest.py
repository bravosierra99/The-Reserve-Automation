"""Pytest configuration and fixtures for all tests."""

import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables before any tests run."""
    # Set WEB_SECRET_KEY for web tests
    os.environ.setdefault("WEB_SECRET_KEY", "test_secret_key_for_testing_only_not_secure_32_chars_min")

    # Set LM Studio URL (use localhost default if not already set)
    os.environ.setdefault("RESERVE_LM_STUDIO_URL", "http://localhost:1234/v1")

    # Set vault path for tests (still needed by some services that use Config)
    os.environ.setdefault("RESERVE_VAULT_PATH", "/tmp/test-vault")

    # Use in-memory SQLite for tests. This ensures the app lifespan
    # re-uses the same in-memory DB instead of creating a file-based one.
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

    yield


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Initialize in-memory SQLite database for all tests.

    This replaces the vault-based test fixtures. Uses in-memory SQLite so
    tests are fast and completely isolated from production data.
    """
    from reserve_automation.db.engine import init_db

    # Initialize in-memory database - tables created automatically
    init_db("sqlite:///:memory:")

    yield


@pytest.fixture(scope="session", autouse=True)
def enable_dev_mode_for_tests():
    """Enable dev mode on the app so API tests can authenticate.

    Production config has dev.enabled: false (fail-closed). Tests need dev mode
    to bypass Cloudflare JWT validation.

    We patch three things:
    1. app.state.auth_config (used by middleware at request time and by require())
    2. _startup_auth_config (used as middleware fallback)
    3. load_auth_config (so lifespan re-loads also get dev mode)
    """
    import reserve_automation.web.auth.config as config_module
    import reserve_automation.web.config as web_config_module
    import reserve_automation.web.app as app_module

    # 1. Enable dev mode on the already-loaded module-level config
    app_module._startup_auth_config.dev.enabled = True

    # 2. Enable dev mode on app.state.auth_config (set at module level)
    if hasattr(app_module.app.state, "auth_config") and app_module.app.state.auth_config is not None:
        app_module.app.state.auth_config.dev.enabled = True

    # 3. Patch load_auth_config so lifespan re-loads also get dev mode
    _original = config_module.load_auth_config

    def _load_with_dev_enabled(*args, **kwargs):
        config = _original(*args, **kwargs)
        config.dev.enabled = True
        return config

    config_module.load_auth_config = _load_with_dev_enabled
    web_config_module.load_auth_config = _load_with_dev_enabled
    app_module.load_auth_config = _load_with_dev_enabled

    yield

    # Restore
    config_module.load_auth_config = _original
    web_config_module.load_auth_config = _original
    app_module.load_auth_config = _original
