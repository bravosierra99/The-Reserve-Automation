"""Cross-reference annotations against run.json for a given auto-crop eval run.

Outputs:
  - Overall category breakdown
  - Per-detector quality breakdown (text vs cv vs none)
  - Worst offenders grouped by failure mode
  - Heuristic patterns (input size correlation with failure, etc.)

Usage:
    uv run python scripts/analyze_crop_eval.py <run-dir>
    uv run python scripts/analyze_crop_eval.py data/eval/auto-crop/20260520-204429
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Annotation categories sorted from best to worst.
GOOD = {"perfect", "acceptable"}
BAD = {"too_tight", "too_loose", "wrong_region", "failed"}
ORDER = ["perfect", "acceptable", "too_tight", "too_loose", "wrong_region", "failed"]


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2

    run_dir = Path(sys.argv[1])
    run_json = run_dir / "run.json"
    annot_files = sorted(run_dir.glob("annotations-*.json"))
    if not run_json.exists():
        print(f"ERROR: {run_json} not found", file=sys.stderr)
        return 1
    if not annot_files:
        print(f"ERROR: no annotations-*.json in {run_dir}", file=sys.stderr)
        return 1

    annot_path = annot_files[-1]
    run = json.loads(run_json.read_text())
    annot = json.loads(annot_path.read_text())
    annotations: dict[str, str] = annot["annotations"]

    # Index run results by bottle_id
    results_by_id = {r["bottle_id"]: r for r in run["results"]}
    total = len(annotations)

    # --- Overall breakdown ----
    cat_counts = Counter(annotations.values())
    good_count = sum(cat_counts.get(c, 0) for c in GOOD)
    bad_count = sum(cat_counts.get(c, 0) for c in BAD)

    print(f"# Auto-crop eval — {run['run_id']}")
    print(f"  Annotations:  {annot_path.name}")
    print(f"  Total bottles annotated: {total}")
    print()

    print("## Overall quality")
    print(f"  acceptable (perfect + acceptable): {good_count}/{total}  ({good_count*100/total:.0f}%)")
    print(f"  failure modes:                     {bad_count}/{total}  ({bad_count*100/total:.0f}%)")
    print()
    print("  category breakdown:")
    for cat in ORDER:
        n = cat_counts.get(cat, 0)
        bar = "█" * n
        print(f"    {cat:<13} {n:>3}  {bar}")
    print()

    # --- Per-detector breakdown ----
    print("## Quality by detector that produced the crop")
    by_detector: dict[str, list[str]] = defaultdict(list)
    for bid, cat in annotations.items():
        r = results_by_id.get(bid)
        det = (r and r.get("detector")) or "none"
        by_detector[det].append(cat)

    for det in ("text", "cv", "none"):
        cats = by_detector.get(det, [])
        if not cats:
            continue
        n = len(cats)
        good = sum(1 for c in cats if c in GOOD)
        print(f"  {det:<5} {n:>2} bottles → {good}/{n} acceptable ({good*100/n:.0f}%)")
        bd = Counter(cats)
        for cat in ORDER:
            if bd.get(cat):
                print(f"           {cat:<13} {bd[cat]}")
    print()

    # --- Worst offenders ----
    print("## Worst offenders by failure mode")
    by_mode: dict[str, list[str]] = defaultdict(list)
    for bid, cat in annotations.items():
        if cat in BAD:
            by_mode[cat].append(bid)

    for mode in ("failed", "wrong_region", "too_loose", "too_tight"):
        ids = by_mode.get(mode, [])
        if not ids:
            continue
        print(f"  {mode} ({len(ids)}):")
        for bid in sorted(ids, key=int):
            r = results_by_id.get(bid, {})
            det = r.get("detector") or "none"
            isz = "×".join(str(x) for x in r.get("input_size", []))
            osz = "×".join(str(x) for x in r.get("output_size", []))
            bounds = r.get("bounds")
            b_str = f"  bounds={bounds}" if bounds else ""
            print(f"    bottle {bid:<4} [{det:<4}]  {isz} → {osz}{b_str}")
    print()

    # --- Size correlation ----
    print("## Failure rate vs input size")
    # Bucket by max(width, height) of input
    buckets = [("<300", 0, 300), ("300-700", 300, 700), ("700-1500", 700, 1500), ("1500-3000", 1500, 3000), ("≥3000", 3000, 10**9)]
    for label, lo, hi in buckets:
        annotated_in_bucket = []
        for bid, cat in annotations.items():
            r = results_by_id.get(bid, {})
            sz = r.get("input_size", [0, 0])
            if not sz or sz == [0, 0]:
                continue
            m = max(sz)
            if lo <= m < hi:
                annotated_in_bucket.append(cat)
        if not annotated_in_bucket:
            continue
        n = len(annotated_in_bucket)
        good = sum(1 for c in annotated_in_bucket if c in GOOD)
        print(f"  {label:<10} {n:>2} bottles → {good}/{n} acceptable ({good*100/n:.0f}%)")
    print()

    # --- No-op detection ---
    print("## Crops where output ≈ input (no real cropping happened)")
    no_op_threshold = 0.98  # output area ≥ 98% of input area
    no_ops = []
    for bid, cat in annotations.items():
        r = results_by_id.get(bid, {})
        isz = r.get("input_size", [0, 0])
        osz = r.get("output_size", [0, 0])
        if not isz or isz == [0, 0]:
            continue
        in_area = isz[0] * isz[1]
        out_area = osz[0] * osz[1]
        if in_area > 0 and (out_area / in_area) >= no_op_threshold:
            no_ops.append((bid, cat, r.get("detector") or "none"))
    print(f"  {len(no_ops)} bottles had ≥{int(no_op_threshold*100)}% area preserved (effectively no crop):")
    for bid, cat, det in sorted(no_ops, key=lambda x: int(x[0])):
        print(f"    bottle {bid:<4} [{det:<4}]  annotated: {cat}")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
