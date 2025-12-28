# Model Coherence Tests

## Overview

This directory contains model coherence tests that prevent field synchronization bugs across data models and schemas. These tests are **Week 2** of the testing implementation plan.

**Status**: Week 2 Complete ✅  
**Tests Created**: 53 tests (across 3 files)  
**Tests Passing**: 53/53 (100%) ✅✅✅  
**Target**: 20 tests with >80% passing rate ✅ EXCEEDED

## Files

### `test_schema_coherence.py` (18 tests)
Tests field synchronization between TastingNote and TastingData models.

**Test Categories**:
- **Field Completeness** (6 tests) - Ensures all core, wine, whiskey, and notes fields exist in both models
- **Type Field Isolation** (2 tests) - Prevents wine fields from leaking into whiskey tastings and vice versa
- **Conversion Round-Trips** (3 tests) - Validates data survives model_dump() conversions
- **Score Validation** (4 tests) - Verifies score ranges match FileClass constraints
- **Total Score Calculations** (3 tests) - Tests total_score() and max_score() methods

**Key Tests**:
```python
def test_notes_fields_in_both_models():
    # REGRESSION TEST: Would have caught appearance_notes bug!
    # Ensures appearance_notes exists in both TastingNote and TastingData
```

**Status**: All 18 tests passing! ✅

### `test_bottle_metadata.py` (19 tests)
Tests BottleMetadata field validation, conversions, and Obsidian compatibility.

**Test Categories**:
- **Creation** (4 tests) - Basic bottle creation with minimal and full field sets
- **Field Validation** (6 tests) - Pydantic validation for year, proof, ABV, age, inventory, confidence
- **Obsidian Dict Conversion** (6 tests) - Tests to_obsidian_dict() for wine vs whiskey field naming
- **Field Name Conventions** (3 tests) - Ensures all required fields exist in the model

**Key Tests**:
```python
def test_wine_to_obsidian_dict_basic_fields():
    # Wine should use Winemaker and Vintage
    assert obsidian_dict["Winemaker"] == "Caymus"
    assert obsidian_dict["Vintage"] == 2019
    
def test_whiskey_to_obsidian_dict_basic_fields():
    # Whiskey should use Distiller and Year
    assert obsidian_dict["Distiller"] == "Buffalo Trace"
    assert obsidian_dict["Year"] == 2022
```

**Status**: All 19 tests passing! ✅

### `test_obsidian_coherence.py` (16 tests)
Tests automation templates against Obsidian FileClass definitions.

**Test Categories**:
- **Wine Tasting Coherence** (5 tests) - Field names, score ranges, template structure
- **Whiskey Tasting Coherence** (5 tests) - Field names, score ranges (0-3 max 10)
- **Wine Bottle Coherence** (3 tests) - Core fields, template exists, type values
- **Whiskey Bottle Coherence** (3 tests) - Core fields, template exists, proof range

**Status**: All 16 tests passing! ✅

## Running Tests

```bash
# Run all model coherence tests
uv run pytest tests/unit/models/ -v

# Run specific test file
uv run pytest tests/unit/models/test_schema_coherence.py -v

# Run specific test
uv run pytest tests/unit/models/test_schema_coherence.py::TestFieldCompleteness::test_notes_fields_in_both_models -v
```

## What These Tests Catch

### ✅ Regression Prevention

1. **appearance_notes field missing** (Dec 27, 2025)
   - Test: `test_notes_fields_in_both_models`
   - Test: `test_tasting_data_to_dict_preserves_appearance_notes`
   - Validates field exists in both TastingNote and TastingData

2. **Wine/whiskey field leakage**
   - Test: `test_wine_tasting_only_populates_wine_fields`
   - Test: `test_whiskey_tasting_only_populates_whiskey_fields`
   - Ensures type-specific fields don't cross contaminate

3. **Score range violations**
   - Test: `test_wine_appearance_score_range` (0-3)
   - Test: `test_whiskey_nose_score_range` (0-3)
   - Test: `test_whiskey_overall_score_range` (0-1)
   - Prevents invalid scores from being created

4. **Obsidian field name mismatches**
   - Test: `test_wine_to_obsidian_dict_basic_fields`
   - Test: `test_whiskey_to_obsidian_dict_basic_fields`
   - Ensures wine uses Winemaker/Vintage, whiskey uses Distiller/Year

### 🔄 Current Bug Prevention

- Field synchronization across TastingNote and TastingData
- Score validation matching FileClass constraints
- Obsidian dict conversion correctness
- Template structure matching vault definitions
- Total score calculations (wine max 20, whiskey max 10)

## Week 2 Summary

**Goal**: Prevent field synchronization bugs like appearance_notes  
**Tests Created**: 53 tests (exceeded 20 target by 165%)  
**Success Criteria**: ✅ All tests passing, automated coherence checks in place

### Test Breakdown

| File | Tests | Purpose |
|------|-------|---------|
| test_schema_coherence.py | 18 | TastingNote ↔ TastingData synchronization |
| test_bottle_metadata.py | 19 | BottleMetadata validation and conversion |
| test_obsidian_coherence.py | 16 | Automation ↔ Obsidian FileClass matching |
| **Total** | **53** | **Complete model coherence coverage** |

### Critical Validations

1. **Field Completeness**: All required fields exist in both TastingNote and TastingData
2. **Type Isolation**: Wine fields don't appear in whiskey tastings and vice versa
3. **Score Ranges**: All scores validate against FileClass constraints
4. **Obsidian Compatibility**: to_obsidian_dict() produces valid FileClass frontmatter
5. **Template Matching**: Automation templates match Obsidian vault templates

## Integration with Testing Plan

This is **Week 2** of the 5-week testing implementation plan:

- ✅ Week 1: Service layer tests (36 tests passing)
- ✅ Week 2: Model coherence tests (53 tests passing) - **CURRENT**
- ⏳ Week 3: API contract tests (25 tests)
- ⏳ Week 4: Utility tests (45 tests)
- ⏳ Week 5: CI integration

**Total Tests So Far**: 89 tests (36 service + 53 model)

## Next Steps

1. ✅ Week 2 Complete - All 53 tests passing
2. ⏳ Week 3: API contract tests for web routes
3. ⏳ Week 4: Utility module tests (bottle_matcher, vault_reader)
4. ⏳ Week 5: CI integration and coverage reporting

## Contributing

When adding new model fields:

1. **Add field to model** (TastingNote, BottleMetadata, etc.)
2. **Add test for field existence** in `test_schema_coherence.py` or `test_bottle_metadata.py`
3. **Add Obsidian coherence test** in `test_obsidian_coherence.py` if field is in templates
4. **Run tests** to verify all pass
5. **Update #CLAUDE_REQ comments** in affected files

## Resources

- Main testing plan: `../../TESTING_GAP_ANALYSIS.md`
- Service tests: `../services/README.md`
- Obsidian vault documentation: `/mnt/d/users/ben/Documents/spirits/the-reserve/CLAUDE.md`
