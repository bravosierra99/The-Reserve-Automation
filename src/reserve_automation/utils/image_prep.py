"""Shared image preparation for vision-model calls.

#CLAUDE_REQ: Every image handed to a vision model must be encoded through
encode_for_vision(). Label extraction (extractors/image_extractor.py) and
manifest OCR (parsers/image.py) each grew their own encoder; only the label
one learned to downscale, so manifests were shipping full-resolution PNGs to
the vision encoder and timing out. New vision callers belong here, not inline.
"""

import io

from PIL import Image, ImageOps

# Single labels: past ~1536px the vision encoder gains no OCR accuracy
# (verified on the prod-label eval set) while prefill time triples — full-res
# uploads took 130s+ vs ~45s at 1536px.
LABEL_MAX_DIM = 1536

# Multi-bottle documents (manifests, invoices, wine lists). A manifest carries
# far smaller glyphs than a single label (a 12-line list vs one big-print
# label), so squeezing it to LABEL_MAX_DIM risks dropping characters and
# silently extracting fewer bottles.
#
# Measured 2026-08-15 against the live stack (LM Studio + qwen3.5-9b) using a
# real 3024x4032 phone capture of a 13-line City Wine Merchant invoice:
#
#   cap    image tokens   TTFT     accuracy
#   512        232         1.2s    BAD - 6 wrong prices, misspelled producers
#   1024       808         2.3s    13/13 exact
#   1536      1768         5.3s    13/13 exact, 0 price errors
#   2048      3112        55.7s    13/13 exact
#   full-res  3112        56.1s    13/13 exact
#
# Solid conclusions from that table:
#   1. Above ~2048 the cap does nothing — the server clamps to its own vision
#      token budget (3112), so full-res and 2048 are the SAME request.
#   2. 512 is genuinely too small: real misreads, not just slower.
#   3. 1024/1536 both extract the document exactly.
#
# CAVEAT on the timings, recorded honestly: the 2048/full-res rows (~56s) were
# measured EARLY in the session and the 512/1024/1536 rows LATER, and this host
# degrades under sustained load — minutes after the table above, an identical
# 1536 request that had taken 14.9s exceeded 300s until LM Studio was bounced.
# So the apparent 1768->3112 token "cliff" may be partly that drift rather than
# a real threshold. Re-measure 2048 against a freshly restarted engine before
# treating the cliff as fact.
#
# 1536 is kept regardless, because it does not depend on the disputed timing:
# it reads the document exactly, it is never slower than 2048, and it matches
# LABEL_MAX_DIM. Kept as its own constant so a manifest eval can retune it
# without touching the label path.
DOCUMENT_MAX_DIM = 1536


def encode_for_vision(image: Image.Image, max_dim: int = LABEL_MAX_DIM) -> bytes:
    """Normalize a PIL image to JPEG bytes suitable for a vision model.

    Args:
        image: Source image. Never mutated (exif_transpose copies).
        max_dim: Longest-edge cap in pixels. Use LABEL_MAX_DIM for a single
            label, DOCUMENT_MAX_DIM for a multi-bottle document.

    Returns:
        Single-frame JPEG bytes.
    """
    # Apply the EXIF orientation tag before re-saving: phone photos are stored
    # rotated with an orientation flag, and re-saving without honoring it feeds
    # the model a sideways image (the flag itself is dropped by the re-save).
    img = ImageOps.exif_transpose(image)

    # Image tokens scale with pixel count, and prefill time scales with them.
    if max(img.size) > max_dim:
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)

    # Always emit a plain JPEG stream — iPhone HDR captures arrive as MPO
    # (multi-frame JPEG container) and some LM Studio vision decoders choke on
    # it, causing the sampler to collapse into runaway "/" output.
    if img.mode != "RGB":
        img = img.convert("RGB")

    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=95)
    return buffer.getvalue()
