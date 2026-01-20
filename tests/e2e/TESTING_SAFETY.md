# E2E Testing Safety & Configuration

## ✅ Vault Safety Guarantee

**ALL E2E tests use an isolated test vault. Your real vault is NEVER modified.**

### How It Works

1. **Test Vault Location**: `/tmp/test-vault-e2e`
   - Created fresh for each test
   - Automatically deleted after each test
   - Completely isolated from your real vault

2. **Real Vault Location**: `/mnt/d/Users/ben/Documents/spirits/the-reserve/Cellar`
   - **Read-only access**: Only used to COPY fixture bottles TO the test vault
   - **Never written to**: No test ever modifies your real vault
   - **Only reference**: Line 32 in `conftest.py` copies ORIGINAL_PRODUCER bottle to test vault

3. **Environment Variable Override**:
   ```python
   # In conftest.py web_server fixture:
   os.environ["RESERVE_VAULT_PATH"] = str(test_vault)
   ```
   This ensures the web server ONLY sees the test vault during tests.

### Verification

Run this to verify no tests reference the real vault (except the read-only copy):
```bash
grep -r "/mnt/d/Users/ben/Documents/spirits/the-reserve/Cellar" tests/e2e/*.py | grep -v "# Use test vault"
```

Should only show the conftest.py copy operation (line 32).

---

## 🔌 Test Server Port

**Test server runs on port 9000 to avoid conflicts with your main server on port 8000.**

### Configuration

- **Main server**: http://localhost:8000 (your regular instance)
- **Test server**: http://localhost:9000 (tests only, isolated vault)

This allows you to:
- Run your main server for manual testing
- Run E2E tests simultaneously
- Both can use the same LLM server (no conflict)

### Changing the Port

To change the test port, edit `tests/e2e/conftest.py`:

```python
# Line 71: Server startup
"--port", "9000"  # Change this number

# Line 85: Port check
result = sock.connect_ex(('localhost', 9000))  # Change this number

# Line 110: URL returned
yield "http://localhost:9000"  # Change this number
```

---

## 🧪 Test Fixtures

### `test_vault` Fixture
- **Scope**: Function (fresh vault for each test)
- **Setup**:
  - Creates `/tmp/test-vault-e2e`
  - Creates directory structure (1_Whiskeys, 1_Wines, 1_Spirits)
  - Copies ORIGINAL_PRODUCER bottle from real vault (read-only)
- **Teardown**: Deletes entire test vault
- **Usage**: Add `test_vault` parameter to any test that needs a vault

### `web_server` Fixture
- **Scope**: Function (fresh server for each test)
- **Setup**:
  - Kills any existing test servers on port 9000
  - Sets RESERVE_VAULT_PATH to test vault
  - Starts uvicorn on port 9000 (without --reload)
  - Waits up to 45 seconds for server to be ready
- **Teardown**: Kills server process group
- **Usage**: Add `web_server` parameter to any E2E test

### `browser_no_cache` Fixture
- **Scope**: Function (fresh browser for each test)
- **Setup**: Launches Firefox with cache disabled
- **Teardown**: Closes browser
- **Usage**: Add `browser_no_cache` parameter to browser tests

---

## 🚨 Safety Checklist

Before running tests, verify:

- [x] Tests use `test_vault` fixture, NOT hardcoded paths
- [x] `conftest.py` overrides RESERVE_VAULT_PATH to test vault
- [x] Test server runs on port 9000 (not 8000)
- [x] Test vault is in /tmp (gets cleaned up)
- [x] No test references `/mnt/d/Users/ben/Documents/spirits/the-reserve/Cellar` except conftest.py line 32

To verify: `uv run pytest tests/e2e/ -v --collect-only` should show all tests using test fixtures.

---

## 📝 Adding New Tests

**Template for E2E tests:**

```python
def test_my_feature(self, web_server, sample_image, browser_no_cache, test_vault):
    """Test description."""
    page = browser_no_cache.new_page()

    # Use test_vault, NEVER hardcode vault path
    vault_path = test_vault  # ✅ Correct
    # vault_path = Path("/mnt/d/...") # ❌ NEVER do this

    # Navigate to test server
    page.goto(f"{web_server}/upload")  # Uses port 9000

    # ... test code ...
```

**Key Rules:**
1. Always use `test_vault` fixture parameter
2. Never hardcode vault paths
3. Use `web_server` parameter for URL (automatically port 9000)
4. Tests automatically clean up - no manual cleanup needed

---

## 🐛 Debugging

**Test server logs:**
- Tests create temp log files during execution
- On failure, logs are printed to console
- Check `stdout_content` and `stderr_content` in error output

**Verify test vault isolation:**
```bash
# Before test
ls /tmp/test-vault-e2e  # Should not exist

# During test (in another terminal)
ls /tmp/test-vault-e2e  # Should exist with test data

# After test
ls /tmp/test-vault-e2e  # Should not exist (cleaned up)
```

**Verify port isolation:**
```bash
# Check which ports are in use
lsof -i :8000  # Your main server
lsof -i :9000  # Test server (only during tests)
```
