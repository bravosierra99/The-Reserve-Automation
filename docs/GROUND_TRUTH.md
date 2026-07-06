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

## 4. Many stored bottle "label.jpg" files are not readable label photos.

As of 2026-07, 39 of 122 prod bottles' `data/media/bottles/{id}/label.jpg` files are
not usable for vision extraction: ~22 are **PDF documents** saved under a .jpg name
(bottles imported from wine-record PDF manifests) and ~17 are **tiny web thumbnails**
(56–320px, from the label-download flow). Only ~83 are real photos.

- Don't benchmark or re-run extraction against stored labels without filtering by
  actual file type and pixel size first — the tiny ones produce garbage/hallucinated
  reads that look like model failures but aren't.
- The media endpoint happily serves these PDFs with a .jpg path.

---

*Add to this file when you learn a fact about the deployed system that the code doesn't
state and that would mislead a future reader who only has the code in front of them.*
