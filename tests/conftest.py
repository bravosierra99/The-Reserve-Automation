"""Pytest configuration and fixtures for all tests."""

import os
from pathlib import Path

import pytest


def _lm_studio_available() -> bool:
    """Probe the configured LM Studio endpoint.

    Mirrors the config the app/CLI use (RESERVE_LM_STUDIO_URL + LM_STUDIO_API_KEY).
    Returns True only on HTTP 200 from /models, so a 401 (keyless) or a refused
    connection both correctly gate real-LLM tests off.
    """
    import httpx

    base_url = os.environ.get("RESERVE_LM_STUDIO_URL", "http://localhost:1234/v1").rstrip("/")
    api_key = os.environ.get("LM_STUDIO_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        resp = httpx.get(f"{base_url}/models", headers=headers, timeout=3.0)
        return resp.status_code == 200
    except Exception:
        return False


# Cache the probe result for the whole session (None = not yet probed).
_LM_STUDIO_AVAILABLE: bool | None = None


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked `requires_lm_studio` when no LM Studio is reachable.

    Consolidates the previously ad-hoc in-test `pytest.skip("likely no LLM")`
    pattern into one discoverable marker + a single reachability probe per session.
    """
    global _LM_STUDIO_AVAILABLE
    skip_marker = None
    for item in items:
        if item.get_closest_marker("requires_lm_studio") is None:
            continue
        if _LM_STUDIO_AVAILABLE is None:
            _LM_STUDIO_AVAILABLE = _lm_studio_available()
        if not _LM_STUDIO_AVAILABLE:
            if skip_marker is None:
                skip_marker = pytest.mark.skip(
                    reason="LM Studio not reachable — set RESERVE_LM_STUDIO_URL + "
                    "LM_STUDIO_API_KEY and load a model to run real-LLM tests"
                )
            item.add_marker(skip_marker)


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables before any tests run."""
    # Set WEB_SECRET_KEY for web tests
    os.environ.setdefault("WEB_SECRET_KEY", "test_secret_key_for_testing_only_not_secure_32_chars_min")

    # Set LM Studio URL (use localhost default if not already set)
    os.environ.setdefault("RESERVE_LM_STUDIO_URL", "http://localhost:1234/v1")

    # Set vault path for tests (still needed by some services that use Config)
    os.environ.setdefault("RESERVE_VAULT_PATH", "/tmp/test-vault")

    # Create the isolated test vault directory so Config.load()'s path
    # validation passes deterministically. Previously this dir was only created
    # by tests/tastings/run_all_tests.sh, leaving vault-dependent tests reliant
    # on test ordering / leaked env vars when pytest was run directly.
    vault_path = Path(os.environ["RESERVE_VAULT_PATH"])
    for subdir in ("1_Wines", "1_Whiskeys"):
        (vault_path / subdir).mkdir(parents=True, exist_ok=True)

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
    import reserve_automation.web.app as app_module
    import reserve_automation.web.auth.config as config_module
    import reserve_automation.web.config as web_config_module

    # 1. Enable dev mode on the already-loaded module-level config
    # require_local_subnet is also disabled because TestClient uses "testclient"
    # as the source IP, which isn't a valid IP and would fail the subnet check.
    app_module._startup_auth_config.dev.enabled = True
    app_module._startup_auth_config.dev.require_local_subnet = False

    # 2. Enable dev mode on app.state.auth_config (set at module level)
    if hasattr(app_module.app.state, "auth_config") and app_module.app.state.auth_config is not None:
        app_module.app.state.auth_config.dev.enabled = True
        app_module.app.state.auth_config.dev.require_local_subnet = False

    # 3. Patch load_auth_config so lifespan re-loads also get dev mode
    _original = config_module.load_auth_config

    def _load_with_dev_enabled(*args, **kwargs):
        config = _original(*args, **kwargs)
        config.dev.enabled = True
        config.dev.require_local_subnet = False
        return config

    config_module.load_auth_config = _load_with_dev_enabled
    web_config_module.load_auth_config = _load_with_dev_enabled
    app_module.load_auth_config = _load_with_dev_enabled

    yield

    # Restore
    config_module.load_auth_config = _original
    web_config_module.load_auth_config = _original
    app_module.load_auth_config = _original
