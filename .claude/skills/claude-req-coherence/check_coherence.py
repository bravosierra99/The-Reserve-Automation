#!/usr/bin/env python3
"""#CLAUDE_REQ coherence checker.

The codebase documents cross-file coherence chains as `#CLAUDE_REQ:` comment
blocks (e.g. "adding a BottleMetadata field must also touch db/models/bottle.py,
db/converters.py, templates, vault_reader.py..."). This tool parses those chains
and, for a given field, reports which files in the chain actually mention the
field — turning "hope the checklist was followed" into a verifiable matrix.

Usage:
    check_coherence.py                 # list every #CLAUDE_REQ chain + file status
    check_coherence.py <field_name>    # show field-presence matrix for relevant chains

Read-only. Exit 1 if a field is given and a chain has gaps; else 0.
"""

import os
import re
import sys

SPIRITS_ROOT = "/mnt/d/Users/ben/Documents/spirits"
AUTOMATION_ROOT = os.path.join(SPIRITS_ROOT, "automation")
PKG_ROOT = os.path.join(AUTOMATION_ROOT, "src/reserve_automation")

# Path tokens inside #CLAUDE_REQ prose, e.g. "db/models/bottle.py" or
# "templates/cocktail.md.j2" or "utils/vault_reader.py".
PATH_TOKEN = re.compile(r"([A-Za-z0-9_][\w./-]*\.(?:py|j2))")
VAULT_REF = re.compile(r"the-reserve/Cellar/[\w/ .*-]+")

# A #CLAUDE_REQ block is a *field-propagation* chain (vs a structural/dependency
# chain) when its header is about fields matching across files. Only these are
# meaningful for a field-presence check.
FIELD_CHAIN = re.compile(
    r"field.*(must match|coherence)|(adding|modifying).*field", re.IGNORECASE
)


def resolve(token):
    """Try to map a #CLAUDE_REQ path token to a real file on disk."""
    token = token.lstrip("./")
    candidates = [
        os.path.join(PKG_ROOT, token),
        os.path.join(AUTOMATION_ROOT, token),
        os.path.join(AUTOMATION_ROOT, token.replace("automation/", "", 1)),
        os.path.join(SPIRITS_ROOT, token),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def find_chains():
    """Walk the package, return list of (anchor_file, [raw_lines])."""
    chains = []
    for dirpath, _, files in os.walk(PKG_ROOT):
        for fn in files:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            with open(path) as f:
                lines = f.readlines()
            block = []
            for ln in lines:
                if "CLAUDE_REQ" in ln:
                    block.append(ln.strip())
                elif block:
                    # block ended
                    if len(block) >= 1:
                        chains.append((path, block))
                    block = []
            if block:
                chains.append((path, block))
    return chains


def chain_files(block):
    """Extract resolvable code/template files + vault refs from a block."""
    text = "\n".join(block)
    resolved, missing, vault = [], [], []
    for tok in PATH_TOKEN.findall(text):
        r = resolve(tok)
        if r:
            resolved.append(r)
        else:
            missing.append(tok)
    for v in VAULT_REF.findall(text):
        vault.append(v.strip())
    # De-dup, preserve order
    return list(dict.fromkeys(resolved)), list(dict.fromkeys(missing)), list(
        dict.fromkeys(vault)
    )


def has_field(path, field):
    try:
        with open(path) as f:
            return re.search(rf"\b{re.escape(field)}\b", f.read()) is not None
    except Exception:
        return False


def rel(p):
    return os.path.relpath(p, SPIRITS_ROOT)


def main():
    field = sys.argv[1] if len(sys.argv) > 1 else None
    chains = find_chains()

    if not field:
        print(f"Found {len(chains)} #CLAUDE_REQ chain(s):\n")
        for anchor, block in chains:
            resolved, missing, vault = chain_files(block)
            print(f"● {rel(anchor)}")
            print(f"    {block[0]}")
            for r in resolved:
                print(f"      ✓ resolves: {rel(r)}")
            for m in missing:
                print(f"      ? unresolved token: {m}")
            for v in vault:
                print(f"      ⌂ vault (out-of-repo on dev): {v}")
            print()
        print("Tip: re-run with a field name to get a presence matrix, e.g.")
        print("  check_coherence.py abv")
        sys.exit(0)

    # Field mode: only consider FIELD-propagation chains whose anchor mentions
    # the field (structural/dependency chains are excluded — a field's absence
    # there is not a coherence gap).
    relevant = [
        (a, b)
        for a, b in chains
        if b and FIELD_CHAIN.search(b[0]) and has_field(a, field)
    ]
    if not relevant:
        print(f"No field-coherence #CLAUDE_REQ chain's anchor mentions '{field}'.")
        print("Either the field name differs, or it isn't a model field governed")
        print("by a coherence chain. Run with no args to list all chains.")
        sys.exit(0)

    gaps = False
    print(f"Coherence matrix for field '{field}':\n")
    for anchor, block in relevant:
        resolved, _, vault = chain_files(block)
        print(f"● chain anchored in {rel(anchor)}")
        files = [anchor] + [r for r in resolved if r != anchor]
        for fpath in files:
            mark = "✓" if has_field(fpath, field) else "✗ MISSING"
            print(f"    {mark:>10}  {rel(fpath)}")
            if mark.startswith("✗"):
                gaps = True
        for v in vault:
            print(f"    {'⌂ manual':>10}  {v}  (verify in vault on PROD)")
        print()

    if gaps:
        print("❌ Field is missing from one or more chain files — coherence gap.")
        sys.exit(1)
    print("✅ Field present in all resolvable chain files (verify vault refs manually).")
    sys.exit(0)


if __name__ == "__main__":
    main()
