# Extraction Test Fixtures

This directory contains ground truth test cases for validating tasting card extraction accuracy.

## Purpose

This testing framework allows you to:

1. **Test new LLM models** - Validate extraction quality when switching models
2. **Test prompt changes** - Ensure prompt modifications don't regress accuracy
3. **Test new form templates** - Add ground truth for new tasting card formats
4. **Track improvements** - Measure accuracy gains over time

## Structure

Each test case consists of two files:

- `{name}.jpg` - The test image
- `{name}.json` - Ground truth data with expected extraction output

## Creating a New Test Case

1. **Save the test image**:
   ```bash
   cp /path/to/tasting_card.jpg tests/fixtures/extraction/aws_wine_test_002.jpg
   ```

2. **Create ground truth JSON**:
   ```json
   {
     "test_name": "Descriptive test name",
     "image_file": "aws_wine_test_002.jpg",
     "template_type": "aws_wine",
     "notes": "Optional notes about this test case",
     "expected_output": {
       "taster_name": "...",
       "tasting_date": "YYYY-MM-DD",
       "place": "...",
       "theme": null,
       "tastings": [
         {
           "row": 1,
           "bottle_name": "...",
           "price": null,
           "wine_appearance": 3.0,
           "wine_aroma": 5.5,
           "wine_taste": 4.0,
           "wine_aftertaste": 1.0,
           "wine_overall": 1.0,
           "total_score": null,
           "nose_notes": ["word1", "word2"],
           "palate_notes": ["word1", "word2"],
           "finish_notes": ["word1"],
           "overall_notes": "text"
         }
       ]
     },
     "common_errors": [
       "List of known issues to watch for"
     ]
   }
   ```

3. **Carefully transcribe** the actual handwritten text from each column
   - Don't guess or hallucinate - only include what's actually written
   - Match the column layout exactly (nose_notes from Aroma column, etc.)
   - Use exact wording, even if misspelled

## Running Tests

### Test all fixtures
```bash
cd /mnt/d/Users/ben/Documents/spirits/automation
python tests/test_extraction_accuracy.py --report
```

### Test specific fixture
```bash
python tests/test_extraction_accuracy.py --fixture aws_wine_test_001 --report
```

### Quick accuracy check
```bash
python tests/test_extraction_accuracy.py
# Output: aws_wine_test_001: 85.2% accuracy
```

### Run with pytest
```bash
pytest tests/test_extraction_accuracy.py -v
```

## Output Example

```
================================================================================
EXTRACTION TEST REPORT: AWS Wine Chart - Dec 13 2025 - Ben
================================================================================
Fixture: aws_wine_test_001.jpg
Template: aws_wine

OVERALL ACCURACY: 87.5%
Tasting Notes Accuracy: 75.0%

--------------------------------------------------------------------------------
METADATA FIELDS
--------------------------------------------------------------------------------
✓ taster_name: Ben → Ben
✓ tasting_date: 2025-12-13 → 2025-12-13
✓ place: Home → Home
✓ theme: None → None

--------------------------------------------------------------------------------
TASTING 1 (Accuracy: 91.7%)
--------------------------------------------------------------------------------

Basic Fields:
  ✓ bottle_name: Lions 2023 de Suduiraut Blanc Sec → Lions 2023 de Suduiraut Blanc Sec
  ✓ wine_appearance: 3.0 → 3.0
  ✓ wine_aroma: 5.5 → 5.5
  ✗ wine_taste: 4.0 → 5.5
  ✓ wine_aftertaste: 1.0 → 1.0

Tasting Notes:
  ✓ nose_notes:
      Expected: ['green apple', 'yeasty', 'floral']
      Actual:   ['floral', 'green apple', 'yeasty']
  ✗ palate_notes:
      Expected: ['lemon', 'peach', 'cedar', 'black olive']
      Actual:   ['cedar', 'lemon']
  ...
```

## Best Practices

1. **Be precise** - Transcribe exactly what's written, no interpretation
2. **Test edge cases** - Include hard-to-read handwriting, unusual formats
3. **Document issues** - Use the `common_errors` field to note known problems
4. **Version control** - Commit test fixtures to track regression over time
5. **Update regularly** - Add new test cases for each new form template

## Using for Model Comparison

When testing a new LLM model:

1. Update LLM config to use new model
2. Run full test suite: `python tests/test_extraction_accuracy.py --report > results_new_model.txt`
3. Compare accuracy metrics against baseline
4. Review specific field failures to understand model strengths/weaknesses

## Adding New Form Templates

When supporting a new tasting form format:

1. Create at least 3 test cases for the new template
2. Include variety: different handwriting, partially filled, fully filled
3. Document the template structure in `common_errors`
4. Update `template_type` field with new template name

## Maintenance

- Review and update ground truth if form specifications change
- Add new test cases when encountering extraction failures in production
- Retire outdated test cases if form templates are deprecated
