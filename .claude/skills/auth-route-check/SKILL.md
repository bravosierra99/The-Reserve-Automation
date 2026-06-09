---
name: auth-route-check
description: Verify every FastAPI route is auth-protected and every permission is defined. Use after adding or editing any route in web/routes/, before committing auth-surface changes, or any time you need to confirm the project's #1 rule — "every route MUST have require() + an entry in config/auth.yaml" — still holds. Catches unprotected endpoints and undefined permission names.
argument-hint: "[optional: a route file or feature, e.g. 'cocktails' or 'bottles/save.py']"
allowed-tools: Bash(python3 *) Read Grep Glob
---

# Auth Route Check

You are verifying the project's most important rule (CLAUDE.md):

> **Every route MUST be guarded by `require("<permission>")`** — at the router
> level (`APIRouter(dependencies=[Depends(require(...))])`) or per-decorator —
> **and every referenced permission MUST exist in `config/auth.yaml`.**

## Step 1 — Run the analyzer

```!
python3 /mnt/d/Users/ben/Documents/spirits/automation/.claude/skills/auth-route-check/check_auth_routes.py
```

This statically scans `src/reserve_automation/web/routes/**` (skipping
`__init__.py` aggregators and unmounted `*_deprecated.py` files) and reports:

- **UNPROTECTED routes** — a decorated route with no `require()` in scope that
  is not on the public allowlist (`/health`, `/`, `/me`).
- **UNDEFINED permissions** — a `require("x")` whose `"x"` is missing from the
  `permissions:` block of `config/auth.yaml`.

Exit code is `0` when clean, `1` when anything is flagged.

## Step 2 — Triage each finding

For every **UNPROTECTED** route, decide:

| Situation | Action |
|---|---|
| Route should be protected | Add `dependencies=[Depends(require("<perm>"))]` to the decorator, or confirm the router-level dependency covers it. Pick the permission that matches the existing convention for that resource (`<resource>.<action>`). |
| Route is genuinely public | Confirm it safely handles anonymous callers (like `/me`), then add its path to `PUBLIC_PATHS` in the analyzer with a one-line justification comment. |

For every **UNDEFINED** permission:

- If it's a typo, fix the `require()` string to match `auth.yaml`.
- If it's a new permission, add it to the `permissions:` block in
  `config/auth.yaml` with the correct role list (`admin` / `family` / `guest`),
  following the `<resource>.<action>: [roles]` convention already there.

## Step 3 — Re-run until clean

Re-run Step 1. Do not consider the auth surface sound until the analyzer prints
`✅ All routes are auth-protected and all permissions are defined.` and exits `0`.

## Notes

- The analyzer is **read-only** — it never edits code. You make the fixes.
- `require` is defined in `web/auth/dependencies.py`; permissions live in
  `config/auth.yaml` (`permissions:` block).
- If `$ARGUMENTS` names a specific area, focus your triage there, but always run
  the full scan — an unprotected route anywhere is the failure this skill exists
  to catch.
