#!/usr/bin/env python3
"""Benchmark LM Studio models against extraction pipelines (PDF + Image).

Loads each model in isolation (all others evicted first), runs the real
extraction pipelines, scores the output, and prints a comparison table.

Tests BOTH text-based extraction (PDF manifests) AND vision-based extraction
(bottle images) to ensure models work correctly in all scenarios.

NOTE: whatever you have loaded in LM Studio before running this will be
      unloaded.  Reload it afterwards if you need it.

Usage:
    # Benchmark a single model (both PDF and image extraction)
    uv run python tests/manual/bench_models.py -m qwen/qwen3-vl-8b

    # Benchmark all configured models
    uv run python tests/manual/bench_models.py

    # Only test image extraction (vision models)
    uv run python tests/manual/bench_models.py --mode image

    # Only test PDF extraction (text models)
    uv run python tests/manual/bench_models.py --mode pdf

    # List available models (no LM Studio needed)
    uv run python tests/manual/bench_models.py --list
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import time
from pathlib import Path

import httpx

from reserve_automation.extractors.bottle import BottleExtractor
from reserve_automation.extractors.image_extractor import ImageMetadataExtractor
from reserve_automation.llm.gateway import LLMGateway
from reserve_automation.parsers.pdf import PDFParser

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LM_STUDIO_BASE = "http://localhost:1234"
CHAT_BASE = f"{LM_STUDIO_BASE}/v1"

# LM Studio requires a Bearer token (GROUND_TRUTH.md #2/#3). The provider authenticates
# its own chat calls, but the management-API helpers below are standalone httpx calls and
# must carry the token too — resolve it the same way LMStudioProvider does.
_API_KEY = os.environ.get("LM_STUDIO_API_KEY")
_HEADERS = {"Authorization": f"Bearer {_API_KEY}"} if _API_KEY else None

# Test fixtures
FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"
MANIFEST_PATH = FIXTURE_DIR / "manifests" / "wine_manifest_sample.pdf"
BOTTLE_DIR = FIXTURE_DIR / "bottles"

# Ground truth for the bottle-label images, hand-verified from the photos.
# Each entry lists the distinctive tokens that a correct OCR read MUST surface
# *somewhere* in the extracted fields (producer / name / additional_details /
# style), so scoring is robust to which field a model files a token under.
# - producer_kw / name_kw : alnum-normalized substrings; ANY hit = that dim correct
# - year                  : exact vintage string, or None if the label has none
# - beverage_type         : expected BottleMetadata.beverage_type value
# - difficulty            : easy / medium / hard (legibility of the photo)
IMAGE_GROUND_TRUTH: dict[str, dict] = {
    "bourbon_001.jpg": {"producer_kw": ["weller"], "name_kw": ["cypb", "wheated"],
                        "year": None, "type_kw": ["whiskey", "bourbon"], "difficulty": "easy"},
    "bourbon_002.jpg": {"producer_kw": ["bluegrass"], "name_kw": ["elkwood"],
                        "year": None, "type_kw": ["whiskey", "bourbon"], "difficulty": "medium"},
    "bourbon_003.jpg": {"producer_kw": ["larue", "william"], "name_kw": ["larue", "weller"],
                        "year": None, "type_kw": ["whiskey", "bourbon"], "difficulty": "hard"},
    "wine_001.jpg":    {"producer_kw": ["detective"], "name_kw": ["cabernet", "syrah"],
                        "year": "2024", "type_kw": ["wine"], "difficulty": "easy"},
    "wine_002.jpg":    {"producer_kw": ["hedges"], "name_kw": ["cms"],
                        "year": "2022", "type_kw": ["wine"], "difficulty": "medium"},
    "wine_003.jpg":    {"producer_kw": ["liquid", "farm"], "name_kw": ["chardonnay", "hill"],
                        "year": "2023", "type_kw": ["wine"], "difficulty": "hard"},
    "wine_004.jpg":    {"producer_kw": ["cosme", "saint"], "name_kw": ["rhone", "cosme"],
                        "year": "2024", "type_kw": ["wine"], "difficulty": "medium"},
}
BOTTLE_IMAGES = [BOTTLE_DIR / name for name in IMAGE_GROUND_TRUTH]

# Per-model load parameters (top-level keys in the load body).
# Several models OOM-kill on fresh API load without an explicit context_length.
MODEL_LOAD_PARAMS: dict[str, dict] = {
    "qwen/qwen3-vl-4b": {"context_length": 16532},
    "qwen/qwen3-vl-8b": {"context_length": 16532},
    "qwen/qwen3-8b": {"context_length": 16384},
    "qwen/qwen3.5-9b": {"context_length": 16384},
    "qwen3.5-27b-claude-4.6-opus-reasoning-distilled@iq4_xs": {"context_length": 16384},
    "qwen3.5-27b-claude-4.6-opus-reasoning-distilled@iq3_m": {"context_length": 16384},
    "mistralai/magistral-small-2509": {"context_length": 16384},
    "qwen3.5-35b-a3b": {"context_length": 16384},
    "froginsect/qwythos-9b-claude-mythos-5-1m": {"context_length": 16384},
    "empero-ai/qwythos-9b-claude-mythos-5-1m": {"context_length": 16384},
}

# Per-model gateway config extras (merged into the provider config sent to LMStudioProvider).
# Used to pass reasoning_effort="none" to models that default thinking on, which otherwise
# exhaust the entire token budget in reasoning and return empty content.
MODEL_GATEWAY_EXTRAS: dict[str, dict] = {
    "qwen/qwen3.5-9b":   {"reasoning_effort": "none"},
    "qwen3.5-27b-claude-4.6-opus-reasoning-distilled@iq4_xs": {"reasoning_effort": "none"},
    "qwen3.5-27b-claude-4.6-opus-reasoning-distilled@iq3_m":  {"reasoning_effort": "none"},
    "qwen3.5-35b-a3b":   {"reasoning_effort": "none"},
    "froginsect/qwythos-9b-claude-mythos-5-1m": {"reasoning_effort": "none"},
    "empero-ai/qwythos-9b-claude-mythos-5-1m":  {"reasoning_effort": "none"},
}

# Models available for benchmarking — add/remove as needed
# NOTE: The 27b models below are text-only (no VL suffix) — PDF mode only, not image.
ALL_MODELS = [
    "qwen/qwen3-8b",        # text 8b baseline
    "qwen/qwen3.5-9b",      # text 9b
    #"qwen3.5-27b-claude-4.6-opus-reasoning-distilled@iq4_xs",  # 27b reasoning (higher quality)
    "qwen3.5-27b-claude-4.6-opus-reasoning-distilled@iq3_m", # 27b reasoning (smaller/faster)
    # "qwen3.5-35b-a3b",  # Too slow on this hardware (CPU-offloaded, ~5-8 tok/s → PDF times out)
    # "qwen/qwen3-vl-8b",   # vision 8b — use --mode image or both for vision comparison
    # "qwen/qwen3-vl-4b",
    # "qwen/qwen3-vl-30b",
    # "mistralai/magistral-small-2509",
    # "zai-org/glm-4.6v-flash",
    # "mistralai/devstral-small-2-2512",
]

# Ground-truth expectations for PDF manifest (12 bottles)
PDF_EXPECTED_COUNT = 12
PDF_KEY_BOTTLES = [
    "Forge Cellars - Willow Vineyard",
    "Jax Vineyards - Y3 Taureau Napa Valley Red",
    "Trimbach - Riesling Alsace",
    "Sandhi - Chardonnay Sta. Rita Hills",
]

IMAGE_SCORE_DIMS = ("producer", "name", "year", "type")


def _alnum(s: str | None) -> str:
    """Lowercase and strip everything but [a-z0-9] for robust substring matching."""
    return re.sub(r"[^a-z0-9]", "", s.lower()) if s else ""


def _score_label(gt: dict, bottle) -> dict:
    """Score one extracted bottle against its ground truth.

    Builds an alnum haystack from all text-bearing fields so a token counts as
    "read" regardless of which field the model placed it in. Returns per-dimension
    booleans; `year` is None (not scored) when the label has no vintage.
    """
    variety = bottle.variety if isinstance(bottle.variety, list) else [bottle.variety]
    haystack = _alnum(" ".join(
        str(x) for x in (
            bottle.producer, bottle.name, getattr(bottle, "additional_details", None),
            bottle.style, bottle.region, bottle.year, *variety,
        ) if x
    ))
    # beverage_type holds normalized categories like "Bourbon" / "Red wine", so match
    # type by keyword across the category-bearing fields rather than an exact value.
    type_haystack = _alnum(" ".join(
        str(x) for x in (bottle.beverage_type, getattr(bottle, "type", None), bottle.style) if x
    ))
    producer_ok = any(_alnum(kw) in haystack for kw in gt["producer_kw"])
    name_ok = any(_alnum(kw) in haystack for kw in gt["name_kw"])
    year_ok = None if gt["year"] is None else (gt["year"] in haystack)
    type_ok = any(_alnum(kw) in type_haystack for kw in gt["type_kw"])
    return {"producer": producer_ok, "name": name_ok, "year": year_ok, "type": type_ok}

# ---------------------------------------------------------------------------
# LM Studio management-API helpers
# ---------------------------------------------------------------------------


async def _load(model_key: str) -> dict | None:
    """POST /api/v1/models/load — blocks until the model is fully loaded.

    Merges any model-specific parameters from MODEL_LOAD_PARAMS (e.g.
    context_length) into the request body.  Returns None if LM Studio refuses.
    """
    body: dict = {"model": model_key, **MODEL_LOAD_PARAMS.get(model_key, {})}
    async with httpx.AsyncClient(timeout=600, headers=_HEADERS) as c:
        r = await c.post(f"{LM_STUDIO_BASE}/api/v1/models/load", json=body)
        if not r.is_success:
            print(f"  [!] LM Studio refused {model_key}: {r.status_code}")
            print(f"      {r.text[:200]}")
            return None
        return r.json()


async def _unload(instance_id: str) -> None:
    """POST /api/v1/models/unload — frees the model instance."""
    async with httpx.AsyncClient(timeout=60, headers=_HEADERS) as c:
        r = await c.post(
            f"{LM_STUDIO_BASE}/api/v1/models/unload",
            json={"instance_id": instance_id},
        )
        r.raise_for_status()


async def _is_loaded(model_key: str) -> bool:
    """Check whether a model has at least one loaded instance."""
    async with httpx.AsyncClient(timeout=10, headers=_HEADERS) as c:
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
    async with httpx.AsyncClient(timeout=30, headers=_HEADERS) as c:
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


def _gateway_config(model_key: str, for_vision: bool = False) -> dict:
    """Minimal LLMGateway config that routes tasks to a single local model.

    Intentionally does NOT go through Config.load() / llm.yaml so that each
    run is isolated to exactly the model under test.

    Args:
        model_key: Model to use
        for_vision: If True, route OCR tasks to this model (for image extraction)
    """
    provider_name = "lm_studio_vision" if for_vision else "lm_studio_text"

    provider_cfg: dict = {
        "provider": "lm_studio",
        "base_url": CHAT_BASE,
        "model": model_key,
        "timeout": 300,
        "max_retries": 1,
        **MODEL_GATEWAY_EXTRAS.get(model_key, {}),
    }

    config = {
        "providers": {provider_name: provider_cfg},
        "routing": {
            "extraction": provider_name,
            "type_detection": provider_name,
        },
        "fallback": {"enabled": False},
    }

    # Add OCR routing for vision models
    if for_vision:
        config["routing"]["ocr"] = provider_name

    return config


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


async def _extract_and_score_pdf(model_key: str) -> dict:
    """Run PDF extraction pipeline and return scored metrics.

    The model must already be loaded before this is called.  PDF parsing
    happens outside the timed section because it is model-independent.
    """
    parser = PDFParser()
    gateway = LLMGateway(_gateway_config(model_key, for_vision=False))
    extractor = BottleExtractor(gateway)

    # Parse PDF (deterministic, not model-dependent — don't time this)
    parser_result = await parser.parse(MANIFEST_PATH)

    # Time only the LLM-driven extraction
    t0 = time.perf_counter()
    bottles = await extractor.extract(parser_result, beverage_type="wine")
    latency_ms = round((time.perf_counter() - t0) * 1000)

    # Score against ground truth (fuzzy: producer match + shared name words)
    labels = {f"{b.producer} - {b.name}" for b in bottles}
    key_found = [k for k in PDF_KEY_BOTTLES if _key_matches(k, labels)]

    return {
        "model": model_key,
        "mode": "pdf",
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


async def _extract_and_score_images(model_key: str) -> dict:
    """Run image extraction pipeline and return scored metrics.

    Tests vision model's ability to read bottle labels directly from images.
    This is the CRITICAL test that catches issues like the forward-slash bug.
    """
    gateway = LLMGateway(_gateway_config(model_key, for_vision=True))
    extractor = ImageMetadataExtractor(gateway)

    per_image: list[dict] = []  # one entry per fixture, in IMAGE_GROUND_TRUTH order
    all_bottles = []
    total_latency_ms = 0

    for image_path in BOTTLE_IMAGES:
        gt = IMAGE_GROUND_TRUTH[image_path.name]
        t0 = time.perf_counter()
        bottle = None
        error = None
        try:
            bottle, _metadata = await extractor.extract_from_image(image_path)
        except Exception as e:
            error = str(e)
        latency_ms = round((time.perf_counter() - t0) * 1000)
        total_latency_ms += latency_ms

        if bottle:
            all_bottles.append(bottle)
            scores = _score_label(gt, bottle)
        else:
            # Total failure → every scored dimension is wrong.
            scores = {"producer": False, "name": False, "year": (None if gt["year"] is None else False), "type": False}

        per_image.append({
            "name": image_path.name,
            "difficulty": gt["difficulty"],
            "scores": scores,
            "bottle": bottle,
            "error": error,
            "latency_ms": latency_ms,
        })

    # Aggregate field-level accuracy across all images.
    def _dim_total(dim: str) -> tuple[int, int]:
        scored = [p for p in per_image if p["scores"][dim] is not None]
        correct = sum(1 for p in scored if p["scores"][dim])
        return correct, len(scored)

    dim_scores = {dim: _dim_total(dim) for dim in IMAGE_SCORE_DIMS}
    total_correct = sum(c for c, _ in dim_scores.values())
    total_scored = sum(t for _, t in dim_scores.values())
    # A label "passes" if its core identity (producer AND name) was read correctly.
    passed = sum(1 for p in per_image if p["scores"]["producer"] and p["scores"]["name"])

    return {
        "model": model_key,
        "mode": "image",
        "count": len(all_bottles),
        "valid_count": passed,  # producer+name correct (kept name for summary table)
        "per_image": per_image,
        "dim_scores": dim_scores,
        "field_accuracy": round(total_correct / total_scored, 3) if total_scored else 0.0,
        "failed_images": [p["name"] for p in per_image if p["bottle"] is None],
        "avg_confidence": round(
            sum(b.confidence for b in all_bottles) / max(len(all_bottles), 1), 3
        ) if all_bottles else 0.0,
        "latency_ms": total_latency_ms,
        "bottles": all_bottles,
    }


def _print_results(r: dict) -> None:
    """Pretty-print one model's extraction results."""
    mode = r.get("mode", "pdf")
    lines = [
        "",
        "=" * 80,
        f"  {r['model']} — {mode.upper()} extraction",
        "=" * 80,
    ]

    if mode == "pdf":
        lines += [
            f"  Bottles extracted  : {r['count']}  (expected ~{PDF_EXPECTED_COUNT})",
            f"  Key bottles found  : {len(r['key_found'])}/{len(PDF_KEY_BOTTLES)}",
        ]
        for k in PDF_KEY_BOTTLES:
            lines.append(f"      {'✓' if k in r['key_found'] else '✗'}  {k}")
        lines += [
            f"  Bottles with year  : {r['with_year']}/{r['count']}",
            f"  Bottles with region: {r['with_region']}/{r['count']}",
            f"  Avg confidence     : {r['avg_confidence']}",
            f"  Extraction latency : {r['latency_ms']} ms",
        ]
    else:  # image mode
        dim = r["dim_scores"]

        def _frac(d: str) -> str:
            c, t = dim[d]
            return f"{c}/{t}" if t else "n/a"

        lines += [
            f"  Images tested      : {len(BOTTLE_IMAGES)}",
            f"  Field accuracy     : {r['field_accuracy']}  "
            f"(producer {_frac('producer')}, name {_frac('name')}, "
            f"year {_frac('year')}, type {_frac('type')})",
            f"  Core read (prod+name): {r['valid_count']}/{len(BOTTLE_IMAGES)}",
            f"  Failed (no output) : {len(r.get('failed_images', []))}",
            "",
            "  Per-image  (P=producer N=name Y=year T=type · ✓ hit  ✗ miss  – n/a):",
        ]
        for p in r["per_image"]:
            s = p["scores"]
            def _m(v: object) -> str:
                return "–" if v is None else ("✓" if v else "✗")
            flags = f"P{_m(s['producer'])} N{_m(s['name'])} Y{_m(s['year'])} T{_m(s['type'])}"
            tag = "FAIL" if p["bottle"] is None else flags
            lines.append(f"      [{p['difficulty']:<6}] {p['name']:<16} {tag}  ({p['latency_ms']} ms)")
        lines += [
            f"  Avg confidence     : {r['avg_confidence']}",
            f"  Total latency      : {r['latency_ms']} ms",
        ]

    lines += ["", "  Extracted bottles:"]
    for b in r["bottles"]:
        lines.append(
            f"      {b.producer} — {b.name} "
            f"({b.year or '?'}) [{b.beverage_type or 'n/a'}]"
        )
    lines.append("=" * 80 + "\n")
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Benchmark loop
# ---------------------------------------------------------------------------


async def _bench_one(model_key: str, mode: str = "both") -> list[dict]:
    """Isolate → load → extract → score → print → unload one model.

    Args:
        model_key: Model to benchmark
        mode: "pdf", "image", or "both"

    Returns:
        List of result dicts (one per mode tested)
    """
    evicted = await _unload_all_llms()
    if evicted:
        print(f"  [{model_key}] evicted {len(evicted)} model(s)")

    print(f"  [{model_key}] loading…")
    resp = await _load(model_key)
    if resp is None:
        print(f"  [{model_key}] SKIPPED — could not load\n")
        return []

    instance_id = resp["instance_id"]
    if not await _is_loaded(model_key):
        print(f"  [{model_key}] SKIPPED — not visible after load\n")
        return []
    print(f"  [{model_key}] loaded in {resp.get('load_time_seconds', '?')}s")

    results = []
    try:
        # Run PDF extraction if requested
        if mode in ("pdf", "both"):
            try:
                pdf_result = await _extract_and_score_pdf(model_key)
                _print_results(pdf_result)
                results.append(pdf_result)
            except Exception as e:
                print(f"\n  [{model_key}] PDF extraction FAILED: {e}\n")

        # Run image extraction if requested
        if mode in ("image", "both"):
            try:
                image_result = await _extract_and_score_images(model_key)
                _print_results(image_result)
                results.append(image_result)
            except Exception as e:
                print(f"\n  [{model_key}] Image extraction FAILED: {e}\n")

        return results
    except Exception as e:
        print(f"\n  [{model_key}] FAILED during benchmarking: {e}\n")
        return results
    finally:
        await _unload(instance_id)
        print(f"  [{model_key}] unloaded\n")


async def main(models: list[str], mode: str = "both") -> None:
    """Run the benchmark loop, then print a summary table if multiple models.

    Args:
        models: List of model keys to benchmark
        mode: "pdf", "image", or "both"
    """
    mode_desc = {
        "pdf": "PDF text extraction",
        "image": "Image vision extraction",
        "both": "PDF + Image extraction",
    }

    print(f"\n{'=' * 80}")
    print(f"  Model Benchmark — {len(models)} model(s) — {mode_desc.get(mode, mode)}")
    if mode in ("pdf", "both"):
        print(f"  PDF Manifest: {MANIFEST_PATH.name}")
    if mode in ("image", "both"):
        print(f"  Image Fixtures: {len(BOTTLE_IMAGES)} bottle images")
    print(f"{'=' * 80}\n")

    all_results: list[dict] = []
    for model_key in models:
        results = await _bench_one(model_key, mode=mode)
        all_results.extend(results)

    # Summary table (only useful when comparing multiple results)
    if len(all_results) > 1:
        print("\n" + "=" * 80)
        print("  SUMMARY  (sorted by mode, then latency)")
        print("=" * 80)
        print(f"  {'Model':<38} {'Mode':>6} {'Result':>20} {'ms':>7}")
        print(f"  {'-'*38} {'-'*6} {'-'*20} {'-'*7}")

        # Sort by mode (pdf first), then latency
        sorted_results = sorted(all_results, key=lambda x: (x.get("mode", "pdf") == "image", x["latency_ms"]))

        n_images = len(BOTTLE_IMAGES)
        for r in sorted_results:
            mode_str = r.get("mode", "pdf").upper()
            if r.get("mode") == "image":
                result = f"{r['valid_count']}/{n_images} read · acc {r['field_accuracy']}"
            else:
                result = f"{r['count']} btl · {len(r['key_found'])}/{len(PDF_KEY_BOTTLES)} keys"
            print(
                f"  {r['model']:<38} "
                f"{mode_str:>6} "
                f"{result:>20} "
                f"{r['latency_ms']:>6}"
            )
        print("=" * 80 + "\n")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Benchmark LM Studio models against extraction pipelines (PDF + Image).",
    )
    parser.add_argument(
        "-m", "--model",
        help="Single model key to benchmark. Omit to run all models in ALL_MODELS.",
    )
    parser.add_argument(
        "--mode",
        choices=["pdf", "image", "both"],
        default="both",
        help="Which extraction mode to test (default: both)",
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
    asyncio.run(main(models_to_run, mode=args.mode))
