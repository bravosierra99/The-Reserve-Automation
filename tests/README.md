# Reserve Automation Tests

This directory contains tests for The Reserve Automation project, covering both CLI and web server components.

## Test Structure

```
tests/
├── unit/                                      # ⭐ UNIT TESTS (fast, isolated)
│   ├── models/                                # Pydantic model validation tests
│   ├── services/                              # Service layer tests
│   ├── utils/                                 # Utility function tests
│   └── test_extractors.py                     # Extractor logic tests
│
├── integration/                               # ⭐ INTEGRATION TESTS
│   └── routes/
│       ├── test_management_routes.py          # ⭐ CRITICAL - Management workflow
│       └── README.md                          # Integration testing guide
│
├── e2e/                                       # ⭐ END-TO-END TESTS (complete workflows)
│   ├── test_bottle_upload_flow.py             # ⭐ Bottle upload E2E tests
│   ├── test_tasting_upload_flow.py            # ⭐ Tasting upload E2E tests
│   └── README.md                              # E2E testing philosophy
│
├── events/                                    # ⭐ EVENT SYSTEM TESTS (AUTOMATED)
│   ├── cleanup_test_events.py                 # Clean up test events
│   ├── create_test_event.py                   # Create whiskey blind tasting
│   ├── populate_event_tastings.py             # Populate with participants
│   ├── create_wine_event.py                   # Create wine blind tasting
│   ├── populate_wine_event.py                 # Populate wine event
│   ├── test_multi_event.py                    # Multi-event participation
│   ├── test_edit_tasting.py                   # Edit existing tastings
│   ├── run_all_tests.sh                       # ⭐ RUN THIS AFTER EVENT CHANGES
│   └── README.md                              # Event testing guide
│
├── tastings/                                  # ⭐ TASTING UPLOAD TESTS
│   ├── test_event_tastings.py                 # Event-based tastings
│   ├── test_cli_extraction.py                 # CLI extraction tests
│   ├── test_vault_integration.py              # Vault integration tests
│   ├── run_all_tests.sh                       # Run all tasting tests
│   └── README.md                              # Tasting testing guide
│
├── fixtures/                                  # ⭐ TEST DATA
│   ├── bottles/                               # Real bottle label images
│   │   ├── bourbon_001.jpg
│   │   ├── bourbon_002.jpg
│   │   ├── bourbon_003.jpg
│   │   └── wine_001.jpg
│   │
│   ├── tasting_cards/                         # Tasting card images + ground truth
│   │   ├── aws_wine_test_001.jpg              # AWS wine tasting card
│   │   ├── aws_wine_test_001.json             # Ground truth annotations
│   │   └── README.md                          # Ground truth testing guide
│   │
│   ├── manifests/                             # Bottle manifests
│   │   ├── wine_manifest_sample.pdf
│   │   └── wine_manifest_expected.json
│   │
│   └── expected_outputs/                      # Expected test outputs
│
├── manual/                                    # Manual testing scripts
│   ├── create_test_event.py                   # DEPRECATED - Use tests/events/
│   ├── populate_event_tastings.py             # DEPRECATED - Use tests/events/
│   ├── create-and-populate-event.sh           # DEPRECATED - Use tests/events/
│   └── README.md                              # Manual testing guide
│
├── test_bottle_extraction_cli.py              # CLI extraction tests
├── test_bottle_extraction_web.py              # Web server tests
├── test_extraction_accuracy.py                # ⭐ Tasting card accuracy testing
├── test_prompt_tuning.py                      # LLM prompt optimization
└── README.md                                  # This file
```

## Management Routes Tests ⭐ CRITICAL

**Location:** `tests/integration/routes/test_management_routes.py`

Integration tests for the bottle management workflow (load → edit → save to vault).

### Quick Start
```bash
# Run management route tests
uv run pytest tests/integration/routes/test_management_routes.py -v
```

### When to Run
**ALWAYS run management tests after modifying:**
- `src/reserve_automation/web/routes/management/core.py`
- `src/reserve_automation/web/routes/management/labels.py`
- `src/reserve_automation/generators/obsidian.py`
- Template directory paths or import structures
- Any refactoring that changes module paths

### Test Coverage
- ✅ Load bottles from vault
- ✅ Search bottles
- ✅ Update bottle fields (writes to vault!)
- ✅ Verify/enrich bottle metadata
- ✅ Rename directories when producer/name/year changes
- ✅ Get tasting summaries

**WHY THIS EXISTS:** After a refactor broke all management imports, we realized there were NO tests exercising the update workflow. These tests prevent that from happening again. See `tests/TESTING_GAP_ANALYSIS.md` for the full story.

## Event System Tests ⭐

**Location:** `tests/events/`

Comprehensive automated test suite for the multi-user tasting event system.

### Quick Start
```bash
# Run all event tests (DO THIS AFTER EVENT CHANGES!)
./tests/events/run_all_tests.sh

# Clean up test events
python3 tests/events/cleanup_test_events.py
```

### When to Run
**ALWAYS run event tests after modifying:**
- `src/reserve_automation/web/routes/events.py`
- `src/reserve_automation/web/routes/tastings.py`
- `src/reserve_automation/web/templates/event_*.html`
- `src/reserve_automation/web/templates/manual_tasting.html`
- Event-related schemas or cookie handling

### Test Coverage
- ✅ Blind whiskey events with 3 participants
- ✅ Blind wine events (AWS scoring)
- ✅ Multi-event participation
- ✅ Edit existing tastings

All 4/4 tests passing! See `tests/events/README.md` for detailed documentation.

## End-to-End Tests ⭐ CRITICAL

**Location:** `tests/e2e/`

Comprehensive E2E tests that verify complete user workflows and catch bugs that unit tests miss.

### Why E2E Tests Matter

**Recent bugs that had passing unit tests but would have been caught by E2E tests:**
- ✅ Orphaned JavaScript (`}; }` in HTML) - E2E checks actual HTML rendering
- ✅ Missing `credentials: 'include'` - E2E simulates browser fetch with cookies
- ✅ Field validation errors - E2E validates extracted data against model constraints

**Unit tests** verify individual functions work correctly.
**E2E tests** verify the entire application works as a user would experience it.

### Quick Start

```bash
# Run all E2E tests
uv run pytest tests/e2e/ -v

# Run specific workflow
uv run pytest tests/e2e/test_bottle_upload_flow.py -v
uv run pytest tests/e2e/test_tasting_upload_flow.py -v

# Run specific test
uv run pytest tests/e2e/test_bottle_upload_flow.py::TestCompleteBottleWorkflow::test_full_workflow_upload_to_approval -xvs
```

### When to Run

**ALWAYS run E2E tests after modifying:**
- `src/reserve_automation/web/routes/bottles.py`
- `src/reserve_automation/web/routes/tastings.py`
- `src/reserve_automation/web/templates/*.html`
- `src/reserve_automation/extractors/image_extractor.py`
- `src/reserve_automation/extractors/tasting_extractor.py`
- Any code that handles user uploads or generates HTML

### Test Coverage - Bottle Upload Flow

**`test_bottle_upload_flow.py`** - 13 tests covering:
- ✅ Upload bottle image → Verify extraction ID and session cookie
- ✅ Review page rendering → Check for orphaned JavaScript, proper HTML structure
- ✅ Get extraction data → Validate JSON structure, requires cookies
- ✅ Enrich metadata → Test enrichment flow
- ✅ Update bottle data → Test data persistence
- ✅ Field validation → Ensure fields don't exceed max lengths
- ✅ Complete workflow → Simulates full user journey from upload to approval

**Key Tests:**
- `test_review_page_renders_without_javascript_errors` - Would have caught the `}; }` bug
- `test_get_extraction_requires_valid_session` - Would have caught missing `credentials: 'include'`
- `test_extraction_data_fields_within_limits` - Would have caught `beverage_type` validation error

### Test Coverage - Tasting Upload Flow

**`test_tasting_upload_flow.py`** - 11 tests covering:
- ✅ Upload tasting card image → Verify extraction and session
- ✅ Get tasting data → Validate JSON structure and field limits
- ✅ Validate score ranges → Ensure wine/whiskey scores are within valid ranges
- ✅ Update tasting data → Test data persistence
- ✅ Complete workflow → Simulates full user journey
- ✅ Cross-browser compatibility → Verify cookies are HttpOnly, JSON content-type correct

**Key Tests:**
- `test_tasting_scores_within_valid_ranges` - Validates wine scores (0-3, 0-6, etc.)
- `test_tasting_extraction_data_fields_within_limits` - Prevents field overflow errors

**See `tests/e2e/README.md` for detailed E2E testing guide and patterns.**

## Unit Tests ⭐

**Location:** `tests/unit/`

Fast, isolated tests for individual functions and classes.

### Quick Start

```bash
# Run all unit tests
uv run pytest tests/unit/ -v

# Run specific category
uv run pytest tests/unit/models/ -v
uv run pytest tests/unit/services/ -v
uv run pytest tests/unit/utils/ -v
```

### When to Run

**ALWAYS run unit tests after modifying:**
- `src/reserve_automation/llm/response_parser.py` - Robust LLM parsing utilities
- `src/reserve_automation/core/models.py` - Pydantic model definitions
- Any utility functions or business logic

### Test Coverage

**`test_extractors.py`** - Robust LLM parsing tests:
- ✅ Parse JSON from markdown code blocks
- ✅ Handle non-array JSON responses (gracefully wrap in array)
- ✅ Sanitize fields with max_length constraints
- ✅ Validate numeric ranges (year, ABV, scores)
- ✅ Use defaults for invalid data instead of crashing

**Critical Tests:**
- `test_non_array_json_response_handled_gracefully` - Wraps single objects in array
- `test_invalid_bottle_data_uses_defaults` - Creates bottles with defaults instead of crashing

### Robust LLM Parsing

All LLM extraction points now use `LLMResponseParser` utilities to prevent crashes:
- **`safe_parse_json()`** - Handles markdown blocks, malformed JSON, returns None on error
- **`sanitize_string()`** - Truncates to max_length, logs warnings
- **`sanitize_int/float()`** - Validates ranges, extracts from strings
- **`safe_model_create()`** - Creates Pydantic models with auto-truncation

**Before:**
```python
# Crash on bad LLM output
data = json.loads(response.content)  # JSONDecodeError!
bottle = BottleMetadata(**data)      # ValidationError!
```

**After:**
```python
# Graceful handling
data = LLMResponseParser.safe_parse_json(response.content)
if not data:
    return []  # Return empty instead of crashing

bottle = LLMResponseParser.safe_model_create(
    BottleMetadata, data,
    required_defaults={"producer": "Unknown", "name": "Unknown"}
)
```

## Test Fixtures ⭐

**Location:** `tests/fixtures/`

### Bottle Images (`fixtures/bottles/`)

Real bottle label images for E2E tests and extraction validation.

**Contents:**
- `bourbon_001.jpg` - Bourbon bottle label
- `bourbon_002.jpg` - Bourbon bottle label (variant)
- `bourbon_003.jpg` - Bourbon bottle label (variant)
- `wine_001.jpg` - Wine bottle label

**Usage:**
```python
fixture_path = Path(__file__).parent.parent / "fixtures" / "bottles" / "bourbon_001.jpg"
with open(fixture_path, 'rb') as f:
    image_bytes = BytesIO(f.read())
```

### Tasting Card Images (`fixtures/tasting_cards/`)

Real tasting card images with ground truth annotations for accuracy testing.

**Contents:**
- `aws_wine_test_001.jpg` - AWS wine tasting card image
- `aws_wine_test_001.json` - Ground truth data for extraction validation
- `README.md` - Ground truth testing guide

**Ground Truth Format:**
```json
{
  "test_name": "AWS Wine Chart - Dec 13 2025 - Ben",
  "image_file": "aws_wine_test_001.jpg",
  "template_type": "aws_wine",
  "notes": "Optional notes about this test case",
  "expected_output": {
    "taster_name": "Ben",
    "tasting_date": "2025-12-13",
    "place": "Home",
    "tastings": [
      {
        "row": 1,
        "bottle_name": "Lions 2023 de Suduiraut Blanc Sec",
        "wine_appearance": 3.0,
        "wine_aroma": 5.5,
        "wine_taste": 4.0,
        "nose_notes": ["floral", "green apple", "yeasty"],
        "palate_notes": ["lemon", "peach", "cedar", "black olive"],
        ...
      }
    ]
  },
  "common_errors": [
    "List of known issues to watch for"
  ]
}
```

**Run accuracy tests:**
```bash
# All fixtures
python tests/test_extraction_accuracy.py --report

# Specific fixture
python tests/test_extraction_accuracy.py --fixture aws_wine_test_001 --report

# Quick accuracy check
python tests/test_extraction_accuracy.py
# Output: aws_wine_test_001: 85.2% accuracy
```

**See `tests/fixtures/tasting_cards/README.md` for creating new ground truth fixtures.**

### Other Fixtures

- **`manifests/`** - Test bottle manifest PDFs and expected extraction results
- **`expected_outputs/`** - Expected JSON outputs for comparison tests

## Tasting Upload Tests ⭐ NEW

**Location:** `tests/tastings/`

Comprehensive test suite for all tasting upload workflows: event-based, image extraction, manual entry, and vault integration.

### Quick Start
```bash
# Run all tasting tests
./tests/tastings/run_all_tests.sh

# Run individual suites
python3 tests/tastings/test_event_tastings.py        # Suite 1: Event-based (safe)
python3 tests/tastings/test_cli_extraction.py         # Suite 2: CLI --dry-run (safe)
python3 tests/tastings/test_vault_integration.py      # Suite 3: Vault integration (temp vault)
```

### When to Run
**ALWAYS run tasting tests after modifying:**
- `src/reserve_automation/web/routes/tastings.py`
- `src/reserve_automation/web/routes/upload.py`
- `src/reserve_automation/web/services/tasting_service.py`
- `src/reserve_automation/generators/tasting_generator.py`
- `src/reserve_automation/cli.py` (extract-tasting command)
- `templates/tasting_*.md.jinja`

### Test Coverage - Three Suites

**Suite 1: Event-Based Tastings** (SAFE - no vault writes)
- ✅ Manual tasting wizard in event mode
- ✅ Edit existing event tastings
- ✅ In-memory event store (no disk writes)

**Suite 2: CLI Extraction** (SAFE - uses --dry-run)
- ✅ AWS wine card extraction
- ⏳ Bourbon card extraction (needs images)
- ✅ Template auto-detection
- ✅ LLM robustness testing

**Suite 3: Vault Integration** (writes to /tmp/test-vault)
- ✅ Manual Obsidian mode tastings
- ✅ CLI extraction to vault
- ✅ Duplicate detection
- ⚠️ Requires: `RESERVE_VAULT_PATH=/tmp/test-vault ./start-web.sh`

See `tests/tastings/README.md` for detailed documentation.

## Test Fixtures

### Wine Manifest (`wine_manifest_sample.pdf`)

This is a real wine manifest PDF containing 12 bottles used for regression testing. It ensures that:
- PDF parsing works correctly
- Bottle extraction produces consistent results
- Both CLI and web workflows handle manifests properly

### Expected Results (`wine_manifest_expected.json`)

Baseline extraction results generated from the current extraction code. Used to detect regressions when modifying extraction logic.

**To regenerate baseline results:**

```bash
uv run python -c "
import asyncio
import json
from pathlib import Path
from reserve_automation.core.config import Config
from reserve_automation.extractors.bottle import BottleExtractor
from reserve_automation.parsers.pdf import PDFParser
from reserve_automation.llm.gateway import LLMGateway

async def extract():
    config = Config.load()
    llm = LLMGateway(config.llm)
    parser = PDFParser()
    extractor = BottleExtractor(llm)

    pdf_path = Path('tests/fixtures/manifests/wine_manifest_sample.pdf')
    result = await parser.parse(pdf_path)
    bottles = await extractor.extract(result, beverage_type='wine')

    baseline = [b.model_dump(mode='json') for b in bottles]
    output_path = Path('tests/fixtures/manifests/wine_manifest_expected.json')
    output_path.write_text(json.dumps(baseline, indent=2))

    print(f'Generated baseline: {len(bottles)} bottles')

asyncio.run(extract())
"
```

## Running Tests

### Run All Tests

```bash
uv run pytest tests/ -v
```

### Run CLI Tests Only

```bash
uv run pytest tests/test_bottle_extraction_cli.py -v
```

### Run Web Server Tests Only

```bash
uv run pytest tests/test_bottle_extraction_web.py -v
```

### Run Specific Test Class

```bash
# CLI tests
uv run pytest tests/test_bottle_extraction_cli.py::TestBottleExtraction -v

# Web tests
uv run pytest tests/test_bottle_extraction_web.py::TestBottleUploadAPI -v
```

### Run Specific Test

```bash
uv run pytest tests/test_bottle_extraction_cli.py::TestBottleExtraction::test_extract_bottles_from_manifest -v
```

### Run with Coverage

```bash
uv run pytest tests/ --cov=reserve_automation --cov-report=html
```

## Test Categories

### CLI Tests (`test_bottle_extraction_cli.py`)

**Test Classes:**

1. **TestPDFParsing** - PDF parsing functionality
   - `test_parse_wine_manifest` - Basic PDF parsing
   - `test_parse_extracts_text_from_all_pages` - Multi-page extraction

2. **TestBottleExtraction** - Bottle extraction from manifests
   - `test_extract_bottles_from_manifest` - Basic extraction
   - `test_extracted_bottle_count` - Verify bottle count matches baseline
   - `test_extracted_bottles_have_required_fields` - Data validation
   - `test_extraction_matches_expected_bottles` - Regression test
   - `test_bottles_have_correct_years` - Year extraction accuracy
   - `test_bottles_extract_regions` - Region extraction

3. **TestBottleDataQuality** - Data quality checks
   - `test_no_duplicate_bottles` - Duplicate detection
   - `test_confidence_scores_reasonable` - Confidence score validation

4. **TestEdgeCases** - Edge cases and error handling
   - `test_empty_pdf_returns_no_bottles` - Empty input handling
   - `test_auto_detect_beverage_type` - Auto-detection

### Web Server Tests (`test_bottle_extraction_web.py`)

**Test Classes:**

1. **TestUploadBottlesPage** - Upload page rendering
   - `test_upload_bottles_page_loads` - Page loads successfully
   - `test_upload_bottles_page_has_upload_forms` - Form elements present

2. **TestBottleUploadAPI** - Upload API endpoints
   - `test_upload_wine_manifest` - Manifest upload
   - `test_upload_manifest_extracts_multiple_bottles` - Bottle count
   - `test_upload_creates_session_cookie` - Session management
   - `test_upload_invalid_file_type_rejected` - Validation

3. **TestBottleReviewAPI** - Review API endpoints
   - `test_get_extraction_data` - Retrieve extraction data
   - `test_extraction_data_has_correct_structure` - Data structure validation

4. **TestBottleEnrichmentAPI** - Enrichment API endpoints
   - `test_enrich_bottle` - Web search enrichment
   - `test_enrichment_updates_stage` - Stage progression

5. **TestBottleUpdateAPI** - Update API endpoints
   - `test_update_bottle_data` - Edit bottle data

6. **TestBottleApprovalAPI** - Approval API endpoints
   - `test_approve_bottle_requires_valid_vault` - Vault validation

7. **TestBottleReviewPage** - Review page rendering
   - `test_review_page_loads` - Page loads successfully

8. **TestBottleWorkflowIntegration** - End-to-end workflows
   - `test_complete_workflow_manifest_to_review` - Full upload workflow
   - `test_reject_bottles_workflow` - Rejection workflow

9. **TestSessionPersistence** - Session management
   - `test_session_persists_across_requests` - Session persistence

## Prerequisites

### LLM Service Running

Tests require a running LLM service (LM Studio or similar) for extraction. Make sure your LLM is running before running tests.

**Check config:**

```bash
cat config/config.yaml
```

Ensure `llm.providers` includes an active provider.

### Web Server Configuration

Web tests require proper web configuration:

```bash
# Set web secret key
export WEB_SECRET_KEY=$(openssl rand -hex 32)

# Or create .env file
echo "WEB_SECRET_KEY=$(openssl rand -hex 32)" > .env
```

## Test Markers

Tests use pytest markers for categorization:

```bash
# Run only async tests
uv run pytest tests/ -m asyncio

# Skip slow tests
uv run pytest tests/ -m "not slow"
```

## Continuous Integration

These tests are designed to run in CI/CD pipelines. They:
- Use fixtures for test data (no external dependencies)
- Test both success and failure paths
- Validate data structure and quality
- Check for regressions using baseline results

## Troubleshooting

### Tests Fail with "LLM not available"

**Solution:** Start your LLM service (LM Studio) before running tests.

### Tests Fail with "Expected results file not found"

**Solution:** Generate baseline results:

```bash
# From project root
uv run python -c "..." # (see command above)
```

### Web Tests Fail with "Service not initialized"

**Solution:** Set `WEB_SECRET_KEY` environment variable:

```bash
export WEB_SECRET_KEY=$(openssl rand -hex 32)
uv run pytest tests/test_bottle_extraction_web.py -v
```

### Tests are Slow

**Reason:** Tests make real LLM calls for extraction (not mocked).

**Solutions:**
- Run specific test classes instead of all tests
- Use faster LLM models during testing
- Consider adding mock fixtures for unit tests (separate from integration tests)

## Adding New Tests

### When to Add Tests

Add tests when:
1. **Adding new features** - Test new extraction logic, API endpoints, or workflows
2. **Fixing bugs** - Add regression test to prevent bug from recurring
3. **Changing extraction logic** - Update baseline results and add tests for new behavior
4. **Adding new routes** - ESPECIALLY if they write to disk or modify the vault

### CRITICAL: Test Write Operations

**If a route writes to disk, you MUST test it.**

Bad example (what we did wrong):
```python
# We tested this:
GET /api/v1/management/bottles/search  # Read-only, no disk writes

# But NOT this:
POST /api/v1/management/bottles/update-fields  # WRITES TO VAULT
```

**Result:** Import errors broke the update endpoint but all tests passed.

Good example (what we should do):
```python
def test_update_bottle_fields_writes_to_vault(client, tmp_path):
    """Update bottle fields and verify vault file changed."""
    # Get bottle
    response = client.get("/api/v1/management/bottles")
    bottle = response.json()["bottles"][0]

    # Update it
    response = client.post(
        "/api/v1/management/bottles/update-fields",
        json={"bottle": bottle, "updates": {"price": 150}}
    )

    assert response.status_code == 200

    # CRITICAL: Verify the file actually changed
    vault_file = tmp_path / "vault" / bottle["vault_path"] / "bottle.md"
    content = vault_file.read_text()
    assert "Price: 150" in content  # Did it actually write?
```

### Test Checklist for New Routes

When adding a new route that modifies data:

- [ ] Test the API returns 200 (basic)
- [ ] Test the response has correct structure (schema)
- [ ] **Test the side effect happened** (file written, directory created, etc.)
- [ ] Test error cases (vault not configured, invalid data, etc.)
- [ ] Test the complete user workflow (load → modify → save → reload)

### What Makes a Good Integration Test

✅ **Good:** Tests actual side effects
```python
# Approves bottle and checks vault file exists
assert (vault_path / bottle["vault_path"] / "bottle.md").exists()
```

❌ **Bad:** Only tests response codes
```python
# Just checks endpoint doesn't crash
assert response.status_code == 200
```

✅ **Good:** Tests complete workflows
```python
# Upload → Extract → Edit → Approve → Verify file written
```

❌ **Bad:** Tests endpoints in isolation
```python
# Just tests /approve endpoint, doesn't check if extraction worked
```

### Test File Naming

- CLI tests: `test_*_cli.py`
- Web tests: `test_*_web.py`
- Integration tests: `test_*_integration.py`

### Fixture Guidelines

- Store test files in `tests/fixtures/`
- Use real data when possible (better integration tests)
- Document fixture sources in comments
- Keep fixtures small (< 1MB) to avoid repo bloat

## Quick Test Reference ⭐

### Run ALL Tests
```bash
# Everything
uv run pytest tests/ -v

# All tests with coverage report
uv run pytest tests/ --cov=reserve_automation --cov-report=html
```

### Run by Category

```bash
# E2E Tests (complete user workflows)
uv run pytest tests/e2e/ -v

# Unit Tests (fast, isolated)
uv run pytest tests/unit/ -v

# Integration Tests (component interactions)
uv run pytest tests/integration/ -v

# Event System Tests (automated bash scripts)
./tests/events/run_all_tests.sh

# Tasting Upload Tests (CLI, web, vault)
./tests/tastings/run_all_tests.sh

# Extraction Accuracy Tests (ground truth comparison)
python tests/test_extraction_accuracy.py --report

# Management Routes Tests (critical workflow)
uv run pytest tests/integration/routes/test_management_routes.py -v
```

### Run Specific Workflows

```bash
# Bottle upload E2E
uv run pytest tests/e2e/test_bottle_upload_flow.py -v

# Tasting upload E2E
uv run pytest tests/e2e/test_tasting_upload_flow.py -v

# Extractor unit tests
uv run pytest tests/unit/test_extractors.py -v

# CLI bottle extraction
uv run pytest tests/test_bottle_extraction_cli.py -v

# Web bottle extraction
uv run pytest tests/test_bottle_extraction_web.py -v
```

### Common Pytest Options

```bash
-v          # Verbose output
-vv         # Extra verbose (show full diffs)
-x          # Stop on first failure
-s          # Show print statements
--lf        # Run last failed tests only
--ff        # Run failed tests first
-k PATTERN  # Run tests matching pattern (e.g., -k "upload")
-n auto     # Run in parallel (requires pytest-xdist)
```

## Test Coverage Summary

| Test Type | Location | Purpose | When to Run |
|-----------|----------|---------|-------------|
| **E2E Tests** | `tests/e2e/` | Complete user workflows | After modifying routes, templates, extractors |
| **Unit Tests** | `tests/unit/` | Individual functions | After modifying utils, models, parsers |
| **Integration Tests** | `tests/integration/` | Component interactions | After modifying routes, services |
| **Event Tests** | `tests/events/` | Event system workflows | After modifying event routes/templates |
| **Tasting Tests** | `tests/tastings/` | Tasting upload workflows | After modifying tasting routes/extractors |
| **Accuracy Tests** | `test_extraction_accuracy.py` | LLM extraction quality | After changing prompts or models |
| **Management Tests** | `integration/routes/` | Vault update workflow | After modifying management routes |

## Test Coverage Goals

**Current Focus:**
- ✅ E2E user workflows (bottle & tasting upload)
- ✅ Robust LLM parsing (handles all edge cases)
- ✅ Field validation (max lengths, score ranges)
- ✅ Session management (cookies, persistence)
- ✅ HTML rendering (no orphaned JavaScript)
- ✅ PDF parsing and extraction
- ✅ Event system (multi-user tastings)
- ✅ Vault integration (management workflow)

**Future Coverage:**
- Performance benchmarks for LLM extraction
- More ground truth fixtures for different tasting card types
- Image preprocessing quality tests
- Browser compatibility testing
- Load testing for concurrent uploads
