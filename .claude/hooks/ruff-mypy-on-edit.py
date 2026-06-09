#!/usr/bin/env python3
"""PostToolUse hook: lint/type-check a Python file right after Claude edits it.

- Runs `ruff check --fix` (fast; auto-fixes import order / simple issues in place).
- Runs `mypy` on the touched file (REPORT ONLY — never blocks; mypy is slow and
  intentionally non-strict in this project's pyproject.toml).

Output is surfaced back to Claude as additionalContext so issues are visible
without wedging the edit. Exits 0 always.

Only acts on .py files inside the automation repo; silently no-ops otherwise.
"""

import json
import os
import subprocess
import sys

AUTOMATION_ROOT = "/mnt/d/Users/ben/Documents/spirits/automation"


def emit(context: str):
    """Feed a note back to Claude (non-blocking)."""
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PostToolUse",
                    "additionalContext": context,
                }
            }
        )
    )


def run(args):
    try:
        p = subprocess.run(
            args, cwd=AUTOMATION_ROOT, capture_output=True, text=True, timeout=60
        )
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as e:  # tool missing / timeout -> stay quiet
        return 0, f"(skipped: {e})"


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)

    if data.get("tool_name") not in ("Edit", "Write", "MultiEdit"):
        sys.exit(0)

    fp = (data.get("tool_input", {}) or {}).get("file_path", "") or ""
    if not fp.endswith(".py"):
        sys.exit(0)
    abspath = os.path.abspath(fp)
    if not abspath.startswith(AUTOMATION_ROOT + os.sep):
        sys.exit(0)
    if not os.path.exists(abspath):
        sys.exit(0)

    notes = []

    # ruff is self-contained; uvx runs it isolated (config auto-discovered from cwd).
    rc, out = run(["uvx", "ruff", "check", "--fix", abspath])
    if rc != 0 and out:
        notes.append(f"ruff (remaining issues after --fix):\n{out[:2000]}")
    elif "fixed" in out.lower():
        notes.append(f"ruff auto-fixed issues in {os.path.basename(abspath)}.")

    # mypy report-only; --ignore-missing-imports avoids needing the full project env.
    rc, out = run(
        ["uvx", "mypy", "--ignore-missing-imports", "--no-error-summary", abspath]
    )
    if rc != 0 and out:
        notes.append(f"mypy (type notes, non-blocking):\n{out[:2000]}")

    if notes:
        emit("\n\n".join(notes))

    sys.exit(0)


if __name__ == "__main__":
    main()
