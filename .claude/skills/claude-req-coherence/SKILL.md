---
name: claude-req-coherence
description: Check #CLAUDE_REQ cross-file coherence chains before/after editing a model field. Use when adding or modifying a field on a core model (BottleMetadata, Cocktail, Ingredient, etc.) to confirm the field is propagated through every file in its documented chain (SQLAlchemy model, converter, templates, vault_reader, routes) and to catch the file you forgot. Turns the "~7-file chain" checklist into a verifiable matrix.
argument-hint: "[field name, e.g. 'abv' or 'variety'] — or no args to list all chains"
allowed-tools: Bash(python3 *) Read Grep Glob
---

# #CLAUDE_REQ Coherence Check

The codebase documents cross-file coherence as `#CLAUDE_REQ:` comment blocks.
Adding a model field means touching every file in that field's chain (model →
DB model → converter → templates → vault_reader → routes). This skill verifies
the propagation instead of trusting the checklist was followed.

## Step 1 — Run the checker

For a specific field:

```!
python3 /mnt/d/Users/ben/Documents/spirits/automation/.claude/skills/claude-req-coherence/check_coherence.py $ARGUMENTS
```

With no argument it lists every chain and which referenced files resolve on disk.
With a field name it prints a presence matrix for the **field-definition chains**
(anchored in `core/` models + the obsidian `_prepare_context` chain) whose anchor
mentions that field. Exit `0` = present everywhere resolvable; `1` = a gap.

## Step 2 — Interpret the matrix

| Marker | Meaning |
|---|---|
| `✓` | The field token appears in this file. |
| `✗ MISSING` | The field does **not** appear — likely an unpropagated edit. **Verify.** |
| `⌂ manual` | A vault file (`the-reserve/Cellar/...`) — out-of-repo on dev. Confirm on PROD. |

A `✗ MISSING` is a **signal, not a verdict** — the checker matches on the field
name as a word. Confirm by reading the file:

- If the field genuinely isn't wired in there yet → that's the gap to fix. Add it,
  following the same shape the other fields in that file use (column, converter
  mapping, template variable, field_name_map entry, etc.).
- If the file handles the field under a different name or mechanism (e.g. a
  `list[str]` field serialized differently, or covered by a generic loop) → it's a
  false positive; note it and move on.

## Step 3 — Re-run after fixing

Re-run Step 1 until the relevant chain is `✓` across all resolvable files (and you
have manually confirmed any `⌂` vault references where applicable).

## Notes

- Read-only — never edits code.
- Structural / dependency `#CLAUDE_REQ` blocks (vault layout, repo wiring,
  autocomplete sync) are intentionally excluded from field mode; use no-arg list
  mode to see them.
- Vault (`the-reserve`) files are read-only references on dev and are committed
  from PROD only — never edit them here.
