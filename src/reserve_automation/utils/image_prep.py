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
# Spot-checked (not a full eval) against a real 3024x4032 phone capture of a
# City Wine Merchant invoice: all 13 line items, vintages and prices stayed
# legible at 2048 through diagonal window glare. 1536 was also readable on that
# sample, but 2048 keeps margin for dimmer light or smaller print while still
# cutting pixel count 3.9x (12.2MP -> 3.1MP), which is most of the prefill win.
# Revisit with a proper manifest eval set before tightening.
DOCUMENT_MAX_DIM = 2048


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
