"""Extract bottle metadata from label images using vision LLM."""

from pathlib import Path
from typing import Optional

from loguru import logger
from PIL import Image

from ..core.models import BottleMetadata
from ..llm import LLMGateway
from ..llm.response_parser import LLMResponseParser
from ..utils.image_prep import LABEL_MAX_DIM, encode_for_vision


def _parse_variety_from_llm(val) -> list[str] | None:
    """Normalize LLM variety output to a list. Handles str, list, or None."""
    if val is None:
        return None
    if isinstance(val, list):
        items = [s.strip() for s in val if isinstance(s, str) and s.strip()]
        return items or None
    if isinstance(val, str):
        if not val.strip():
            return None
        import re
        items = [s.strip() for s in re.split(r'\s*[,/]\s*', val) if s.strip()]
        return items or None
    return None


class ImageMetadataExtractor:
    """
    Extract bottle metadata from label images.

    Uses vision LLM to read text and details from bottle labels,
    then enriches with web search for complete metadata.
    """

    # Canonical wine sub-categories, in keyword-match order (most specific first)
    _WINE_TYPE_MAP = [
        (["rosé champagne", "rose champagne", "pink champagne"],  "Rosé Champagne"),
        (["champagne", "prosecco", "cava", "crémant", "cremant", "sparkling", "pétillant", "petillant", "mousseux", "frizzante"], "Sparkling wine"),
        (["port", "porto", "sherry", "madeira", "marsala", "fortified"], "Fortified wine"),
        (["dessert", "ice wine", "icewine", "sauternes", "beerenauslese", "trockenbeerenauslese"], "Dessert wine"),
        (["rosé", "rose"],                                        "Rosé"),
        (["white", "blanc", "bianco", "weiss", "blanco"],         "White wine"),
        (["red", "rouge", "tinto", "rosso", "rot"],               "Red wine"),
    ]

    # Canonical spirit sub-categories, most specific first to prevent early-exit on partial matches
    _SPIRIT_TYPE_MAP = [
        (["bourbon"],                                                       "Bourbon"),
        (["tennessee"],                                                     "Tennessee Whiskey"),
        (["scotch whisky", "scotch whiskey", "scotch",
          "blended scotch", "blended malt"],                               "Scotch Whisky"),
        (["irish whiskey", "irish whisky", "irish"],                       "Irish Whiskey"),
        (["japanese whisky", "japanese whiskey", "japanese"],              "Japanese Whisky"),
        (["canadian whisky", "canadian whiskey", "canadian"],              "Canadian Whisky"),
        (["rye whiskey", "rye whisky", "american rye", "rye"],            "Rye Whiskey"),
        (["indian whisky", "indian whiskey"],                              "Indian Whisky"),
        (["american whiskey", "american whisky"],                          "American Whiskey"),
        (["extra añejo", "extra anejo", "extra-añejo"],                    "Extra Añejo Tequila"),
        (["añejo tequila", "anejo tequila"],                               "Añejo Tequila"),
        (["reposado"],                                                      "Reposado Tequila"),
        (["blanco tequila", "plata tequila", "silver tequila"],            "Blanco Tequila"),
        (["mezcal"],                                                        "Mezcal"),
        (["dark rum"],                                                      "Dark Rum"),
        (["spiced rum"],                                                    "Spiced Rum"),
        (["aged rum", "añejo rum", "anejo rum"],                           "Aged Rum"),
        (["light rum", "white rum", "silver rum"],                         "Light Rum"),
    ]

    # Canonical country names; keys are lowercase normalized variants
    _COUNTRY_MAP = {
        "usa": "United States",
        "us": "United States",
        "u.s.": "United States",
        "u.s.a.": "United States",
        "united states of america": "United States",
        "america": "United States",
        "uk": "United Kingdom",
        "u.k.": "United Kingdom",
        "great britain": "United Kingdom",
        "gb": "United Kingdom",
        "england": "United Kingdom",
        "italia": "Italy",
        "italie": "Italy",
        "españa": "Spain",
        "espana": "Spain",
        "deutschland": "Germany",
    }

    @staticmethod
    def _normalize_wine_beverage_type(raw: str) -> str | None:
        """
        Map a raw LLM type string to a standard wine category.

        Returns a standardized category (e.g. "Red wine", "Rosé") or None
        if the value is unrecognizable (wine name, variety, or empty).
        """
        if not raw:
            return None
        lower = raw.lower().strip()
        for keywords, label in ImageMetadataExtractor._WINE_TYPE_MAP:
            if any(kw in lower for kw in keywords):
                return label
        # "wine" alone or unrecognizable (wine name / variety) — let enrichment fill it in
        return None

    @staticmethod
    def _normalize_spirit_beverage_type(raw: str) -> str | None:
        """
        Map a raw LLM spirit-type string to a canonical sub-category label.

        Returns a standardized label (e.g. "Bourbon", "Scotch Whisky") or None
        if the value is unrecognizable or empty.
        """
        if not raw:
            return None
        lower = raw.lower().strip()
        for keywords, label in ImageMetadataExtractor._SPIRIT_TYPE_MAP:
            if any(kw in lower for kw in keywords):
                return label
        return None

    @staticmethod
    def _normalize_country(raw: str) -> str | None:
        """
        Map common country abbreviations/variants to canonical full names.

        Returns the canonical country name, or the original sanitized value
        if no known variant matches.
        """
        if not raw:
            return None
        key = raw.lower().strip()
        return ImageMetadataExtractor._COUNTRY_MAP.get(key, raw)

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

        # Build extraction prompt. The web upload form sends "auto" when the
        # user didn't pick a type — that means "no hint", not a beverage called
        # "auto" (previously this injected "The bottle is a auto." into the prompt).
        type_hint = ""
        if beverage_type and beverage_type != "auto":
            type_hint = f"\n\nThe bottle is a {beverage_type}."

        # Prompt tuned against the prod collection (2026-07): field-placement
        # rules with examples cut producer/name swaps from 5/23 to 1/23 and took
        # name accuracy from 74% to 96% on the reviewed-bottle eval set.
        prompt = f"""You are reading a photograph of a bottle (wine or spirits). The photo may be rotated or sideways and may show other bottles or clutter — read the label of the main, most prominent bottle only.{type_hint}

First transcribe ALL text you can read on the label, then fill in the fields using the rules below.

PRODUCER vs NAME — the two most important fields:

producer = the company that MADE the product: the distillery, winery, or producing house.
name = the specific product or expression, WITHOUT the producer's name. Keep it concise — a product name, not a sentence. Include batch/lot/edition identifiers (e.g. "Batch 24D", "Lot 23").

How to split them:
1. If the label shows a company name (often near "Distillery", "Distillers", "Winery", "Cellars", "Vineyards", "Estate", "Spirits", or in smaller text at top or bottom) AND a separate product name: producer = the company, name = the product.
   Example: "BLUEGRASS DISTILLERS" (top) + "ELKWOOD RESERVE" (large) → producer="Bluegrass Distillers", name="Elkwood Reserve"
2. If the label shows ONE brand followed by a beverage description, the brand is the producer and the description is the name.
   Example: "WILLETT" (large) + "Family Estate Bottled Single Barrel Bourbon" → producer="Willett", name="Family Estate Bottled Single Barrel Bourbon"
   Example: "KNOBEL" (large) + "Tennessee Whiskey / Barrel Strength" → producer="Knobel", name="Barrel Strength Tennessee Whiskey"
3. EXCEPTION: if the brand is a well-known PRODUCT LINE made by a distillery whose name is not printed on the label (e.g. "George T. Stagg", "Stagg", "Thomas H. Handy", "Eagle Rare", "W.L. Weller", "Blanton's", "Booker's", "Elmer T. Lee" — all products of larger distilleries), then it goes in name, and producer = null. Do NOT fill in the distillery from memory.
   Example: "GEORGE T. STAGG" + "Kentucky Straight Bourbon Whiskey" → producer=null, name="George T. Stagg"
4. Text like "Presented by", "Selected by", "Barrel selected by <store>" names a retailer or barrel picker — it is NEITHER the producer NOR part of the name. Never copy it into any field.
5. The name is the PRINTED product name. Handwritten or filled-in details (barrel number, batch code, proof written on a line) never REPLACE the printed name — at most append a batch/barrel identifier to it.
   Example: "HEAVEN HILL" + "GRAIN TO GLASS / KENTUCKY STRAIGHT RYE WHISKEY" printed, with "Chinquapin, Beck's 6229" handwritten → producer="Heaven Hill", name="Grain to Glass Kentucky Straight Rye Whiskey Beck's 6229"
- producer and name must NEVER contain the same text. If unsure who made it, producer=null — never guess.
- Transcribe names EXACTLY as printed, keeping digits and symbols: write "90+ Cellars", not "Ninety Plus Cellars".

Other fields:
- year: the VINTAGE or bottling year only (e.g. 2019). "EST. 1870" or founding dates are NOT the year. Batch numbers are not years. If both a distillation and a bottling year appear, use the bottling year. null if none printed.
- alcohol: the alcohol content exactly as printed, including units (e.g. "45% ALC/VOL", "68.05% ALC. BY VOL. (136.1 PROOF)"). Proof may be handwritten on craft labels — read carefully.
- region: the geographic origin printed on the label (e.g. "Kentucky", "Napa Valley", "Mendoza"). Not an importer or distributor address.
- age_statement: only if the label states an age (e.g. "Aged 12 Years" → "12 years"). Do NOT compute it from dates. null otherwise.
- proof: proof number if printed (numeric). null otherwise.
- variety: grape varieties for wine as a JSON array (e.g. ["Malbec"]); for whiskey only if grains are explicitly stated. null if not shown.
- vineyard: a specific named vineyard for wine. null otherwise.
- style: a production style ONLY if printed: whiskey e.g. "Single Barrel", "Small Batch", "Cask Strength", "Bottled in Bond"; wine e.g. "Brut", "Reserve", "Old Vine". null otherwise.

IMPORTANT: Only report what is actually printed on the label. If something is not visible, use null — never guess. A wrong value is worse than null; missing values are filled in later from other sources.

Return a JSON object with this exact structure:
{{
  "additional_details": "ALL text transcribed from the label, in reading order",
  "producer": "maker per the rules above, or null",
  "name": "product/expression name per the rules above",
  "year": "vintage or bottling year if printed, otherwise null",
  "type": "standardized beverage category — for wine use ONLY: 'Red wine', 'White wine', 'Rosé', 'Rosé Champagne', 'Sparkling wine', 'Dessert wine', 'Fortified wine'; for spirits use the MOST SPECIFIC type printed on the label: 'Bourbon', 'Wheated Bourbon', 'Rye Whiskey', 'Tennessee Whiskey', 'American Whiskey', 'American Light Whiskey', 'Canadian Whisky', 'Scotch', 'Single Malt Scotch', 'Blended Scotch', 'Irish Whiskey', 'Japanese Whisky', 'Vodka', 'Gin', 'Rum', 'Tequila', 'Mezcal', 'Brandy', 'Cognac'. If the label says 'Tennessee Whiskey', use 'Tennessee Whiskey' — NOT 'Bourbon'. Do NOT use the wine name or grape variety here",
  "beverage_type": "wine OR whiskey OR vodka OR gin OR rum OR tequila OR brandy OR other",
  "alcohol": "alcohol content exactly as printed, or null",
  "region": "geographic origin if shown, otherwise null",
  "variety": ["grape or grain varieties as array"],
  "country": "country if shown, otherwise null",
  "age_statement": "stated age if shown, otherwise null",
  "proof": "proof number if printed (numeric), otherwise null",
  "vineyard": "specific vineyard name for wine if shown, otherwise null",
  "style": "production style if printed, otherwise null",
  "confidence": "high OR medium OR low",
  "missing_year": true or false
}}

For wine type: "Brut", "Brut Nature", "Cava", "Champagne", "Prosecco", "Spumante", or "Méthode" on the label → 'Sparkling wine' (not 'Red wine' or 'White wine').

For beverage_type:
- Any kind of whiskey/whisky/bourbon/rye/scotch → "whiskey"
- Wine, a grape variety, or "vineyard" → "wine"
- "vodka" → "vodka"; "gin" → "gin"; "rum" → "rum"; "tequila" or "mezcal" → "tequila"; "brandy" or "cognac" → "brandy"
- Otherwise → "other"

Return only the JSON, nothing else."""

        try:
            # Convert image to bytes for vision LLM. EXIF orientation, the
            # 1536px cap and single-frame JPEG encoding all live in the shared
            # helper so the manifest path can't drift from this one again.
            image_bytes = encode_for_vision(img, max_dim=LABEL_MAX_DIM)

            logger.debug("=" * 80)
            logger.debug("VISION LLM EXTRACTION - Starting")
            logger.debug(f"Image: {image_path.name} ({len(image_bytes)} bytes)")
            logger.debug("Prompt sent to LLM:")
            logger.debug(prompt)
            logger.debug("=" * 80)

            # Call vision LLM
            # IMPORTANT: Must pass as "images" (plural) as a list, not "image" (singular)
            response = await self.llm_gateway.complete(
                task_type="ocr",
                prompt=prompt,
                images=[image_bytes],  # Fixed: was "image=", should be "images=" as a list
                temperature=0.1,  # Very deterministic for extraction
                max_tokens=3000,  # Increased from 800: reasoning models need ~400-800 tokens to think before answering
            )

            logger.debug("=" * 80)
            logger.debug("VISION LLM RESPONSE - Raw content:")
            logger.debug(response.content)
            logger.debug("=" * 80)

            # Parse JSON response with robust error handling
            extracted_data = LLMResponseParser.safe_parse_json(
                response.content,
                context="image extraction"
            )

            if extracted_data:
                logger.info("=" * 80)
                logger.info("PARSED EXTRACTION DATA:")
                import json
                logger.info(json.dumps(extracted_data, indent=2))
                logger.info("=" * 80)

            if not extracted_data:
                return None, {"error": "Failed to parse extraction response"}

            # Create bottle metadata from extracted data (may use web search for type identification)
            bottle = await self._create_bottle_from_extraction(extracted_data, image_path)

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


    async def _infer_beverage_type(self, extracted_data: dict) -> str:
        """
        Intelligently infer beverage type from extracted data.

        Uses a multi-step approach:
        1. Check LLM-provided beverage_type
        2. Try keyword matching in extracted text
        3. Fall back to web search if available

        Args:
            extracted_data: Data extracted from image

        Returns:
            Beverage type string (wine, whiskey, vodka, gin, rum, tequila, brandy, other)
        """
        logger.info("=" * 80)
        logger.info("BEVERAGE TYPE INFERENCE - Starting")

        # Check LLM-provided beverage_type first
        llm_type = extracted_data.get("beverage_type", "").lower().strip()
        valid_types = ["wine", "whiskey", "vodka", "gin", "rum", "tequila", "brandy", "other"]

        logger.info(f"Step 1: LLM provided beverage_type = '{llm_type}'")

        if llm_type in valid_types:
            logger.info(f"✓ RESULT: Using LLM-provided beverage type: {llm_type}")
            logger.info("=" * 80)
            return llm_type

        # If LLM didn't provide a valid type, infer from other fields
        logger.warning(f"Step 1 FAILED: LLM provided invalid beverage_type '{llm_type}'")
        logger.info("Step 2: Trying keyword matching...")

        # Combine all text fields for comprehensive keyword matching
        all_text = " ".join([
            str(extracted_data.get("producer", "")),
            str(extracted_data.get("name", "")),
            str(extracted_data.get("type", "")),
            " ".join(extracted_data.get("variety", []) or []) if isinstance(extracted_data.get("variety"), list) else str(extracted_data.get("variety", "")),
            str(extracted_data.get("region", "")),
            str(extracted_data.get("additional_details", "")),
        ]).lower()

        logger.info(f"Combined text for keyword matching: {all_text[:200]}...")

        # Keyword dictionaries for each beverage type (order matters - more specific first)
        whiskey_keywords = [
            "bourbon", "rye", "scotch", "whisky", "whiskey", "distillery",
            "single malt", "blended", "tennessee", "kentucky straight",
            "mash bill", "barrel", "cask", "proof", "aged", "straight whiskey"
        ]

        wine_keywords = [
            "winery", "vineyard", "estate", "vintage", "appellation",
            "cabernet", "merlot", "chardonnay", "pinot", "sauvignon",
            "shiraz", "syrah", "zinfandel", "sangiovese", "nebbiolo",
            "bordeaux", "burgundy", "napa", "sonoma", "tuscany",
            "red wine", "white wine", "docg", "doc", "ava", "reserves"
        ]

        vodka_keywords = ["vodka", "водка"]
        gin_keywords = ["gin", "distilled gin", "london dry"]
        rum_keywords = ["rum", "rhum", "aged rum", "spiced rum"]
        tequila_keywords = ["tequila", "añejo", "reposado", "blanco", "mezcal"]
        brandy_keywords = ["brandy", "cognac", "armagnac", "calvados"]

        # Check each type (most specific first)
        matched_whiskey = [kw for kw in whiskey_keywords if kw in all_text]
        if matched_whiskey:
            logger.info(f"✓ Step 2 SUCCESS: Matched whiskey keywords: {matched_whiskey}")
            logger.info("✓ RESULT: whiskey (from keywords)")
            logger.info("=" * 80)
            return "whiskey"

        matched_vodka = [kw for kw in vodka_keywords if kw in all_text]
        if matched_vodka:
            logger.info(f"✓ Step 2 SUCCESS: Matched vodka keywords: {matched_vodka}")
            logger.info("✓ RESULT: vodka (from keywords)")
            logger.info("=" * 80)
            return "vodka"

        matched_gin = [kw for kw in gin_keywords if kw in all_text]
        if matched_gin:
            logger.info(f"✓ Step 2 SUCCESS: Matched gin keywords: {matched_gin}")
            logger.info("✓ RESULT: gin (from keywords)")
            logger.info("=" * 80)
            return "gin"

        matched_rum = [kw for kw in rum_keywords if kw in all_text]
        if matched_rum:
            logger.info(f"✓ Step 2 SUCCESS: Matched rum keywords: {matched_rum}")
            logger.info("✓ RESULT: rum (from keywords)")
            logger.info("=" * 80)
            return "rum"

        matched_tequila = [kw for kw in tequila_keywords if kw in all_text]
        if matched_tequila:
            logger.info(f"✓ Step 2 SUCCESS: Matched tequila keywords: {matched_tequila}")
            logger.info("✓ RESULT: tequila (from keywords)")
            logger.info("=" * 80)
            return "tequila"

        matched_brandy = [kw for kw in brandy_keywords if kw in all_text]
        if matched_brandy:
            logger.info(f"✓ Step 2 SUCCESS: Matched brandy keywords: {matched_brandy}")
            logger.info("✓ RESULT: brandy (from keywords)")
            logger.info("=" * 80)
            return "brandy"

        matched_wine = [kw for kw in wine_keywords if kw in all_text]
        if matched_wine:
            logger.info(f"✓ Step 2 SUCCESS: Matched wine keywords: {matched_wine}")
            logger.info("✓ RESULT: wine (from keywords)")
            logger.info("=" * 80)
            return "wine"

        logger.warning("Step 2 FAILED: No keyword matches found")

        # Keywords didn't match - try web search as fallback
        producer = extracted_data.get("producer", "Unknown")
        name = extracted_data.get("name", "Unknown")

        logger.info("Step 3: Attempting web search...")
        logger.info(f"Producer: {producer}, Name: {name}")

        if producer != "Unknown" and name != "Unknown":
            try:
                # Construct search query
                search_query = f"What type of alcoholic beverage is {producer} {name}? Is it wine, whiskey, vodka, gin, rum, tequila, or brandy? Answer with just the beverage category."

                logger.info(f"Web search query: {search_query}")

                # Perform web search
                search_result = await self.llm_gateway.web_search(search_query, max_tokens=200)

                logger.info(f"Web search result: {search_result}")

                # Parse result to extract beverage type
                result_lower = search_result.lower()
                for bev_type in valid_types:
                    if bev_type in result_lower:
                        logger.info(f"✓ Step 3 SUCCESS: Web search identified beverage type: {bev_type}")
                        logger.info(f"✓ RESULT: {bev_type} (from web search)")
                        logger.info("=" * 80)
                        return bev_type

                logger.warning(f"Step 3 PARTIAL: Web search completed but couldn't identify type from: {search_result[:100]}")

            except Exception as e:
                logger.error(f"Step 3 FAILED: Web search error: {e}")
        else:
            logger.warning(f"Step 3 SKIPPED: Missing producer or name (producer={producer}, name={name})")

        # If we still can't determine, check alcohol content as a hint
        logger.info("Step 4: Checking alcohol content as hint...")
        alcohol = str(extracted_data.get("alcohol", "")).lower()
        logger.info(f"Alcohol field: {alcohol}")

        if "proof" in alcohol:  # Proof is typically used for spirits
            logger.warning("✓ RESULT: 'other' (saw proof measurement, defaulting to generic spirit)")
            logger.info("=" * 80)
            return "other"

        # Last resort: default to wine if we see percentage (most common)
        logger.warning("✗ ALL STEPS FAILED: Defaulting to 'wine'")
        logger.warning(f"Could not confidently determine beverage type from: {all_text[:100]}...")
        logger.info("=" * 80)
        return "wine"

    async def _create_bottle_from_extraction(
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
        # Determine beverage type with comprehensive inference (including web search)
        beverage_type = await self._infer_beverage_type(extracted_data)

        # Parse year
        year = extracted_data.get("year")
        if year and year != "NOT VISIBLE":
            try:
                year = int(year)
            except (ValueError, TypeError):
                year = None
        else:
            year = None

        # Parse alcohol content (can be ABV% or proof)
        alcohol_str = extracted_data.get("alcohol", "")
        abv = None
        proof = None

        if alcohol_str:
            alcohol_lower = str(alcohol_str).lower()
            # Try to extract numeric values
            import re
            numbers = re.findall(r'\d+\.?\d*', alcohol_str)

            if numbers:
                # Check if the string explicitly contains both ABV and proof
                # Example: "68.05% ALC. BY VOL. (136.1 PROOF)"
                if "proof" in alcohol_lower and ("%" in alcohol_str or "abv" in alcohol_lower):
                    # Extract ABV (look for number before %)
                    abv_match = re.search(r'(\d+\.?\d*)\s*%', alcohol_str)
                    if abv_match:
                        abv = float(abv_match.group(1))

                    # Extract proof (look for number before "proof")
                    proof_match = re.search(r'(\d+\.?\d*)\s*proof', alcohol_lower)
                    if proof_match:
                        proof = float(proof_match.group(1))

                    logger.debug(f"Parsed alcohol with both values '{alcohol_str}' -> ABV: {abv}%, Proof: {proof}")

                else:
                    # Only one value provided
                    value = float(numbers[0])

                    # Determine if it's proof or ABV based on keywords or value range
                    if "proof" in alcohol_lower:
                        proof = value
                        abv = value / 2  # Convert proof to ABV
                    elif "%" in alcohol_str or "abv" in alcohol_lower or value < 60:
                        # Most likely ABV if < 60 or has % sign
                        abv = value
                        proof = value * 2  # Convert ABV to proof
                    else:
                        # Ambiguous - assume it's proof if > 60, ABV if < 60
                        if value > 60:
                            proof = value
                            abv = value / 2
                        else:
                            abv = value
                            proof = value * 2

                    logger.debug(f"Parsed alcohol '{alcohol_str}' -> ABV: {abv}%, Proof: {proof}")

        # Sanity check: wine proof can't exceed ~50 (25% ABV fortified max).
        # Values like "75 CL" in the alcohol field produce proof=75 — discard them.
        if proof is not None and beverage_type == "wine" and proof > 50:
            logger.debug(f"Discarding implausible wine proof={proof} (likely bottle volume in alcohol field)")
            proof = None
            abv = None

        # Parse age_statement (whiskey-specific): may arrive as "12 years", "12", or 12
        age_statement = None
        age_raw = extracted_data.get("age_statement")
        if age_raw is not None and age_raw != "":
            try:
                # If the LLM returned a string like "12 years", extract the first integer
                if isinstance(age_raw, str):
                    import re
                    age_match = re.search(r'\d+', age_raw)
                    if age_match:
                        age_statement = int(age_match.group(0))
                else:
                    age_statement = int(age_raw)
            except (ValueError, TypeError):
                age_statement = None

        # Parse proof field directly from extraction (separate from alcohol field parsing above).
        # If the schema field "proof" is set and we didn't already derive proof from "alcohol",
        # use it.
        proof_raw = extracted_data.get("proof")
        if proof is None and proof_raw is not None and proof_raw != "":
            try:
                if isinstance(proof_raw, str):
                    import re
                    proof_match = re.search(r'\d+\.?\d*', proof_raw)
                    if proof_match:
                        proof = float(proof_match.group(0))
                else:
                    proof = float(proof_raw)

                # If we got proof but no abv, derive abv
                if proof is not None and abv is None:
                    abv = proof / 2

                # Sanity check: wine proof can't exceed ~50 (25% ABV fortified max).
                # Values like 75 are bottle volumes (75 CL), not proof — discard them.
                if proof is not None and beverage_type == "wine" and proof > 50:
                    logger.debug(f"Discarding implausible wine proof={proof} (likely bottle volume)")
                    proof = None
                    abv = None
            except (ValueError, TypeError):
                pass

        # Build bottle metadata with robust field sanitization
        bottle_data = {
            "producer": LLMResponseParser.sanitize_string(
                extracted_data.get("producer"),
                max_length=200,
                field_name="producer",
                default="Unknown Producer"
            ),
            "name": LLMResponseParser.sanitize_string(
                extracted_data.get("name"),
                max_length=200,
                field_name="name",
                default="Unknown"
            ),
            "year": year,
            "type": beverage_type,
            "beverage_type": (
                self._normalize_wine_beverage_type(extracted_data.get("type", ""))
                if beverage_type == "wine"
                else (
                    self._normalize_spirit_beverage_type(extracted_data.get("type", ""))
                    or LLMResponseParser.sanitize_string(
                        extracted_data.get("type"), max_length=100, field_name="beverage_type"
                    )
                )
            ),
            "country": self._normalize_country(
                LLMResponseParser.sanitize_string(
                    extracted_data.get("country"),
                    max_length=100,
                    field_name="country"
                )
            ),
            "region": LLMResponseParser.sanitize_string(
                extracted_data.get("region"),
                max_length=200,
                field_name="region"
            ),
            "variety": _parse_variety_from_llm(extracted_data.get("variety")),
            "vineyard": LLMResponseParser.sanitize_string(
                extracted_data.get("vineyard"),
                max_length=200,
                field_name="vineyard"
            ),
            "style": LLMResponseParser.sanitize_string(
                extracted_data.get("style"),
                max_length=100,
                field_name="style"
            ),
            "age_statement": age_statement,
            "abv": abv,
            "proof": proof,
            "price": 0.0,  # Will be enriched or set by user
            "source": f"image:{image_path.name}",
        }

        # Log what we're about to create to help debug empty fields
        logger.info("About to create BottleMetadata:")
        logger.info(f"  producer: '{bottle_data['producer']}'")
        logger.info(f"  name: '{bottle_data['name']}'")
        logger.info(f"  type: '{bottle_data['type']}'")

        if not extracted_data.get("producer") or not extracted_data.get("name"):
            logger.warning("=" * 80)
            logger.warning("EXTRACTION PROBLEM: LLM returned empty producer or name!")
            logger.warning("This usually means:")
            logger.warning("  1. LM Studio is not running")
            logger.warning("  2. The vision model can't read text from images")
            logger.warning("  3. The model returned malformed JSON")
            logger.warning("Check the PARSED EXTRACTION DATA above to see what was extracted")
            logger.warning("Using default values to continue...")
            logger.warning("=" * 80)

        # Create bottle with robust error handling
        bottle = LLMResponseParser.safe_model_create(
            BottleMetadata,
            bottle_data,
            context="image extraction",
            required_defaults={
                "producer": "Unknown Producer",
                "name": "Unknown",
                "type": "other"
            }
        )

        if not bottle:
            logger.error("Failed to create BottleMetadata even with sanitized data")
            # Return a minimal valid bottle as last resort
            bottle = BottleMetadata(
                producer="Unknown Producer",
                name="Unknown",
                type="other",
                source=f"image:{image_path.name}"
            )

        return bottle
