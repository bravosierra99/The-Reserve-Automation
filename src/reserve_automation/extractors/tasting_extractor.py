"""Extract tasting notes from filled-out tasting card images."""

import logging
from datetime import date
from pathlib import Path
from typing import Literal, Optional

from ..core.models import LLMRequest
from ..core.tasting_note import TastingExtractionResult, TastingNote
from ..llm.gateway import LLMGateway

logger = logging.getLogger(__name__)


class TastingExtractor:
    """Extract structured tasting notes from images of filled-out tasting cards."""

    def __init__(self, llm_gateway: LLMGateway):
        self.llm = llm_gateway

    async def extract_from_image(
        self,
        image_path: Path,
        template_type: Optional[Literal["aws_wine", "bourbon"]] = None,
    ) -> TastingExtractionResult:
        """
        Extract tasting notes from an image of a filled-out tasting card.

        Args:
            image_path: Path to image file
            template_type: Type of template (auto-detected if None)

        Returns:
            TastingExtractionResult with extracted tastings
        """
        logger.info(f"Extracting tasting notes from {image_path}")

        # Step 1: Auto-detect template type if not provided
        if template_type is None:
            template_type = await self._detect_template_type(image_path)
            logger.info(f"Detected template type: {template_type}")

        # Step 2: Extract based on template type
        if template_type == "aws_wine":
            result = await self._extract_aws_wine(image_path)
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

    async def _extract_aws_wine(self, image_path: Path) -> TastingExtractionResult:
        """Extract tasting notes from AWS Wine Evaluation Chart."""
        prompt = """
Extract ALL tasting notes from this AWS Wine Evaluation Chart image.

The chart has the following structure:
- Header: Name (taster), Date, Place, Theme
- Table columns: Wine | Price | Appearance (3 max) | Aroma/Bouquet (6 max) | Taste/Texture (6 max) | Aftertaste (3 max) | Overall Impression (2 max) | Total Score (20 max)

For EACH wine row that has been filled out, extract:
1. Wine name (from "Wine" column)
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
      "bottle_name": "Wine name",
      "price": "...",
      "appearance": 2.5,
      "aroma": 5.0,
      "taste": 5.5,
      "aftertaste": 2.5,
      "overall": 1.5,
      "total_score": 17.0
    }
  ]
}

Important:
- Only include wines that have been filled out (non-empty rows)
- If a score is partially filled or unclear, estimate it
- If date is missing the year, use 2025
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

        # Parse response and create TastingNote objects
        import json

        data = json.loads(response.content)

        tastings = []
        for wine_data in data.get("tastings", []):
            tasting = TastingNote(
                bottle_name=wine_data["bottle_name"],
                taster_name=data.get("taster_name", "Unknown"),
                tasting_date=date.fromisoformat(data.get("tasting_date", str(date.today()))),
                beverage_type="wine",
                wine_appearance=wine_data.get("appearance"),
                wine_aroma=wine_data.get("aroma"),
                wine_taste=wine_data.get("taste"),
                wine_aftertaste=wine_data.get("aftertaste"),
                wine_overall=wine_data.get("overall"),
                place=data.get("place"),
                theme=data.get("theme"),
                price=wine_data.get("price"),
                confidence=0.8,  # TODO: Calculate based on completeness
            )
            tastings.append(tasting)

        return TastingExtractionResult(
            tastings=tastings,
            template_type="aws_wine",
            raw_text=response.content,
            confidence=0.8,
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

        # Parse response and create TastingNote object
        import json

        data = json.loads(response.content)

        # Use explicit numeric scores if provided, otherwise fall back to rating-based estimation
        if "nose_score" in data and data["nose_score"] is not None:
            # Explicit scores provided
            nose_score = data.get("nose_score", 2.5)
            palate_score = data.get("palate_score", 2.5)
            finish_score = data.get("finish_score", 2.5)
            overall_score = data.get("overall_score", 0.75)
        else:
            # Fall back to rating-based estimation
            rating = data.get("rating", 3)
            scores = self._rating_to_scores(rating)
            nose_score = scores["nose"]
            palate_score = scores["palate"]
            finish_score = scores["finish"]
            overall_score = scores["overall"]

        tasting = TastingNote(
            bottle_name=data.get("bottle_name", "Unknown Bourbon"),
            taster_name=data.get("taster_name", "Unknown"),
            tasting_date=date.today(),  # TODO: Extract if visible
            beverage_type="whiskey",
            whiskey_nose=nose_score,
            whiskey_palate=palate_score,
            whiskey_finish=finish_score,
            whiskey_overall=overall_score,
            nose_notes=data.get("nose_notes", []),
            palate_notes=data.get("palate_notes", []),
            finish_notes=data.get("finish_notes", []),
            overall_notes=data.get("overall_notes"),
            color=data.get("color"),
            confidence=0.8,
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
