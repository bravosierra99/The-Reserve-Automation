# Development Guide

## Testing Protocol

**CRITICAL: Always check for and run tests when modifying code.**

### Before Making Changes

1. **Identify the system you're working on** (events, extraction, vault, web UI, etc.)
2. **Check for existing tests** in `tests/[system]/`
3. **Read the test documentation** to understand what's covered

### After Making Changes

1. **Run the relevant test suite** for the system you modified
2. **Verify all tests pass** (or document new failures)
3. **Update tests** if you changed behavior or added features
4. **Document test results** in your response to the user

## Test Discovery Pattern

### File-Based Discovery

When modifying a file, check for tests:

```bash
# Modified: src/reserve_automation/web/routes/events.py
# Look for: tests/events/ or tests/web/
# Run: ./tests/events/run_all_tests.sh

# Modified: src/reserve_automation/extractors/bottle.py
# Look for: tests/extraction/ or tests/unit/test_*extraction*.py
# Run: uv run pytest tests/test_bottle_extraction_cli.py -v
```

### System-Based Test Suites

| System | Test Location | Run Command |
|--------|--------------|-------------|
| **Event System** | `tests/events/` | `./tests/events/run_all_tests.sh` |
| **Bottle Extraction (CLI)** | `tests/test_bottle_extraction_cli.py` | `uv run pytest tests/test_bottle_extraction_cli.py -v` |
| **Bottle Extraction (Web)** | `tests/test_bottle_extraction_web.py` | `uv run pytest tests/test_bottle_extraction_web.py -v` |
| **All Tests** | `tests/` | `uv run pytest tests/ -v` |

### Quick Test Check Commands

```bash
# List all test files
find tests/ -name "*.py" -o -name "*.sh" | grep -v __pycache__

# Search for tests related to a component
grep -r "class Test" tests/ | grep -i "events"
grep -r "def test_" tests/ | grep -i "extraction"
```

## When Tests Don't Exist

If you're modifying a system without tests:

1. **Alert the user** that no tests exist for this system
2. **Suggest creating tests** if the changes are significant
3. **Offer to create a test suite** similar to `tests/events/`

Example response:
> "I'm about to modify the vault management system, but I don't see any tests in `tests/vault/`. Would you like me to create a test suite for this system before making changes?"

## Test Creation Guidelines

### When to Create New Tests

- Adding new features
- Fixing bugs (regression tests)
- Refactoring complex logic
- Making changes that affect multiple files

### Test Structure Pattern

Follow the `tests/events/` pattern:

```
tests/[system]/
├── README.md                    # Full documentation
├── run_all_tests.sh            # Master test runner
├── cleanup_test_[system].py    # Cleanup utility
├── test_[feature_1].py         # Feature tests
├── test_[feature_2].py         # More feature tests
└── fixtures/                   # Test data
```

### Test Documentation

Every test directory must have:

1. **README.md** with:
   - What the tests cover
   - How to run them
   - When to run them (which files trigger the tests)
   - Expected output
   - Known issues

2. **Quick reference** in main `TESTING.md`

## Automated Test Running

### Pre-Commit Checklist

Before considering work "done":

- [ ] Identified relevant test suite
- [ ] Ran all tests for modified systems
- [ ] All tests pass (or failures documented)
- [ ] Updated test documentation if needed
- [ ] Reported test results to user

### Test Result Reporting

Always include in your final response:

```
## Tests Run

**System:** Event System
**Command:** `./tests/events/run_all_tests.sh`
**Result:** 3/4 passing ✅

- ✅ Blind Whiskey Event
- ✅ Blind Wine Event (skipped)
- ❌ Multi-Event Participation (known issue)
- ✅ Edit Existing Tasting
```

## Test Maintenance

### Keeping Tests Up-to-Date

When APIs or schemas change:

1. **Update test fixtures** to match new structure
2. **Update assertions** to match new behavior
3. **Document changes** in test README
4. **Re-run tests** to verify updates

### Marking Known Issues

If a test fails due to a known bug:

1. **Document in test README** under "Known Issues"
2. **Keep test in suite** (don't remove failing tests)
3. **Mark as expected failure** in test output
4. **Link to issue** or explanation

Example from `tests/events/README.md`:
```markdown
### Known Issues

#### Multi-Event Cookie Bug
**Location:** `src/reserve_automation/web/routes/events.py:216-240`
**Problem:** When user joins Event 2, Event 1 session disappears from cookie.
**Test:** `test_multi_event.py` (currently failing)
```

## Current Test Coverage

### ✅ Well-Tested Systems

- **Event System** - `tests/events/` (3/4 passing)
  - Blind whiskey events
  - Blind wine events
  - Edit tastings
  - Multi-event participation (failing - known bug)

- **Bottle Extraction** - `tests/test_bottle_extraction_*.py`
  - PDF parsing
  - CLI extraction workflow
  - Web upload workflow
  - Session management

### ⚠️ Systems Without Tests

- Vault management
- Obsidian file generation
- Image label extraction (single bottle photos)
- Web search enrichment
- User authentication

## Example Workflow

### Scenario: Fixing Event Results Bug

1. **User reports issue:** "Rankings aren't displaying correctly"

2. **Check for tests:**
   ```bash
   ls tests/events/
   cat tests/events/README.md
   ```

3. **Identify relevant test:** `test_edit_tasting.py` covers rankings

4. **Run test before changes:**
   ```bash
   ./tests/events/run_all_tests.sh
   ```

5. **Make code changes** to `src/reserve_automation/web/templates/event_results.html`

6. **Run test again:**
   ```bash
   ./tests/events/run_all_tests.sh
   ```

7. **Report results:**
   > "I've fixed the rankings display bug. Test results:
   > - ✅ All 4/4 event tests passing
   > - Verified rankings now sort correctly in `test_edit_tasting.py`"

## Integration with Git

### Recommended Git Hooks

Consider adding to `.git/hooks/pre-commit`:

```bash
#!/bin/bash
# Run relevant tests based on changed files

if git diff --cached --name-only | grep -q "routes/events.py\|routes/tastings.py\|templates/event"; then
    echo "Event files changed - running event tests..."
    ./tests/events/run_all_tests.sh || exit 1
fi

if git diff --cached --name-only | grep -q "extractors/\|parsers/"; then
    echo "Extraction files changed - running extraction tests..."
    uv run pytest tests/test_bottle_extraction_cli.py -v || exit 1
fi
```

## Quick Reference

**Most Important Rule:**
> When you modify code, ask yourself: "Are there tests for this system?"
> If yes: Run them.
> If no: Consider creating them.

**Test Commands Cheat Sheet:**
```bash
# Event system
./tests/events/run_all_tests.sh

# All Python tests
uv run pytest tests/ -v

# Specific test file
uv run pytest tests/test_bottle_extraction_cli.py -v

# Clean up test data
python3 tests/events/cleanup_test_events.py
```

**Files That Trigger Event Tests:**
- `src/reserve_automation/web/routes/events.py`
- `src/reserve_automation/web/routes/tastings.py`
- `src/reserve_automation/web/templates/event_*.html`
- `src/reserve_automation/web/templates/manual_tasting.html`
