"""Extract bottle metadata from label images using vision LLM."""

import json
from pathlib import Path
from typing import Optional

from loguru import logger
from PIL import Image

from ..core.models import BottleMetadata
from ..llm import LLMGateway


class ImageMetadataExtractor:
    """
    Extract bottle metadata from label images.

    Uses vision LLM to read text and details from bottle labels,
    then enriches with web search for complete metadata.
    """

    def __init__(self, llm_gateway: LLMGateway):
        """
        Initialize image metadata extractor.

        Args:
            llm_gateway: LLM gateway for vision and text requests
        """
        self.llm_gateway = llm_gateway

    async def extract_from_image(
        self, image_path: Path, beverage_type: Optional[str] = None
    ) -> tuple[BottleMetadata, dict]:
        """
        Extract bottle metadata from a label image.

        Args:
            image_path: Path to bottle/label image
            beverage_type: Optional beverage type hint ("wine" or "whiskey")

        Returns:
            Tuple of (bottle metadata, extraction details dict)
        """
        logger.info(f"Extracting metadata from image: {image_path}")

        # Read image
        try:
            img = Image.open(image_path)
            img_width, img_height = img.size
            logger.debug(f"Image dimensions: {img_width}x{img_height}")
        except Exception as e:
            logger.error(f"Failed to open image: {e}")
            return None, {"error": f"Failed to open image: {e}"}

        # Build extraction prompt
        type_hint = ""
        if beverage_type:
            type_hint = f"\n\nThe bottle is a {beverage_type}."

        prompt = f"""You are a wine and spirits expert. Analyze this bottle/label image and extract ALL visible information.

**Task:** Read the label carefully and extract every detail you can see.

**Extract the following if visible:**
- Producer/Winery/Distillery name
- Wine/Whiskey name (the specific product name)
- Vintage/Year (if shown - this is CRITICAL)
- Type (red wine, white wine, bourbon, rye, etc.)
- Alcohol percentage or proof
- Region/Appellation (if shown)
- Grape variety or mash bill (if shown)
- Any other distinguishing details{type_hint}

**IMPORTANT:**
- Only extract information that is CLEARLY VISIBLE on the label
- Do NOT guess or infer information not shown
- If the vintage/year is not visible, say "Year: NOT VISIBLE"
- Read all text carefully, including small print
- Pay attention to official designations (DOCG, DOC, AVA, etc.)

**Return JSON:**
{{
  "producer": "producer name from label",
  "name": "specific wine/whiskey name",
  "year": "YYYY or null if not visible",
  "type": "wine/whiskey and style",
  "beverage_type": "wine" or "whiskey",
  "alcohol": "percentage or proof if shown",
  "region": "region/appellation if shown",
  "variety": "grape variety or whiskey type if shown",
  "country": "country if shown",
  "additional_details": "any other notable information",
  "confidence": "high/medium/low",
  "missing_year": true/false (true if year not visible)
}}

Read the label carefully and extract everything visible."""

        try:
            # Convert image to bytes for vision LLM
            import io
            img_buffer = io.BytesIO()
            img.save(img_buffer, format=img.format or "JPEG")
            image_bytes = img_buffer.getvalue()

            # Call vision LLM
            response = await self.llm_gateway.complete(
                task_type="ocr",
                prompt=prompt,
                image=image_bytes,
                temperature=0.1,  # Very deterministic for extraction
                max_tokens=800,
            )

            # Parse JSON response
            extracted_data = self._parse_extraction_response(response.content)

            if not extracted_data:
                return None, {"error": "Failed to parse extraction response"}

            # Create bottle metadata from extracted data
            bottle = self._create_bottle_from_extraction(extracted_data, image_path)

            metadata = {
                "success": True,
                "extracted_data": extracted_data,
                "missing_year": extracted_data.get("missing_year", False),
                "confidence": extracted_data.get("confidence", "unknown"),
                "tokens_used": response.tokens_used,
            }

            logger.info(
                f"✓ Extracted: {bottle.producer} - {bottle.name} "
                f"({bottle.year or 'year missing'})"
            )

            return bottle, metadata

        except Exception as e:
            logger.error(f"Image extraction failed: {e}")
            return None, {"error": str(e)}

    def _parse_extraction_response(self, response_text: str) -> Optional[dict]:
        """
        Parse vision LLM extraction response.

        Args:
            response_text: Raw LLM response

        Returns:
            Dictionary with extracted data, or None if parsing fails
        """
        try:
            # Extract JSON from response
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1

            if json_start < 0 or json_end <= json_start:
                logger.error("No JSON found in extraction response")
                return None

            json_str = response_text[json_start:json_end]
            data = json.loads(json_str)

            return data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse extraction JSON: {e}")
            logger.debug(f"Response was: {response_text}")
            return None

    def _create_bottle_from_extraction(
        self, extracted_data: dict, image_path: Path
    ) -> BottleMetadata:
        """
        Create BottleMetadata from extracted data.

        Args:
            extracted_data: Data extracted from image
            image_path: Path to source image

        Returns:
            BottleMetadata instance
        """
        # Determine beverage type
        beverage_type = extracted_data.get("beverage_type", "wine")
        if beverage_type not in ["wine", "whiskey"]:
            # Try to infer from type field
            type_str = str(extracted_data.get("type", "")).lower()
            if any(w in type_str for w in ["bourbon", "rye", "scotch", "whiskey", "whisky"]):
                beverage_type = "whiskey"
            else:
                beverage_type = "wine"

        # Parse year
        year = extracted_data.get("year")
        if year and year != "NOT VISIBLE":
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None
        else:
            year = None

        # Build bottle metadata
        bottle_data = {
            "producer": extracted_data.get("producer", "Unknown Producer"),
            "name": extracted_data.get("name", "Unknown"),
            "year": year,
            "type": beverage_type,
            "beverage_type": extracted_data.get("type"),
            "country": extracted_data.get("country"),
            "region": extracted_data.get("region"),
            "variety": extracted_data.get("variety"),
            "price": 0.0,  # Will be enriched or set by user
            "source_image": str(image_path),
        }

        return BottleMetadata(**bottle_data)
