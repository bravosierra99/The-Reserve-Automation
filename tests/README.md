# Reserve Automation Tests

This directory contains tests for The Reserve Automation project, covering both CLI and web server components.

## Test Structure

```
tests/
├── fixtures/
│   └── manifests/
│       ├── wine_manifest_sample.pdf          # Real wine manifest for testing
│       └── wine_manifest_expected.json       # Baseline extraction results
├── test_bottle_extraction_cli.py             # CLI extraction tests
├── test_bottle_extraction_web.py             # Web server tests
└── README.md                                 # This file
```

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

### Test File Naming

- CLI tests: `test_*_cli.py`
- Web tests: `test_*_web.py`
- Integration tests: `test_*_integration.py`

### Fixture Guidelines

- Store test files in `tests/fixtures/`
- Use real data when possible (better integration tests)
- Document fixture sources in comments
- Keep fixtures small (< 1MB) to avoid repo bloat

## Test Coverage Goals

**Current Focus:**
- ✅ PDF parsing
- ✅ Bottle extraction
- ✅ Web upload workflow
- ✅ Session management
- ✅ 3-stage review process

**Future Coverage:**
- Image label extraction (single bottle photos)
- Enrichment accuracy
- Obsidian file generation
- Error handling edge cases
- Performance benchmarks
