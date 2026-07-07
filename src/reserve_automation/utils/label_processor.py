"""Vision-based label quality assessment and cropping.

Auto-crop design (evaluated against real prod bottle photos, July 2026):
- Detection runs on a downscaled copy (max 1024px) via the vision LLM.
- The model is asked for ONE box covering ALL label/text regions on the main
  bottle, in 0-1000 normalized coordinates. Both qwen3-vl-8b and qwen3.5-9b
  consistently emit Qwen-grounding-style 0-1000 normalized boxes regardless of
  prompt wording, so normalized coords are the reliable contract — never ask
  for or assume absolute pixels.
- The box is scaled to the full-res image, padded, clamped, sanity-checked,
  and applied. Any failure falls back to the EXIF-normalized original image
  (a skipped crop is always better than a wrong crop).

The previous pytesseract/OpenCV detection was removed: on a 17-image eval of
real prod photos it returned essentially the full frame 15/17 times (background
clutter produces spurious OCR boxes), which made auto-crop a silent no-op.
"""

import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image, ImageOps

from ..core.exceptions import LLMProviderNotFoundError
from ..core.models import BottleMetadata
from ..llm.gateway import LLMGateway

logger = logging.getLogger(__name__)

# One box covering every label/text region on the main bottle. 0-1000
# normalized coords — see module docstring; do not switch to absolute pixels.
LABEL_BBOX_PROMPT = (
    "Look at the main bottle in the foreground of this image. Find ALL of its labels and "
    "printed text regions: the front label, any neck or shoulder label, any bottom strip label, "
    "and any text printed, etched, or handwritten directly on the glass. "
    "Return ONE bounding box that covers ALL of these text regions together (ignore other "
    "bottles in the background). "
    "The box must NEVER pass through printed text: if you are unsure about an edge, move it "
    "OUTWARD. It is always better to include extra background than to cut off any text. "
    "Use a coordinate system where the top-left of the image is (0,0) and the bottom-right is "
    '(1000,1000). Return ONLY JSON: {"bbox_2d": [x1, y1, x2, y2]} with all values 0-1000.'
)


class LabelImageProcessor:
    """Process bottle label images using a vision LLM."""

    # Max dimension of the downscaled copy sent for detection. 1024 keeps
    # detection fast without hurting box accuracy (boxes are normalized).
    DETECTION_MAX_DIM = 1024
    # Padding added around the detected box, as a fraction of box size.
    # Covers the model's tendency to place edges exactly on the text.
    PADDING_FRAC = 0.05
    # A detected box smaller than this fraction of the image area is treated
    # as a detection failure (a real label crop keeps a substantial region).
    MIN_AREA_FRAC = 0.02
    # A box wider than this w:h ratio is a strip of text (e.g. one word of a
    # label on an already-cropped image), not a label region — reject it.
    # Eval: real label crops never exceeded ~1.5:1 wide; bottles are tall.
    MAX_WIDE_ASPECT = 2.5
    # Tall limit is looser: a neck-to-base box on a skinny bottle is legit.
    MAX_TALL_ASPECT = 5.0

    def __init__(self, llm_gateway: LLMGateway):
        """
        Initialize processor.

        Args:
            llm_gateway: LLM gateway for vision tasks
        """
        self.llm = llm_gateway
        self.quality_threshold = 7.0

    def normalize_image_orientation(self, image_bytes: bytes) -> bytes:
        """
        CRITICAL: Apply EXIF orientation to fix rotated images.

        Many phone cameras don't rotate pixels - they just set an EXIF tag.
        This causes coordinate mismatch between vision APIs and PIL.

        This MUST be called before any other processing.

        Args:
            image_bytes: Original image bytes

        Returns:
            Normalized image bytes with correct orientation
        """
        try:
            img = Image.open(BytesIO(image_bytes))

            # Apply EXIF orientation if present
            img = ImageOps.exif_transpose(img)

            # Convert back to bytes
            buffer = BytesIO()
            img.save(buffer, format='JPEG', quality=95)
            normalized_bytes = buffer.getvalue()

            logger.info(f"Image normalized from {img.size} (EXIF applied)")
            return normalized_bytes

        except Exception as e:
            logger.warning(f"EXIF normalization failed (using original): {e}")
            return image_bytes

    async def score_label_quality(
        self, image_bytes: bytes, bottle: BottleMetadata
    ) -> Optional[float]:
        """
        Score image quality using vision LLM.

        Args:
            image_bytes: Image file bytes
            bottle: Bottle metadata for context

        Returns:
            Quality score 0-10, or None if scoring fails
        """
        prompt = self._create_quality_prompt(bottle)

        try:
            response = await self.llm.complete(
                task_type="ocr",  # Routes to lm_studio_vision
                prompt=prompt,
                images=[image_bytes],
                max_tokens=50,
                temperature=0.1,  # Deterministic scoring
            )

            # Parse score from response
            score = self._parse_score(response.content)

            if score is not None:
                logger.info(
                    f"Quality score: {score:.1f}/10 for {bottle.producer} {bottle.name}"
                )
            else:
                logger.warning(f"Failed to parse quality score from: {response.content}")

            return score

        except Exception as e:
            logger.error(f"Quality scoring failed: {e}")
            return None

    async def detect_label_bounds(
        self, image_bytes: bytes
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect the bottle's label region using the vision LLM.

        The image must already be EXIF-normalized (see
        normalize_image_orientation) so pixel coordinates match what the
        model sees.

        Args:
            image_bytes: EXIF-normalized image bytes

        Returns:
            Padded, clamped bounding box as (x, y, width, height) in the
            ORIGINAL image's pixel coordinates, or None if detection fails.
        """
        try:
            img = Image.open(BytesIO(image_bytes))
            img_width, img_height = img.size

            detection_bytes = self._make_detection_image(img)

            # Prefer a dedicated "label_detection" routing when configured
            # (lets a deployment point cropping at a grounding-tuned model,
            # e.g. qwen3-vl-8b) and fall back to the standard vision provider.
            try:
                response = await self.llm.complete(
                    task_type="label_detection",
                    prompt=LABEL_BBOX_PROMPT,
                    images=[detection_bytes],
                    max_tokens=200,
                    temperature=0.0,
                )
            except LLMProviderNotFoundError:  # no routing rule for label_detection
                response = await self.llm.complete(
                    task_type="ocr",
                    prompt=LABEL_BBOX_PROMPT,
                    images=[detection_bytes],
                    max_tokens=200,
                    temperature=0.0,
                )

            logger.info(f"Label bbox response: {response.content!r}")
            norm_box = self._parse_bounding_box(response.content)
            if not norm_box:
                logger.warning(f"Failed to parse bounding box from: {response.content!r}")
                return None

            bounds = self._normalized_to_bounds(norm_box, img_width, img_height)
            if not bounds:
                logger.warning(f"Rejected implausible bounding box: {norm_box}")
                return None

            logger.info(f"Detected label bounds (padded): {bounds}")
            return bounds

        except Exception as e:
            logger.error(f"Bounding box detection failed: {e}")
            return None

    def _make_detection_image(self, img: Image.Image) -> bytes:
        """Downscale a copy for detection; coordinates come back normalized."""
        det = img.copy()
        det.thumbnail((self.DETECTION_MAX_DIM, self.DETECTION_MAX_DIM))
        if det.mode != "RGB":
            det = det.convert("RGB")
        buffer = BytesIO()
        det.save(buffer, format="JPEG", quality=90)
        return buffer.getvalue()

    def _normalized_to_bounds(
        self, norm_box: Tuple[int, int, int, int], img_width: int, img_height: int
    ) -> Optional[Tuple[int, int, int, int]]:
        """Scale a 0-1000 normalized (x1, y1, x2, y2) box to padded, clamped
        (x, y, width, height) pixel bounds on the full-res image."""
        x1, y1, x2, y2 = norm_box

        # Normalize ordering and clamp to the 0-1000 grid
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        if not (0 <= x1 <= 1000 and 0 <= y1 <= 1000 and x2 <= 1000 and y2 <= 1000):
            return None
        if x2 - x1 < 10 or y2 - y1 < 10:  # degenerate box (<1% of image)
            return None

        # Scale to pixels
        px1 = x1 * img_width / 1000
        py1 = y1 * img_height / 1000
        px2 = x2 * img_width / 1000
        py2 = y2 * img_height / 1000

        # Pad
        pad_x = (px2 - px1) * self.PADDING_FRAC
        pad_y = (py2 - py1) * self.PADDING_FRAC
        px1 = max(0.0, px1 - pad_x)
        py1 = max(0.0, py1 - pad_y)
        px2 = min(float(img_width), px2 + pad_x)
        py2 = min(float(img_height), py2 + pad_y)

        x, y = int(px1), int(py1)
        width, height = int(px2 - px1), int(py2 - py1)

        # Sanity checks
        if width < 50 or height < 50:
            return None
        if width * height < img_width * img_height * self.MIN_AREA_FRAC:
            return None
        if width > height * self.MAX_WIDE_ASPECT:
            return None
        if height > width * self.MAX_TALL_ASPECT:
            return None

        return (x, y, width, height)

    async def validate_crop_quality(
        self, cropped_image_bytes: bytes, bottle: BottleMetadata
    ) -> bool:
        """
        Validate that a cropped image still shows a good bottle/label.

        Uses vision LLM to check if the crop looks reasonable.

        Args:
            cropped_image_bytes: Cropped image bytes
            bottle: Bottle metadata for context

        Returns:
            True if crop looks good, False if it cut off too much
        """
        beverage = "wine" if bottle.type == "wine" else "whiskey"

        prompt = f"""Look at this cropped image that should show a {beverage} bottle or label.

**Expected bottle:** {bottle.producer} {bottle.name} {bottle.year or ''}

Rate how well the crop worked (0-10):
- 10: Perfect - shows full label or bottle, nothing cut off
- 7-9: Good - minor edges might be cropped but label is readable
- 4-6: Mediocre - significant parts cut off but still usable
- 0-3: Bad - label text cut off, bottle mostly missing, or wrong object

Return ONLY a number 0-10. No explanation."""

        try:
            response = await self.llm.complete(
                task_type="ocr",
                prompt=prompt,
                images=[cropped_image_bytes],
                max_tokens=10,
                temperature=0.1,
            )

            score = self._parse_score(response.content)

            if score is not None:
                logger.info(f"Crop quality score: {score:.1f}/10")
                return score >= 6.0  # Accept crops rated 6+
            else:
                logger.warning(f"Failed to parse crop quality score: {response.content}")
                return True  # Assume OK if we can't validate

        except Exception as e:
            logger.error(f"Crop quality validation failed: {e}")
            return True  # Assume OK if validation fails

    async def crop_to_label(
        self, image_path: Path, bounds: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Path]:
        """
        Crop image to label using automatic detection or provided bounds.

        Workflow:
        1. Apply EXIF normalization (fixes rotation)
        2. Auto-detect label bounds via the vision LLM if not provided
        3. Apply crop

        If detection fails the EXIF-normalized original is kept — a skipped
        crop is always better than a wrong crop.

        Args:
            image_path: Path to original image
            bounds: Optional bounding box (x, y, width, height) in full-res
                    pixels. If None, will auto-detect.

        Returns:
            Path to processed image (cropped, or original if detection
            failed), or None on error.
        """
        try:
            # Step 1: CRITICAL - Normalize EXIF orientation
            logger.info(f"Processing image: {image_path}")
            with open(image_path, 'rb') as f:
                original_bytes = f.read()

            normalized_bytes = self.normalize_image_orientation(original_bytes)

            # Open normalized image
            img = Image.open(BytesIO(normalized_bytes))
            logger.info(f"Image dimensions after EXIF: {img.width}x{img.height}")

            # Step 2: Auto-detect bounds if not provided
            if bounds is None:
                logger.info("Auto-detecting label bounds via vision LLM...")
                bounds = await self.detect_label_bounds(normalized_bytes)

                if not bounds:
                    logger.warning("Label detection failed, keeping original image")
                    img = self._to_rgb(img)
                    img.save(image_path, 'JPEG', quality=95, optimize=True)
                    return image_path

            # Step 3: Apply crop
            x, y, width, height = bounds
            logger.info(f"Cropping with bounds: x={x}, y={y}, w={width}, h={height}")

            # Convert bounds to PIL box format (left, top, right, bottom)
            box = (x, y, x + width, y + height)

            # Validate box is within image dimensions
            if (
                box[0] < 0
                or box[1] < 0
                or box[2] > img.width
                or box[3] > img.height
            ):
                logger.error(
                    f"Crop box {box} exceeds image dimensions {img.width}x{img.height}"
                )
                return None

            # Crop image
            cropped = img.crop(box)
            logger.info(f"Cropped to: {cropped.width}x{cropped.height}")

            cropped = self._to_rgb(cropped)

            # Save cropped version (overwrite original)
            cropped.save(image_path, 'JPEG', quality=95, optimize=True)

            logger.info(f"✅ Cropped image saved to {image_path}")
            return image_path

        except Exception as e:
            logger.error(f"Image cropping failed: {e}")
            return None

    @staticmethod
    def _to_rgb(img: Image.Image) -> Image.Image:
        """Convert palette/alpha modes to RGB for JPEG saving."""
        if img.mode in ('P', 'RGBA', 'LA'):
            if img.mode == 'P':
                return img.convert('RGB')
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if 'A' in img.mode else None)
            return rgb_img
        if img.mode != 'RGB':
            return img.convert('RGB')
        return img

    def _create_quality_prompt(self, bottle: BottleMetadata) -> str:
        """Create prompt for quality scoring."""
        beverage = "wine" if bottle.type == "wine" else "whiskey"

        return f"""Analyze this image and rate how well it shows a {beverage} bottle label (0-10):

**Scoring Guide:**
- 10: Perfect product shot, label fills frame, clear and readable
- 7-9: Good bottle shot, label visible and clear
- 4-6: Lifestyle/pour shot, label visible but small
- 0-3: No bottle or label not visible

**Bottle:** {bottle.producer} {bottle.name} {bottle.year or ''}

Return ONLY a number 0-10. No explanation."""

    def _parse_score(self, content: str) -> Optional[float]:
        """Parse quality score from LLM response."""
        try:
            # Try to extract just the number
            content = content.strip()

            # Remove any markdown or extra text
            if "/" in content:
                content = content.split("/")[0]

            # Extract first number found
            match = re.search(r"(\d+(?:\.\d+)?)", content)
            if match:
                score = float(match.group(1))
                # Validate range
                if 0 <= score <= 10:
                    return score

            return None

        except Exception as e:
            logger.debug(f"Score parsing error: {e}")
            return None

    def _parse_bounding_box(self, content: str) -> Optional[Tuple[int, int, int, int]]:
        """Parse an (x1, y1, x2, y2) box from LLM output.

        Accepts the formats local vision models actually produce:
        - {"bbox_2d": [x1, y1, x2, y2]} (Qwen grounding, possibly in a list
          or fenced code block, possibly with extra keys)
        - {"x": ..., "y": ..., "width": ..., "height": ...}
        - <box>x1 y1 x2 y2</box> (MiniCPM grounding)
        - a bare [x1, y1, x2, y2] array
        """
        if not content:
            return None

        # <box>x1 y1 x2 y2</box>
        m = re.search(r"<box>\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*</box>", content)
        if m:
            return tuple(int(g) for g in m.groups())  # type: ignore[return-value]

        # keyed 4-number array
        for key in ("bbox_2d", "bbox", "box"):
            m = re.search(
                key + r'"?\s*[:=]\s*\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]',
                content,
            )
            if m:
                return tuple(int(g) for g in m.groups())  # type: ignore[return-value]

        # x/y/width/height object
        m = re.search(
            r'"x"\s*:\s*(\d+)\s*,\s*"y"\s*:\s*(\d+)\s*,\s*"width"\s*:\s*(\d+)\s*,\s*"height"\s*:\s*(\d+)',
            content,
        )
        if m:
            x, y, w, h = (int(g) for g in m.groups())
            return (x, y, x + w, y + h)

        # bare 4-number array
        m = re.search(r"\[\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\]", content)
        if m:
            return tuple(int(g) for g in m.groups())  # type: ignore[return-value]

        # last resort: strict JSON parse of the whole payload
        try:
            data = json.loads(content.strip().strip("`"))
            if isinstance(data, dict) and "bbox_2d" in data:
                vals = data["bbox_2d"]
                if isinstance(vals, list) and len(vals) == 4:
                    return tuple(int(v) for v in vals)  # type: ignore[return-value]
        except Exception:
            pass

        return None
