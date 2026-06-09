"""
Evaluate the current auto-crop pipeline against every bottle in data/media/bottles/.

For each bottle, runs the LabelImageProcessor detection chain (text-based OCR,
then OpenCV contour fallback) on a *copy* of the current label image, captures
which detector won and what bounds it returned, then writes a side-by-side
HTML report so the user can annotate each result as
    perfect | acceptable | too tight | too loose | wrong region | failed

The annotation UI persists to localStorage and exports JSON. Re-running the
script with a different detector (later, when we wire one up) produces a
comparable run we can diff against this baseline.

Usage (run from project root):
    uv run --env-file .env python scripts/eval_auto_crop.py
    uv run --env-file .env python scripts/eval_auto_crop.py --media data/media/bottles --out data/eval/auto-crop
    uv run --env-file .env python scripts/eval_auto_crop.py --bottle-ids 1,5,10
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from html import escape
from io import BytesIO
from pathlib import Path

from loguru import logger as _logger

_logger.remove()
_logger.add(sys.stderr, level="WARNING")

from PIL import Image, ImageOps

from reserve_automation.utils.label_processor import LabelImageProcessor

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MEDIA = REPO_ROOT / "data" / "media" / "bottles"
DEFAULT_OUT = REPO_ROOT / "data" / "eval" / "auto-crop"


def discover_bottles(media_dir: Path) -> list[tuple[str, Path]]:
    """Return [(bottle_id, label_path), ...] for every bottle with a usable label."""
    bottles: list[tuple[str, Path]] = []
    for child in sorted(media_dir.iterdir(), key=lambda p: int(p.name) if p.name.isdigit() else 1 << 30):
        if not child.is_dir():
            continue
        # Prefer the original backup if one exists, else the current label.
        candidates = sorted(child.glob("label_original*")) + [child / "label.jpg", child / "label.png"]
        for cand in candidates:
            if cand.exists():
                bottles.append((child.name, cand))
                break
    return bottles


def run_detection_chain(processor: LabelImageProcessor, image_bytes: bytes) -> dict:
    """Run the same detection chain crop_to_label uses, but return metadata.

    Mirrors label_processor.crop_to_label:
      1. Normalize EXIF.
      2. detect_label_bounds_text (pytesseract).
      3. detect_label_bounds_cv (OpenCV contours) if text-based fails.
    """
    start = time.perf_counter()
    normalized = processor.normalize_image_orientation(image_bytes)

    detector = None
    bounds = None
    error = None

    t0 = time.perf_counter()
    try:
        bounds = processor.detect_label_bounds_text(normalized)
        if bounds:
            detector = "text"
    except Exception as e:
        error = f"text detector error: {e}"
    text_ms = (time.perf_counter() - t0) * 1000

    cv_ms = None
    if bounds is None:
        t0 = time.perf_counter()
        try:
            bounds = processor.detect_label_bounds_cv(normalized)
            if bounds:
                detector = "cv"
        except Exception as e:
            error = f"cv detector error: {e}"
        cv_ms = (time.perf_counter() - t0) * 1000

    total_ms = (time.perf_counter() - start) * 1000
    return {
        "normalized_bytes": normalized,
        "detector": detector,
        "bounds": list(bounds) if bounds else None,
        "text_ms": round(text_ms, 1),
        "cv_ms": round(cv_ms, 1) if cv_ms is not None else None,
        "total_ms": round(total_ms, 1),
        "error": error,
    }


async def run_detection_llm(processor: LabelImageProcessor, image_bytes: bytes, bottle) -> dict:
    """Run the LLM-based bbox detection (Qwen3-VL via LM Studio)."""
    start = time.perf_counter()
    normalized = processor.normalize_image_orientation(image_bytes)
    error = None
    bounds = None
    try:
        bounds = await processor.detect_label_bounds(normalized, bottle)
    except Exception as e:
        error = f"llm detector error: {e}"
    total_ms = (time.perf_counter() - start) * 1000
    return {
        "normalized_bytes": normalized,
        "detector": "llm" if bounds else None,
        "bounds": list(bounds) if bounds else None,
        "text_ms": None,
        "cv_ms": None,
        "total_ms": round(total_ms, 1),
        "error": error,
    }


async def run_detection_llm_downsampled(
    processor: LabelImageProcessor, image_bytes: bytes, bottle, max_dim: int = 1024
) -> dict:
    """LLM detection with the image downsampled to max_dim before sending.

    Bounds returned by the LLM are in the downsampled coordinate space; we
    scale them back to the original image's pixel space so the crop is applied
    at full resolution.
    """
    start = time.perf_counter()
    normalized = processor.normalize_image_orientation(image_bytes)

    orig_img = Image.open(BytesIO(normalized))
    orig_w, orig_h = orig_img.size
    long_side = max(orig_w, orig_h)

    error = None
    bounds = None
    downsampled = long_side > max_dim
    scale = 1.0

    try:
        if downsampled:
            scale = long_side / max_dim
            small = orig_img.copy()
            small.thumbnail((max_dim, max_dim), Image.LANCZOS)
            if small.mode != "RGB":
                small = small.convert("RGB")
            buf = BytesIO()
            small.save(buf, format="JPEG", quality=92)
            small_bytes = buf.getvalue()

            # Call the underlying detect_label_bounds against the *small* image.
            # It will report bounds in small-image coordinates and clamp to small dims.
            small_bounds = await processor.detect_label_bounds(small_bytes, bottle)
            if small_bounds:
                sx, sy, sw, sh = small_bounds
                # Scale back to original dims and clamp.
                x = max(0, int(round(sx * scale)))
                y = max(0, int(round(sy * scale)))
                w = min(orig_w - x, int(round(sw * scale)))
                h = min(orig_h - y, int(round(sh * scale)))
                if w > 0 and h > 0:
                    bounds = (x, y, w, h)
        else:
            bounds = await processor.detect_label_bounds(normalized, bottle)
    except Exception as e:
        error = f"llm-ds detector error: {e}"

    total_ms = (time.perf_counter() - start) * 1000
    return {
        "normalized_bytes": normalized,
        "detector": "llm-ds" if bounds else None,
        "bounds": list(bounds) if bounds else None,
        "text_ms": None,
        "cv_ms": None,
        "total_ms": round(total_ms, 1),
        "error": error,
        "downsampled": downsampled,
        "scale": round(scale, 2),
    }


def apply_crop(normalized_bytes: bytes, bounds: tuple[int, int, int, int] | None, out_path: Path) -> tuple[int, int]:
    """Write the cropped (or normalized fallback) image, return final (w, h)."""
    img = Image.open(BytesIO(normalized_bytes))
    if bounds is None:
        # No detector succeeded — save the EXIF-normalized image as the "result".
        img.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True)
        return img.size

    x, y, w, h = bounds
    box = (x, y, x + w, y + h)
    if box[0] < 0 or box[1] < 0 or box[2] > img.width or box[3] > img.height:
        # Detector returned out-of-bounds — fall back to normalized.
        img.convert("RGB").save(out_path, "JPEG", quality=92, optimize=True)
        return img.size

    cropped = img.crop(box)
    if cropped.mode != "RGB":
        cropped = cropped.convert("RGB")
    cropped.save(out_path, "JPEG", quality=92, optimize=True)
    return cropped.size


def make_thumb(src: Path, dst: Path, max_dim: int = 600) -> None:
    img = Image.open(src)
    img.thumbnail((max_dim, max_dim))
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(dst, "JPEG", quality=85, optimize=True)


def render_report(out_dir: Path, results: list[dict], run_id: str) -> Path:
    """Write report.html with the annotation UI."""
    rows_html = []
    for r in results:
        bid = r["bottle_id"]
        bounds_str = ", ".join(str(v) for v in r["bounds"]) if r["bounds"] else "—"
        detector_label = r["detector"] or "none"
        in_size = f"{r['input_size'][0]}×{r['input_size'][1]}"
        out_size = f"{r['output_size'][0]}×{r['output_size'][1]}"
        err = f'<div class="err">⚠ {escape(r["error"])}</div>' if r.get("error") else ""

        rows_html.append(f"""
<div class="row" data-bottle="{escape(bid)}">
  <div class="meta">
    <div class="bid">Bottle {escape(bid)}</div>
    <div class="kv"><span>detector:</span> <b>{escape(detector_label)}</b></div>
    <div class="kv"><span>bounds:</span> <code>{escape(bounds_str)}</code></div>
    <div class="kv"><span>input:</span> <code>{in_size}</code></div>
    <div class="kv"><span>output:</span> <code>{out_size}</code></div>
    <div class="kv"><span>time:</span> <code>{r['total_ms']} ms</code></div>
    {err}
  </div>
  <div class="img-pair">
    <figure>
      <img src="bottles/{escape(bid)}/input_thumb.jpg" loading="lazy" />
      <figcaption>input</figcaption>
    </figure>
    <figure>
      <img src="bottles/{escape(bid)}/auto_crop_thumb.jpg" loading="lazy" />
      <figcaption>auto-crop</figcaption>
    </figure>
  </div>
  <div class="annot">
    <label><input type="radio" name="a-{escape(bid)}" value="perfect"> <kbd>1</kbd> perfect</label>
    <label><input type="radio" name="a-{escape(bid)}" value="acceptable"> <kbd>2</kbd> acceptable</label>
    <label><input type="radio" name="a-{escape(bid)}" value="too_tight"> <kbd>3</kbd> too tight (cut)</label>
    <label><input type="radio" name="a-{escape(bid)}" value="too_loose"> <kbd>4</kbd> too loose (bg)</label>
    <label><input type="radio" name="a-{escape(bid)}" value="wrong_region"> <kbd>5</kbd> wrong region</label>
    <label><input type="radio" name="a-{escape(bid)}" value="failed"> <kbd>6</kbd> failed/no-op</label>
  </div>
</div>
""")

    html = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Auto-crop eval — {escape(run_id)}</title>
<style>
  body {{ font: 14px/1.4 system-ui, sans-serif; margin: 0; padding: 0; background:#0f1115; color:#e4e4e7; }}
  header {{ position: sticky; top: 0; background:#1a1d24; padding: 12px 20px; border-bottom: 1px solid #2a2e38; z-index: 10; display: flex; gap: 18px; align-items: center; flex-wrap: wrap; }}
  header h1 {{ font-size: 16px; margin: 0; }}
  header .summary {{ font-size: 13px; color: #9ca3af; }}
  header .summary b {{ color:#e4e4e7; }}
  header button {{ background:#2563eb; color:white; border:0; padding: 6px 12px; border-radius: 4px; cursor:pointer; font-size: 13px; }}
  header button.secondary {{ background:#374151; }}
  header label.filter {{ font-size: 13px; color: #9ca3af; display: inline-flex; gap: 6px; align-items: center; cursor: pointer; }}
  .row {{ display: grid; grid-template-columns: 220px 1fr 220px; gap: 16px; padding: 14px 20px; border-bottom: 1px solid #1f232b; align-items: start; }}
  .row.done {{ opacity: 0.45; }}
  .row.hidden {{ display: none; }}
  .meta .bid {{ font-weight: 600; font-size: 15px; margin-bottom: 6px; }}
  .meta .kv {{ font-size: 12px; color:#9ca3af; margin-bottom: 2px; }}
  .meta .kv span {{ color:#6b7280; }}
  .meta .kv b {{ color:#fbbf24; }}
  .meta code {{ font-size: 11px; color:#cbd5e1; background:#1a1d24; padding: 1px 4px; border-radius: 3px; }}
  .meta .err {{ color:#f87171; font-size: 12px; margin-top: 6px; }}
  .img-pair {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  figure {{ margin: 0; text-align: center; }}
  figure img {{ max-width: 100%; max-height: 360px; background:#1a1d24; border: 1px solid #2a2e38; cursor: zoom-in; }}
  figcaption {{ font-size: 11px; color:#6b7280; margin-top: 4px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .annot {{ display: flex; flex-direction: column; gap: 4px; font-size: 13px; }}
  .annot label {{ padding: 4px 8px; border-radius: 4px; cursor: pointer; user-select: none; }}
  .annot label:hover {{ background:#1f232b; }}
  .annot kbd {{ background:#374151; color:#e4e4e7; padding: 1px 6px; border-radius: 3px; font-size: 11px; font-family: ui-monospace, monospace; }}
  .annot input:checked + kbd {{ background:#2563eb; }}
  .annot input {{ margin-right: 4px; }}
  .lightbox {{ position: fixed; inset: 0; background: rgba(0,0,0,0.92); display: none; align-items: center; justify-content: center; z-index: 100; cursor: zoom-out; }}
  .lightbox.open {{ display: flex; }}
  .lightbox img {{ max-width: 95vw; max-height: 95vh; }}
</style>
</head>
<body>
<header>
  <h1>Auto-crop eval</h1>
  <div class="summary">run <b>{escape(run_id)}</b> · <b id="annot-count">0</b> / <b id="total-count">{len(results)}</b> annotated · <span id="breakdown"></span></div>
  <label class="filter"><input type="checkbox" id="hide-done"> hide annotated</label>
  <button onclick="exportJson()">Export JSON</button>
  <button class="secondary" onclick="clearAll()">Clear annotations</button>
</header>

{''.join(rows_html)}

<div class="lightbox" onclick="this.classList.remove('open')"><img id="lb-img"></div>

<script>
const RUN_ID = {json.dumps(run_id)};
const STORAGE_KEY = "auto-crop-eval:" + RUN_ID;
const CATEGORIES = ["perfect","acceptable","too_tight","too_loose","wrong_region","failed"];

function load() {{
  try {{ return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{{}}"); }} catch {{ return {{}}; }}
}}
function save(state) {{
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}}

let state = load();

function applyState() {{
  for (const row of document.querySelectorAll(".row")) {{
    const bid = row.dataset.bottle;
    const val = state[bid];
    if (val) {{
      const input = row.querySelector(`input[value="${{val}}"]`);
      if (input) input.checked = true;
      row.classList.add("done");
    }}
  }}
  updateSummary();
  applyFilter();
}}

function updateSummary() {{
  const counts = Object.fromEntries(CATEGORIES.map(c => [c, 0]));
  for (const v of Object.values(state)) {{
    if (counts[v] !== undefined) counts[v]++;
  }}
  document.getElementById("annot-count").textContent = Object.keys(state).length;
  const bd = CATEGORIES.map(c => `${{c}}=${{counts[c]}}`).join(" · ");
  document.getElementById("breakdown").textContent = bd;
}}

function applyFilter() {{
  const hide = document.getElementById("hide-done").checked;
  for (const row of document.querySelectorAll(".row")) {{
    row.classList.toggle("hidden", hide && row.classList.contains("done"));
  }}
}}

document.addEventListener("change", (e) => {{
  if (e.target.tagName !== "INPUT" || e.target.type !== "radio") return;
  const row = e.target.closest(".row");
  if (!row) return;
  state[row.dataset.bottle] = e.target.value;
  save(state);
  row.classList.add("done");
  updateSummary();
  applyFilter();
}});

document.getElementById("hide-done").addEventListener("change", applyFilter);

// Keyboard shortcuts: 1-6 select category for the row currently nearest the viewport center.
document.addEventListener("keydown", (e) => {{
  if (e.target.matches("input,textarea")) return;
  const map = {{"1":"perfect","2":"acceptable","3":"too_tight","4":"too_loose","5":"wrong_region","6":"failed"}};
  const cat = map[e.key];
  if (!cat) return;
  const rows = [...document.querySelectorAll(".row:not(.hidden)")];
  const mid = window.innerHeight / 2 + window.scrollY;
  let nearest = rows[0]; let bestDist = Infinity;
  for (const r of rows) {{
    const top = r.offsetTop;
    const d = Math.abs(top + r.offsetHeight/2 - mid);
    if (d < bestDist) {{ bestDist = d; nearest = r; }}
  }}
  if (!nearest) return;
  const input = nearest.querySelector(`input[value="${{cat}}"]`);
  if (input) {{ input.checked = true; input.dispatchEvent(new Event("change", {{bubbles:true}})); }}
}});

// Lightbox on image click.
document.addEventListener("click", (e) => {{
  if (e.target.tagName === "IMG" && e.target.closest("figure")) {{
    document.getElementById("lb-img").src = e.target.src.replace("_thumb", "");
    document.querySelector(".lightbox").classList.add("open");
  }}
}});

function exportJson() {{
  const payload = {{
    run_id: RUN_ID,
    exported_at: new Date().toISOString(),
    annotations: state,
  }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{type:"application/json"}});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `annotations-${{RUN_ID}}.json`;
  a.click();
  URL.revokeObjectURL(url);
}}

function clearAll() {{
  if (!confirm("Clear all annotations for this run?")) return;
  state = {{}};
  save(state);
  for (const r of document.querySelectorAll(".row")) r.classList.remove("done");
  for (const i of document.querySelectorAll("input[type=radio]")) i.checked = false;
  updateSummary();
  applyFilter();
}}

applyState();
</script>
</body>
</html>
"""
    report_path = out_dir / "report.html"
    report_path.write_text(html)
    return report_path


def _build_llm_gateway(vision_model_override: str | None):
    """Load config, force lm_studio_vision to use a real vision model, build gateway."""
    from reserve_automation.core.config import Config
    from reserve_automation.llm.gateway import LLMGateway

    config = Config.load()
    # The user's user.yaml has lm_studio_vision pointing at a text-only model
    # ("qwen/qwen3.5-9b"). Override to a real vision model just for this run.
    if vision_model_override:
        providers = config.llm.setdefault("providers", {})
        vision = providers.setdefault("lm_studio_vision", {})
        vision["model"] = vision_model_override
        # If user.yaml's lm_studio_vision base_url isn't reachable from where we
        # run, fall back to localhost. We're running on the same WSL host that
        # already responded to a curl on localhost:1234 during smoke checks.
        vision.setdefault("base_url", "http://localhost:1234/v1")
        vision.setdefault("provider", "lm_studio")
    return LLMGateway(config.llm)


_DB_READY = False


def _get_bottle_metadata(bid: str):
    """Load BottleMetadata from the DB for prompt context. Returns a stub on failure."""
    from reserve_automation.core.models import BottleMetadata
    global _DB_READY

    try:
        import os

        from reserve_automation.db.engine import get_db, init_db
        from reserve_automation.db.repositories.bottle_repo import SQLiteBottleRepository

        if not _DB_READY:
            url = os.environ.get("DATABASE_URL", "sqlite:///data/reserve.db")
            init_db(url)
            _DB_READY = True

        gen = get_db()
        db = next(gen)
        try:
            repo = SQLiteBottleRepository(db)
            bottle = repo.get_by_id(int(bid))
            if bottle is not None:
                return bottle
        finally:
            try:
                next(gen)
            except StopIteration:
                pass
    except Exception as e:
        print(f"    (couldn't load bottle {bid} from DB: {e})", file=sys.stderr)

    return BottleMetadata(producer="Unknown", name="bottle", type="wine")


async def _process_bottle_async(processor, bid, label_path, bottle_out, mode):
    """Run detection for one bottle. Returns (input_size, detection)."""
    image_bytes = label_path.read_bytes()
    input_copy = bottle_out / "input.jpg"
    img = Image.open(BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    img.save(input_copy, "JPEG", quality=92, optimize=True)
    input_size = img.size

    if mode == "llm":
        bottle = _get_bottle_metadata(bid)
        detection = await run_detection_llm(processor, image_bytes, bottle)
    elif mode == "llm-ds":
        bottle = _get_bottle_metadata(bid)
        detection = await run_detection_llm_downsampled(processor, image_bytes, bottle)
    else:
        detection = run_detection_chain(processor, image_bytes)

    return input_copy, input_size, detection


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--media", type=Path, default=DEFAULT_MEDIA, help="Bottle media dir (default: data/media/bottles)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output root (default: data/eval/auto-crop)")
    ap.add_argument("--bottle-ids", type=str, default=None, help="Comma-separated bottle IDs to evaluate (default: all)")
    ap.add_argument("--run-id", type=str, default=None, help="Override run ID (default: timestamp)")
    ap.add_argument("--detector", choices=["chain", "llm", "llm-ds"], default="chain",
                    help="chain = pytesseract→OpenCV (current pipeline); "
                         "llm = vision LLM bbox at full resolution; "
                         "llm-ds = vision LLM bbox with images downsampled to 1024px max")
    ap.add_argument("--vision-model", type=str, default="qwen/qwen3-vl-8b",
                    help="LM Studio vision model id (only used for --detector llm)")
    args = ap.parse_args()

    if not args.media.exists():
        print(f"ERROR: media dir does not exist: {args.media}", file=sys.stderr)
        return 2

    bottles = discover_bottles(args.media)
    if args.bottle_ids:
        wanted = {b.strip() for b in args.bottle_ids.split(",") if b.strip()}
        bottles = [(bid, p) for bid, p in bottles if bid in wanted]

    if not bottles:
        print("No bottles found with label images.", file=sys.stderr)
        return 1

    run_id = args.run_id or datetime.now().strftime("%Y%m%d-%H%M%S")
    if args.detector != "chain":
        run_id = f"{run_id}-{args.detector}"
    out_dir = args.out / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.detector in ("llm", "llm-ds"):
        llm = _build_llm_gateway(args.vision_model)
        processor = LabelImageProcessor(llm_gateway=llm)
        suffix = " (downsampled to 1024px)" if args.detector == "llm-ds" else ""
        print(f"LLM detector: {args.vision_model} via lm_studio_vision{suffix}")
    else:
        processor = LabelImageProcessor(llm_gateway=None)  # type: ignore[arg-type]

    print(f"Eval run: {run_id}")
    print(f"Output:   {out_dir}")
    print(f"Bottles:  {len(bottles)}")
    print()

    results = []

    async def run_all():
        for i, (bid, label_path) in enumerate(bottles, 1):
            bottle_out = out_dir / "bottles" / bid
            bottle_out.mkdir(parents=True, exist_ok=True)
            try:
                _, input_size, detection = await _process_bottle_async(
                    processor, bid, label_path, bottle_out, args.detector
                )
                auto_crop_path = bottle_out / "auto_crop.jpg"
                bounds_tuple = tuple(detection["bounds"]) if detection["bounds"] else None
                output_size = apply_crop(detection["normalized_bytes"], bounds_tuple, auto_crop_path)

                make_thumb(bottle_out / "input.jpg", bottle_out / "input_thumb.jpg")
                make_thumb(auto_crop_path, bottle_out / "auto_crop_thumb.jpg")

                result = {
                    "bottle_id": bid,
                    "source_path": str(label_path.relative_to(REPO_ROOT)),
                    "input_size": list(input_size),
                    "output_size": list(output_size),
                    "detector": detection["detector"],
                    "bounds": detection["bounds"],
                    "text_ms": detection.get("text_ms"),
                    "cv_ms": detection.get("cv_ms"),
                    "total_ms": detection["total_ms"],
                    "error": detection["error"],
                }
                results.append(result)
                tag = detection["detector"] or "NONE"
                err_tag = f"  ⚠ {detection['error']}" if detection.get("error") else ""
                print(f"  [{i:>3}/{len(bottles)}] bottle {bid:>4}  {tag:<5}  {detection['total_ms']:>6.0f}ms  {input_size[0]}×{input_size[1]} → {output_size[0]}×{output_size[1]}{err_tag}")
            except Exception as e:
                print(f"  [{i:>3}/{len(bottles)}] bottle {bid:>4}  ERROR: {e}", file=sys.stderr)
                results.append({"bottle_id": bid, "error": str(e), "detector": None, "bounds": None,
                                "input_size": [0, 0], "output_size": [0, 0], "text_ms": 0, "cv_ms": 0, "total_ms": 0,
                                "source_path": str(label_path)})

    asyncio.run(run_all())

    # Save run metadata
    metadata = {
        "run_id": run_id,
        "timestamp": datetime.now().isoformat(),
        "media_dir": str(args.media),
        "bottle_count": len(bottles),
        "detector_chain": [args.detector] if args.detector in ("llm", "llm-ds") else ["text", "cv"],
        "vision_model": args.vision_model if args.detector in ("llm", "llm-ds") else None,
        "results": results,
    }
    (out_dir / "run.json").write_text(json.dumps(metadata, indent=2))

    report_path = render_report(out_dir, results, run_id)

    # Summary
    by_detector = {}
    for r in results:
        d = r.get("detector") or "none"
        by_detector[d] = by_detector.get(d, 0) + 1
    print()
    print("Detector breakdown:")
    for d, c in sorted(by_detector.items(), key=lambda kv: -kv[1]):
        print(f"  {d:<6} {c:>3}  ({c*100/len(results):.0f}%)")
    print()
    print(f"Report: {report_path}")
    print("Open it in a browser and annotate (keyboard: 1-6).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
