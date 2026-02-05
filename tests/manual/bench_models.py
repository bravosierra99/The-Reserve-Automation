#!/usr/bin/env python3
"""Benchmark LM Studio models against the wine-manifest extraction pipeline.

Loads each model in isolation (all others evicted first), runs the real
BottleExtractor, scores the output, and prints a comparison table.

NOTE: whatever you have loaded in LM Studio before running this will be
      unloaded.  Reload it afterwards if you need it.

Usage:
    # Benchmark a single model
    uv run python tests/manual/bench_models.py -m qwen/qwen3-vl-8b

    # Benchmark all configured models
    uv run python tests/manual/bench_models.py

    # List available models (no LM Studio needed)
    uv run python tests/manual/bench_models.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

import httpx

from reserve_automation.extractors.bottle import BottleExtractor
from reserve_automation.llm.gateway import LLMGateway
from reserve_automation.parsers.pdf import PDFParser

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LM_STUDIO_BASE = "http://localhost:1234"
CHAT_BASE = f"{LM_STUDIO_BASE}/v1"

MANIFEST_PATH = Path(__file__).parent.parent / "fixtures" / "manifests" / "wine_manifest_sample.pdf"

# Per-model load parameters (top-level keys in the load body).
# Several models OOM-kill on fresh API load without an explicit context_length.
MODEL_LOAD_PARAMS: dict[str, dict] = {
    "qwen/qwen3-vl-4b": {"context_length": 16532},
    "qwen/qwen3-vl-8b": {"context_length": 16532},
    "mistralai/magistral-small-2509": {"context_length": 16384},
}

# Models available for benchmarking — add/remove as needed
ALL_MODELS = [
    "qwen/qwen3-vl-4b",
    "qwen/qwen3-vl-8b",
    "qwen/qwen3-vl-30b",
    "mistralai/magistral-small-2509",
    "zai-org/glm-4.6v-flash",
    "mistralai/devstral-small-2-2512",
]

# Ground-truth expectations (12 bottles in the fixture)
EXPECTED_COUNT = 12
KEY_BOTTLES = [
    "Forge Cellars - Willow Vineyard",
    "Jax Vineyards - Y3 Taureau Napa Valley Red",
    "Trimbach - Riesling Alsace",
    "Sandhi - Chardonnay Sta. Rita Hills",
]

# ---------------------------------------------------------------------------
# LM Studio management-API helpers
# ---------------------------------------------------------------------------


async def _load(model_key: str) -> dict | None:
    """POST /api/v1/models/load — blocks until the model is fully loaded.

    Merges any model-specific parameters from MODEL_LOAD_PARAMS (e.g.
    context_length) into the request body.  Returns None if LM Studio refuses.
    """
    body: dict = {"model": model_key, **MODEL_LOAD_PARAMS.get(model_key, {})}
    async with httpx.AsyncClient(timeout=600) as c:
        r = await c.post(f"{LM_STUDIO_BASE}/api/v1/models/load", json=body)
        if not r.is_success:
            print(f"  [!] LM Studio refused {model_key}: {r.status_code}")
            print(f"      {r.text[:200]}")
            return None
        return r.json()


async def _unload(instance_id: str) -> None:
    """POST /api/v1/models/unload — frees the model instance."""
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post(
            f"{LM_STUDIO_BASE}/api/v1/models/unload",
            json={"instance_id": instance_id},
        )
        r.raise_for_status()


async def _is_loaded(model_key: str) -> bool:
    """Check whether a model has at least one loaded instance."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{LM_STUDIO_BASE}/api/v1/models")
        r.raise_for_status()
        for m in r.json().get("models", []):
            if m["key"] == model_key and m.get("loaded_instances"):
                return True
    return False


async def _unload_all_llms() -> list[str]:
    """Unload every loaded LLM instance so the next model runs alone.

    Skips embedding models — those are tiny and don't compete for GPU memory.
    """
    unloaded: list[str] = []
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.get(f"{LM_STUDIO_BASE}/api/v1/models")
        r.raise_for_status()
        for m in r.json().get("models", []):
            if m.get("type") == "embedding":
                continue
            for instance in m.get("loaded_instances", []):
                try:
                    await _unload(instance["id"])
                    unloaded.append(instance["id"])
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        continue  # phantom instance from a failed load
                    raise
    return unloaded


# ---------------------------------------------------------------------------
# Gateway config — points directly at one model, no routing yaml needed
# ---------------------------------------------------------------------------


def _gateway_config(model_key: str) -> dict:
    """Minimal LLMGateway config that routes extraction to a single local model.

    Intentionally does NOT go through Config.load() / llm.yaml so that each
    run is isolated to exactly the model under test.
    """
    return {
        "providers": {
            "lm_studio_text": {
                "provider": "lm_studio",
                "base_url": CHAT_BASE,
                "model": model_key,
                "timeout": 300,
                "max_retries": 1,
            }
        },
        "routing": {
            "extraction": "lm_studio_text",
            "type_detection": "lm_studio_text",
        },
        "fallback": {"enabled": False},
    }


# ---------------------------------------------------------------------------
# Extraction + scoring
# ---------------------------------------------------------------------------


def _key_matches(key: str, labels: set[str]) -> bool:
    """Fuzzy match a KEY_BOTTLES entry against extracted labels.

    A key like "Forge Cellars - Willow Vineyard" matches any label whose
    producer contains the key's producer AND whose name shares at least one
    meaningful word with the key's name.  This avoids penalising models that
    add detail (e.g. grape variety) to the name.
    """
    if " - " not in key:
        return any(key.lower() in lbl.lower() for lbl in labels)

    key_producer, key_name = key.split(" - ", 1)
    key_producer_norm = key_producer.strip().lower()
    # Words > 2 chars to skip noise like "de", "la", etc.
    key_name_words = {w for w in key_name.strip().lower().split() if len(w) > 2}

    for lbl in labels:
        if " - " not in lbl:
            continue
        lbl_producer, lbl_name = lbl.split(" - ", 1)

        if key_producer_norm not in lbl_producer.strip().lower():
            continue

        lbl_name_words = {w for w in lbl_name.strip().lower().split() if len(w) > 2}
        if key_name_words & lbl_name_words:  # at least one word in common
            return True

    return False


async def _extract_and_score(model_key: str) -> dict:
    """Run the real extraction pipeline and return scored metrics.

    The model must already be loaded before this is called.  PDF parsing
    happens outside the timed section because it is model-independent.
    """
    parser = PDFParser()
    gateway = LLMGateway(_gateway_config(model_key))
    extractor = BottleExtractor(gateway)

    # Parse PDF (deterministic, not model-dependent — don't time this)
    parser_result = await parser.parse(MANIFEST_PATH)

    # Time only the LLM-driven extraction
    t0 = time.perf_counter()
    bottles = await extractor.extract(parser_result, beverage_type="wine")
    latency_ms = round((time.perf_counter() - t0) * 1000)

    # Score against ground truth (fuzzy: producer match + shared name words)
    labels = {f"{b.producer} - {b.name}" for b in bottles}
    key_found = [k for k in KEY_BOTTLES if _key_matches(k, labels)]

    return {
        "model": model_key,
        "count": len(bottles),
        "key_found": key_found,
        "with_year": sum(1 for b in bottles if b.year),
        "with_region": sum(1 for b in bottles if b.region),
        "avg_confidence": round(
            sum(b.confidence for b in bottles) / max(len(bottles), 1), 3
        ),
        "latency_ms": latency_ms,
        "bottles": bottles,
    }


def _print_results(r: dict) -> None:
    """Pretty-print one model's extraction results."""
    lines = [
        "",
        "=" * 64,
        f"  {r['model']}",
        "=" * 64,
        f"  Bottles extracted  : {r['count']}  (expected ~{EXPECTED_COUNT})",
        f"  Key bottles found  : {len(r['key_found'])}/{len(KEY_BOTTLES)}",
    ]
    for k in KEY_BOTTLES:
        lines.append(f"      {'✓' if k in r['key_found'] else '✗'}  {k}")
    lines += [
        f"  Bottles with year  : {r['with_year']}/{r['count']}",
        f"  Bottles with region: {r['with_region']}/{r['count']}",
        f"  Avg confidence     : {r['avg_confidence']}",
        f"  Extraction latency : {r['latency_ms']} ms",
        "",
        "  Extracted bottles:",
    ]
    for b in r["bottles"]:
        lines.append(
            f"      {b.producer} — {b.name} "
            f"({b.year or '?'}) [{b.beverage_type or 'n/a'}]"
        )
    lines.append("=" * 64 + "\n")
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Benchmark loop
# ---------------------------------------------------------------------------


async def _bench_one(model_key: str) -> dict | None:
    """Isolate → load → extract → score → print → unload one model."""
    evicted = await _unload_all_llms()
    if evicted:
        print(f"  [{model_key}] evicted {len(evicted)} model(s)")

    print(f"  [{model_key}] loading…")
    resp = await _load(model_key)
    if resp is None:
        print(f"  [{model_key}] SKIPPED — could not load\n")
        return None

    instance_id = resp["instance_id"]
    if not await _is_loaded(model_key):
        print(f"  [{model_key}] SKIPPED — not visible after load\n")
        return None
    print(f"  [{model_key}] loaded in {resp.get('load_time_seconds', '?')}s")

    try:
        results = await _extract_and_score(model_key)
        _print_results(results)
        return results
    except Exception as e:
        print(f"\n  [{model_key}] FAILED during extraction: {e}\n")
        return None
    finally:
        await _unload(instance_id)
        print(f"  [{model_key}] unloaded\n")


async def main(models: list[str]) -> None:
    """Run the benchmark loop, then print a summary table if multiple models."""
    print(f"\n{'=' * 64}")
    print(f"  Model Benchmark — {len(models)} model(s)")
    print(f"  Manifest: {MANIFEST_PATH.name}")
    print(f"{'=' * 64}\n")

    all_results: list[dict] = []
    for model_key in models:
        result = await _bench_one(model_key)
        if result:
            all_results.append(result)

    # Summary table (only useful when comparing multiple models)
    if len(all_results) > 1:
        print("\n" + "=" * 64)
        print("  SUMMARY  (sorted by latency)")
        print("=" * 64)
        print(f"  {'Model':<42} {'Btls':>4} {'Keys':>5} {'ms':>7}")
        print(f"  {'-'*42} {'-'*4} {'-'*5} {'-'*7}")
        for r in sorted(all_results, key=lambda x: x["latency_ms"]):
            print(
                f"  {r['model']:<42} "
                f"{r['count']:>4} "
                f"{len(r['key_found']):>2}/{len(KEY_BOTTLES)} "
                f"{r['latency_ms']:>6}"
            )
        print("=" * 64 + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark LM Studio models against wine-manifest extraction.",
    )
    parser.add_argument(
        "-m", "--model",
        help="Single model key to benchmark. Omit to run all models in ALL_MODELS.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print configured model keys and exit (no LM Studio connection).",
    )
    args = parser.parse_args()

    if args.list:
        print("\nConfigured models:")
        for m in ALL_MODELS:
            params = MODEL_LOAD_PARAMS.get(m)
            extra = f"  (context_length={params['context_length']})" if params else ""
            print(f"  {m}{extra}")
        print()
        raise SystemExit(0)

    models_to_run = [args.model] if args.model else ALL_MODELS
    asyncio.run(main(models_to_run))
