"""Diff two annotated auto-crop eval runs.

Usage:
    uv run python scripts/compare_crop_evals.py <baseline-run-dir> <new-run-dir>

Each run-dir must contain run.json and annotations-*.json.

Outputs:
  - Headline: acceptable rate baseline vs new
  - Per-bottle delta (improved / regressed / unchanged)
  - Failure-mode shifts (e.g. how many "too_tight" became "perfect")
"""

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

GOOD = {"perfect", "acceptable"}
BAD = {"too_tight", "too_loose", "wrong_region", "failed"}
ORDER = ["perfect", "acceptable", "too_tight", "too_loose", "wrong_region", "failed"]
RANK = {c: i for i, c in enumerate(ORDER)}  # lower = better


def load_run(run_dir: Path) -> tuple[dict, dict, dict]:
    """Returns (run_json, annotations, results_by_id)."""
    run = json.loads((run_dir / "run.json").read_text())
    annot_files = sorted(run_dir.glob("annotations-*.json"))
    if not annot_files:
        raise FileNotFoundError(f"No annotations-*.json in {run_dir}")
    annot = json.loads(annot_files[-1].read_text())["annotations"]
    results = {r["bottle_id"]: r for r in run["results"]}
    return run, annot, results


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2

    base_dir = Path(sys.argv[1])
    new_dir = Path(sys.argv[2])

    base_run, base_annot, base_results = load_run(base_dir)
    new_run, new_annot, new_results = load_run(new_dir)

    common = sorted(set(base_annot.keys()) & set(new_annot.keys()), key=int)
    only_base = set(base_annot) - set(new_annot)
    only_new = set(new_annot) - set(base_annot)

    print(f"# Comparison: {base_run['run_id']} → {new_run['run_id']}")
    print(f"  baseline detector: {base_run.get('detector_chain', '?')}")
    print(f"  new detector:      {new_run.get('detector_chain', '?')}"
          + (f"  ({new_run.get('vision_model')})" if new_run.get("vision_model") else ""))
    print(f"  Bottles in both runs: {len(common)}")
    if only_base: print(f"  Only in baseline: {sorted(only_base, key=int)}")
    if only_new:  print(f"  Only in new:      {sorted(only_new, key=int)}")
    print()

    # --- Overall ---
    def acceptable_rate(annot, ids):
        n = len(ids)
        g = sum(1 for i in ids if annot[i] in GOOD)
        return g, n

    g_base, n_base = acceptable_rate(base_annot, common)
    g_new, n_new = acceptable_rate(new_annot, common)
    print("## Headline (over bottles annotated in both runs)")
    print(f"  baseline: {g_base}/{n_base}  ({g_base*100/n_base:.0f}%) acceptable")
    print(f"  new:      {g_new}/{n_new}  ({g_new*100/n_new:.0f}%) acceptable")
    delta = (g_new - g_base) * 100 / n_base if n_base else 0
    print(f"  delta:    {g_new - g_base:+d} bottles  ({delta:+.0f}%)")
    print()

    # --- Per-bottle movement ---
    improved, regressed, unchanged = [], [], []
    for bid in common:
        rb, rn = base_annot[bid], new_annot[bid]
        if rb == rn:
            unchanged.append((bid, rb))
        elif RANK[rn] < RANK[rb]:
            improved.append((bid, rb, rn))
        else:
            regressed.append((bid, rb, rn))

    print("## Movement")
    print(f"  improved:  {len(improved)}")
    print(f"  regressed: {len(regressed)}")
    print(f"  unchanged: {len(unchanged)}")
    print()

    if improved:
        print("### Improved")
        for bid, rb, rn in improved:
            print(f"  bottle {bid:<4}  {rb:<13} → {rn}")
        print()

    if regressed:
        print("### Regressed")
        for bid, rb, rn in regressed:
            print(f"  bottle {bid:<4}  {rb:<13} → {rn}")
        print()

    # --- Failure-mode shifts ---
    print("## Failure-mode shifts (where each baseline category landed in new)")
    shifts: dict[str, Counter] = defaultdict(Counter)
    for bid in common:
        shifts[base_annot[bid]][new_annot[bid]] += 1
    for src in ORDER:
        if not shifts[src]:
            continue
        total = sum(shifts[src].values())
        line = f"  {src} ({total}):"
        for dst in ORDER:
            n = shifts[src][dst]
            if n:
                arrow = "→" if dst != src else "="
                line += f"  {arrow}{dst}={n}"
        print(line)
    print()

    # --- Timing if available ---
    print("## Latency")
    for label, results in [("baseline", base_results), ("new", new_results)]:
        times = [r.get("total_ms", 0) for r in results.values() if r.get("total_ms")]
        if times:
            times.sort()
            print(f"  {label}:  median {times[len(times)//2]:.0f}ms  p90 {times[int(len(times)*0.9)]:.0f}ms  max {max(times):.0f}ms")

    return 0


if __name__ == "__main__":
    sys.exit(main())
