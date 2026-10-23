# Ground Truth — non-obvious facts about the *running* system

Facts here are about how the **deployed** Reserve actually behaves — things that are
NOT derivable from reading the code, and that have burned us when forgotten or
"reasoned away." This file is committed on purpose: it lives in the repo, shows up in
PRs and on the prod box, and is the canonical source over anyone's (human or AI)
recollection. If something here is wrong, fix it here in the same change.

Rule of thumb: **a fact you have to *remember to believe* belongs in code, config, or a
test — not just in someone's head.** Where each fact below is also enforced by a comment
or test, the location is noted so it can't be quietly violated.

---

## 1. `qwen/qwen3.5-9b` is multimodal (vision + text). It is NOT text-only.

It performs OCR / image analysis as well as text generation. Production points the
`lm_studio_vision` provider at it (`config/user.yaml`), and that is correct.

- **Do not** "fix" a vision provider away from `qwen3.5-9b` to a `*-vl` model on the
  belief that 3.5-9b can't see. It can.
- **Never infer a model's vision capability from its name.** "3.5-9b" looking less
  vision-y than "qwen3-vl-8b" is not evidence of anything.
- The vision/text/agent provider split in `config/default.yaml` is about
  latency/quality tradeoffs, **not** capability.

**Enforced by:** comment block in `config/default.yaml` (above `llm.providers`) and
`tests/test_llm_config_vision.py` (vision routing must resolve to a known-vision model).
History: this fact was repeatedly forgotten and caused misdiagnosis of upload failures.

## 2. Prod LM Studio requires an API key (Bearer token).

LM Studio at `192.168.86.2:1234` has **"Require API Key" enabled** (since 2026-05-22).
Every request must send `Authorization: Bearer <token>` or it 401s.

- The token is read from the `LM_STUDIO_API_KEY` env var, injected into the container by
  docker-compose from `~/reserve/app/.env` on the VM. It tends to fall out during
  env-passthrough reworks — when "prod can't reach LM Studio" recurs, check the env first.
- LM Studio's own log showing `GET /v1/models … Unexpected endpoint … Returning 200
  anyway` is **routing noise**, not success — the real reply to an unauthenticated call
  is a 401.
- Secrets/env are operator-managed in the private homelab repo and are **not** changed
  from this repo (see `CLAUDE.local.md`).

## 3. ANY standalone httpx call to LM Studio must carry the Bearer token — not just the provider.

The `LMStudioProvider` authenticates correctly, so text features kept working while
*uploads* failed. The cause: the bottle-upload pre-flight probe `_poll_for_model` in
`web/routes/bottles/extraction.py` (added by the v1.8.2 fail-fast commit) did a bare
`GET {base_url}/models` with **no Authorization header** → 401 → read as "unreachable" →
the upload aborted *before* the (authed, working) extraction call ever ran. That's why a
working model looked "unreachable" and why it looked vision/model-specific (it was not —
see fact #1).

- If you add a new direct HTTP call to LM Studio anywhere, resolve and send the key the
  same way `LMStudioProvider` does.
- **Enforced by:** `tests/test_bottle_stateless_upload.py::test_poll_for_model_sends_bearer_token`
  and `…_no_token_sends_no_auth_header`.

## 4. Many stored bottle "label.jpg" files were not readable label photos.

As of 2026-07, ~37 of 124 prod bottles' `data/media/bottles/{id}/label.jpg` files were
not usable for vision extraction: ~24 were **purchase-invoice PDFs** saved under a
.jpg name — NOT label photos at all. The manifest upload flow staged the uploaded
document as the temp label and `save.py` attached it to *every* bottle from that
import, so multiple bottles share byte-identical invoice "labels". Another ~13 were
**tiny web thumbnails** (56–320px) saved by the label-download flow with no size
validation.

- Both causes are fixed (v1.12.1): manifest uploads no longer stage a label, and
  `utils/image_validation.py` gates both `save.py` and the download endpoint
  (reject non-images everywhere; reject <400px on download).
  **Enforced by:** `tests/unit/test_image_validation.py` and
  `tests/integration/routes/test_label_hygiene.py`.
- Don't benchmark or re-run extraction against stored labels without filtering by
  actual file type and pixel size first — the tiny ones produce garbage/hallucinated
  reads that look like model failures but aren't.
- The media endpoint happily serves any bytes at a .jpg path.

## 5. Label-import speed: image size on our side, three LM Studio settings on the host.

A label extraction should take ~10s warm and ~20s on a cold first upload. It slowed to
minutes three times (Jul, Aug, Sep–Oct 2026), and each time looked like a model, runtime
or code problem. It was an LM Studio setting on the host (192.168.86.2) reset by an
update or a GUI toggle, compounded by the image size we send.

The host has two GPUs: Vulkan0 = RTX 3060 (Ben's display/gaming card), Vulkan1 =
RX 6900 XT. The model is meant to run on the 6900 XT alone ("Disabled GPUs: [0]").

1. **qwen/qwen3.5-9b must load with `parallel` = 1** (Max Concurrent Predictions).
   Any value > 1 drops its hybrid (Gated DeltaNet) architecture to ~47 prefill / 19
   decode tok/s on Vulkan. With 1 it gets ~780 / 63. The tell is "decode exactly ~19 tok/s".
2. **The vision encoder is very slow on the 6900 XT, and its cost explodes with image
   size.** A photo at 768px takes 4.9s, 1024px 26s, 1536px ~165s (head-dim-72 flash
   attention with no matrix cores). That is why the app crops to the label and reads it at
   768px (`image_prep.LABEL_MAX_DIM`, enforced by `tests/unit/test_image_prep.py`).
   **Never raise those caps to "improve accuracy"** without timing on the 6900 XT.
   The encoder runs on the *first visible* Vulkan device: enabling the 3060 (split
   "evenly", nothing disabled) puts it there at ~2s. That is the fallback if the caps
   ever have to grow, at the cost of ~5GB on the gaming card.
3. Runtime version is NOT the cause. Vulkan 2.42.0 and 2.28.2 both run a label in ~10–12s
   once 1 and 2 are handled. An earlier "2.42 is slow" result was the encoder-on-6900 effect.
4. The 9b's GGUF folder is a junction onto the C: NVMe
   (`C:\Users\ben\.lmstudio\models-nvme\…`). Models on D: sit on a spinning HDD, which
   made a cold load take ~48s whenever the file wasn't in the Windows cache. From the NVMe
   it takes ~8s, so a true first upload (model unloaded) is ~19s.

Diagnose before touching code. A prefill/decode split comes from
`POST /api/v0/chat/completions` (`stats`). Use a *fresh* image every time: re-sending the
same image hits LM Studio's prompt cache and looks fast. Full A/B method and numbers are
in the operator's notes (2026-10-23).

---

*Add to this file when you learn a fact about the deployed system that the code doesn't
state and that would mislead a future reader who only has the code in front of them.*
