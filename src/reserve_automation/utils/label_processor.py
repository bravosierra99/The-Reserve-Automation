"""Vision-based label quality assessment and cropping."""

import json
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple

import cv2
import numpy as np
import pytesseract
from PIL import Image, ImageOps

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
            logger.info(f"LLM response: {response.content}")
            bounds = self._parse_bounding_box(response.content)

            if bounds:
                x, y, w, h = bounds
                logger.info(f"Detected label bounds: x={x}, y={y}, w={w}, h={h}")
                logger.info(f"Label covers from top-left ({x}, {y}) to bottom-right ({x+w}, {y+h})")

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

    def detect_label_bounds_cv(
        self, image_bytes: bytes
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect bottle/label bounding box using computer vision (OpenCV).

        Strategy: Find the bottle itself (vertical object) rather than just
        the darkest rectangle. This works better for full bottle images.

        Args:
            image_bytes: Image file bytes

        Returns:
            Bounding box as (x, y, width, height), or None if detection fails
        """
        try:
            # Convert bytes to numpy array
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                logger.error("Failed to decode image")
                return None

            h, w = img.shape[:2]
            logger.info(f"CV detection on image: {w}x{h}")

            # Convert to grayscale
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # Apply Gaussian blur to reduce noise
            blurred = cv2.GaussianBlur(gray, (5, 5), 0)

            # Use Otsu's thresholding to separate foreground from background
            _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            # Invert if background is darker than foreground
            if np.mean(thresh) > 127:
                thresh = cv2.bitwise_not(thresh)

            # Morphological operations to clean up
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)
            thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)

            # Find contours
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            if not contours:
                logger.warning("No contours found in image")
                return None

            # Find contours that are likely bottles (tall and narrow)
            # or labels (reasonable aspect ratio)
            candidates = []
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < (w * h) * 0.05:  # Must be at least 5% of image
                    continue

                x, y, cw, ch = cv2.boundingRect(contour)
                aspect_ratio = ch / cw if cw > 0 else 0

                # Bottle-like (tall) or label-like (squarish)
                if aspect_ratio > 1.2 or (0.5 <= aspect_ratio <= 2.0 and area > (w * h) * 0.2):
                    candidates.append((area, x, y, cw, ch))

            if not candidates:
                logger.warning("No bottle/label-like contours found, using largest contour")
                # Fallback to largest contour
                largest_contour = max(contours, key=cv2.contourArea)
                x, y, width, height = cv2.boundingRect(largest_contour)
            else:
                # Use the largest candidate
                candidates.sort(reverse=True)
                _, x, y, width, height = candidates[0]

            logger.info(f"CV detected bounds: x={x}, y={y}, w={width}, h={height}")
            logger.info(f"Object covers {(width*height)/(w*h)*100:.1f}% of image")

            # Add 2% padding to ensure we don't cut off edges
            padding_x = int(width * 0.02)
            padding_y = int(height * 0.02)

            x = max(0, x - padding_x)
            y = max(0, y - padding_y)
            width = min(w - x, width + 2 * padding_x)
            height = min(h - y, height + 2 * padding_y)

            logger.info(f"After 2% padding: x={x}, y={y}, w={width}, h={height}")

            # Validate bounds are reasonable
            if width < 50 or height < 50:
                logger.warning(f"Detected object too small: {width}x{height}")
                return None

            return (x, y, width, height)

        except Exception as e:
            logger.error(f"CV bounding box detection failed: {e}")
            return None

    def detect_label_bounds_text(
        self, image_bytes: bytes
    ) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect label by finding text regions using OCR (Most Reliable).

        Labels = dense text regions. This works better than edge detection
        because it directly finds what matters (the text on the label).

        Args:
            image_bytes: Image file bytes

        Returns:
            Bounding box as (x, y, width, height), or None if detection fails
        """
        try:
            # Convert bytes to numpy array
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

            if img is None:
                logger.error("Failed to decode image")
                return None

            h, w = img.shape[:2]
            logger.info(f"Text-based detection on image: {w}x{h}")

            # Get all text bounding boxes from OCR
            ocr_data = pytesseract.image_to_data(
                img,
                output_type=pytesseract.Output.DICT,
                config='--psm 11'  # Sparse text mode
            )

            # Filter to high-confidence text boxes
            text_boxes = []
            for i in range(len(ocr_data['text'])):
                conf = int(ocr_data['conf'][i])
                text = ocr_data['text'][i].strip()

                # Only consider high-confidence text
                if conf > 30 and len(text) > 0:
                    x = ocr_data['left'][i]
                    y = ocr_data['top'][i]
                    box_w = ocr_data['width'][i]
                    box_h = ocr_data['height'][i]
                    text_boxes.append((x, y, box_w, box_h))

            if not text_boxes:
                logger.warning("No text detected in image")
                return None

            logger.info(f"Found {len(text_boxes)} text regions")

            # Find bounding box that contains all text
            min_x = min(box[0] for box in text_boxes)
            min_y = min(box[1] for box in text_boxes)
            max_x = max(box[0] + box[2] for box in text_boxes)
            max_y = max(box[1] + box[3] for box in text_boxes)

            # Add padding around text region (labels have whitespace/graphics)
            text_width = max_x - min_x
            text_height = max_y - min_y

            # Use 20% padding to capture label borders and graphics
            padding_x = int(text_width * 0.20)
            padding_y = int(text_height * 0.20)

            x = max(0, min_x - padding_x)
            y = max(0, min_y - padding_y)
            width = min(w - x, text_width + 2 * padding_x)
            height = min(h - y, text_height + 2 * padding_y)

            logger.info(f"Text-based bounds: x={x}, y={y}, w={width}, h={height}")
            logger.info(f"Label covers {(width*height)/(w*h)*100:.1f}% of image")

            # Validate bounds are reasonable
            if width < 50 or height < 50:
                logger.warning(f"Detected text region too small: {width}x{height}")
                return None

            return (x, y, width, height)

        except Exception as e:
            logger.error(f"Text-based detection failed: {e}")
            return None

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

    def crop_to_label(
        self, image_path: Path, bounds: Optional[Tuple[int, int, int, int]] = None
    ) -> Optional[Path]:
        """
        Crop image to label using automatic detection or provided bounds.

        Workflow:
        1. Apply EXIF normalization (fixes rotation)
        2. Auto-detect label bounds if not provided
           - Try text-based detection first (most reliable)
           - Fall back to CV contour detection
        3. Apply crop

        Args:
            image_path: Path to original image
            bounds: Optional bounding box (x, y, width, height).
                   If None, will auto-detect.

        Returns:
            Path to cropped image, or None if cropping fails
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
                logger.info("Auto-detecting label bounds...")

                # Try text-based detection first (most reliable)
                bounds = self.detect_label_bounds_text(normalized_bytes)

                if bounds:
                    logger.info("✅ Text-based detection succeeded")
                else:
                    logger.info("Text detection failed, trying CV contour detection...")
                    bounds = self.detect_label_bounds_cv(normalized_bytes)

                    if bounds:
                        logger.info("✅ CV contour detection succeeded")
                    else:
                        logger.warning("❌ All detection methods failed, using original image")
                        # Save normalized image (at least we fixed rotation)
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

            # Convert to RGB if needed (for PNG palette mode)
            if cropped.mode in ('P', 'RGBA', 'LA'):
                rgb_img = Image.new('RGB', cropped.size, (255, 255, 255))
                if cropped.mode == 'P':
                    cropped = cropped.convert('RGB')
                else:
                    rgb_img.paste(cropped, mask=cropped.split()[-1] if 'A' in cropped.mode else None)
                    cropped = rgb_img

            # Save cropped version (overwrite original)
            cropped.save(image_path, 'JPEG', quality=95, optimize=True)

            logger.info(f"✅ Cropped image saved to {image_path}")
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

CRITICAL REQUIREMENTS:
- Coordinates are pixels from top-left corner (0,0)
- x = leftmost pixel of the label
- y = topmost pixel of the label
- width = FULL horizontal span from leftmost to rightmost edge of label
- height = FULL vertical span from topmost to bottommost edge of label
- The bounding box MUST include ALL FOUR CORNERS of the label
- The bounding box MUST include the entire bottom edge and right edge
- Do NOT cut off any part of the label design, text, or borders
- It is BETTER to include extra pixels around the label than to crop off ANY part of it
- Validate: x + width must not exceed {img_width}
- Validate: y + height must not exceed {img_height}

DOUBLE CHECK: Does your bounding box include the BOTTOM-RIGHT corner of the label? If not, increase width and height.

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
