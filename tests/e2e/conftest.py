"""Shared fixtures for E2E browser tests."""

import subprocess
import time
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


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
def test_vault(request):
    """Create a test vault with necessary structure and fixture bottles.

    Copies fixture bottles WITH LABELS from tests/fixtures/vault_bottles/
    to enable testing of label operations (crop, replace, etc.)

    Uses unique path per test to ensure complete isolation between tests.
    """
    import shutil
    import uuid

    # Use test name + uuid for unique path to ensure complete isolation
    test_name = request.node.name.replace("[", "_").replace("]", "_")
    unique_id = str(uuid.uuid4())[:8]
    test_vault_path = Path(f"/tmp/test-vault-{test_name}-{unique_id}")

    # Clean up any existing test vault
    if test_vault_path.exists():
        shutil.rmtree(test_vault_path)

    # Create vault directory structure
    test_vault_path.mkdir(parents=True)
    (test_vault_path / "1_Whiskeys").mkdir()
    (test_vault_path / "1_Wines").mkdir()
    (test_vault_path / "1_Spirits").mkdir()

    # Copy fixture bottles WITH LABELS from tests/fixtures/vault_bottles/
    fixtures_dir = Path(__file__).parent.parent / "fixtures" / "vault_bottles"
    if fixtures_dir.exists():
        for bottle_dir in fixtures_dir.iterdir():
            if bottle_dir.is_dir():
                # Determine destination based on bottle type
                bottle_md = list(bottle_dir.glob("*.md"))
                if bottle_md:
                    content = bottle_md[0].read_text()
                    if "fileClass: Whiskey" in content:
                        dest_dir = test_vault_path / "1_Whiskeys" / bottle_dir.name
                    elif "fileClass: Wine" in content:
                        dest_dir = test_vault_path / "1_Wines" / bottle_dir.name
                    else:
                        dest_dir = test_vault_path / "1_Spirits" / bottle_dir.name

                    # Copy entire bottle directory including labels/
                    shutil.copytree(bottle_dir, dest_dir)
                    print(f"  Copied fixture bottle: {bottle_dir.name}")

    # Also create a simple Weller bottle for duplicate detection testing
    # (in case fixture bottles aren't available)
    weller_bottle_dir = test_vault_path / "1_Whiskeys" / "Weller - THE ORIGINAL WHEATED BOURBON"
    if not weller_bottle_dir.exists():
        weller_bottle_dir.mkdir()

        weller_md = weller_bottle_dir / "Weller - THE ORIGINAL WHEATED BOURBON.md"
        weller_md.write_text("""---
fileClass: Whiskey
Name: Weller - THE ORIGINAL WHEATED BOURBON
Distiller: Weller
WhiskeyName: THE ORIGINAL WHEATED BOURBON
AgeStatement:
Year:
Type: Kentucky Straight Bourbon Whiskey
MashBill:
BarrelType:
Proof: 90.0
Region-State: Kentucky
BatchNumber:
BottleNumber:
Price:
PurchaseSource:
PurchaseLink:
Inventory: 1
Buy: 0
Stars: --
ValueForMoney:
BottleOpenedDate:
BottleImage:
---

## Bottle Information

### Product Details

This is a test fixture bottle for E2E duplicate detection tests.
""")

    yield test_vault_path

    # Cleanup after test
    if test_vault_path.exists():
        shutil.rmtree(test_vault_path)


@pytest.fixture(scope="function")
def web_server(test_vault):
    """Start the web server for browser testing."""
    import tempfile
    import os
    import signal

    # E2E tests use a temporary test vault, NOT the real vault
    os.environ["RESERVE_VAULT_PATH"] = str(test_vault)

    # Kill any existing test servers on port 9000
    subprocess.run(["pkill", "-9", "-f", "uvicorn.*reserve_automation"], stderr=subprocess.DEVNULL)
    time.sleep(1)

    # Write output to temp files instead of PIPE to avoid blocking
    stdout_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.log')
    stderr_file = tempfile.NamedTemporaryFile(mode='w+', delete=False, suffix='.log')

    # Get the automation directory
    automation_dir = Path(__file__).parent.parent.parent

    # Start server WITHOUT --reload to avoid subprocess complexity in tests
    # Use port 9000 to avoid conflicts with the main server on 8000
    server_process = subprocess.Popen(
        ["uv", "run", "--env-file", ".env", "uvicorn",
         "reserve_automation.web.app:app", "--host", "0.0.0.0", "--port", "9000"],
        cwd=str(automation_dir),
        stdout=stdout_file,
        stderr=stderr_file,
        env=os.environ.copy(),
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
        except Exception as e:
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
    return "/mnt/d/users/ben/Documents/spirits/automation/tests/fixtures/bottles/bourbon_001.jpg"
