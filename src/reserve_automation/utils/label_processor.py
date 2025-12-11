"""Vision-based label quality assessment and cropping."""

import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

from ..core.models import BottleMetadata
from ..llm.gateway import LLMGateway

logger = logging.getLogger(__name__)


class LabelImageProcessor:
    """Process bottle label images using vision LLM."""

    def __init__(self, llm_gateway: LLMGateway):
        """
        Initialize processor.

        Args:
            llm_gateway: LLM gateway for vision tasks
        """
        self.llm = llm_gateway
        self.quality_threshold = 7.0

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
        self, image_bytes: bytes, bottle: BottleMetadata
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect label bounding box using vision LLM.

        Args:
            image_bytes: Image file bytes
            bottle: Bottle metadata for context

        Returns:
            Bounding box as (x, y, width, height), or None if detection fails
        """
        # Get image dimensions
        img = Image.open(BytesIO(image_bytes))
        img_width, img_height = img.width, img.height

        prompt = self._create_bounding_box_prompt(bottle, img_width, img_height)

        try:
            response = await self.llm.complete(
                task_type="ocr",
                prompt=prompt,
                images=[image_bytes],
                max_tokens=100,
                temperature=0.1,
            )

            # Parse JSON bounding box
            bounds = self._parse_bounding_box(response.content)

            if bounds:
                x, y, w, h = bounds
                logger.info(f"Detected label bounds: x={x}, y={y}, w={w}, h={h}")

                # Add padding to ensure we capture the full label (expand by 3% on each side)
                padding_x = int(w * 0.03)
                padding_y = int(h * 0.03)
                padded_bounds = (
                    max(0, x - padding_x),
                    max(0, y - padding_y),
                    w + (2 * padding_x),
                    h + (2 * padding_y)
                )

                if padded_bounds != bounds:
                    logger.info(f"Added 3% padding: {bounds} → {padded_bounds}")

                # Validate and clamp bounds if needed
                clamped_bounds = self._clamp_bounds(padded_bounds, img_width, img_height)

                if clamped_bounds != padded_bounds:
                    logger.warning(
                        f"Bounds exceeded image, clamped from {padded_bounds} to {clamped_bounds}"
                    )

                # Validate clamped bounds are reasonable
                if self._validate_bounds(clamped_bounds, image_bytes):
                    return clamped_bounds
                else:
                    logger.warning(f"Invalid bounds detected: {clamped_bounds}")
                    return None
            else:
                logger.warning(
                    f"Failed to parse bounding box from: {response.content}"
                )
                return None

        except Exception as e:
            logger.error(f"Bounding box detection failed: {e}")
            return None

    def crop_to_label(
        self, image_path: Path, bounds: Tuple[int, int, int, int]
    ) -> Optional[Path]:
        """
        Crop image to label bounds using PIL.

        Args:
            image_path: Path to original image
            bounds: Bounding box as (x, y, width, height)

        Returns:
            Path to cropped image, or None if cropping fails
        """
        try:
            x, y, width, height = bounds

            # Open image with PIL
            img = Image.open(image_path)

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

            # Convert to RGB if needed (for PNG palette mode)
            if cropped.mode in ('P', 'RGBA', 'LA'):
                # Convert palette or transparent images to RGB
                rgb_img = Image.new('RGB', cropped.size, (255, 255, 255))
                if cropped.mode == 'P':
                    cropped = cropped.convert('RGB')
                else:
                    rgb_img.paste(cropped, mask=cropped.split()[-1] if 'A' in cropped.mode else None)
                    cropped = rgb_img

            # Save cropped version (overwrite original)
            cropped.save(image_path, 'JPEG', quality=95, optimize=True)

            logger.info(f"Cropped image saved to {image_path}")
            return image_path

        except Exception as e:
            logger.error(f"Image cropping failed: {e}")
            return None

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

    def _create_bounding_box_prompt(
        self, bottle: BottleMetadata, img_width: int, img_height: int
    ) -> str:
        """Create prompt for bounding box detection."""
        beverage = "wine" if bottle.type == "wine" else "whiskey"

        return f"""Identify the bottle label location in this {beverage} bottle image.

**Image dimensions:** {img_width} x {img_height} pixels
**Bottle:** {bottle.producer} {bottle.name} {bottle.year or ''}

Return ONLY a JSON object with the label's bounding box:
{{"x": <left>, "y": <top>, "width": <width>, "height": <height>}}

IMPORTANT:
- Coordinates are pixels from top-left (0,0)
- x must be between 0 and {img_width}
- y must be between 0 and {img_height}
- x + width must not exceed {img_width}
- y + height must not exceed {img_height}
- The box should encompass the ENTIRE label including all edges and corners
- Make sure the bottom and right edges are fully included (don't cut off text or design)
- It's better to include a few extra pixels than to cut off part of the label

Return ONLY the JSON object, no other text."""

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
        """Parse bounding box from LLM response."""
        try:
            # Remove markdown code blocks if present
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            # Parse JSON
            data = json.loads(content)

            # Extract coordinates
            x = int(data.get("x", 0))
            y = int(data.get("y", 0))
            width = int(data.get("width", 0))
            height = int(data.get("height", 0))

            return (x, y, width, height)

        except Exception as e:
            logger.debug(f"Bounding box parsing error: {e}")
            return None

    def _clamp_bounds(
        self, bounds: Tuple[int, int, int, int], img_width: int, img_height: int
    ) -> Tuple[int, int, int, int]:
        """
        Clamp bounding box to image dimensions.

        Args:
            bounds: Original bounding box (x, y, width, height)
            img_width: Image width
            img_height: Image height

        Returns:
            Clamped bounding box
        """
        x, y, width, height = bounds

        # Clamp position to image
        x = max(0, min(x, img_width - 1))
        y = max(0, min(y, img_height - 1))

        # Clamp size to not exceed image
        width = min(width, img_width - x)
        height = min(height, img_height - y)

        return (x, y, width, height)

    def _validate_bounds(
        self, bounds: Tuple[int, int, int, int], image_bytes: bytes
    ) -> bool:
        """
        Validate bounding box is reasonable.

        Args:
            bounds: Bounding box (x, y, width, height)
            image_bytes: Image to validate against

        Returns:
            True if bounds are valid
        """
        try:
            x, y, width, height = bounds

            # Check for negative values
            if x < 0 or y < 0 or width <= 0 or height <= 0:
                return False

            # Open image to check dimensions
            img = Image.open(BytesIO(image_bytes))

            # Check bounds don't exceed image
            if x + width > img.width or y + height > img.height:
                return False

            # Check minimum size (label should be at least 50x50 pixels)
            if width < 50 or height < 50:
                return False

            return True

        except Exception:
            return False
