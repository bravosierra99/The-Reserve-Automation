"""Guard rails for LLM vision configuration.

GROUND TRUTH (see docs/GROUND_TRUTH.md): `qwen/qwen3.5-9b` is multimodal — it does
OCR/vision as well as text. This fact has been forgotten and "reasoned away" repeatedly,
causing misdiagnosed upload failures. These tests exist so that a future "helpful fix"
that swaps the vision path onto a text-only model, or that drops qwen3.5-9b from the set
of accepted vision models, trips the suite instead of shipping silently.

The point is NOT to pin one exact model string forever — deployments override the model
in the gitignored user.yaml. The point is to keep the committed default config's vision
routing on a model we *know* can see, and to keep qwen3.5-9b in that known-good set.
"""

from pathlib import Path

import yaml

# Models we have verified can do vision/OCR via LM Studio. qwen3.5-9b belongs here
# because it IS multimodal (do not remove it on the assumption that it is text-only).
KNOWN_VISION_MODELS = {
    "qwen/qwen3-vl-8b",
    "qwen/qwen3.5-9b",
}

# Routing keys whose work requires actually looking at an image.
VISION_ROUTING_KEYS = ("ocr", "structured_extraction")

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "default.yaml"


def _load_default_llm() -> dict:
    with open(DEFAULT_CONFIG_PATH) as f:
        config = yaml.safe_load(f) or {}
    llm: dict = config["llm"]
    return llm


def test_qwen35_9b_is_registered_as_vision_capable():
    """qwen/qwen3.5-9b is multimodal; it must stay in the known-vision allowlist.

    If this fails because someone removed it, the fix is NOT to "agree" the model is
    text-only — it is vision-capable. See docs/GROUND_TRUTH.md fact #1.
    """
    assert "qwen/qwen3.5-9b" in KNOWN_VISION_MODELS


def test_default_vision_routing_resolves_to_a_known_vision_model():
    """Every vision routing key must map to a provider running a known-vision model."""
    llm = _load_default_llm()
    providers = llm["providers"]
    routing = llm["routing"]

    for key in VISION_ROUTING_KEYS:
        provider_name = routing[key]
        model = providers[provider_name]["model"]
        assert model in KNOWN_VISION_MODELS, (
            f"Vision routing key '{key}' -> provider '{provider_name}' uses model "
            f"'{model}', which is not in KNOWN_VISION_MODELS. If that model genuinely "
            f"does vision, add it to the allowlist; do NOT point vision work at a "
            f"text-only model. See docs/GROUND_TRUTH.md."
        )
