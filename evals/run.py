"""The Reserve's model eval suite (model-eval contract 1).

The household runs every AI app on one shared LM Studio box; `model-eval run
<model>` (workbench) runs this suite, and every other app's, to decide whether a
model is better or worse *for this app* than the one it uses today. The contract
lives in proxmox/model-eval/README.md. This file owns Reserve's side:

- It drives the prod code path: `ExtractionService` (web/services), the same
  object the upload and tasting routes call, so label crop + 768px read, manifest
  parsing and tasting-card extraction all run as in prod. No DB, no routes.
- Config = config/default.yaml + an override written here (the local
  config/user.yaml is NOT read): both LM Studio providers point at the
  model-eval proxy with the model under test, and **fallback is off**. Prod
  falls back to Claude Sonnet, which would hide a local-model failure.
- Fixtures are the repo's own ground-truth sets (tests/fixtures/...): retail
  bottle-label photos and a store manifest, which the judge may see, and tasting
  cards (a family member's handwritten notes), which it may not. Scoring for
  labels and the manifest is reused from tests/manual/bench_models.py.

Run it through model-eval (it needs the proxy's env):
    model-eval run <model> --apps reserve [--cases label/bourbon_001]
"""
import asyncio
import importlib.util
import json
import os
import re
import sys
import time
import traceback
import urllib.request
from pathlib import Path

if "MODEL_EVAL_BASE_URL" not in os.environ:
    sys.exit("run this through `model-eval run <model> --apps reserve` (it sets MODEL_EVAL_*)")

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)  # Config.load() reads config/default.yaml relative to cwd

MODEL = os.environ.get("MODEL_EVAL_MODEL", "model-eval")
OUT = Path(os.environ["MODEL_EVAL_OUT"])
CONTROL = os.environ["MODEL_EVAL_CONTROL"]
ONLY = set(filter(None, os.environ.get("MODEL_EVAL_CASES", "").split(",")))

# Prod sets RESERVE_LM_STUDIO_URL (overrides every lm_studio provider's base_url).
os.environ["RESERVE_LM_STUDIO_URL"] = os.environ["MODEL_EVAL_BASE_URL"]
os.environ["LM_STUDIO_API_KEY"] = os.environ.get("MODEL_EVAL_API_KEY", "")  # proxy adds the real one
for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "LLMWHISPERER_API_KEY"):
    os.environ.pop(var, None)

from loguru import logger  # noqa: E402

logger.remove()
logger.add(sys.stderr, level="WARNING")

from reserve_automation.core.config import Config  # noqa: E402
from reserve_automation.web.services.extraction_service import ExtractionService  # noqa: E402

_spec = importlib.util.spec_from_file_location("bench_models", ROOT / "tests/manual/bench_models.py")
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)  # import only: no LM Studio calls at import time

LABELS = ["bourbon_001.jpg", "wine_001.jpg", "bourbon_002.jpg", "wine_002.jpg",
          "hard_damilano_97.jpg", "wine_003.jpg", "hard_stagg_58.jpg", "hard_feudomontoni_91.jpg"]
TASTING_DIR = ROOT / "tests/fixtures/tasting_cards"
TASTINGS = ["aws_wine_test_001", "bourbon_test_001", "bourbon_test_002"]
MANIFEST_EXPECTED = ROOT / "tests/fixtures/manifests/wine_manifest_expected.json"


def make_service() -> ExtractionService:
    override = {
        "llm": {
            "providers": {"lm_studio_vision": {"model": MODEL}, "lm_studio_text": {"model": MODEL}},
            "fallback": {"enabled": False},
        },
        "extraction": {"llm_whisperer": {"api_key": None}},
    }
    path = OUT / "reserve-eval-config.yaml"
    path.write_text(json.dumps(override))  # JSON is valid YAML
    return ExtractionService(Config.load(config_file=path))


def mark(workflow, case, timeout_s=None):
    body = {"workflow": workflow, "case": case, "timeout_s": timeout_s}
    req = urllib.request.Request(f"{CONTROL}/_case", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=30).read()


def score(checks, critical):
    vals = [bool(v) for v in checks.values()]
    return (all(checks.get(k) for k in critical), round(sum(vals) / len(vals), 3) if vals else 0.0)


def alnum(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower()) if s else ""


def words(s) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", str(s or "").lower()) if len(w) > 2}


def bottle_view(b) -> dict:
    keep = ("producer", "name", "year", "beverage_type", "country", "region", "variety", "style",
            "abv", "proof", "age_statement")
    d = b.model_dump(mode="json") if hasattr(b, "model_dump") else dict(b)
    return {k: d.get(k) for k in keep if d.get(k) not in (None, "", [])}


# ---------------------------------------------------------------- workflows

async def wf_label(svc, name):
    gt = bench.IMAGE_GROUND_TRUTH[name]
    bottle, _meta = await svc.extract_bottle_from_image(image_path=bench.BOTTLE_DIR / name,
                                                        beverage_type="auto")
    s = bench._score_label(gt, bottle)
    checks = {"producer": s["producer"], "name": s["name"], "type": s["type"]}
    if s["year"] is not None:
        checks["year"] = s["year"]
    ok, sc = score(checks, ["producer", "name"])
    expect = (f"Retail bottle-label photo ({gt['difficulty']} to read). A correct read names producer "
              f"~{gt['producer_kw']}, name ~{gt['name_kw']}, vintage {gt['year'] or 'none on label'}, "
              f"type ~{gt['type_kw']}.")
    judge = {"input": expect, "output": json.dumps(bottle_view(bottle), ensure_ascii=False)}
    return {"ok": ok, "score": sc, "checks": checks, "judge": judge, "error": None}


async def wf_manifest(svc, _case):
    expected = json.loads(MANIFEST_EXPECTED.read_text())
    bottles = await svc.extract_bottles_from_manifest(file_path=bench.MANIFEST_PATH,
                                                      beverage_type="auto", expected_count=None)
    labels = {f"{b.producer} - {b.name}" for b in bottles}
    key_found = [k for k in bench.PDF_KEY_BOTTLES if bench._key_matches(k, labels)]

    def find(exp):  # match an expected bottle by producer, else by a shared name word
        for b in bottles:
            if alnum(exp["producer"])[:8] and alnum(exp["producer"])[:8] in alnum(b.producer):
                return b
        for b in bottles:
            if words(exp["name"]) & words(f"{b.producer} {b.name}"):
                return b
        return None

    matched = [(e, find(e)) for e in expected]
    found = [(e, b) for e, b in matched if b is not None]
    years_ok = sum(1 for e, b in found if (str(e["year"]) if e["year"] else None) == (str(b.year) if b.year else None))
    checks = {
        "count": len(bottles) == len(expected),
        "key_bottles": len(key_found) == len(bench.PDF_KEY_BOTTLES),
        "matched": len(found) >= len(expected) - 1,
        "years": years_ok >= 0.8 * len(expected),
    }
    ok, sc = score(checks, ["count", "key_bottles"])
    err = None if ok else (f"{len(bottles)} bottles (want {len(expected)}), key {len(key_found)}/"
                           f"{len(bench.PDF_KEY_BOTTLES)}, years {years_ok}/{len(expected)}")
    judge = {"input": "Store purchase manifest (PDF) listing 12 wines: "
                      + "; ".join(f"{e['producer']} {e['name']} {e['year'] or ''}" for e in expected),
             "output": "\n".join(json.dumps(bottle_view(b), ensure_ascii=False) for b in bottles)}
    return {"ok": ok, "score": sc, "checks": checks, "judge": judge, "error": err}


SCORE_FIELDS = ("wine_appearance", "wine_aroma", "wine_taste", "wine_aftertaste", "wine_overall",
                "whiskey_nose", "whiskey_palate", "whiskey_finish", "whiskey_overall")
NOTE_FIELDS = ("nose_notes", "palate_notes", "finish_notes")


async def wf_tasting(svc, fixture):
    gt = json.loads((TASTING_DIR / f"{fixture}.json").read_text())
    exp = gt["expected_output"]
    res = await svc.extract_tasting_card(image_path=TASTING_DIR / gt["image_file"],
                                         template_type=gt["template_type"])
    got = res.tastings
    names = scores = notes = n_scores = n_notes = 0
    for i, e in enumerate(exp["tastings"]):
        a = got[i] if i < len(got) else None
        if a is None:
            n_scores += sum(1 for f in SCORE_FIELDS if e.get(f) is not None)
            n_notes += sum(len(e.get(f) or []) for f in NOTE_FIELDS)
            continue
        ew = words(e["bottle_name"])
        names += len(ew & words(a.bottle_name)) >= max(1, len(ew) // 2)
        for f in SCORE_FIELDS:
            if e.get(f) is not None:
                n_scores += 1
                v = getattr(a, f, None)
                scores += v is not None and abs(float(v) - float(e[f])) <= 0.25
        for f in NOTE_FIELDS:
            hay = alnum(" ".join(getattr(a, f, None) or []))
            for note in e.get(f) or []:
                n_notes += 1
                notes += bool(alnum(note)) and alnum(note) in hay
    n = len(exp["tastings"])
    checks = {
        "count": len(got) == n,
        "names": names == n,
        "scores": n_scores == 0 or scores >= 0.8 * n_scores,
        "notes": n_notes == 0 or notes >= 0.6 * n_notes,
        "taster": bool(got) and alnum(got[0].taster_name) == alnum(exp.get("taster_name")),
    }
    ok, sc = score(checks, ["count", "names", "scores"])
    err = None if ok else f"names {names}/{n}, scores {scores}/{n_scores}, notes {notes}/{n_notes}"
    # No judge: handwritten notes by a family member stay local.
    return {"ok": ok, "score": sc, "checks": checks, "error": err}


WORKFLOWS = [
    {"id": "label", "title": "Bottle-label photo import (crop + read)", "fn": wf_label, "timeout_s": 180,
     "vision": True, "cases": [(n.removesuffix(".jpg"), n) for n in LABELS],
     "judge_rubric": "Fields read from a bottle-label photo for a home spirits/wine collection. Score: "
                     "producer, name and vintage right (most important); no invented fields; useful extras "
                     "(region, variety, ABV/proof, age) only when they're really on such a label."},
    {"id": "manifest", "title": "Purchase manifest (PDF) to bottles", "fn": wf_manifest, "timeout_s": 120,
     "vision": False, "cases": [("wine-store-12", None)],
     "judge_rubric": "Bottles extracted from a store manifest. Score: every listed wine present once, "
                     "producer/name split sensibly, vintage right; no invented bottles."},
    {"id": "tasting", "title": "Tasting-card photo (handwritten scores + notes)", "fn": wf_tasting,
     "timeout_s": 180, "vision": True, "cases": [(f, f) for f in TASTINGS]},
]


async def main():
    out = {"contract": 1, "app": "reserve", "suite_version": "1", "workflows": []}
    svc = make_service()
    for wf in WORKFLOWS:
        w = {"id": wf["id"], "title": wf["title"], "timeout_s": wf["timeout_s"],
             "requires": {"vision": wf["vision"]}, "cases": []}
        if wf.get("judge_rubric"):
            w["judge_rubric"] = wf["judge_rubric"]
        for case_id, arg in wf["cases"]:
            if ONLY and f"{wf['id']}/{case_id}" not in ONLY:
                continue
            mark(wf["id"], case_id, wf["timeout_s"])
            t0 = time.time()
            try:
                res = await wf["fn"](svc, arg)
            except Exception as e:  # noqa: BLE001
                res = {"ok": False, "score": 0.0, "checks": {}, "error": f"{type(e).__name__}: {e}",
                       "trace": traceback.format_exc()[-800:]}
            res["id"] = case_id
            res["wall_s"] = round(time.time() - t0, 2)
            w["cases"].append(res)
            print(f"{wf['id']}/{case_id}: {'ok' if res['ok'] else 'FAIL'} score={res['score']} "
                  f"{res['wall_s']}s {res.get('error') or ''}", flush=True)
        if w["cases"]:
            out["workflows"].append(w)
    mark(None, None)
    (OUT / "result.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
