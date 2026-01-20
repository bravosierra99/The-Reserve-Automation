"""Extract tasting notes from filled-out tasting card images."""

import json
import logging
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from ..core.models import LLMRequest
from ..core.tasting_note import TastingExtractionResult, TastingNote
from ..llm.gateway import LLMGateway
from ..llm.response_parser import LLMResponseParser
from ..utils.table_ocr import detect_table_structure
from ..utils.llm_whisperer import extract_layout_text

logger = logging.getLogger(__name__)


class TastingExtractor:
    """Extract structured tasting notes from images of filled-out tasting cards."""

    def __init__(self, llm_gateway: LLMGateway, extraction_config: Optional[dict] = None):
        self.llm = llm_gateway
        self.extraction_config = extraction_config or {}

    async def extract_from_image(
        self,
        image_path: Path,
        template_type: Optional[Literal["aws_wine", "bourbon"]] = None,
        expected_count: Optional[int] = None,
    ) -> TastingExtractionResult:
        """
        Extract tasting notes from an image of a filled-out tasting card.

        Args:
            image_path: Path to image file
            template_type: Type of template (auto-detected if None)
            expected_count: User-specified expected number of tastings (helps guide extraction)

        Returns:
            TastingExtractionResult with extracted tastings
        """
        logger.info(f"Extracting tasting notes from {image_path} (expected_count={expected_count})")

        # Step 1: Auto-detect template type if not provided
        if template_type is None:
            template_type = await self._detect_template_type(image_path)
            logger.info(f"Detected template type: {template_type}")

        # Step 2: Extract based on template type
        if template_type == "aws_wine":
            result = await self._extract_aws_wine(image_path, expected_count=expected_count)
        elif template_type == "bourbon":
            result = await self._extract_bourbon(image_path)
        else:
            raise ValueError(f"Unknown template type: {template_type}")

        result.template_type = template_type
        return result

    async def _detect_template_type(self, image_path: Path) -> Literal["aws_wine", "bourbon"]:
        """Detect which template type is in the image."""
        prompt = """
Analyze this tasting card image and identify which template it is:

1. **AWS Wine Evaluation Chart**:
   - Table format with columns: Wine, Price, Appearance (3 max), Aroma/Bouquet (6 max), Taste/Texture (6 max), Aftertaste (3 max), Overall Impression (2 max), Total Score (20 max)
   - Header says "AWS Wine Evaluation Chart"
   - Has fields for Name, Date, Place, Theme at top

2. **Bourbon Tasting Sheet**:
   - Says "BOURBON TASTING SHEET" at top
   - Has sections for NOSE, PALATE, FINISH, UNIQUENESS, OVERALL
   - Rating scale 1-5 (1="I'd pour this out", 5="All-time favorite!")
   - Has REVEAL field for bottle name
   - Color rating chart (Light/Med/Dark)

Return ONLY the template type as a single word:
- "aws_wine" for AWS Wine Evaluation Chart
- "bourbon" for Bourbon Tasting Sheet
"""

        # Read image file as bytes
        with open(image_path, 'rb') as f:
            image_bytes = f.read()

        response = await self.llm.complete(
            task_type="ocr",
            prompt=prompt,
            images=[image_bytes]
        )

        result = response.content.strip().lower()
        if "aws_wine" in result:
            return "aws_wine"
        elif "bourbon" in result:
            return "bourbon"
        else:
            # Default based on content
            return "bourbon" if "bourbon" in result else "aws_wine"

    async def _extract_aws_wine(self, image_path: Path, expected_count: Optional[int] = None) -> TastingExtractionResult:
        """
        Extract tasting notes from AWS Wine Evaluation Chart using hybrid approach.

        Uses OCR for:
        - Auto-rotation detection
        - Table structure detection (row boundaries)

        Then uses LLM for:
        - Handwritten content extraction guided by detected structure
        """
        # Step 1: Use OCR to detect table structure
        try:
            structure = detect_table_structure(image_path)
            logger.info(
                f"Detected table structure: {structure['num_rows']} rows, "
                f"rotation: {structure['rotation_angle']}°"
            )

            # Save rotation-corrected image for LLM
            import tempfile
            import cv2
            corrected_path = Path(tempfile.mktemp(suffix='.jpg'))
            cv2.imwrite(str(corrected_path), structure['rotated_image'])

            # Step 2: Extract using LLM with structure guidance
            result = await self._extract_aws_wine_llm_guided(
                corrected_path,
                num_rows=structure['num_rows'],
                row_boundaries=structure['row_boundaries'],
                column_boundaries=structure['column_boundaries'],
                column_text=structure['column_text'],
                expected_count=expected_count
            )

            # Clean up temporary file
            corrected_path.unlink(missing_ok=True)

            return result

        except Exception as e:
            logger.warning(f"OCR structure detection failed: {e}, falling back to LLM-only")
            return await self._extract_aws_wine_llm(image_path)

    async def _extract_aws_wine_llm(self, image_path: Path) -> TastingExtractionResult:
        """Extract tasting notes from AWS Wine Evaluation Chart using LLM (fallback)."""
        prompt = """
Extract ALL tasting notes from this AWS Wine Evaluation Chart image.

The chart has the following structure:
- Header: Name (taster), Date, Place, Theme
- Table with ROWS for each wine. Each ROW has columns: Wine | Price | Appearance (3 max) | Aroma/Bouquet (6 max) | Taste/Texture (6 max) | Aftertaste (3 max) | Overall Impression (2 max) | Total Score (20 max)

CRITICAL - Row Detection Rules:
1. The table has EXACTLY 4 ROWS for wines (look for horizontal lines separating rows)
2. Each ROW is a SINGLE wine, even if the wine name spans multiple lines within that row
3. A row is considered "filled out" ONLY if it has at least one score value (Appearance, Aroma, Taste, Aftertaste, Overall, or Total)
4. Empty rows (no scores written) should be SKIPPED entirely
5. Wine names may wrap to multiple lines within a single row - combine them into one name
6. Do NOT split a single wine name into multiple wines

For EACH filled-out row, extract:
1. Wine name (combine all text in the Wine column for that row)
2. Price (if filled in)
3. Appearance score (0-3)
4. Aroma/Bouquet score (0-6)
5. Taste/Texture score (0-6)
6. Aftertaste score (0-3)
7. Overall Impression score (0-2)
8. Total Score (0-20)

Also extract the header information:
- Taster name
- Date (format as YYYY-MM-DD, if year missing use current year)
- Place (location)
- Theme (tasting theme/event)

Return a JSON object with this structure:
{
  "taster_name": "...",
  "tasting_date": "YYYY-MM-DD",
  "place": "...",
  "theme": "...",
  "tastings": [
    {
      "bottle_name": "Complete wine name from that row",
      "price": "...",
      "wine_appearance": 2.5,
      "wine_aroma": 5.0,
      "wine_taste": 5.5,
      "wine_aftertaste": 2.5,
      "wine_overall": 1.5,
      "nose_notes": ["array", "of", "strings describing nose/aroma notes, if present"],
      "palate_notes": ["array", "of", "strings describing palate/taste notes, if present"],
      "finish_notes": ["array", "of", "strings describing finish/aftertaste notes, if present"],
      "overall_notes": "string with overall tasting notes if present"
    }
  ]
}

Important:
- ONLY include rows that have at least one score filled in
- Each physical table row = one wine entry (even if name wraps)
- Count the horizontal lines to identify separate rows
- If a score is partially filled or unclear, estimate it
- If date is missing the year, use 2025
- Extract any handwritten tasting notes if present in the row (nose, palate, finish, overall observations)
- Return valid JSON only, no other text
"""

        # Read image file as bytes
        with open(image_path, 'rb') as f:
            image_bytes = f.read()

        response = await self.llm.complete(
            task_type="structured_extraction",
            prompt=prompt,
            images=[image_bytes],
            response_format="json"
        )

        # Parse response and create TastingNote objects with robust error handling
        data = LLMResponseParser.safe_parse_json(
            response.content,
            context="AWS wine tasting extraction"
        )

        if not data:
            logger.error("Failed to parse LLM response for wine tasting")
            return TastingExtractionResult(
                tastings=[],
                template_type="aws_wine",
                raw_text=response.content,
                confidence=0.0,
            )

        tastings = []
        for i, wine_data in enumerate(data.get("tastings", [])):
            try:
                tasting = TastingNote(
                    bottle_name=LLMResponseParser.sanitize_string(
                        wine_data.get("bottle_name"),
                        max_length=200,
                        field_name=f"wine[{i}].bottle_name",
                        default="Unknown Wine"
                    ),
                    taster_name=LLMResponseParser.sanitize_string(
                        data.get("taster_name"),
                        max_length=100,
                        field_name="taster_name",
                        default="Unknown"
                    ),
                    tasting_date=LLMResponseParser.sanitize_date(
                        data.get("tasting_date"),
                        field_name="tasting_date",
                        default=date.today()
                    ),
                    beverage_type="wine",
                    wine_appearance=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_appearance"),
                        min_value=0.0,
                        max_value=3.0,
                        field_name=f"wine[{i}].appearance"
                    ),
                    wine_aroma=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_aroma"),
                        min_value=0.0,
                        max_value=6.0,
                        field_name=f"wine[{i}].aroma"
                    ),
                    wine_taste=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_taste"),
                        min_value=0.0,
                        max_value=6.0,
                        field_name=f"wine[{i}].taste"
                    ),
                    wine_aftertaste=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_aftertaste"),
                        min_value=0.0,
                        max_value=3.0,
                        field_name=f"wine[{i}].aftertaste"
                    ),
                    wine_overall=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_overall"),
                        min_value=0.0,
                        max_value=2.0,
                        field_name=f"wine[{i}].overall"
                    ),
                    nose_notes=LLMResponseParser.sanitize_list(
                        wine_data.get("nose_notes"),
                        field_name=f"wine[{i}].nose_notes"
                    ),
                    palate_notes=LLMResponseParser.sanitize_list(
                        wine_data.get("palate_notes"),
                        field_name=f"wine[{i}].palate_notes"
                    ),
                    finish_notes=LLMResponseParser.sanitize_list(
                        wine_data.get("finish_notes"),
                        field_name=f"wine[{i}].finish_notes"
                    ),
                    overall_notes=LLMResponseParser.sanitize_string(
                        wine_data.get("overall_notes"),
                        field_name=f"wine[{i}].overall_notes"
                    ),
                    place=LLMResponseParser.sanitize_string(
                        data.get("place"),
                        field_name="place"
                    ),
                    theme=LLMResponseParser.sanitize_string(
                        data.get("theme"),
                        field_name="theme"
                    ),
                    price=LLMResponseParser.sanitize_string(
                        wine_data.get("price"),
                        field_name=f"wine[{i}].price"
                    ),
                    confidence=0.8,  # TODO: Calculate based on completeness
                )
                tastings.append(tasting)
            except Exception as e:
                logger.error(f"Failed to create tasting note for wine #{i+1}: {e}")
                continue

        return TastingExtractionResult(
            tastings=tastings,
            template_type="aws_wine",
            raw_text=response.content,
            confidence=0.8,
        )

    async def _extract_aws_wine_llm_guided(
        self,
        image_path: Path,
        num_rows: int,
        row_boundaries: list[dict],
        column_boundaries: list[dict],
        column_text: dict,
        expected_count: Optional[int] = None
    ) -> TastingExtractionResult:
        """
        Extract tasting notes from AWS Wine Evaluation Chart using LLMWhisperer + LLM.

        Uses LLMWhisperer API to get layout-preserving ASCII representation of the table,
        then passes that to the local LLM for structured extraction.

        Args:
            image_path: Path to rotation-corrected image
            num_rows: Number of rows detected by OCR (may not be used)
            row_boundaries: List of row boundary dicts from OCR (may not be used)
            column_boundaries: List of column boundary dicts from OCR (may not be used)
            column_text: Dict mapping column labels to OCR-extracted text per row (may not be used)
            expected_count: User-specified expected number of tastings
        """
        logger.info(f"Using LLMWhisperer for layout-preserving text extraction from {image_path}")

        # Step 1: Use LLMWhisperer to extract layout-preserving ASCII text
        try:
            layout_text = extract_layout_text(image_path, self.extraction_config)
            logger.info(f"LLMWhisperer extracted {len(layout_text)} characters")
            logger.debug(f"Layout text preview: {layout_text[:500]}")
        except Exception as e:
            logger.error(f"LLMWhisperer extraction failed: {e}")
            # Fall back to image-only extraction if LLMWhisperer fails
            logger.info("Falling back to image-only extraction")
            return await self._extract_aws_wine_llm(image_path)

        # Step 2: Build prompt that uses the layout-preserving text
        prompt = f"""Extract ALL wines from this tasting table. Return ONLY valid JSON, no markdown, no explanations.

Table:
{layout_text}

Extract the shared metadata (taster, date, place) and ALL wine rows. Return this exact JSON structure:

{{{{
  "taster_name": "string",
  "tasting_date": "YYYY-MM-DD",
  "place": "string or null",
  "theme": "string or null",
  "tastings": [
    {{{{
      "bottle_name": "string",
      "beverage_type": "wine",
      "price": "string or null",
      "wine_appearance": number or null,
      "wine_aroma": number or null,
      "wine_taste": number or null,
      "wine_aftertaste": number or null,
      "wine_overall": number or null,
      "nose_notes": ["array", "of", "strings"] or null,
      "palate_notes": ["array", "of", "strings"] or null,
      "finish_notes": ["array", "of", "strings"] or null,
      "overall_notes": "string or null"
    }}}}
  ]
}}}}

CRITICAL: Extract EVERY wine row from the table. Each row is a separate object in the "tastings" array. Do not skip any rows.

Return ONLY the JSON object."""

        # Read image file as bytes
        with open(image_path, 'rb') as f:
            image_bytes = f.read()

        response = await self.llm.complete(
            task_type="structured_extraction",
            prompt=prompt,
            images=[image_bytes],
            response_format="json"
        )

        # Log raw LLM response for debugging
        logger.debug(f"Raw LLM response: {response.content[:1000]}")  # Log first 1000 chars

        # Parse response and create TastingNote objects with robust error handling
        data = LLMResponseParser.safe_parse_json(
            response.content,
            context="AWS wine tasting (LLM guided)"
        )

        if not data:
            logger.error("Failed to parse LLM response for wine tasting (guided)")
            return TastingExtractionResult(
                tastings=[],
                template_type="aws_wine",
                raw_text=response.content,
                confidence=0.0,
            )

        logger.debug(f"Parsed JSON data successfully")

        tastings = []
        for i, wine_data in enumerate(data.get("tastings", [])):
            try:
                tasting = TastingNote(
                    bottle_name=LLMResponseParser.sanitize_string(
                        wine_data.get("bottle_name"),
                        max_length=200,
                        field_name=f"wine[{i}].bottle_name",
                        default="Unknown Wine"
                    ),
                    taster_name=LLMResponseParser.sanitize_string(
                        data.get("taster_name"),
                        max_length=100,
                        field_name="taster_name",
                        default="Unknown"
                    ),
                    tasting_date=LLMResponseParser.sanitize_date(
                        data.get("tasting_date"),
                        field_name="tasting_date",
                        default=date.today()
                    ),
                    beverage_type="wine",
                    wine_appearance=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_appearance"),
                        min_value=0.0,
                        max_value=3.0,
                        field_name=f"wine[{i}].appearance"
                    ),
                    wine_aroma=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_aroma"),
                        min_value=0.0,
                        max_value=6.0,
                        field_name=f"wine[{i}].aroma"
                    ),
                    wine_taste=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_taste"),
                        min_value=0.0,
                        max_value=6.0,
                        field_name=f"wine[{i}].taste"
                    ),
                    wine_aftertaste=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_aftertaste"),
                        min_value=0.0,
                        max_value=3.0,
                        field_name=f"wine[{i}].aftertaste"
                    ),
                    wine_overall=LLMResponseParser.sanitize_float(
                        wine_data.get("wine_overall"),
                        min_value=0.0,
                        max_value=2.0,
                        field_name=f"wine[{i}].overall"
                    ),
                    nose_notes=LLMResponseParser.sanitize_list(
                        wine_data.get("nose_notes"),
                        field_name=f"wine[{i}].nose_notes"
                    ),
                    palate_notes=LLMResponseParser.sanitize_list(
                        wine_data.get("palate_notes"),
                        field_name=f"wine[{i}].palate_notes"
                    ),
                    finish_notes=LLMResponseParser.sanitize_list(
                        wine_data.get("finish_notes"),
                        field_name=f"wine[{i}].finish_notes"
                    ),
                    overall_notes=LLMResponseParser.sanitize_string(
                        wine_data.get("overall_notes"),
                        field_name=f"wine[{i}].overall_notes"
                    ),
                    place=LLMResponseParser.sanitize_string(
                        data.get("place"),
                        field_name="place"
                    ),
                    theme=LLMResponseParser.sanitize_string(
                        data.get("theme"),
                        field_name="theme"
                    ),
                    price=LLMResponseParser.sanitize_string(
                        wine_data.get("price"),
                        field_name=f"wine[{i}].price"
                    ),
                    confidence=0.9,  # Higher confidence with structure guidance
                )
                tastings.append(tasting)
            except Exception as e:
                logger.error(f"Failed to create tasting note for wine #{i+1}: {e}")
                continue

        return TastingExtractionResult(
            tastings=tastings,
            template_type="aws_wine",
            raw_text=response.content,
            confidence=0.9,
        )

    async def _extract_bourbon(self, image_path: Path) -> TastingExtractionResult:
        """Extract tasting notes from Bourbon Tasting Sheet."""
        prompt = """
Extract the tasting notes from this Bourbon Tasting Sheet image.

This is a BOURBON TASTING for WHISKEY, so validate all flavor descriptors are appropriate for bourbon/whiskey tasting.

The sheet has the following structure:
- Header: "Your Name", "Taste No"
- Notes sections: NOSE, PALATE, FINISH, UNIQUENESS, OVERALL (free text with flavor descriptors and notes)
- Numeric scores: May have handwritten numbers (0-3 range for Nose/Palate/Finish, 0-1 for Overall)
- Rating: 1-5 scale (1="I'd pour this out", 5="All-time favorite!")
- Reveal: Bottle name (filled in after blind tasting)
- Color rating: Visual assessment

IMPORTANT - Extraction Rules:
1. Look for HANDWRITTEN NUMERIC SCORES first (numbers written next to each section)
   - Nose score: 0-3
   - Palate score: 0-3
   - Finish score: 0-3
   - Overall score: 0-1
2. If no numeric scores visible, use the 1-5 rating scale to estimate
3. For flavor descriptors: Extract individual words/phrases from NOSE, PALATE, FINISH sections
4. For overall notes: Extract complete text from OVERALL and UNIQUENESS sections (not just keywords)
5. VALIDATE all flavor descriptors are plausible for bourbon (e.g., "ginger" is valid, "singer" is not)

Common bourbon flavor descriptors include:
- Spices: pepper, cinnamon, nutmeg, clove, ginger, allspice
- Sweet: caramel, vanilla, butterscotch, toffee, honey, brown sugar, maple
- Fruit: cherry, apple, orange, raisin, fig, dried fruit
- Wood: oak, cedar, char, smoke, tobacco, leather
- Grain: corn, wheat, rye, biscuit
- Nuts: almond, walnut, pecan
- Other: chocolate, coffee, mint, anise

Extract ALL filled-in information and return JSON:
{
  "taster_name": "...",
  "taste_number": "...",
  "bottle_name": "... (from REVEAL field)",
  "nose_score": 2.5,  // If handwritten number visible (0-3)
  "palate_score": 2.5,  // If handwritten number visible (0-3)
  "finish_score": 2.5,  // If handwritten number visible (0-3)
  "overall_score": 0.75,  // If handwritten number visible (0-1)
  "nose_notes": ["descriptor1", "descriptor2", ...],  // Individual keywords from NOSE section
  "palate_notes": ["descriptor1", "descriptor2", ...],  // Individual keywords from PALATE section
  "finish_notes": ["descriptor1", "descriptor2", ...],  // Individual keywords from FINISH section
  "overall_notes": "Complete text from OVERALL and UNIQUENESS sections...",  // Full prose, not keywords
  "rating": 4,  // 1-5 rating (if visible, otherwise estimate from notes quality)
  "color": "Amber"  // Color observation
}

If the tasting date is not visible, use today's date.

Return valid JSON only, no other text.
"""

        # Read image file as bytes
        with open(image_path, 'rb') as f:
            image_bytes = f.read()

        response = await self.llm.complete(
            task_type="structured_extraction",
            prompt=prompt,
            images=[image_bytes],
            response_format="json"
        )

        # Parse response and create TastingNote object with robust error handling
        data = LLMResponseParser.safe_parse_json(
            response.content,
            context="bourbon tasting extraction"
        )

        if not data:
            logger.error("Failed to parse LLM response for bourbon tasting")
            return TastingExtractionResult(
                tastings=[],
                template_type="bourbon",
                raw_text=response.content,
                confidence=0.0,
            )

        # Use explicit numeric scores if provided, otherwise fall back to rating-based estimation
        if "nose_score" in data and data.get("nose_score") is not None:
            # Explicit scores provided
            nose_score = LLMResponseParser.sanitize_float(
                data.get("nose_score"),
                min_value=0.0,
                max_value=3.0,
                field_name="nose_score",
                default=2.5
            )
            palate_score = LLMResponseParser.sanitize_float(
                data.get("palate_score"),
                min_value=0.0,
                max_value=3.0,
                field_name="palate_score",
                default=2.5
            )
            finish_score = LLMResponseParser.sanitize_float(
                data.get("finish_score"),
                min_value=0.0,
                max_value=3.0,
                field_name="finish_score",
                default=2.5
            )
            overall_score = LLMResponseParser.sanitize_float(
                data.get("overall_score"),
                min_value=0.0,
                max_value=1.0,
                field_name="overall_score",
                default=0.75
            )
        else:
            # Fall back to rating-based estimation
            rating = LLMResponseParser.sanitize_int(
                data.get("rating"),
                min_value=1,
                max_value=5,
                field_name="rating",
                default=3
            )
            scores = self._rating_to_scores(rating)
            nose_score = scores["nose"]
            palate_score = scores["palate"]
            finish_score = scores["finish"]
            overall_score = scores["overall"]

        try:
            tasting = TastingNote(
                bottle_name=LLMResponseParser.sanitize_string(
                    data.get("bottle_name"),
                    max_length=200,
                    field_name="bottle_name",
                    default="Unknown Bourbon"
                ),
                taster_name=LLMResponseParser.sanitize_string(
                    data.get("taster_name"),
                    max_length=100,
                    field_name="taster_name",
                    default="Unknown"
                ),
                tasting_date=date.today(),  # TODO: Extract if visible
                beverage_type="whiskey",
                whiskey_nose=nose_score,
                whiskey_palate=palate_score,
                whiskey_finish=finish_score,
                whiskey_overall=overall_score,
                nose_notes=LLMResponseParser.sanitize_list(
                    data.get("nose_notes"),
                    field_name="nose_notes"
                ),
                palate_notes=LLMResponseParser.sanitize_list(
                    data.get("palate_notes"),
                    field_name="palate_notes"
                ),
                finish_notes=LLMResponseParser.sanitize_list(
                    data.get("finish_notes"),
                    field_name="finish_notes"
                ),
                overall_notes=LLMResponseParser.sanitize_string(
                    data.get("overall_notes"),
                    field_name="overall_notes"
                ),
                color=LLMResponseParser.sanitize_string(
                    data.get("color"),
                    field_name="color"
                ),
                confidence=0.8,
            )
        except Exception as e:
            logger.error(f"Failed to create bourbon tasting note: {e}")
            return TastingExtractionResult(
                tastings=[],
                template_type="bourbon",
                raw_text=response.content,
                confidence=0.0,
            )

        return TastingExtractionResult(
            tastings=[tasting],
            template_type="bourbon",
            raw_text=response.content,
            confidence=0.8,
        )

    def _rating_to_scores(self, rating: int) -> dict[str, float]:
        """
        Convert 1-5 rating to 10-point scale scores.

        Uses midpoint of each range for consistency.
        """
        score_ranges = {
            5: {"nose": 2.9, "palate": 2.9, "finish": 2.9, "overall": 0.95},  # 9.65 total
            4: {"nose": 2.5, "palate": 2.5, "finish": 2.5, "overall": 0.75},  # 8.25 total
            3: {"nose": 2.0, "palate": 2.0, "finish": 2.0, "overall": 0.55},  # 6.55 total
            2: {"nose": 1.3, "palate": 1.3, "finish": 1.3, "overall": 0.35},  # 4.25 total
            1: {"nose": 0.5, "palate": 0.5, "finish": 0.5, "overall": 0.1},  # 1.6 total
        }

        return score_ranges.get(rating, score_ranges[3])  # Default to 3 if unknown

    def _parse_date(self, date_str: Optional[str]) -> date:
        """Parse date string from various formats."""
        if not date_str:
            return date.today()

        # Try common formats
        import re
        from datetime import datetime

        # Clean up the date string
        date_str = date_str.strip()

        # Try ISO format first
        try:
            return date.fromisoformat(date_str)
        except (ValueError, AttributeError):
            pass

        # Try common formats
        formats = [
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%d/%m/%Y",
            "%B %d, %Y",
            "%b %d, %Y",
            "%m-%d-%Y",
            "%d-%m-%Y",
            "%Y/%m/%d",
            "%m/%d/%y",
            "%b %d %Y",
            "%B %d %Y",
            "%d %b %Y",
            "%d %B %Y",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except (ValueError, AttributeError):
                continue

        # If all else fails, return today
        logger.warning(f"Could not parse date: {date_str}, using today's date")
        return date.today()
