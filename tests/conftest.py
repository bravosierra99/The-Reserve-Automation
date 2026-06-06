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
        if resp.status_code != 200:
            return False
        # A reachable server with no model loaded returns 200 + {"data": []}.
        # Require at least one model so real-LLM tests skip (not noisily fail)
        # in that case — matching the skip reason's "load a model" guidance.
        return bool(resp.json().get("data"))
    except Exception:
        return False


# Cache the probe result for the whole session (None = not yet probed).
_LM_STUDIO_AVAILABLE: bool | None = None


def pytest_collection_modifyitems(config, items):
    """Auto-skip tests marked `requires_lm_studio` when no LM Studio is reachable.

    A discoverable marker + single per-session reachability probe, offered as a
    cleaner alternative to the ad-hoc in-test `pytest.skip("likely no LLM")`
    pattern still used in a few suites (test_bottle_stateless_upload.py et al.).
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
    #
    # Safety: only ever auto-create an isolated /tmp vault. If RESERVE_VAULT_PATH
    # was exported to a real vault, never mkdir inside it — dev must not touch
    # personal data (see CLAUDE.md dev/prod separation).
    vault_path = Path(os.environ["RESERVE_VAULT_PATH"])
    if str(vault_path).startswith("/tmp/"):
        for subdir in ("1_Wines", "1_Whiskeys"):
            (vault_path / subdir).mkdir(parents=True, exist_ok=True)

    # Isolate label/image media to a tmp dir so the label-crop endpoint tests
    # never read or overwrite real bottle images under data/media. The label
    # routes resolve MEDIA_DIR/bottles/{id}/label.jpg by integer id, which
    # collides with real bottle ids; without this a crop test would clobber a
    # production label (CLAUDE.md: tests use isolated /tmp, never real data).
    os.environ.setdefault("MEDIA_DIR", "/tmp/test-media")
    media_path = Path(os.environ["MEDIA_DIR"])
    if str(media_path).startswith("/tmp/"):
        media_path.mkdir(parents=True, exist_ok=True)
        # These modules captured MEDIA_DIR at import; repoint in case any were
        # imported before this session-autouse fixture ran.
        for _mod in (
            "reserve_automation.web.routes.management.labels",
            "reserve_automation.web.routes.bottles.save",
            "reserve_automation.web.routes.bottles.serving",
        ):
            try:
                import importlib
                importlib.import_module(_mod).MEDIA_DIR = media_path
            except Exception:
                pass

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
