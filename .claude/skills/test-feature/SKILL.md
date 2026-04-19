---
name: test-feature
description: After adding or modifying a feature, audit test coverage and close gaps. Use this after implementing any change — it maps the changed code to test files, runs coverage, identifies untested paths, writes missing tests, and verifies coverage is solid before shipping.
argument-hint: "[file or feature description, e.g. 'routes/bottles/save.py' or 'force_save upsert']"
allowed-tools: Bash(uv run pytest*) Bash(uv run coverage*) Bash(git diff*) Bash(git status*) Read Grep Glob
---

# Test Feature Coverage

You have been asked to audit and improve test coverage for: **$ARGUMENTS**

## Step 0 — Get context

What changed? Run:

```!
cd /mnt/d/Users/ben/Documents/spirits/automation && git diff HEAD~1 --stat 2>/dev/null || git status --short
```

If `$ARGUMENTS` names specific files, focus on those. Otherwise work from the diff above.

---

## Step 1 — Map changed code to tests

For every changed source file, identify:
- The **module path** (e.g. `web/routes/bottles/save.py`)
- The **expected test location** (e.g. `tests/integration/routes/test_bottle_save_route.py`)
- Whether a test file **exists** for it yet

Use this mapping:

| Source location | Test location |
|---|---|
| `web/routes/<system>/` | `tests/integration/routes/test_<system>_routes.py` |
| `db/repositories/` | `tests/` (whichever test exercises the repo) |
| `core/` models | unit tests in `tests/unit/` |
| `extractors/`, `parsers/` | `tests/test_<extractor>*.py` |
| `web/services/` | `tests/` covering the route that uses the service |

If no test file exists for a changed module, **that is the first gap to fill**.

---

## Step 2 — Run coverage against changed modules

Run pytest with coverage scoped to the changed modules only (fast feedback):

```bash
uv run pytest tests/ --ignore=tests/e2e --ignore=tests/manual \
  --cov=reserve_automation \
  --cov-report=term-missing \
  -q 2>&1 | head -80
```

Read the `MISS` column for the changed files. Every missed line is a gap.

---

## Step 3 — Classify the gaps

For each uncovered line/branch, classify it as one of:

| Type | Example | Priority |
|------|---------|----------|
| **Happy path** | Normal save succeeds | Must have |
| **Error path** | 500 on DB failure, 422 on bad input | Must have |
| **Branch variant** | `force_save=True` vs `False` | Must have |
| **Edge case** | `replace_bottle_id` for non-existent ID | Should have |
| **UI / route contract** | HTTP status codes, response shape | Must have for routes |

**Mandatory checks for route changes:**
- Does a test POST/GET the endpoint with valid data and assert `200`?
- Does a test verify the response JSON shape (required keys present)?
- Does a test cover every `if`/`elif` branch in the route handler?
- Does a test send bad input and assert `422`?
- Does a test trigger the error handler and assert `500` or appropriate error?

---

## Step 4 — Write missing tests

Follow the project test patterns:

**Integration route test (most common):**
```python
# tests/integration/routes/test_<system>_route.py
import pytest
from unittest.mock import Mock
from fastapi.testclient import TestClient
from reserve_automation.core.config import Config

@pytest.fixture
def client(tmp_path):
    from reserve_automation.web import app as app_module
    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)
    app_module.core_config = Config(
        paths={"vault": str(vault_path), "templates_dir": "templates"}
    )
    web_config = Mock()
    web_config.sessions.secret_key = "test-secret"
    app_module.web_config = web_config
    return TestClient(app_module.app)   # No `with` — bypasses lifespan

@pytest.fixture
def repo(db_session):          # db_session from conftest (in-memory SQLite)
    from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository
    return SQLiteBottleRepository(db_session)
```

**Key rules:**
- Never use `with TestClient(app) as c:` — that triggers the lifespan and fails on vault path
- Use `return TestClient(app_module.app)` instead
- Seed data via repositories (they commit), not raw SQL
- In-memory SQLite uses StaticPool — all sessions share the same DB, so seeded data IS visible to route handlers
- Do NOT skip tests on 500 — a 500 is a bug, assert the expected status explicitly

**Anti-pattern that hid the `find_duplicates` bug:**
```python
# BAD — treats 500 as acceptable
if response.status_code == 200:
    assert "status" in response.json()
else:
    assert response.status_code in [400, 500]  # ← this masks crashes

# GOOD — be explicit
assert response.status_code == 200, response.text
assert response.json()["status"] == "success"
```

---

## Step 5 — Verify coverage closed

Re-run the same coverage command from Step 2. Confirm:
- The `MISS` lines for changed modules are gone (or justified)
- All new tests pass
- No previously-passing tests are broken

---

## Step 6 — Report

Summarise:

```
## Test Coverage Report

**Feature:** <what was changed>

**Gaps found:**
- [ ] <gap 1>
- [ ] <gap 2>

**Tests written:**
- `tests/integration/routes/test_foo.py::TestBar::test_happy_path`
- `tests/integration/routes/test_foo.py::TestBar::test_422_on_bad_input`

**Coverage before:** XX% (N lines missing)
**Coverage after:**  XX% (N lines missing)

**Remaining uncovered (justified):**
- `line 42` — LLM-dependent path, skipped in CI
```

---

## What NOT to do

- Do not skip a test because "it's hard to trigger" — if there's a branch, test it
- Do not assert `status_code in [200, 500]` — pick one
- Do not create tests that only test the happy path and call it done
- Do not use `pytest.skip()` as a first resort — only for genuinely LLM-dependent paths
- Do not write tests that mock the database (use in-memory SQLite instead)
