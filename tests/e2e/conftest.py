"""Shared fixtures for E2E browser tests."""

import os
import subprocess
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

# Playwright's bundled Firefox build ships a host-validation manifest that
# stats a phantom `firefox/lock` file which does not exist in this build, so
# `validateDependenciesLinux` throws ENOENT before the browser ever launches
# (upstream packaging bug). The engine itself (libxul.so etc.) is present and
# works fine, so we skip the broken pre-launch validation. setdefault leaves an
# explicit override in place. Without this, every E2E browser test errors.
os.environ.setdefault("PLAYWRIGHT_SKIP_VALIDATE_HOST_REQUIREMENTS", "1")

# ============================================================================
# PYTEST HOOKS FOR PROGRESS VISIBILITY
# ============================================================================

def pytest_configure(config):
    """Configure pytest with E2E-specific settings."""
    # Register markers
    config.addinivalue_line("markers", "e2e: mark test as end-to-end browser test")
    config.addinivalue_line("markers", "slow: mark test as slow (uses LLM calls)")


def pytest_collection_modifyitems(config, items):
    """Auto-mark all tests in e2e/ directory and set appropriate timeouts."""
    for item in items:
        # Auto-mark all tests in e2e/ as e2e tests with 5-minute timeout
        if "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
            # Set 5 minute timeout for E2E tests (they involve browser + LLM)
            item.add_marker(pytest.mark.timeout(300))

        # Mark tests that involve LLM extraction as slow
        if any(kw in item.name for kw in ["upload", "extract", "metadata", "verify"]):
            item.add_marker(pytest.mark.slow)


def pytest_runtest_setup(item):
    """Log when each test starts."""
    print(f"\n{'='*60}")
    print(f"🧪 STARTING: {item.name}")
    print(f"{'='*60}")


def pytest_runtest_teardown(item, nextitem):
    """Log when each test ends."""
    print(f"\n{'='*60}")
    print(f"✅ FINISHED: {item.name}")
    print(f"{'='*60}")


@pytest.fixture(scope="function")
def test_db(tmp_path):
    """Create a seeded SQLite file DB for an e2e test server subprocess.

    The app uses DATABASE_URL from the environment. In-memory SQLite cannot be
    shared across processes, so e2e tests use a temp file DB pre-seeded with
    representative bottles.

    Yields the file path string (pass as DATABASE_URL=sqlite:///path to the
    subprocess env).
    """

    db_path = tmp_path / "e2e_test.db"
    db_url = f"sqlite:///{db_path}"

    # Initialise schema using the app's own init_db
    from reserve_automation.core.models import BeverageType, BottleMetadata
    from reserve_automation.db.engine import init_db as app_init_db
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository

    engine = app_init_db(db_url)
    from reserve_automation.db.engine import _SessionLocal
    session = _SessionLocal()

    repo = SQLiteBottleRepository(session)
    created = [
        repo.create(BottleMetadata(
            producer="Weller",
            name="Original Wheated Bourbon",
            type=BeverageType.WHISKEY,
            inventory=2,
            source="test",
        )),
        repo.create(BottleMetadata(
            producer="Buffalo Trace",
            name="Kentucky Straight Bourbon",
            type=BeverageType.WHISKEY,
            inventory=1,
            source="test",
        )),
        repo.create(BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon 2021",
            type=BeverageType.WINE,
            inventory=3,
            source="test",
        )),
    ]
    session.close()
    engine.dispose()

    # Seed a real label image for each bottle under the (isolated) MEDIA_DIR so
    # browser tests that open a bottle's label (e.g. the management manual-crop
    # / Cropper.js flow) have an image to initialize on. The vault-era test
    # fixtures copied labeled bottles; the SQLite test_db otherwise has none.
    import os
    import shutil
    media_dir = Path(os.environ.get("MEDIA_DIR", "data/media"))
    fixture_label = Path(__file__).parent.parent / "fixtures" / "bottles" / "bourbon_001.jpg"
    if str(media_dir).startswith("/tmp/") and fixture_label.exists():
        for bottle in created:
            label_dir = media_dir / "bottles" / str(bottle.id)
            label_dir.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fixture_label, label_dir / "label.jpg")

    yield str(db_path)


# Keep test_vault for any test that still needs the old vault-based fixture
# (deprecated — remove once all e2e tests are migrated to test_db)
@pytest.fixture(scope="function")
def test_vault(tmp_path):
    """Deprecated vault fixture kept for backward compat. Prefer test_db."""
    vault_path = tmp_path / "vault"
    vault_path.mkdir()
    (vault_path / "1_Whiskeys").mkdir()
    (vault_path / "1_Wines").mkdir()
    yield vault_path


@pytest.fixture(scope="function")
def web_server(test_db):
    """Start an isolated web server for browser testing.

    Uses a seeded temp SQLite file so the server has realistic data without
    touching the production database. Prior fixture used RESERVE_VAULT_PATH
    which the app no longer reads for data — that caused tests to silently run
    against prod data or an empty DB.
    """
    import os
    import signal
    import tempfile

    # Kill any existing test servers on port 9000
    subprocess.run(["pkill", "-9", "-f", "uvicorn.*reserve_automation"], stderr=subprocess.DEVNULL)
    time.sleep(1)

    # Write output to temp files instead of PIPE to avoid blocking
    stdout_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.log')
    stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.log')

    # Get the automation directory
    automation_dir = Path(__file__).parent.parent.parent

    # Build subprocess env: inherit parent + override DATABASE_URL and dev auth
    server_env = os.environ.copy()
    server_env["DATABASE_URL"] = f"sqlite:///{test_db}"
    server_env.setdefault("WEB_SECRET_KEY", "e2e-test-secret-key-not-secure-32chars")
    # Enable dev-mode auth in the SUBPROCESS server. The root conftest patches
    # app.state.auth_config in-process, but this fixture launches a separate
    # uvicorn that never sees that patch — it loads config/auth.yaml, where
    # dev.enabled is false (prod default), so every guarded route 401s and the
    # browser sees an empty error page. AUTH_DEV_ENABLED is the documented
    # override (web/auth/config.py); without it all browser-driven e2e fails.
    server_env["AUTH_DEV_ENABLED"] = "1"

    # Start server WITHOUT --reload to avoid subprocess complexity in tests
    # Use port 9000 to avoid conflicts with the main server on 8000.
    #
    # When E2E_COVERAGE=1, run uvicorn under `coverage run --parallel-mode` so
    # the server process's route/template coverage is captured (it's a separate
    # process, so plain pytest-cov in the test process never sees it). The
    # fixture SIGTERM-kills the server; .coveragerc has `sigterm = true` so the
    # data flushes. Combine afterwards with `coverage combine && coverage report`.
    # `--env-file .env` only if it exists: uv HARD-ERRORS on a missing env file
    # ("No environment file found at: `.env`"), which killed every browser test
    # on CI where .env is gitignored/absent. The server's required vars
    # (DATABASE_URL, WEB_SECRET_KEY, AUTH_DEV_ENABLED) are already injected via
    # server_env above; .env only adds local extras (e.g. LLM keys), and the
    # LLM-dependent e2e tests are gated to skip without LM Studio anyway.
    launcher = ["uv", "run"]
    if (automation_dir / ".env").exists():
        launcher += ["--env-file", ".env"]
    if os.environ.get("E2E_COVERAGE"):
        launcher += ["coverage", "run", "--parallel-mode", "--rcfile=.coveragerc", "-m"]
    server_process = subprocess.Popen(
        [*launcher, "uvicorn",
         "reserve_automation.web.app:app", "--host", "0.0.0.0", "--port", "9000"],
        cwd=str(automation_dir),
        stdout=stdout_file,
        stderr=stderr_file,
        env=server_env,
        preexec_fn=os.setsid  # Create new process group for easier cleanup
    )

    # Wait for server to start (up to 45 seconds for slow LLM initialization)
    server_ready = False
    for i in range(45):
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            result = sock.connect_ex(('localhost', 9000))
            sock.close()
            if result == 0:
                print(f"\n✓ Test server started on port 9000 after {i+1} seconds")
                server_ready = True
                break
        except Exception:
            if i == 0:
                print("Waiting for test server to start on port 9000...")
        time.sleep(1)

    if not server_ready:
        # Server failed to start - read the log files
        os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        time.sleep(0.5)
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout_content = stdout_file.read()
        stderr_content = stderr_file.read()
        stdout_file.close()
        stderr_file.close()
        print(f"\n❌ Server stdout:\n{stdout_content[:1000]}")
        print(f"\n❌ Server stderr:\n{stderr_content[:1000]}")
        pytest.fail("Test server failed to start on port 9000 after 45 seconds")

    yield "http://localhost:9000"

    # Cleanup - kill entire process group
    try:
        os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
        server_process.wait(timeout=5)
    except:
        try:
            os.killpg(os.getpgid(server_process.pid), signal.SIGKILL)
        except:
            pass

    # Wait for port to be released before next test
    time.sleep(1)

    # Clean up temp files
    try:
        stdout_file.close()
        stderr_file.close()
        Path(stdout_file.name).unlink(missing_ok=True)
        Path(stderr_file.name).unlink(missing_ok=True)
    except:
        pass


@pytest.fixture
def browser_no_cache():
    """Create a Playwright browser with caching disabled."""
    with sync_playwright() as p:
        # Launch Firefox with cache disabled
        browser = p.firefox.launch(
            headless=True,
            firefox_user_prefs={
                "browser.cache.disk.enable": False,
                "browser.cache.memory.enable": False,
                "browser.cache.offline.enable": False,
                "network.http.use-cache": False,
            }
        )
        yield browser
        browser.close()


@pytest.fixture
def sample_image():
    """Sample bottle image for testing."""
    # Resolve relative to this file, NOT a hardcoded local path — the old
    # absolute /mnt/d/... path only existed on the author's machine and made
    # every upload e2e test FileNotFoundError on CI.
    return str(Path(__file__).parent.parent / "fixtures" / "bottles" / "bourbon_001.jpg")
