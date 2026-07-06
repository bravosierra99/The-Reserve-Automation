"""Validation for bottle label images.

Guards the two paths that historically wrote junk into data/media/bottles/:
manifest documents (PDFs) saved as label.jpg, and tiny web thumbnails from
the label-download flow (see docs/GROUND_TRUTH.md #4).
"""

from io import BytesIO
from pathlib import Path
from typing import Tuple, Union

from PIL import Image, UnidentifiedImageError

# Below this, vision extraction produces garbage/hallucinated reads.
MIN_LABEL_LONG_SIDE = 400


def validate_label_image(
    source: Union[bytes, Path],
    min_long_side: int = MIN_LABEL_LONG_SIDE,
) -> Tuple[bool, str]:
    """Check that bytes/file decode as a real raster image of usable size.

    Args:
        source: raw image bytes, or a path to the file on disk
        min_long_side: minimum pixels on the longer side (0 to skip size check)

    Returns:
        (ok, detail) — detail is "WxHpx" on success, or a human-readable
        rejection reason suitable for an HTTP 400 body.
    """

    def _open() -> Image.Image:
        return Image.open(BytesIO(source) if isinstance(source, bytes) else source)

    try:
        img = _open()
        img.verify()  # detects truncated/corrupt data; invalidates img
        width, height = _open().size
    except (UnidentifiedImageError, OSError, ValueError):
        return False, "not a readable image (is it a PDF or corrupt file?)"

    if max(width, height) < min_long_side:
        return False, (
            f"image too small to be a usable label ({width}x{height}px; "
            f"need at least {min_long_side}px on the long side)"
        )

    return True, f"{width}x{height}px"
