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

=== CARD LAYOUT ===
TOP SECTION (header metadata — filled in once for the whole session):
  Name:  <taster's personal name, e.g. "Ben" or "Sarah">
  Date:  <date of the tasting event>
  Place: <location where the tasting took place>
  Theme: <name of the tasting EVENT or SESSION, e.g. "French Reds Night", "Burgundy Blind #3",
          "My First Band of Tasting". This is NOT a wine name — it describes the whole evening.>

TABLE SECTION (one row per wine):
  Each horizontal row = one specific wine being evaluated.
  Columns: Wine Name | Price | Appearance (0-3) | Aroma/Bouquet (0-6) | Taste/Texture (0-6) | Aftertaste (0-3) | Overall Impression (0-2) | Total Score (0-20)

=== CRITICAL FIELD DISTINCTIONS ===
- "theme" = the EVENT name from the header (e.g. "My First Band of Tasting"). It describes the session, not a wine.
- "bottle_name" = the WINE name from the left-most column of a TABLE ROW (e.g. "Chateau Margaux 2018", "Opus One").
  These are DIFFERENT fields. Do NOT put the theme value into bottle_name or vice versa.

=== ROW EXTRACTION RULES ===
1. The table has exactly 4 rows for wines (separated by horizontal lines)
2. Each row is ONE wine, even if the name wraps across multiple lines within that row
3. Skip rows with no scores filled in
4. Combine multi-line wine names into a single string

=== NOTES EXTRACTION ===
This card may have handwritten text notes in addition to numeric scores.
Notes can appear two ways — handle both:

Layout A (table columns): written text inside or adjacent to a score column cell.
Layout B (labeled sections): a clearly labeled section header (e.g. "Aroma:", "Nose:",
  "Taste:", "Palate:", "Finish:", "Aftertaste:", "Overall:") followed by handwritten text.

Map notes to fields as follows — these are the ONLY valid destinations:
  "Aroma", "Bouquet", "Nose", "Smell"          → nose_notes   (array of strings)
  "Taste", "Texture", "Palate", "Mouth"         → palate_notes (array of strings)
  "Finish", "Aftertaste", "Length"              → finish_notes (array of strings)
  "Overall", "Comments", "Notes", other general → overall_notes (single string)

Rules:
- Extract ALL written text you can read, even partial words or short phrases.
- Each distinct descriptor or phrase should be a separate string in the array.
- If a section has a number AND written text, extract both (score in the score field, text in the notes field).
- Do NOT put notes from one section into another section's field.
- If a section has only a number with no written text, leave that notes field as null.

=== OUTPUT FORMAT ===
Return ONLY this JSON, no markdown, no explanation:
{
  "taster_name": "name from the Name field at the top",
  "tasting_date": "YYYY-MM-DD",
  "place": "location from Place field",
  "theme": "event name from Theme field (NOT a wine name)",
  "tastings": [
    {
      "bottle_name": "wine name from this table row (NOT the theme)",
      "price": "price if filled in, else null",
      "wine_appearance": 2.5,
      "wine_aroma": 5.0,
      "wine_taste": 5.5,
      "wine_aftertaste": 2.5,
      "wine_overall": 1.5,
      "nose_notes": ["written text near Aroma column, if any"],
      "palate_notes": ["written text near Taste column, if any"],
      "finish_notes": ["written text near Aftertaste column, if any"],
      "overall_notes": "any general written comments for this wine"
    }
  ]
}
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

        data = self._validate_aws_wine_data(data)

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
        prompt = f"""Extract all wines from this AWS Wine Evaluation Chart. Return ONLY valid JSON, no markdown, no explanations.

=== TABLE TEXT (layout-preserving) ===
{layout_text}

=== FIELD DISTINCTIONS — READ CAREFULLY ===
The card has a header section (filled once per session) and a table section (one row per wine).

Header fields:
  "taster_name" — the person's name (Name field at top)
  "tasting_date" — date of the tasting session
  "place" — location of the tasting
  "theme" — the EVENT or SESSION name (e.g. "My First Band of Tasting", "French Reds Night").
             This is NOT a wine name. It describes the whole evening, not a single bottle.

Table fields (per wine row):
  "bottle_name" — the specific wine/bottle name from that row's Wine column.
                  This is NOT the same as theme. Each row has a different wine name.

Do NOT put the theme value into bottle_name. Do NOT put a wine name into theme.

=== NOTES EXTRACTION ===
Notes may appear as written text in table cells OR in clearly labeled sections
(e.g. "Aroma:", "Nose:", "Taste:", "Palate:", "Finish:", "Aftertaste:", "Overall:").
Map them to fields using these labels — these are the ONLY valid destinations:
  "Aroma" / "Bouquet" / "Nose" / "Smell"        → nose_notes   (array of strings)
  "Taste" / "Texture" / "Palate" / "Mouth"       → palate_notes (array of strings)
  "Finish" / "Aftertaste" / "Length"             → finish_notes (array of strings)
  "Overall" / "Comments" / "Notes" / other       → overall_notes (string)
Extract ALL readable text. Each phrase = one string in the array.
If a section has only a number with no written text, leave notes null.

=== OUTPUT ===
{{{{
  "taster_name": "string",
  "tasting_date": "YYYY-MM-DD",
  "place": "string or null",
  "theme": "event/session name from header — NOT a wine name",
  "tastings": [
    {{{{
      "bottle_name": "wine name from this table row — NOT the theme",
      "price": "string or null",
      "wine_appearance": number or null,
      "wine_aroma": number or null,
      "wine_taste": number or null,
      "wine_aftertaste": number or null,
      "wine_overall": number or null,
      "nose_notes": ["text near Aroma column"] or null,
      "palate_notes": ["text near Taste column"] or null,
      "finish_notes": ["text near Aftertaste column"] or null,
      "overall_notes": "string or null"
    }}}}
  ]
}}}}

Extract EVERY wine row. Return ONLY the JSON object."""

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

        data = self._validate_aws_wine_data(data)
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

    def _validate_aws_wine_data(self, data: dict) -> dict:
        """
        Post-extraction sanity checks for AWS wine card data.

        Catches common LLM mistakes:
        - theme/bottle_name swapped (theme looks like a wine, bottle_name looks like an event)
        - notes all lumped into overall_notes when they belong in category fields
        """
        import re

        theme = (data.get("theme") or "").strip()
        tastings = data.get("tastings") or []

        # --- Check 1: theme/bottle_name swap ---
        # Heuristics: a theme that contains a 4-digit year, or a well-known varietal/producer
        # keyword, is probably a wine name that ended up in the wrong field.
        wine_pattern = re.compile(
            r'\b(19|20)\d{2}\b'                              # vintage year
            r'|cabernet|merlot|pinot|chardonnay|sauvignon'  # varietals
            r'|chateau|domaine|castello|bodega'              # producer words
            r'|blanc|rouge|noir|gris',
            re.IGNORECASE
        )
        event_pattern = re.compile(
            r'\bfirst\b|\bband\b|\bnight\b|\bclub\b|\bblind\b|\bsession\b|\bevent\b|\btasting\b',
            re.IGNORECASE
        )

        if theme and wine_pattern.search(theme):
            # Theme looks like a wine name — check if any bottle_name looks like an event
            for tasting in tastings:
                bottle = (tasting.get("bottle_name") or "").strip()
                if bottle and event_pattern.search(bottle) and not wine_pattern.search(bottle):
                    logger.warning(
                        f"Detected likely theme/bottle_name swap: "
                        f"theme='{theme}' ↔ bottle_name='{bottle}'. Swapping."
                    )
                    tasting["bottle_name"] = theme
                    data["theme"] = bottle
                    break
            else:
                # No clear swap candidate — just warn
                logger.warning(
                    f"theme='{theme}' looks like a wine name but no swap candidate found. "
                    f"Review manually."
                )

        # --- Check 2: all notes in overall_notes, category fields empty ---
        # If overall_notes is populated but nose/palate/finish are all empty,
        # try to split overall_notes on common delimiters into the category fields.
        # This is a best-effort recovery, not guaranteed to be accurate.
        for tasting in tastings:
            overall = (tasting.get("overall_notes") or "").strip()
            has_category_notes = any([
                tasting.get("nose_notes"),
                tasting.get("palate_notes"),
                tasting.get("finish_notes"),
            ])
            if overall and not has_category_notes:
                logger.info(
                    f"Wine '{tasting.get('bottle_name')}': all notes in overall_notes, "
                    f"category note fields empty — leaving as-is (wine cards often have "
                    f"no per-category text notes, only scores)."
                )
                # We intentionally do NOT auto-split: splitting prose into nose/palate/finish
                # without knowing the card layout would produce worse results than leaving
                # everything in overall_notes.

        return data

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
