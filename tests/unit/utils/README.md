# Utility Module Tests

## Overview

This directory contains unit tests for utility modules that handle core infrastructure: bottle matching, vault reading, and Obsidian frontmatter updates.

**Status**: Week 4 Complete ✅  
**Tests Created**: 61 tests (across 3 files)  
**Tests Passing**: 61/61 (100%) ✅✅✅  
**Target**: 45 tests with >80% passing rate ✅ EXCEEDED

## Files

### `test_bottle_matcher.py` (23 tests)
Tests fuzzy matching and bottle search functionality.

**Test Categories**:
- **Fuzzy Matching** (7 tests) - Similarity calculation, typo tolerance, case sensitivity, scoring
- **Substring Matching** (4 tests) - Strict substring search, exact matches, partial matches
- **Caching** (5 tests) - Cache population, invalidation, per-type caching
- **Best Match** (3 tests) - Single best match selection, auto-accept thresholds
- **BottleMatch Object** (2 tests) - Object construction, repr
- **Edge Cases** (3 tests) - Empty names, unicode, multiple vintages

**Key Functionality Tested**:
```python
# Fuzzy matching with typo tolerance
matcher.find_matches("Caymis Cabernet", "wine")  # Finds "Caymus"

# Substring matching
matcher.find_matches("Stagg", "whiskey", strict_substring=True)

# Caching
matcher.find_matches("Wine", "wine")  # Populates cache
matcher.invalidate_cache("wine")       # Clears cache
```

**Status**: All 23 tests passing! ✅

### `test_vault_reader.py` (24 tests)
Tests reading bottle metadata from Obsidian vault markdown files.

**Test Categories**:
- **Reading Bottles** (4 tests) - Read all bottles, filter by type, vault_path assignment
- **Wine Parsing** (5 tests) - Winemaker, Vintage, Country-Region, Price, Variety, ABV
- **Whiskey Parsing** (5 tests) - Distiller, Year, Proof, ABV, MashBill, BarrelType
- **Frontmatter Parsing** (3 tests) - Extract frontmatter, skip invalid files, handle empty values
- **Edge Cases** (5 tests) - Missing files, invalid values, nonexistent directories
- **Vault Paths** (2 tests) - Path format for wines and whiskeys

**Key Functionality Tested**:
```python
# Read all bottles from vault
vault_reader.read_all_bottles(beverage_type="wine")

# Parse wine-specific fields
bottle.producer  # From "Winemaker" field
bottle.year      # From "Vintage" field

# Parse whiskey-specific fields
bottle.producer  # From "Distiller" field
bottle.year      # From "Year" field
bottle.proof     # Whiskey-only field
```

**Status**: All 24 tests passing! ✅

### `test_obsidian_updater.py` (14 tests)
Tests updating Obsidian markdown frontmatter fields.

**Test Categories**:
- **Label Field Update** (4 tests) - Update Label field, preserve frontmatter, preserve body
- **Frontmatter Parsing** (4 tests) - Parse YAML frontmatter, handle quotes, empty values
- **Frontmatter Writing** (3 tests) - Write frontmatter, quote values with spaces, handle empty values
- **Get Bottle File Path** (2 tests) - Find bottle file in folder, handle missing files
- **Integration** (2 tests) - Full update workflow, multiple updates

**Key Functionality Tested**:
```python
# Update Label field
updater.update_label_field(bottle_file, "labels/new-label.jpg")

# Parse frontmatter
frontmatter, body = updater.parse_frontmatter(content)

# Write frontmatter back
updater.write_frontmatter(bottle_file, frontmatter, body)
```

**Status**: All 14 tests passing! ✅

## Running Tests

```bash
# Run all utility tests
uv run pytest tests/unit/utils/ -v

# Run specific test file
uv run pytest tests/unit/utils/test_bottle_matcher.py -v

# Run specific test
uv run pytest tests/unit/utils/test_bottle_matcher.py::TestFuzzyMatching::test_typo_tolerance -v
```

## What These Tests Verify

### ✅ Bottle Matching Logic

1. **Fuzzy Matching**
   - Test: `test_exact_match_returns_high_score`
   - Test: `test_typo_tolerance`
   - Ensures fuzzy matching tolerates typos and finds similar bottles

2. **Substring Matching**
   - Test: `test_substring_match_finds_partial`
   - Test: `test_substring_exact_match_highest_score`
   - Validates strict substring search for precise matching

3. **Caching Performance**
   - Test: `test_cache_populated_on_first_search`
   - Test: `test_invalidate_cache_specific_type`
   - Ensures caching works correctly and can be invalidated

### ✅ Vault Reading

1. **Wine Parsing**
   - Test: `test_parse_wine_basic_fields`
   - Test: `test_parse_wine_country_region`
   - Validates wine-specific field extraction (Winemaker, Vintage)

2. **Whiskey Parsing**
   - Test: `test_parse_whiskey_basic_fields`
   - Test: `test_parse_whiskey_proof`
   - Validates whiskey-specific field extraction (Distiller, Year, Proof)

3. **Edge Case Handling**
   - Test: `test_invalid_price_value`
   - Test: `test_invalid_year_value`
   - Ensures graceful handling of malformed data

### ✅ Frontmatter Updates

1. **Label Updates**
   - Test: `test_update_label_field_success`
   - Test: `test_update_label_field_preserves_frontmatter`
   - Ensures Label field can be updated without breaking file structure

2. **Frontmatter Preservation**
   - Test: `test_update_label_field_preserves_body`
   - Test: `test_full_update_workflow`
   - Validates that markdown body content is preserved during updates

## Week 4 Summary

**Goal**: Utility infrastructure reliability  
**Tests Created**: 61 tests (exceeded 45 target by 136%)  
**Success Criteria**: ✅ All tests passing, utility modules thoroughly covered

### Test Breakdown

| File | Tests | Purpose |
|------|-------|---------|
| test_bottle_matcher.py | 23 | Fuzzy matching, caching, best match selection |
| test_vault_reader.py | 24 | Parsing bottles from Obsidian vault |
| test_obsidian_updater.py | 14 | Updating Obsidian frontmatter fields |
| **Total** | **61** | **Complete utility module coverage** |

### Critical Validations

1. **Bottle Matching**: Fuzzy matching with typo tolerance, substring search, caching
2. **Vault Reading**: Wine vs whiskey field parsing, Country-Region splitting, invalid value handling
3. **Frontmatter Updates**: Label field updates, frontmatter preservation, multi-line content
4. **Edge Cases**: Unicode handling, missing files, invalid data, empty values
5. **Performance**: Caching reduces repeated vault reads

## Integration with Testing Plan

This is **Week 4** of the 5-week testing implementation plan:

- ✅ Week 1: Service layer tests (36 tests passing)
- ✅ Week 2: Model coherence tests (53 tests passing)
- ✅ Week 3: API contract tests (21 tests passing)
- ✅ Week 4: Utility tests (61 tests passing) - **CURRENT**
- ⏳ Week 5: CI integration

**Total Tests So Far**: **171 tests** (36 service + 53 model + 21 API + 61 utility)

## Next Steps

1. ✅ Week 4 Complete - All 61 tests passing
2. ⏳ Week 5: CI integration and coverage reporting
3. ⏳ Set up automated test runs in GitHub Actions
4. ⏳ Configure coverage thresholds

## Contributing

When adding new utility functions:

1. **Add unit test** in appropriate test file
2. **Test edge cases** (empty inputs, invalid data, unicode)
3. **Test error handling** (missing files, malformed data)
4. **Test caching** if applicable
5. **Run tests** to verify all pass
6. **Update documentation** if adding new test categories

## Test Implementation Notes

### Fuzzy Matching Strategy

Tests use `difflib.SequenceMatcher` for fuzzy matching:
- Exact match score ~1.0
- Partial match score 0.5-0.9
- Typo tolerance (one char diff still matches)
- Case-insensitive matching

### Vault Structure Assumptions

Tests assume Obsidian vault structure:
```
vault/
├── 1_Wines/
│   └── Producer - Name - Year/
│       └── Producer - Name - Year.md
└── 1_Whiskeys/
    └── Distiller - Name - Year/
        └── Distiller - Name - Year.md
```

### Frontmatter Format

Tests validate YAML frontmatter parsing:
```yaml
---
fileClass: Wine
Winemaker: Producer Name
Vintage: 2020
---
```

## Resources

- Main testing plan: `../../../TESTING_GAP_ANALYSIS.md`
- Service tests: `../services/README.md`
- Model tests: `../models/README.md`
- API tests: `../../integration/routes/README.md`
