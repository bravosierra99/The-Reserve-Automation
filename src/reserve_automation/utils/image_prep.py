"""Shared image preparation for vision-model calls.

#CLAUDE_REQ: Every image handed to a vision model must be encoded through
encode_for_vision(). Label extraction (extractors/image_extractor.py) and
manifest OCR (parsers/image.py) each grew their own encoder; only the label
one learned to downscale, so manifests were shipping full-resolution PNGs to
the vision encoder and timing out. New vision callers belong here, not inline.
"""

import io

from PIL import Image, ImageOps

# Why these caps are small: the vision encoder's cost grows far faster than
# pixel count, and on the RX 6900 XT (Vulkan, no matrix cores) it is extreme.
# qwen3.5-9b's encoder on that card, one label photo: 768px 4.9s, 1024px 26s,
# 1536px ~165s (Oct 2026). Faster GPUs hide this; the 6900 XT alone does not.
#
# Single labels are read AFTER cropping to the label (extractors/image_extractor
# via LabelImageProcessor.crop_image_to_label), so 768px of label carries as
# much text detail as ~1536px of whole photo. Oct 2026 prod eval, 134 photos,
# 6900 XT only:  crop+768: name 80%, producer 66%, 9.5s median / 11.7s p90.
#                full 1536 (old): name 77%, producer 67%, ~165s on that card.
#                full 768, no crop: name 75%, misreads small print ("Mecher's").
LABEL_MAX_DIM = 768

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
# The erratic timings in that table (and the "cliff") were the encoder-on-6900
# effect described above, not load drift. Re-measured Oct 2026 with the
# encoder on the 6900 XT: same capture at 1024 = 9.1s, 13/13 lines exact; 1536
# would be minutes. Documents are not cropped, so this cap is larger than
# LABEL_MAX_DIM on purpose.
DOCUMENT_MAX_DIM = 1024


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
