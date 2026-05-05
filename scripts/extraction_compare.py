"""
Compare wine bottle extraction (current code) vs enrichment results.
Also shows which fields the OLD code would have missed (fields newly added by
the crew-recommended changes: age_statement, proof, vineyard, style).

Usage (from automation/):
    uv run python scripts/extraction_compare.py

Requires LM Studio running at the URL configured in config/user.yaml.
"""
import asyncio
import json
import subprocess
import sys
import tempfile
from pathlib import Path

WINE_FIXTURES = [
    Path("tests/fixtures/bottles/wine_001.jpg"),
    Path("tests/fixtures/bottles/wine_002.jpg"),
    Path("tests/fixtures/bottles/wine_003.jpg"),
    Path("tests/fixtures/bottles/wine_004.jpg"),
    Path("tests/fixtures/vault_bottles/Caymus Vineyards - 1858 Cabernet Sauvignon - 2021/labels/label.jpg"),
]

COMPARE_FIELDS = [
    "producer", "name", "year", "beverage_type", "country", "region",
    "variety", "vineyard", "style", "abv", "proof", "age_statement",
]

# Fields added by the crew fix — used to show before/after delta
NEW_FIELDS = {"age_statement", "proof", "vineyard", "style"}


def run_extract(image_path: Path, out_json: Path) -> dict:
    result = subprocess.run(
        ["uv", "run", "reserve-automation", "extract", str(image_path),
         "--type", "image", "--beverage", "auto", "--no-review",
         "--output", str(out_json)],
        capture_output=True, text=True, timeout=300,
    )
    if out_json.exists():
        data = json.loads(out_json.read_text())
        # CLI returns {metadata: {...}, bottles: [...]}
        if isinstance(data, dict) and "bottles" in data:
            bottles = data["bottles"]
            return bottles[0] if bottles else {"_error": "empty extraction (no bottles)"}
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
    return {"_error": result.stderr[-500:] if result.stderr else "no output"}


def run_lookup(extraction_json: Path, out_json: Path) -> dict:
    result = subprocess.run(
        ["uv", "run", "reserve-automation", "lookup", str(extraction_json),
         "--output", str(out_json)],
        capture_output=True, text=True, timeout=300,
    )
    if out_json.exists():
        data = json.loads(out_json.read_text())
        if isinstance(data, dict) and "bottles" in data:
            bottles = data["bottles"]
            return bottles[0] if bottles else {}
        if isinstance(data, list) and data:
            return data[0]
        if isinstance(data, dict):
            return data
    return {"_error": result.stderr[-500:] if result.stderr else "no output"}


def fmt(val) -> str:
    if val is None or val == "" or val == []:
        return "—"
    return str(val)


def match(ext_val, enr_val) -> str:
    e, n = fmt(ext_val).lower(), fmt(enr_val).lower()
    if e == "—" and n == "—":
        return ""
    if e == "—":
        return "✗ missing"
    if n == "—":
        return "← extracted only"
    if e == n:
        return "✓"
    if e in n or n in e:
        return "~ close"
    return "✗ differs"


def main():
    all_results = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        for fixture in WINE_FIXTURES:
            if not fixture.exists():
                print(f"SKIP (not found): {fixture}", file=sys.stderr)
                continue

            label = fixture.name if fixture.name != "label.jpg" else fixture.parts[-2]
            print(f"\n{'='*60}", file=sys.stderr)
            print(f"Processing: {label}", file=sys.stderr)

            ext_out = tmp / "extracted.json"
            enr_out = tmp / "enriched.json"
            for f in [ext_out, enr_out]:
                if f.exists():
                    f.unlink()

            extracted = run_extract(fixture, ext_out)
            if extracted.get("_error"):
                print(f"  Extraction failed: {extracted['_error'][:200]}", file=sys.stderr)
                all_results[label] = {"extracted": extracted, "enriched": {}}
                continue

            print(f"  Extracted: {extracted.get('producer','?')} / {extracted.get('name','?')}", file=sys.stderr)

            enriched = {}
            if ext_out.exists():
                enriched = run_lookup(ext_out, enr_out)
                if enriched.get("_error"):
                    print(f"  Enrichment failed: {enriched['_error'][:200]}", file=sys.stderr)
                    enriched = {}
                else:
                    print(f"  Enriched:  {enriched.get('producer','?')} / {enriched.get('name','?')}", file=sys.stderr)

            all_results[label] = {"extracted": extracted, "enriched": enriched}

    # Save raw JSON
    out = Path("scripts/extraction_compare_results.json")
    out.write_text(json.dumps(all_results, indent=2, default=str))
    print(f"\nRaw results: {out}", file=sys.stderr)

    # Markdown report
    print("\n# Wine bottle extraction vs enrichment comparison\n")
    print(f"Fields marked with `*` are **new** in this version (previously always null): "
          f"{', '.join(sorted(NEW_FIELDS))}\n")

    for label, data in all_results.items():
        ext = data["extracted"]
        enr = data["enriched"]
        print(f"## {label}\n")

        if ext.get("_error"):
            print(f"**Extraction error**: `{ext['_error'][:300]}`\n")
            continue

        print(f"| Field | Extracted (new) | Enriched | Match |")
        print(f"|-------|-----------------|----------|-------|")
        rows_printed = 0
        for field in COMPARE_FIELDS:
            ev = fmt(ext.get(field))
            nv = fmt(enr.get(field)) if enr else "—"
            mark = match(ext.get(field), enr.get(field) if enr else None)
            if not mark:
                continue
            flag = " `*`" if field in NEW_FIELDS else ""
            print(f"| {field}{flag} | {ev} | {nv} | {mark} |")
            rows_printed += 1
        if rows_printed == 0:
            print("| (all fields empty) | — | — | |")
        print()

    # Summary: before vs after delta
    print("## Before/after delta (fields added by crew fix)\n")
    print("| Image | age_statement | proof | vineyard | style |")
    print("|-------|--------------|-------|----------|-------|")
    for label, data in all_results.items():
        ext = data["extracted"]
        if ext.get("_error"):
            print(f"| {label} | error | error | error | error |")
            continue
        row = [label]
        for f in ["age_statement", "proof", "vineyard", "style"]:
            row.append(fmt(ext.get(f)))
        print("| " + " | ".join(row) + " |")


if __name__ == "__main__":
    main()
