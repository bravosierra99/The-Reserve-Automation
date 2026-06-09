#!/usr/bin/env python3
"""Static auth-coverage checker for FastAPI routes.

Enforces the project's #1 rule (CLAUDE.md): every route MUST be guarded by
`require("<permission>")` — either at the router level
(`APIRouter(dependencies=[Depends(require(...))])`) or per-decorator
(`@router.get(..., dependencies=[Depends(require(...))])`) — and every
permission referenced MUST exist in `config/auth.yaml`.

Reports two classes of problem:
  1. UNPROTECTED routes (no require() in scope, not on the public allowlist).
  2. UNDEFINED permissions (require("x") where "x" is missing from auth.yaml).

Exit code: 0 if clean, 1 if any problem found. Read-only.
"""

import os
import re
import sys

ROOT = "/mnt/d/Users/ben/Documents/spirits/automation"
ROUTES_DIR = os.path.join(ROOT, "src/reserve_automation/web/routes")
AUTH_YAML = os.path.join(ROOT, "config/auth.yaml")

# Routes that are intentionally public (no auth). Match on the path literal.
#   /health  - liveness probe (details endpoint IS protected)
#   /me      - identity probe; returns {authenticated: false} for anonymous callers
PUBLIC_PATHS = {"/health", "/", "/me"}

ROUTE_DECO = re.compile(r"@router\.(get|post|put|delete|patch|head|options)\(")
REQUIRE_PERM = re.compile(r"require\(\s*[\"']([^\"']+)[\"']")
PERM_KEY = re.compile(r"^\s{2}([a-z_][a-zA-Z0-9_.]*):\s*\[")


def load_defined_permissions():
    perms = set()
    in_block = False
    with open(AUTH_YAML) as f:
        for line in f:
            if re.match(r"^permissions:\s*$", line):
                in_block = True
                continue
            if in_block:
                if re.match(r"^\S", line):  # dedent to a new top-level key
                    break
                m = PERM_KEY.match(line)
                if m:
                    perms.add(m.group(1))
    return perms


def router_level_perms(text):
    """Permissions applied at `router = APIRouter(...)` level (cover all routes)."""
    m = re.search(r"=\s*APIRouter\(", text)
    if not m:
        return set()
    # Scan to the matching close paren.
    i = m.end() - 1
    depth = 0
    start = i
    while i < len(text):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                break
        i += 1
    block = text[start : i + 1]
    return set(REQUIRE_PERM.findall(block))


def analyze_file(path):
    """Return (routes, used_perms) where routes = list of dicts."""
    with open(path) as f:
        text = f.read()
    lines = text.splitlines()

    rl_perms = router_level_perms(text)
    routes = []
    used = set(rl_perms)

    n = len(lines)
    for idx, line in enumerate(lines):
        dm = ROUTE_DECO.search(line)
        if not dm:
            continue
        method = dm.group(1)
        # Accumulate decorator text from here until the handler `def`/`async def`.
        chunk = []
        j = idx
        while j < n and not re.match(r"\s*(async\s+)?def\s", lines[j]):
            chunk.append(lines[j])
            j += 1
        chunk_text = "\n".join(chunk)
        # Extract the route path (first string arg of the decorator).
        pm = re.search(r"@router\.\w+\(\s*[\"']([^\"']*)[\"']", chunk_text)
        route_path = pm.group(1) if pm else "?"
        deco_perms = set(REQUIRE_PERM.findall(chunk_text))
        used |= deco_perms
        protected = bool(rl_perms) or bool(deco_perms)
        routes.append(
            {
                "file": os.path.relpath(path, ROOT),
                "line": idx + 1,
                "method": method.upper(),
                "path": route_path,
                "protected": protected,
                "public_ok": route_path in PUBLIC_PATHS,
            }
        )
    return routes, used


def main():
    defined = load_defined_permissions()
    all_routes = []
    all_used = set()

    for dirpath, _, files in os.walk(ROUTES_DIR):
        for fn in files:
            # Skip __init__ aggregators and *_deprecated.py routers (not mounted).
            if fn.endswith(".py") and fn != "__init__.py" and not fn.endswith(
                "_deprecated.py"
            ):
                r, u = analyze_file(os.path.join(dirpath, fn))
                all_routes.extend(r)
                all_used |= u

    unprotected = [
        r for r in all_routes if not r["protected"] and not r["public_ok"]
    ]
    undefined = sorted(p for p in all_used if p not in defined)

    total = len(all_routes)
    protected = sum(1 for r in all_routes if r["protected"])
    print(f"Scanned {total} routes across {ROUTES_DIR.split('routes')[-1] or 'routes'}")
    print(f"  protected: {protected}")
    print(f"  public (allowlisted): {sum(1 for r in all_routes if r['public_ok'])}")
    print(f"  permissions defined in auth.yaml: {len(defined)}")
    print(f"  permissions referenced in code: {len(all_used)}")
    print()

    ok = True
    if unprotected:
        ok = False
        print(f"❌ UNPROTECTED routes ({len(unprotected)}):")
        for r in unprotected:
            print(f"   {r['file']}:{r['line']}  {r['method']} {r['path']}")
        print()
    if undefined:
        ok = False
        print(f"❌ require() permissions NOT defined in auth.yaml ({len(undefined)}):")
        for p in undefined:
            print(f"   {p}")
        print()

    if ok:
        print("✅ All routes are auth-protected and all permissions are defined.")
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
