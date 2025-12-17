# Tasting Card Extraction - Testing & Optimization Guide

This guide documents the complete extraction pipeline and how to test and optimize each stage.

## Table of Contents
1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Testing the Full Pipeline](#testing-the-full-pipeline)
4. [Testing Individual Stages](#testing-individual-stages)
5. [Prompt Testing & Optimization](#prompt-testing--optimization)
6. [Performance Metrics](#performance-metrics)
7. [Common Issues & Solutions](#common-issues--solutions)

---

## Overview

The extraction system converts handwritten tasting cards (images) into structured JSON data. It uses a two-stage pipeline:

1. **LLMWhisperer API** - Layout-preserving OCR that converts images to ASCII tables
2. **Local LLM** - Structured extraction from ASCII tables to JSON

**Current Performance**: 73.9% field-level accuracy (17/23 fields correct)

**Previous Approaches That Failed**:
- Direct vision-based extraction: 25-32% accuracy
- Tesseract OCR + column detection: Failed due to handwriting
- Custom table structure detection: Column blending issues

---

## Architecture

### Stage 1: LLMWhisperer (Layout-Preserving OCR)

**Purpose**: Convert image to ASCII table while preserving spatial layout

**Configuration**: `config/default.yaml`
```yaml
llm_whisperer:
  api_key: null  # Set in user.yaml or LLMWHISPERER_API_KEY env var
  base_url: "https://llmwhisperer-api.us-central.unstract.com/api/v2"
  mode: "table"  # CRITICAL: Must be "table" not "form" or "text"
  output_mode: "layout_preserving"
  timeout: 60
```

**Code**: `src/reserve_automation/utils/llm_whisperer.py`

**Key Points**:
- Mode MUST be "table" for wine tasting cards
- Preserves column alignment using ASCII spacing
- Result path: `result["extraction"]["result_text"]`

### Stage 2: Local LLM (Structured Extraction)

**Purpose**: Parse ASCII table into structured JSON

**Configuration**: `config/default.yaml` (llm.providers section)
```yaml
llm:
  providers:
    lm_studio_vision:
      type: "lm_studio"
      base_url: "http://192.168.86.49:1234/v1"
      model: "llama-3.2-11b-vision-preview"
      default_for: ["structured_extraction", "ocr"]
```

**Code**: `src/reserve_automation/extractors/tasting_extractor.py`
- Method: `_extract_aws_wine_llm_guided()` (lines 249-391)

**Prompt** (lines 286-318):
- Extracts ALL wines from table
- Returns JSON with shared metadata + array of tastings
- Simple, direct instructions
- Emphasizes extracting EVERY row

---

## Testing the Full Pipeline

### End-to-End Extraction Test

Test a complete tasting card image through the full pipeline:

```bash
# Run extraction on a test image
uv run python -c "
import asyncio
from pathlib import Path
from reserve_automation.core.config import Config
from reserve_automation.llm.gateway import LLMGateway
from reserve_automation.extractors.tasting_extractor import TastingExtractor

async def test():
    config = Config.load()
    llm = LLMGateway(config.llm)
    extractor = TastingExtractor(llm, config.extraction)

    result = await extractor.extract_from_image(
        Path('tests/fixtures/extraction/aws_wine_test_001.jpg'),
        template_type='aws_wine'
    )

    print(f'Extracted {len(result.tastings)} wines:')
    for i, tasting in enumerate(result.tastings, 1):
        print(f'{i}. {tasting.bottle_name}')
        print(f'   Scores: App={tasting.wine_appearance}, Aroma={tasting.wine_aroma}')
        print(f'   Nose notes: {tasting.nose_notes}')

asyncio.run(test())
"
```

---

## Testing Individual Stages

### Stage 1: Test LLMWhisperer Output

Extract the ASCII table to see what LLMWhisperer produces:

```bash
# Extract table and save to file
uv run python tests/test_prompt_tuning.py extract \
  --fixture aws_wine_test_001 \
  --output /tmp/llmwhisperer_table.txt

# View the extracted table
cat /tmp/llmwhisperer_table.txt
```

**Expected Output**:
```
                   AWS Wine Evaluation Chart

      mer can Name: Ben      Date: 13 Dec 25
       w ne
       society
            Place: Home      Theme:

+----------------------------------------+-------+-------------------+------------------------------------------+...
| Lions 2023 de SudeiGut Blanc Sec       | Straw 2.5 | green apple yeasty floral 4 | lemon peach Cedar black olive 3.5 |...
```

**Quality Check**:
- ✅ Column alignment preserved (words in correct columns)
- ✅ All wines present (one per row)
- ✅ Metadata extracted (taster, date, place)

### Stage 2: Test LLM Parsing

Test how well the LLM parses the ASCII table:

```bash
# Test with the optimized prompt
uv run python tests/test_prompt_tuning.py test \
  --table-file /tmp/llmwhisperer_table.txt \
  --prompt-file /tmp/test_simple_prompt.txt \
  --fixture aws_wine_test_001
```

**Output Includes**:
- Extracted data for each wine
- Field-by-field comparison with ground truth (✓/✗)
- Overall accuracy percentage

---

## Prompt Testing & Optimization

### Interactive Prompt Testing Tool

The fastest way to iterate on prompts without repeated API calls:

```bash
# Interactive mode - extract once, test many prompts
uv run python tests/test_prompt_tuning.py interactive --fixture aws_wine_test_001
```

**Workflow**:
1. Tool extracts table using LLMWhisperer (one-time, saves API credits)
2. You enter prompts interactively
3. Get immediate feedback with accuracy percentage
4. Iterate rapidly on prompt wording

**Commands**:
- Type your prompt (use `{layout_text}` placeholder)
- Type `table` to see the extracted table again
- Type `quit` to exit

### Batch Prompt Testing

Test a saved prompt file:

```bash
# Test a specific prompt file
uv run python tests/test_prompt_tuning.py test \
  --table-file /tmp/llmwhisperer_table.txt \
  --prompt-file /path/to/your_prompt.txt \
  --fixture aws_wine_test_001
```

### Creating Test Prompts

**CRITICAL**: Prompts must escape curly braces for Python `.format()`:

```python
# WRONG - will cause KeyError
{
  "taster_name": "string"
}

# CORRECT - double the braces
{{
  "taster_name": "string"
}}
```

**Current Best Prompt** (`/tmp/test_simple_prompt.txt`):
```
Extract ALL wines from this tasting table. Return ONLY valid JSON matching this schema:

{{
  "taster_name": "string",
  "tasting_date": "YYYY-MM-DD",
  "place": "string or null",
  "theme": "string or null",
  "tastings": [
    {{
      "bottle_name": "string",
      "beverage_type": "wine",
      "price": "string or null",
      "wine_appearance": float or null,
      "wine_aroma": float or null,
      "wine_taste": float or null,
      "wine_aftertaste": float or null,
      "wine_overall": float or null,
      "nose_notes": ["list", "of", "strings"] or null,
      "palate_notes": ["list", "of", "strings"] or null,
      "finish_notes": ["list", "of", "strings"] or null,
      "overall_notes": "string or null"
    }}
  ]
}}

Extract EVERY wine row from the table.

Table data:
{layout_text}

Return ONLY the JSON object, no markdown, no explanation.
```

**Performance**: 73.9% accuracy (17/23 fields)

### Prompt Design Best Practices

Based on testing, effective prompts:

1. **Start with clear instruction**: "Extract ALL wines"
2. **Show exact JSON schema**: Use concrete example structure
3. **Emphasize completeness**: "Extract EVERY wine row"
4. **Request JSON only**: "Return ONLY the JSON object, no markdown"
5. **Keep it simple**: Shorter, clearer prompts work better
6. **Use multi-wine format**: Share metadata + array of tastings

**What Doesn't Work**:
- ❌ Long, verbose instructions (confuses model)
- ❌ Single-wine schema (only extracts first wine)
- ❌ Complex column-mapping instructions (model ignores them)
- ❌ Asking for markdown code blocks (adds extra text to parse)

---

## Performance Metrics

### Accuracy Calculation

The testing tool calculates field-level accuracy:

```
Total Fields = (Metadata fields) + (Wine fields × Number of wines)
Metadata: taster_name, tasting_date, place, theme (4 fields)
Per Wine: bottle_name, wine_appearance, wine_aroma, wine_taste,
          wine_aftertaste, wine_overall, nose_notes, palate_notes,
          finish_notes, overall_notes (10 fields)

Example (2 wines):
Total = 3 metadata + (10 fields × 2 wines) = 23 fields
Matches = 17
Accuracy = 17/23 = 73.9%
```

### Comparison Logic

Fields match if:
- **Strings**: Case-insensitive, whitespace-trimmed match
- **Numbers**: Within 0.1 tolerance
- **Arrays**: Same items (case-insensitive, sorted)
- **Null handling**: Both null or both non-null

See: `tests/test_prompt_tuning.py:282-294` (`compare_values()`)

### Current Performance (73.9%)

**Correct (17/23)**:
- ✓ All metadata (taster, date, place)
- ✓ All scores (appearance, aroma, taste, aftertaste, overall)
- ✓ Most tasting notes arrays

**Incorrect (6/23)**:
- ✗ Bottle names (OCR errors: "SudeiGut" vs "Suduiraut")
- ✗ Some note words (OCR: "fix" vs "fig", "tanning" vs "tannins")
- ✗ Overall notes (missing spaces/punctuation)

**Key Insight**: Most errors are from LLMWhisperer OCR, not LLM parsing!

---

## Common Issues & Solutions

### Issue: Only One Wine Extracted

**Symptom**: Script extracts first wine but skips others

**Cause**: Prompt uses single-wine schema instead of multi-wine array

**Solution**: Update prompt to use `tastings` array:
```json
{
  "taster_name": "...",
  "tastings": [
    { "bottle_name": "wine 1", ... },
    { "bottle_name": "wine 2", ... }
  ]
}
```

### Issue: No Accuracy Percentage Shown

**Symptom**: See extracted data but no comparison or accuracy

**Cause**: Missing `--fixture` parameter

**Solution**: Always include fixture for ground truth comparison:
```bash
uv run python tests/test_prompt_tuning.py test \
  --table-file /tmp/llmwhisperer_table.txt \
  --prompt-file /tmp/test_simple_prompt.txt \
  --fixture aws_wine_test_001  # ← REQUIRED for accuracy
```

### Issue: KeyError in Prompt Formatting

**Symptom**: `KeyError: '\n  "taster_name"'`

**Cause**: Unescaped curly braces in prompt file

**Solution**: Double all curly braces in JSON examples:
```
# Change { to {{
# Change } to }}
```

### Issue: LLM Returns Prose Instead of JSON

**Symptom**: "Let me know if you'd like this reformatted..."

**Cause**: LLM not understanding it should return ONLY JSON

**Solution**:
1. Make prompt more explicit: "Return ONLY the JSON object, no markdown, no explanation"
2. Use simpler, clearer instructions
3. The testing tool has regex fallback to extract JSON from prose

### Issue: LLMWhisperer Mode Error

**Symptom**: Poor table extraction or API errors

**Cause**: Wrong mode setting

**Solution**: Mode MUST be "table" in config:
```yaml
llm_whisperer:
  mode: "table"  # NOT "form" or "text"
```

### Issue: Column Misalignment

**Symptom**: Tasting notes in wrong categories (nose notes in palate, etc.)

**Cause**: LLMWhisperer layout not preserved, or LLM ignoring spatial info

**Current Status**: 73.9% accuracy - most notes are correct. Remaining errors are OCR mistakes (wrong words) not column errors.

**If This Becomes a Problem Again**:
1. Verify LLMWhisperer output preserves columns
2. Add explicit column markers to prompt
3. Try different LLM models

---

## Testing Different LLM Models

### Switching LLM Models

Update `config/user.yaml`:

```yaml
llm:
  providers:
    lm_studio_vision:
      type: "lm_studio"
      base_url: "http://192.168.86.49:1234/v1"
      model: "YOUR-MODEL-NAME-HERE"  # ← Change this
      default_for: ["structured_extraction", "ocr"]
```

Then test with the same prompts:

```bash
# Test new model with same prompt
uv run python tests/test_prompt_tuning.py test \
  --table-file /tmp/llmwhisperer_table.txt \
  --prompt-file /tmp/test_simple_prompt.txt \
  --fixture aws_wine_test_001
```

### Model Comparison Workflow

1. **Baseline with current model**:
   ```bash
   uv run python tests/test_prompt_tuning.py test \
     --table-file /tmp/llmwhisperer_table.txt \
     --prompt-file /tmp/test_simple_prompt.txt \
     --fixture aws_wine_test_001 > /tmp/model_a_results.txt
   ```

2. **Change model in config**

3. **Test with new model**:
   ```bash
   uv run python tests/test_prompt_tuning.py test \
     --table-file /tmp/llmwhisperer_table.txt \
     --prompt-file /tmp/test_simple_prompt.txt \
     --fixture aws_wine_test_001 > /tmp/model_b_results.txt
   ```

4. **Compare accuracy**:
   ```bash
   grep "OVERALL ACCURACY" /tmp/model_a_results.txt
   grep "OVERALL ACCURACY" /tmp/model_b_results.txt
   ```

### Recommended Models to Test

Vision models that support structured extraction:
- LLaVA variants (current: llama-3.2-11b-vision)
- Qwen-VL
- Idefics2
- CogVLM
- GPT-4V (via OpenAI API)
- Claude 3+ (via Anthropic API)

**Note**: Current accuracy (73.9%) is limited more by OCR errors than LLM capability. Different models may not improve much until OCR is improved.

---

## Ground Truth Fixtures

### Creating New Test Fixtures

Test fixtures live in `tests/fixtures/extraction/`

**Structure**:
```
tests/fixtures/extraction/
├── aws_wine_test_001.jpg         # Image file
└── aws_wine_test_001.json        # Ground truth
```

**Ground Truth Format**:
```json
{
  "test_name": "Descriptive name",
  "image_file": "aws_wine_test_001.jpg",
  "template_type": "aws_wine",
  "notes": "Description of what this tests",
  "expected_output": {
    "taster_name": "Ben",
    "tasting_date": "2025-12-13",
    "place": "Home",
    "theme": null,
    "tastings": [
      {
        "row": 1,
        "bottle_name": "Exact bottle name as written",
        "price": null,
        "wine_appearance": 2.5,
        "wine_aroma": 4.0,
        "wine_taste": 3.5,
        "wine_aftertaste": 1.5,
        "wine_overall": 1.0,
        "nose_notes": ["green apple", "yeasty", "floral"],
        "palate_notes": ["lemon", "peach", "cedar", "black olive"],
        "finish_notes": ["mineral", "oak", "bit thin"],
        "overall_notes": "meh, low acid"
      }
    ]
  },
  "common_errors": [
    "Common mistakes to watch for"
  ]
}
```

### Testing With Your Own Images

1. **Take photo of tasting card**
2. **Create fixture directory**:
   ```bash
   mkdir -p tests/fixtures/extraction
   cp your_card.jpg tests/fixtures/extraction/my_test_001.jpg
   ```

3. **Create ground truth JSON** (manually transcribe the card)

4. **Test extraction**:
   ```bash
   uv run python tests/test_prompt_tuning.py extract --fixture my_test_001
   uv run python tests/test_prompt_tuning.py test \
     --table-file /tmp/llmwhisperer_table.txt \
     --prompt-file /tmp/test_simple_prompt.txt \
     --fixture my_test_001
   ```

---

## File Reference

### Key Files

**Configuration**:
- `config/default.yaml` - Default config (LLMWhisperer, LLM settings)
- `config/user.yaml` - User overrides (API keys, model selection)

**Core Extraction**:
- `src/reserve_automation/extractors/tasting_extractor.py` - Main extraction logic
- `src/reserve_automation/utils/llm_whisperer.py` - LLMWhisperer client
- `src/reserve_automation/llm/gateway.py` - LLM provider abstraction

**Testing Tools**:
- `tests/test_prompt_tuning.py` - Interactive prompt testing tool
- `tests/fixtures/extraction/` - Test images and ground truth

**Prompts**:
- `/tmp/test_simple_prompt.txt` - Current best prompt (73.9% accuracy)
- `/tmp/multi_wine_prompt.txt` - Verbose version (same accuracy)

### Important Code Locations

**LLMWhisperer Integration**:
- `src/reserve_automation/utils/llm_whisperer.py:30-50` - `extract_layout_text()`
- Result extraction: line 47-49

**Extraction Prompt**:
- `src/reserve_automation/extractors/tasting_extractor.py:286-318` - Prompt template
- Parsing: lines 331-355

**Testing Tool**:
- `tests/test_prompt_tuning.py:32-68` - `extract_table()`
- `tests/test_prompt_tuning.py:71-279` - `test_prompt()` with comparison
- `tests/test_prompt_tuning.py:282-294` - `compare_values()` accuracy logic

---

## Quick Reference

### Common Commands

```bash
# Extract table from image
uv run python tests/test_prompt_tuning.py extract --fixture aws_wine_test_001

# Test a prompt file
uv run python tests/test_prompt_tuning.py test \
  --table-file /tmp/llmwhisperer_table.txt \
  --prompt-file /tmp/test_simple_prompt.txt \
  --fixture aws_wine_test_001

# Interactive testing
uv run python tests/test_prompt_tuning.py interactive --fixture aws_wine_test_001

# View extracted table
cat /tmp/llmwhisperer_table.txt
```

### Accuracy Targets

- ✅ **Current**: 73.9% (17/23 fields)
- 🎯 **Target**: 90%+
- 📊 **Baseline (before LLMWhisperer)**: 25-32%

### What Works

✅ LLMWhisperer in "table" mode (preserves layout)
✅ Simple, direct prompts
✅ Multi-wine array format
✅ Local vision LLM (llama-3.2-11b-vision)
✅ Incremental testing with immediate feedback

### What Doesn't Work

❌ Direct vision-based extraction (column confusion)
❌ Tesseract OCR (can't read handwriting)
❌ Verbose, complex prompts (confuse model)
❌ Single-wine schema (skips rows)
❌ LLMWhisperer in "form" or "text" mode (wrong structure)

---

## Next Steps for Improvement

1. **Improve OCR accuracy**: Current errors are mostly OCR mistakes
   - Try different LLMWhisperer settings
   - Preprocessing (contrast, rotation, denoising)
   - Alternative OCR services

2. **Prompt refinement**: Fine-tune wording
   - A/B test variations
   - Add examples to prompt
   - Specify common error cases

3. **Post-processing**: Validate and correct output
   - Spell-check wine names against database
   - Validate score ranges
   - Auto-correct common OCR mistakes ("0" vs "O")

4. **More test fixtures**: Expand test coverage
   - Different handwriting styles
   - Partial fill-outs
   - Edge cases (smudges, rotations)

Current performance is good enough for production use with human review. The 26% error rate is mostly OCR issues (wrong words) rather than structural problems (wrong columns, missing wines).
