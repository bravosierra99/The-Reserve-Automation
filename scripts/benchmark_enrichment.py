"""
Benchmark metadata enrichment configurations for local LM Studio.

Tests different max_results (DuckDuckGo results per search) and max_iterations
(max LLM tool-call loops per bottle) to find the best balance of speed vs quality.

Usage (run from project root, same as ./start-web.sh):
    uv run --env-file .env python scripts/benchmark_enrichment.py /path/to/manifest.pdf
    uv run --env-file .env python scripts/benchmark_enrichment.py /path/to/manifest.pdf --bottles 3
    uv run --env-file .env python scripts/benchmark_enrichment.py /path/to/manifest.pdf --fresh
    uv run --env-file .env python scripts/benchmark_enrichment.py /path/to/manifest.pdf --output results.json
    uv run --env-file .env python scripts/benchmark_enrichment.py /path/to/manifest.pdf --configs fast,balanced
"""

import argparse
import asyncio
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

# Suppress loguru output during benchmark (we print our own progress)
from loguru import logger as _logger

_logger.remove()

from reserve_automation.core.config import Config
from reserve_automation.core.models import BottleMetadata
from reserve_automation.enrichment.metadata_enricher import MetadataEnricher
from reserve_automation.llm import LLMGateway

# ── Config variants to benchmark ──────────────────────────────────────────────
CONFIGS = [
    {
        "key":           "fast",
        "label":         "Fast     (3 results × 3 iters)",
        "max_results":   3,
        "max_iterations": 3,
    },
    {
        "key":           "balanced",
        "label":         "Balanced (5 results × 3 iters)",
        "max_results":   5,
        "max_iterations": 3,
    },
    {
        "key":           "medium",
        "label":         "Medium   (5 results × 5 iters)",
        "max_results":   5,
        "max_iterations": 5,
    },
    {
        "key":           "default",
        "label":         "Default  (10 results × 10 iters)",
        "max_results":   10,
        "max_iterations": 10,
    },
]


# ── Extraction ─────────────────────────────────────────────────────────────────
async def extract_bottles_from_pdf(pdf_path: Path, llm_config: dict, app_config: Config) -> list[dict]:
    """Run the full extraction pipeline on the PDF, return list of bottle dicts."""
    from reserve_automation.pipeline import extraction_pipeline

    config_dict = app_config.model_dump()
    result = await extraction_pipeline(pdf_path, config_dict)
    return [b.model_dump(mode="json") for b in result.bottles]


# ── Enrichment benchmark ───────────────────────────────────────────────────────
async def _warmup(gateway: LLMGateway):
    """Fire a cheap health check so LM Studio is fully awake before timing starts."""
    provider = gateway.providers.get("lm_studio_text")
    if provider:
        try:
            await provider._is_model_loaded()
        except Exception:
            pass


async def run_single_bottle(
    bottle: BottleMetadata,
    enricher: MetadataEnricher,
) -> dict:
    """Enrich one bottle and return timing/quality stats."""
    enricher._searcher.call_count = 0

    start = time.time()
    try:
        _, metadata = await enricher.verify_bottle(bottle)
        elapsed = time.time() - start

        # verify_bottle catches its own errors and returns {"verified": False, "error": ...}
        if not metadata.get("verified", False) and "error" in metadata:
            raise RuntimeError(metadata["error"])

        changes = metadata.get("changes", {})
        return {
            "bottle":         f"{bottle.producer} – {bottle.name}",
            "time_s":         round(elapsed, 1),
            "searches":       enricher._searcher.call_count,
            "tokens":         metadata.get("tokens_used", 0),
            "fields_changed": len(changes),
            "changes":        {k: v["new"] for k, v in changes.items()},
            "confidence":     metadata.get("confidence", "?"),
            "error":          None,
        }

    except Exception as e:
        elapsed = time.time() - start
        return {
            "bottle":         f"{bottle.producer} – {bottle.name}",
            "time_s":         round(elapsed, 1),
            "searches":       enricher._searcher.call_count,
            "tokens":         0,
            "fields_changed": 0,
            "changes":        {},
            "confidence":     "error",
            "error":          str(e)[:120],
        }


async def run_config(cfg: dict, bottles: list[BottleMetadata], base_llm_config: dict) -> list[dict]:
    """Run verify_bottle on all test bottles with the given config."""
    print(f"\n{'─'*60}")
    print(f"  Config: {cfg['label']}")

    gateway = LLMGateway(copy.deepcopy(base_llm_config))
    enricher = MetadataEnricher(gateway, max_results=cfg["max_results"])

    # Warm up LM Studio before timing starts
    print("  Warming up LM Studio...", end="", flush=True)
    await _warmup(gateway)
    print(" ready.")

    results = []
    for bottle in bottles:
        print(f"  ⟳  {bottle.producer} – {bottle.name} ...", end="", flush=True)
        r = await run_single_bottle(bottle, enricher)
        results.append(r)

        if r["error"]:
            print(f" ✗  {r['time_s']:.1f}s  ERROR: {r['error'][:60]}")
        else:
            print(
                f" ✓  {r['time_s']:.1f}s  "
                f"{r['searches']} searches  "
                f"{r['tokens']} tokens  "
                f"{r['fields_changed']} changes ({r['confidence']})"
            )

    return results


# ── Reporting ──────────────────────────────────────────────────────────────────
def print_summary_table(all_results: dict[str, list[dict]]):
    """Print formatted comparison tables."""
    W = 80

    print(f"\n{'='*W}")
    print("  ENRICHMENT BENCHMARK — AVERAGES")
    print(f"{'='*W}")
    print(
        f"  {'Configuration':<36}"
        f"{'Avg Time':>10}"
        f"{'Searches':>10}"
        f"{'Tokens':>9}"
        f"{'Changes':>9}"
    )
    print(f"  {'─'*36}{'─'*10}{'─'*10}{'─'*9}{'─'*9}")

    for label, bottle_results in all_results.items():
        ok = [r for r in bottle_results if not r["error"]]
        if not ok:
            print(f"  {label:<36}  (all errors)")
            continue
        n = len(ok)
        print(
            f"  {label:<36}"
            f"  {sum(r['time_s']    for r in ok)/n:>7.1f}s"
            f"  {sum(r['searches']  for r in ok)/n:>7.1f}"
            f"  {sum(r['tokens']    for r in ok)/n:>7.0f}"
            f"  {sum(r['fields_changed'] for r in ok)/n:>7.1f}"
        )

    print(f"\n{'='*W}")
    print("  ENRICHMENT BENCHMARK — PER BOTTLE")
    print(f"{'='*W}")

    for label, bottle_results in all_results.items():
        short = label.split("(")[0].strip()
        print(f"\n  [{short}]")
        for r in bottle_results:
            name = r["bottle"][:40]
            if r["error"]:
                print(f"    {name:<42}  ✗ {r['error'][:40]}")
            else:
                changed_fields = ", ".join(r["changes"].keys()) if r["changes"] else "—"
                print(
                    f"    {name:<42}"
                    f"  {r['time_s']:>5.1f}s"
                    f"  {r['searches']:>2} srch"
                    f"  {r['tokens']:>5} tok"
                    f"  {r['fields_changed']:>2} chg"
                    f"  [{changed_fields}]"
                )

    # Recommendation
    print(f"\n{'='*W}")
    print("  RECOMMENDATION")
    print(f"{'─'*W}")
    _print_recommendation(all_results)
    print(f"{'='*W}\n")


def _print_recommendation(all_results: dict[str, list[dict]]):
    """Simple heuristic recommendation based on time/quality ratio."""
    scored = []
    for label, results in all_results.items():
        ok = [r for r in results if not r["error"]]
        if not ok:
            continue
        avg_time    = sum(r["time_s"] for r in ok) / len(ok)
        avg_changes = sum(r["fields_changed"] for r in ok) / len(ok)
        avg_srch    = sum(r["searches"] for r in ok) / len(ok)

        # Quality score: normalize changes (diminishing returns above 3)
        # Speed score: penalize time logarithmically
        import math
        quality = min(avg_changes / 5.0, 1.0)     # 5 changes = 100% quality
        speed   = max(0, 1 - math.log(max(avg_time, 1)) / math.log(120))  # 120s = worst
        score   = 0.5 * quality + 0.5 * speed
        scored.append((score, label, avg_time, avg_changes, avg_srch))

    if not scored:
        print("  Not enough data for recommendation.")
        return

    scored.sort(reverse=True)
    best_label, best_time, best_changes, best_srch = (
        scored[0][1], scored[0][2], scored[0][3], scored[0][4]
    )

    print(f"  Best balance of speed and quality: {best_label}")
    print(f"    Avg time: {best_time:.1f}s  |  Avg searches: {best_srch:.1f}  |  Avg fields changed: {best_changes:.1f}")

    if len(scored) > 1:
        _, fastest_time = scored[-1][1], scored[-1][2]
        default_changes = max(r[3] for r in scored)
        best_changes_val = best_changes

        if best_time < fastest_time * 1.5 and best_changes_val >= default_changes * 0.85:
            print(f"\n  ✓ Switching from 'Default' to '{best_label.split('(')[0].strip()}' is likely")
            print(f"    safe: similar field coverage at {best_time:.0f}s vs {fastest_time:.0f}s per bottle.")
        else:
            print("\n  Run more bottles (--bottles 5+) for a more reliable recommendation.")


# ── Main ───────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(
        description="Benchmark enrichment configs (max_results × max_iterations)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("pdf", type=Path, help="Path to manifest PDF")
    parser.add_argument(
        "--bottles", type=int, default=3,
        help="Number of bottles to test (default: 3)"
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Re-extract bottles from PDF (ignore cache)"
    )
    parser.add_argument(
        "--output", type=Path,
        help="Save raw results to JSON file"
    )
    parser.add_argument(
        "--configs", type=str,
        help="Comma-separated configs to run: fast,balanced,medium,default (default: all)"
    )
    args = parser.parse_args()

    if not args.pdf.exists():
        print(f"ERROR: PDF not found: {args.pdf}")
        sys.exit(1)

    # ── Load app config ──
    print("Loading config...")
    try:
        app_config = Config.load()
    except Exception as e:
        print(f"ERROR loading config: {e}")
        print("Run from the project root directory (same place as ./start-web.sh)")
        sys.exit(1)

    base_llm_config = app_config.model_dump()["llm"]

    # ── Extract bottles (with caching) ──
    pdf_hash = hashlib.md5(str(args.pdf.absolute()).encode()).hexdigest()[:8]
    cache_file = Path(f"/tmp/benchmark_bottles_{pdf_hash}.json")

    if cache_file.exists() and not args.fresh:
        print(f"Loading cached extraction from {cache_file}")
        print("  (pass --fresh to re-extract from PDF)")
        with open(cache_file) as f:
            all_bottles_data = json.load(f)
        print(f"  Loaded {len(all_bottles_data)} bottles")
    else:
        print(f"Extracting bottles from {args.pdf.name}...")
        try:
            all_bottles_data = await extract_bottles_from_pdf(
                args.pdf, base_llm_config, app_config
            )
        except Exception as e:
            print(f"ERROR extracting bottles: {e}")
            sys.exit(1)
        with open(cache_file, "w") as f:
            json.dump(all_bottles_data, f, indent=2, default=str)
        print(f"  Extracted {len(all_bottles_data)} bottles (cached to {cache_file})")

    if not all_bottles_data:
        print("ERROR: No bottles extracted from PDF")
        sys.exit(1)

    # ── Build BottleMetadata objects ──
    test_data = all_bottles_data[:args.bottles]
    test_bottles = []
    for b_data in test_data:
        try:
            test_bottles.append(BottleMetadata(**b_data))
        except Exception as e:
            print(f"  Warning: skipping bottle (invalid data): {e}")

    if not test_bottles:
        print("ERROR: No valid bottles to test")
        sys.exit(1)

    print(f"\nTesting enrichment on {len(test_bottles)} bottles:")
    for b in test_bottles:
        print(f"  - {b.producer} – {b.name} ({b.type})")

    # ── Select configs ──
    if args.configs:
        keys = {k.strip() for k in args.configs.split(",")}
        configs_to_run = [c for c in CONFIGS if c["key"] in keys]
        if not configs_to_run:
            print(f"ERROR: No matching configs for '{args.configs}'")
            print(f"Valid keys: {', '.join(c['key'] for c in CONFIGS)}")
            sys.exit(1)
    else:
        configs_to_run = CONFIGS

    # ── Run benchmark ──
    all_results = {}
    start_total = time.time()

    for cfg in configs_to_run:
        results = await run_config(cfg, test_bottles, base_llm_config)
        all_results[cfg["label"]] = results

    total_time = time.time() - start_total
    print(f"\nTotal benchmark time: {total_time:.0f}s")

    # ── Print summary ──
    print_summary_table(all_results)

    # ── Save raw results ──
    if args.output:
        raw = {
            "pdf": str(args.pdf),
            "bottles_tested": [f"{b.producer} – {b.name}" for b in test_bottles],
            "configs": all_results,
            "total_time_s": round(total_time, 1),
        }
        with open(args.output, "w") as f:
            json.dump(raw, f, indent=2, default=str)
        print(f"Raw results saved to: {args.output}")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
