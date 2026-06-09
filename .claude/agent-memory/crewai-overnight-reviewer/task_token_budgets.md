---
name: Task Token Budgets
description: Measured token counts per task for qwen3.5-9b with 120k warn threshold
type: project
---

Token estimates from `_estimate_tokens()` (chars/3, conservative). LM Studio is configured for 150k context; tasks.py warns at 120k to leave headroom for system prompt + backstory + response.

**Why:** Knowing actual usage prevents under- or over-budget tasks. The pipeline is fragile near the context limit — context-overflow errors are non-retryable.

**How to apply:** When loading new files into a task, target ≤ 30k tokens per task. Both bottle-extraction-review tasks land well under budget:

- Field-Placement Auditor (5 files: core/models.py, llm/prompts/extraction.py, llm/response_parser.py, llm/tool_executor.py, web/routes/bottles/extraction.py): ~24k tokens
- Missing-Data Auditor (7 files: above plus extractors/bottle.py, extractors/image_extractor.py, parsers/image.py, parsers/detector.py, web/services/extraction_service.py, minus tool_executor and routes): ~30k tokens
- Synthesizer (only reads completed findings files): ~1k tokens

`response_parser.py` is 508 lines; the default `MAX_LINES_PER_FILE=600` cap (raised from 500) avoids truncating its sanitization tail (lines ~462-505), which is exactly the field-coercion logic the field-placement auditor needs.

If adding files for a future review, run the dry-validation snippet at the bottom of this note to confirm budget:

```python
from tasks import field_placement_task, _estimate_tokens
t = field_placement_task()
print(f'{len(t.description):,} chars, ~{_estimate_tokens(t.description):,} tokens')
```
