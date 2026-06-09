---
name: Spirits-Crew Architecture
description: Load-bearing constraints for the spirits-crew at /spirits/spirits-crew/ — do not change without re-validating
type: project
---

The spirits-crew at `/mnt/d/Users/ben/Documents/spirits/spirits-crew/` runs overnight reviews of the automation codebase using a local LM Studio model. The architecture is deliberately stripped down because qwen3.5-9b cannot reliably handle CrewAI's ReAct tool loop.

**Why:** Earlier runs with tools attached caused two failure modes: (1) the model hallucinated continuations of preloaded source files because it interpreted them as code to extend, and (2) the model dropped the "Final Answer:" prefix CrewAI's parser requires. Removing tools and preloading file contents into the task description bypasses both.

**How to apply:** When designing or refining tasks for this crew:

- Model: `openai/qwen/qwen3.5-9b` via LM Studio at `localhost:1234`. Settings hard-coded in `agents.py` make_llm(): temperature=0.2, max_tokens=16000, timeout=1200.
- No tools. `tools=[]` on every Agent. No DirectoryReadTool, no FileReadTool.
- File contents are pre-loaded via `_load_file_block()` between `===BEGIN FILE: <path>===` / `===END FILE===` delimiters with line numbers. Non-code framing breaks the code-continuation attractor.
- `max_iter=3`, `allow_delegation=False`, `memory=False`.
- `Process.sequential` only.
- Per-task checkpoint via `_output_is_valid()` in main.py — re-running skips completed tasks unless `--fresh` is passed.
- Shape guard requires ≥ 3 `## Finding N:` headers (configurable per task via `header_pattern` in TASK_DEFS).
- Single retry on shape-guard failure or transient exception. Context-overflow errors fail fast — no retry.
- Output captured by `_extract_raw_output()` which pulls `result.tasks_output[0].raw`. CrewAI's `output_file=` parameter is unreliable with this LLM, so main.py writes the raw output manually.
- Raw output always persisted to a `.last_raw.txt` sibling regardless of validity, for post-mortems.

When adding a new task: register it in `main.py` TASK_DEFS as `(label, factory, output_filename, header_pattern)`. The synthesizer is detected by label match `"Crew Synthesizer"` and uses a different validity check (`# Reserve Automation` heading present).
