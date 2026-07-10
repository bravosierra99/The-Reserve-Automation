# Testing Guide

## Quick Reference

| System Modified | Tests to Run | Location |
|----------------|--------------|----------|
| Management routes (update bottles) | `uv run pytest tests/integration/routes/test_management_routes.py -v` | `tests/integration/routes/` |
| Event system | `./tests/events/run_all_tests.sh` | `tests/events/` |
| Tasting upload/creation | `./tests/tastings/run_all_tests.sh` | `tests/tastings/` |
| Bottle extraction | `uv run pytest tests/test_bottle_extraction_*.py -v` | `tests/` |
| ObsidianGenerator | Management + Bottle extraction tests | Multiple |
| Frontend JS modules (`static/js/`) | `npm test` (vitest + jsdom) | `tests/js/` |
| API response shapes (frontend↔backend contract) | `uv run pytest tests/contract/` (regen: `UPDATE_CONTRACT_FIXTURES=1 …`, then re-run `npm test`) | `tests/contract/` + `tests/fixtures/contract/` |
| Browser flows (Alpine bindings + backend) | `uv run pytest -m e2e` (slow; also runs in CI) | `tests/e2e/` |

**Frontend note:** inline template JS is invisible to every pytest layer — API tests
never execute JS and `tests/ui` only greps rendered HTML. As of July 2026 ALL page
logic lives in `static/js/` modules (every template's inline script was extracted;
only one-line `window.PAGE_DATA` bootstraps remain inline) and every module has a
vitest suite in `tests/js/` — `npm test` runs them, `npm run test:coverage` gives
the per-module report (scoped to `static/js/`; HTML report in `coverage-js/`).
Keep it that way: new frontend logic goes in a `static/js/` module with a vitest
suite, never inline in a template. A 0% coverage row is a regression.
Page factories with `get foo()` getters must attach as WHOLE factories
(`window.fooApp = function() {...}`) — spreading one freezes its getters.

**Contract fixtures (July 2026):** the JSON files in `tests/fixtures/contract/`
are real API responses captured by `tests/contract/` and loaded verbatim by the
vitest suites (`tests/js/helpers/contract.js`). Never hand-write a "this is what
the API returns" fixture — see `tests/contract/README.md` for the protocol and
the postmortem that motivated it.

## Management Routes Tests ⭐ CRITICAL

**Location:** `tests/integration/routes/test_management_routes.py`

### Quick Commands

```bash
# Run management route tests
uv run pytest tests/integration/routes/test_management_routes.py -v
```

### When to Test

**⚠️ ALWAYS run management tests after modifying:**
- `src/reserve_automation/web/routes/management/*.py`
- `src/reserve_automation/generators/obsidian.py`
- Template directory paths or module import structures
- Any refactoring that changes file paths

### What It Tests

- ✅ Load bottles from vault
- ✅ **Update bottle fields (writes to vault!)**
- ✅ Verify/enrich bottle metadata
- ✅ Rename directories when producer/name/year changes
- ✅ Tasting summaries

**WHY:** These are the tests that would have caught the import/path errors. They actually write to the vault and verify side effects. See `tests/TESTING_GAP_ANALYSIS.md`.

## Event System Tests

**Location:** `tests/events/`

### Quick Commands

```bash
# Run all event tests (4/4 passing - ALL TESTS PASS!)
./tests/events/run_all_tests.sh

# Clean up test events
python3 tests/events/cleanup_test_events.py

# View test events in browser
http://localhost:8000/events
```

## Tasting Upload Tests ⭐ NEW

**Location:** `tests/tastings/`

### Quick Commands

```bash
# Run all tasting tests
./tests/tastings/run_all_tests.sh

# Run individual suites
python3 tests/tastings/test_event_tastings.py        # Suite 1: Event-based (safe)
python3 tests/tastings/test_cli_extraction.py         # Suite 2: CLI --dry-run (safe)
python3 tests/tastings/test_vault_integration.py      # Suite 3: Vault integration (temp vault)
```

### Three Test Suites

1. **Event-Based Tastings** (SAFE - no vault writes)
   - Manual tasting wizard in event mode
   - Edit existing event tastings
   - All data stored in-memory

2. **CLI Extraction** (SAFE - uses --dry-run)
   - AWS wine card extraction
   - Bourbon card extraction
   - Template auto-detection
   - LLM robustness testing

3. **Vault Integration** (writes to /tmp/test-vault)
   - Manual Obsidian mode tastings
   - CLI extraction to vault
   - Duplicate detection
   - **Requires:** `RESERVE_VAULT_PATH=/tmp/test-vault ./start-web.sh`

**⚠️ ALWAYS run tasting tests after modifying:**
- `src/reserve_automation/web/routes/tastings.py`
- `src/reserve_automation/web/routes/upload.py`
- `src/reserve_automation/web/services/tasting_service.py`
- `src/reserve_automation/generators/tasting_generator.py`
- `src/reserve_automation/cli.py` (extract-tasting command)
- `templates/tasting_*.md.jinja`

### When to Test

**⚠️ ALWAYS run event tests after modifying:**
- `src/reserve_automation/web/routes/events.py`
- `src/reserve_automation/web/routes/tastings.py`
- `src/reserve_automation/web/templates/event_*.html`
- `src/reserve_automation/web/templates/manual_tasting.html`
- Event schemas or cookie/session handling

### Event Test Coverage

The event suite lives in `tests/events/` and runs as part of the full
`uv run pytest` run (600+ tests overall). It exercises:

1. **Blind Whiskey Event** - Full 3-participant tasting with scores & notes
2. **Blind Wine Event** - Wine variant of the blind flow
3. **Multi-Event Participation** - Users can join multiple events simultaneously
4. **Edit Existing Tasting** - Verifies edits replace (don't duplicate)

> Note: a few `test_cocktail_event_api.py` tests pass standalone but can fail in
> a full-suite run due to a known cross-module SQLite test-isolation leak (not a
> product defect). Run `uv run pytest tests/events/` to check them in isolation.

## Other Tests

See `tests/README.md` for:
- Bottle extraction tests
- Manual testing scripts
- Unit tests
- Integration tests

## Full Documentation

- **Event tests:** `tests/events/README.md`
- **All tests:** `tests/README.md`
