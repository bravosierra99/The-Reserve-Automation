# Tasting Upload Test Suite

Comprehensive test coverage for all tasting upload workflows: event-based, image extraction, manual entry, and vault integration.

## Quick Start

```bash
# Run all tasting tests
./tests/tastings/run_all_tests.sh

# Run individual suites
python3 tests/tastings/test_event_tastings.py      # Suite 1: Event-based (safe)
python3 tests/tastings/test_cli_extraction.py       # Suite 2: CLI extraction (safe)
python3 tests/tastings/test_vault_integration.py    # Suite 3: Vault integration (temp vault)
```

## Test Suites Overview

### Suite 1: Event-Based Tastings ✅ (SAFE - No Vault Writes)
**File:** `test_event_tastings.py`

Tests manual tasting wizard in event mode, which stores tastings in in-memory event store without writing to vault.

**Tests:**
- `test_manual_event_tasting()` - Complete manual tasting workflow
  - Search for bottles
  - Create event
  - Join as participant
  - Start wizard in event mode
  - Select bottle
  - Submit tasting scores
  - Verify saved to event store (not vault)

- `test_edit_event_tasting()` - Edit existing event tasting
  - Create initial tasting
  - Edit same bottle with new scores
  - Verify only 1 tasting exists (edit replaces original)
  - Verify scores/notes updated correctly

**Why This is Safe:**
- Event mode saves to `event_store[event_id]` in memory
- No files written to disk
- No vault pollution
- Perfect for testing tasting form validation and workflow

**Run:**
```bash
python3 tests/tastings/test_event_tastings.py
```

---

### Suite 1b: Manual Tasting UI Tests ✅ (SAFE - No Writes)
**File:** `test_manual_tasting_ui.py`

Tests the manual tasting wizard form fields to ensure they behave correctly in both Obsidian and Event modes.

**Tests:**
- `test_obsidian_mode_fields_editable()` - Verify form fields editable in Obsidian mode
  - Checks taster name field has correct Alpine.js bindings
  - Checks beverage type radios have correct bindings
  - Verifies fields use `:readonly="isEventMode"` and `:disabled="isEventMode"`
  - Confirms date field is always editable

- `test_event_mode_fields_readonly()` - Verify form fields readonly in Event mode
  - Creates test event and joins as participant
  - Loads manual tasting page with event parameters
  - Verifies readonly/disabled bindings present
  - Confirms fields locked when in event mode

- `test_isEventMode_computed_property()` - Verify isEventMode property exists
  - Checks computed property exists in template
  - Verifies it's used in field bindings

- `test_wine_whiskey_tasting_notes_fields()` - Verify wine and whiskey have correct note fields
  - Wine section shows: Appearance Notes, Aroma Notes, Taste Notes, Aftertaste Notes
  - Whiskey section shows: Nose Notes, Palate Notes, Finish Notes
  - Verifies conditional rendering based on `beverageType`
  - Confirms JavaScript note management functions exist for both types

**Bugs Fixed:**
1. **Taster name/beverage type fields readonly** - Fields were incorrectly readonly even in Obsidian mode (non-event). The issue was that `participantSession?.event_id` wasn't being properly cleared when entering Obsidian mode.
   - **Fix:** Added `isEventMode` computed property that explicitly checks mode
   - Updated field bindings to use `isEventMode` instead of `participantSession?.event_id`
   - Made `init()` function more defensive about clearing `participantSession` in Obsidian mode

2. **Wine showing whiskey tasting note fields** - Wine tastings were incorrectly showing whiskey note fields (Nose, Palate, Finish) instead of wine fields (Appearance, Aroma, Taste, Aftertaste).
   - **Fix:** Created separate conditional sections for wine and whiskey tasting notes
   - Added `appearance_notes` field to TastingData and TastingNote models
   - Wine notes now correctly map: Appearance → `appearance_notes`, Aroma → `nose_notes`, Taste → `palate_notes`, Aftertaste → `finish_notes`

**Why This is Safe:**
- Only tests HTML rendering and Alpine.js bindings
- No data writes
- No vault pollution
- Uses BeautifulSoup to parse server-rendered HTML

**Run:**
```bash
python3 tests/tastings/test_manual_tasting_ui.py
```

---

### Suite 2: CLI Extraction Tests ✅ (SAFE - Uses --dry-run)
**File:** `test_cli_extraction.py`

Tests CLI `extract-tasting` command with `--dry-run` flag to verify extraction works without writing files.

**Tests:**
- `test_aws_wine_extraction()` - Extract from AWS wine tasting card
  - Uses `tests/fixtures/extraction/aws_wine_test_001.jpg`
  - Verifies extraction completes without errors
  - Confirms dry-run mode (no files written)
  - Compares to ground truth if available

- `test_bourbon_extraction()` - Extract from bourbon tasting card
  - Looks for `bourbon_*.jpg` in fixtures
  - Skips gracefully if no bourbon images found
  - Verifies whiskey scoring fields present
  - Confirms dry-run mode

- `test_auto_detect_template()` - Template auto-detection
  - Runs extraction without specifying template type
  - Verifies system auto-detects AWS wine template

- `test_extraction_no_llm_errors()` - Robustness testing
  - Verifies extraction doesn't crash even if LLM returns unexpected data
  - Main goal: No exceptions, process completes

**LLM Reliability:**
- Tests check extraction completes without errors (most important)
- Verifies extracted fields are non-empty
- Compares against ground truth with threshold tolerance
- Doesn't require perfect extraction (LLM can vary)

**Why This is Safe:**
- All tests use `--dry-run` flag
- Preview mode only - no files written
- No vault pollution

**Run:**
```bash
python3 tests/tastings/test_cli_extraction.py
```

**Adding Bourbon Test Images:**
Place bourbon tasting card images in `tests/fixtures/extraction/`:
```
tests/fixtures/extraction/bourbon_test_001.jpg
tests/fixtures/extraction/bourbon_test_002.jpg
```

Tests will automatically detect and use them.

---

### Suite 3: Vault Integration Tests ⚠️ (Writes to /tmp/test-vault)
**File:** `test_vault_integration.py`

Tests actual file creation in a temporary test vault at `/tmp/test-vault`. These tests write real Obsidian markdown files to disk.

**Prerequisites:**
```bash
# 1. Create/setup test vault
mkdir -p /tmp/test-vault/1_Whiskeys /tmp/test-vault/1_Wines

# 2. Restart web server with test vault
pkill -f uvicorn
RESERVE_VAULT_PATH=/tmp/test-vault ./start-web.sh
```

**Tests:**
- `test_manual_obsidian_tasting()` - Manual Obsidian mode tasting
  - Start wizard in Obsidian mode (not event mode)
  - Select test bottle from temp vault
  - Submit tasting data
  - Verify file created: `Tasting-YYYY-MM-DD-TasterName.md`
  - Validate file structure (frontmatter, scores, notes)
  - Verify correct fileClass: "Whiskey Tasting" or "Wine Tasting"

- `test_cli_extraction_to_vault()` - CLI extraction without --dry-run
  - Run `extract-tasting` WITHOUT `--dry-run` flag
  - Verify files written to temp vault
  - Graceful handling if LLM fails to match bottles
  - Validates created file structure

- `test_duplicate_detection()` - Duplicate tasting handling
  - Create first tasting for bottle
  - Attempt to create duplicate (same bottle, taster, date)
  - Verify only 1 file exists
  - System either prevents duplicate or updates existing

**Why This Needs Careful Setup:**
- Writes real files to `/tmp/test-vault`
- Requires server restart with `RESERVE_VAULT_PATH` env var
- Tests actual vault integration end-to-end

**Run:**
```bash
# After setting RESERVE_VAULT_PATH=/tmp/test-vault
python3 tests/tastings/test_vault_integration.py
```

**Cleanup:**
```bash
# Remove test vault entirely
rm -rf /tmp/test-vault

# Or just remove tasting files
find /tmp/test-vault -name "Tasting-*.md" -delete
```

---

## Test Vault Structure

The temp vault at `/tmp/test-vault` contains test bottles:

```
/tmp/test-vault/
├── 1_Whiskeys/
│   ├── Test Distillery - Test Bourbon - 2020/
│   │   └── Test Distillery - Test Bourbon - 2020.md
│   └── Buffalo Trace - Test Stagg - 2024/
│       └── Buffalo Trace - Test Stagg - 2024.md
└── 1_Wines/
    └── Château Test - Bordeaux - 2015/
        └── Château Test - Bordeaux - 2015.md
```

Tasting files are created as:
```
{bottle_dir}/Tasting-2025-12-27-TasterName.md
```

---

## Running All Tests

### Master Test Runner
```bash
./tests/tastings/run_all_tests.sh
```

**What It Does:**
1. Checks if web server is running
2. Sets up test vault at `/tmp/test-vault`
3. Runs Suite 1 (event-based) ✅
4. Runs Suite 2 (CLI dry-run) ✅
5. Prompts to restart server for Suite 3
6. Runs Suite 3 (vault integration) if confirmed
7. Shows summary with pass/fail counts

**Interactive Prompt for Suite 3:**
```
⚠️  Suite 3 requires server restart with test vault
Restart server with RESERVE_VAULT_PATH=/tmp/test-vault? (y/n)
```

If you answer yes, manually restart the server, then press Enter to continue.

---

## Test Fixtures

### Existing Test Images

**AWS Wine Card:**
```
tests/fixtures/extraction/aws_wine_test_001.jpg
tests/fixtures/extraction/aws_wine_test_001.json  # Ground truth
```

### Adding More Test Fixtures

**Bourbon Cards:**
Place bourbon tasting card images here:
```
tests/fixtures/extraction/bourbon_test_001.jpg
tests/fixtures/extraction/bourbon_test_002.jpg
```

**Ground Truth Files (Optional):**
Create corresponding JSON files with expected extraction:
```json
{
  "test_name": "Bourbon tasting card test 1",
  "image_file": "bourbon_test_001.jpg",
  "template_type": "bourbon",
  "expected_output": {
    "taster_name": "Expected Name",
    "tasting_date": "YYYY-MM-DD",
    "tastings": [{
      "bottle_name": "Expected Bottle Name",
      "whiskey_nose": 2.5,
      "whiskey_palate": 2.8,
      "whiskey_finish": 2.3,
      "whiskey_overall": 0.9,
      "nose_notes": ["expected", "notes"],
      "overall_notes": "Expected overall notes"
    }]
  }
}
```

---

## When to Run Tests

### Always Run After Modifying:
- `src/reserve_automation/web/routes/tastings.py` - Manual wizard routes
- `src/reserve_automation/web/routes/upload.py` - Image upload routes
- `src/reserve_automation/web/services/tasting_service.py` - Tasting save logic
- `src/reserve_automation/generators/tasting_generator.py` - Obsidian file generation
- `src/reserve_automation/cli.py` - CLI `extract-tasting` command
- `templates/tasting_*.md.jinja` - Tasting file templates

### Run Suite 1 When Modifying:
- Manual tasting wizard UI
- Event-based tasting logic
- Manual tasting form validation

### Run Suite 2 When Modifying:
- CLI extraction command
- LLM extraction prompts
- Tasting card parsing logic
- Template detection

### Run Suite 3 When Modifying:
- Tasting file generation
- Vault integration
- Obsidian markdown templates
- Duplicate detection logic

---

## Test Philosophy

### Safe by Default
- Suites 1 & 2 never write to vault
- Suite 3 writes only to isolated temp vault
- No risk of polluting real Obsidian vault

### LLM Tolerance
- Tests verify extraction completes (no crashes)
- Extraction accuracy can vary - that's acceptable
- Ground truth comparisons use thresholds, not exact matches
- Main goal: System is robust, not perfect

### Comprehensive Coverage
All tasting upload paths covered:
1. ✅ Manual event mode (in-memory)
2. ✅ Manual Obsidian mode (vault write)
3. ✅ Image extraction - dry-run (preview)
4. ✅ Image extraction - actual save (vault write)
5. ✅ CLI extraction - dry-run
6. ✅ CLI extraction - actual save
7. ✅ Duplicate detection
8. ✅ Edit existing tastings

---

## Troubleshooting

### Web Server Not Running
```
❌ Web server is not running
```

**Solution:**
```bash
./start-web.sh
```

### Suite 3 Fails - Wrong Vault
```
AssertionError: Test bottle not found in test vault
```

**Solution:** Server is still pointing to real vault
```bash
pkill -f uvicorn
RESERVE_VAULT_PATH=/tmp/test-vault ./start-web.sh
```

### Bourbon Tests Skipped
```
⚠️  No bourbon test images found in fixtures
```

**Solution:** Add bourbon tasting card images to fixtures:
```bash
cp ~/path/to/bourbon_card.jpg tests/fixtures/extraction/bourbon_test_001.jpg
```

### LLM Extraction Unreliable
```
⚠️  Extraction exited with code 1
This is okay - LLM extraction can be unreliable
```

**This is Expected:** Tests verify the system doesn't crash, not that extraction is perfect. If you see "No exceptions thrown", the test passed.

---

## Test Status

**Current Status:** All 3 suites implemented and ready

### Suite 1: Event-Based Tastings
- ✅ Manual event tasting workflow
- ✅ Edit event tasting
- ✅ Ready to run

### Suite 2: CLI Extraction
- ✅ AWS wine extraction
- ⏳ Bourbon extraction (needs images)
- ✅ Auto-detect template
- ✅ Robustness testing
- ✅ Ready to run

### Suite 3: Vault Integration
- ✅ Manual Obsidian mode
- ✅ CLI to vault
- ✅ Duplicate detection
- ✅ Ready to run (needs server restart)

---

## Future Test Ideas

- **Large batch extraction** - Multiple tastings from single image
- **Partial extraction** - Some fields missing
- **Incorrect template** - AWS wine template on bourbon card
- **Event + extraction** - Upload image in event mode
- **Web UI image upload** - Test full web upload workflow
- **Multi-page tasting cards** - PDF with multiple cards
- **Edge cases** - Empty fields, malformed data, special characters

---

## Contributing New Tests

1. **Add test function** to appropriate suite file
2. **Update master runner** if new suite created
3. **Document** in this README
4. **Add fixtures** if needed (images, JSON)
5. **Verify safe** - no vault pollution unless Suite 3

---

Built with love for testing all the tasting upload paths! 🥃🍷
