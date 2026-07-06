"""Metadata enrichment service using LLM knowledge."""

import asyncio
from typing import Optional

from loguru import logger

from ..core.models import BottleMetadata
from ..extractors.bottle import _parse_variety_from_llm
from ..llm import LLMGateway
from ..llm.response_parser import LLMResponseParser
from ..llm.tool_executor import ToolExecutor
from ..llm.tools import get_tools_for_task


class MetadataEnricher:
    """
    Enrich bottle metadata using LLM knowledge.

    Uses language models to fill in missing metadata fields like country,
    region, and variety based on the producer name, wine name, and context.
    """

    def __init__(self, llm_gateway: LLMGateway, max_results: int = 5):
        """
        Initialize metadata enricher.

        Args:
            llm_gateway: LLM gateway for making requests
            max_results: Number of DuckDuckGo results to fetch and pass to the LLM
        """
        self.llm_gateway = llm_gateway
        self._searcher = ToolExecutor(max_results=max_results)

    async def enrich_bottle(
        self, bottle: BottleMetadata, fields: Optional[list[str]] = None
    ) -> tuple[BottleMetadata, dict]:
        """
        Enrich a single bottle's metadata.

        Args:
            bottle: Bottle to enrich
            fields: Specific fields to enrich (default: all missing fields)

        Returns:
            Tuple of (enriched bottle, enrichment metadata dict)
        """
        # Determine which fields need enrichment
        missing_fields = self._identify_missing_fields(bottle, fields)

        if not missing_fields:
            logger.debug(f"No missing fields for {bottle.producer} - {bottle.name}")
            return bottle, {"enriched": False, "fields_added": []}

        logger.info(
            f"Enriching {bottle.producer} - {bottle.name}: "
            f"missing {', '.join(missing_fields)}"
        )

        # Build prompt
        prompt = self._build_enrichment_prompt(bottle, missing_fields)

        # Get web search tools for enrichment
        tools = get_tools_for_task("metadata_enrichment")

        # Call LLM with web search tools
        try:
            response = await self.llm_gateway.complete(
                task_type="metadata_enrichment",
                prompt=prompt,
                tools=tools,
                temperature=0.2,
                max_tokens=1200,  # Increased to handle more fields (beverage_type, year, age_statement, proof, abv)
            )

            # Parse response
            enriched_data = self._parse_llm_response(response.content)

            # Update bottle with enriched data
            updated_bottle = self._apply_enrichment(bottle, enriched_data, missing_fields)

            # Track what was added
            fields_added = [
                field for field in missing_fields if enriched_data.get(field)
            ]

            metadata = {
                "enriched": True,
                "fields_added": fields_added,
                "confidence": enriched_data.get("confidence", "unknown"),
                "reasoning": enriched_data.get("reasoning", ""),
                "tokens_used": response.tokens_used,
            }

            logger.info(
                f"✓ Enriched {bottle.producer} - {bottle.name}: "
                f"added {', '.join(fields_added)}"
            )

            return updated_bottle, metadata

        except Exception as e:
            logger.error(f"Failed to enrich {bottle.producer} - {bottle.name}: {e}")
            return bottle, {"enriched": False, "error": str(e)}

    def _identify_missing_fields(
        self, bottle: BottleMetadata, requested_fields: Optional[list[str]] = None
    ) -> list[str]:
        """
        Identify which fields are missing and should be enriched.

        Args:
            bottle: Bottle to check
            requested_fields: Optional list of specific fields to check

        Returns:
            List of field names that are missing
        """
        # Define enrichable fields (common to all beverages)
        # Note: year is NOT enrichable - it's user-provided and used as context for finding other metadata
        enrichable = {
            "producer": bottle.producer,
            "name": bottle.name,
            "beverage_type": bottle.beverage_type,
            "country": bottle.country,
            "region": bottle.region,
        }

        # Add type-specific fields
        if bottle.type == "wine":
            enrichable["abv"] = bottle.abv
            enrichable["variety"] = bottle.variety
            enrichable["vineyard"] = bottle.vineyard
        elif bottle.type == "whiskey":
            enrichable["age_statement"] = bottle.age_statement
            enrichable["proof"] = bottle.proof
            enrichable["mash_bill"] = bottle.mash_bill
            enrichable["barrel_type"] = bottle.barrel_type

        # Filter to requested fields if specified
        if requested_fields:
            enrichable = {k: v for k, v in enrichable.items() if k in requested_fields}

        # Return list of missing fields
        return [field for field, value in enrichable.items() if value is None]

    def _build_enrichment_prompt(
        self, bottle: BottleMetadata, missing_fields: list[str]
    ) -> str:
        """
        Build LLM prompt for metadata enrichment.

        Args:
            bottle: Bottle needing enrichment
            missing_fields: Fields to enrich

        Returns:
            Formatted prompt string
        """
        beverage_type = "wine" if bottle.type == "wine" else "whiskey"

        # Build field descriptions
        field_desc = []
        if "producer" in missing_fields:
            if bottle.type == "wine":
                field_desc.append("- Producer/Winery name (actual producer, may differ from bottle name)")
            else:
                field_desc.append("- Producer/Distillery name (actual distiller, may differ from bottle name)")
        if "name" in missing_fields:
            if bottle.type == "wine":
                field_desc.append("- Wine name (specific product/cuvée name, NOT just grape variety - e.g., '1858 Cabernet Sauvignon', 'Insignia', 'Reserve')")
            else:
                field_desc.append("- Whiskey name (specific product name, NOT just whiskey type - e.g., 'Eagle Rare', 'Blanton's Single Barrel')")
        if "beverage_type" in missing_fields:
            if bottle.type == "wine":
                field_desc.append("- Beverage type: 'Red wine', 'White wine', 'Rosé', 'Champagne', 'Sparkling', etc.")
            else:
                field_desc.append("- Beverage type: 'Bourbon', 'Rye', 'Scotch', 'Irish', 'Japanese', etc.")
        if "country" in missing_fields:
            field_desc.append("- Country of origin")
        if "region" in missing_fields:
            field_desc.append(
                "- Region (wine region, appellation, DOC/IGT for wine; state/country for whiskey)"
            )
        if "abv" in missing_fields:
            field_desc.append("- Alcohol by volume (ABV) percentage")
        if "variety" in missing_fields:
            field_desc.append("- Grape variety or blend composition")
        if "vineyard" in missing_fields:
            field_desc.append("- Vineyard or estate name (if known)")
        if "age_statement" in missing_fields:
            field_desc.append("- Age statement in years (e.g., 12, 18, 25)")
        if "proof" in missing_fields:
            field_desc.append("- Proof (US proof, e.g., 90, 100)")
        if "mash_bill" in missing_fields:
            field_desc.append("- Mash bill composition (e.g., '75% corn, 21% rye, 4% malted barley')")
        if "barrel_type" in missing_fields:
            field_desc.append("- Barrel type (ex-bourbon, new oak, sherry, etc.)")

        fields_str = "\n".join(field_desc)

        # Build JSON template fields (can't use backslashes in f-string expressions)
        json_fields = []
        if "producer" in missing_fields:
            json_fields.append('"producer": "..."')
        if "name" in missing_fields:
            json_fields.append('"name": "..."')
        if "beverage_type" in missing_fields:
            json_fields.append('"beverage_type": "..."')
        if "country" in missing_fields:
            json_fields.append('"country": "..."')
        if "region" in missing_fields:
            json_fields.append('"region": "..."')
        if "abv" in missing_fields:
            json_fields.append('"abv": 14.5')
        if "variety" in missing_fields:
            json_fields.append('"variety": ["Grape1", "Grape2"]  // list; single grape is still a list')
        if "vineyard" in missing_fields:
            json_fields.append('"vineyard": "..."')
        if "age_statement" in missing_fields:
            json_fields.append('"age_statement": 12')
        if "proof" in missing_fields:
            json_fields.append('"proof": 90')
        if "mash_bill" in missing_fields:
            json_fields.append('"mash_bill": "..."')
        if "barrel_type" in missing_fields:
            json_fields.append('"barrel_type": "..."')

        json_fields_str = ",\n  ".join(json_fields)
        if json_fields_str:
            json_fields_str += ","

        vintage_line = f"Vintage: {bottle.year}" if bottle.year else "Vintage: NV"
        country_line = f"Country: {bottle.country}" if bottle.country else ""
        region_line = f"Region: {bottle.region}" if bottle.region else ""

        prompt = f"""You are a {beverage_type} expert. Use web search to find accurate, current metadata for this bottle.

Bottle Information:
Producer: {bottle.producer}
Name: {bottle.name}
{vintage_line}
Type: {bottle.beverage_type or bottle.type}
{country_line}
{region_line}
Price: ${bottle.price}

**Task:** Search the web to find the following missing information:
{fields_str}

**Instructions:**
1. Use web_search to find the producer's website, wine databases, or retailer pages
2. Look for official product information about this specific {beverage_type}
3. **CRITICAL - Producer vs Name**: These are often SWAPPED or confused!
   - Producer = actual winery/distillery (e.g., "Caymus Vineyards", "Buffalo Trace")
   - Name = product/brand/label (e.g., "1858 Cabernet Sauvignon", "George T. Stagg")
   - For wine: "1858 Cabernet Sauvignon" is the NAME from "Caymus Vineyards" (the PRODUCER)
   - For whiskey: "George T. Stagg" is the NAME from "Buffalo Trace" (the PRODUCER)
   - Name should include the product line, NOT just grape variety or whiskey type
4. For wine: Use the provided vintage year to find the correct bottle, then search for producer, name, beverage_type (Red wine/White wine/etc.), grape variety, vineyard, region, ABV
5. For whiskey: Use the provided release year to find the correct bottle, then search for producer (distillery), name, beverage_type (Bourbon/Rye/etc.), age statement, proof, ABV, mash bill, barrel type, and distillery location
6. beverage_type should be specific and match extraction schema: "Red wine", "Bourbon", "Rye", "Single Malt Scotch", etc.
7. For proof and ABV: ABV is universal (percentage), proof is US-specific (2x ABV)
8. Verify information from multiple sources when possible
9. Fill out as many fields as possible - don't leave fields empty if you can find the information

**Confidence levels:**
- "high": Found on official producer website or multiple reliable sources
- "medium": Found on one reliable source (wine-searcher, vivino, retailer)
- "low": Inferred from producer's typical style or general region knowledge

Format your response as JSON:
{{
  {json_fields_str}
  "confidence": "high/medium/low",
  "reasoning": "Brief explanation citing your sources"
}}

**CRITICAL - Name vs Producer vs Variety:**
- Producer: The winery/distillery (e.g., "Caymus Vineyards", "Buffalo Trace")
- Name: The specific product name (e.g., "1858 Cabernet Sauvignon", "Eagle Rare 10 Year")
- Variety: The grape type or whiskey style (e.g., "Cabernet Sauvignon", "Bourbon")
- The name should be the product line/label name, NOT just the grape variety

Only include fields that were requested. Use web search to find real data - don't guess."""

        return prompt

    def _parse_llm_response(self, response_text: str) -> dict:
        """
        Parse LLM response to extract metadata with robust error handling.

        Args:
            response_text: Raw LLM response

        Returns:
            Dictionary with enriched metadata

        Raises:
            ValueError: If response cannot be parsed
        """
        data = LLMResponseParser.safe_parse_json(
            response_text,
            context="metadata enrichment"
        )

        if not data:
            raise ValueError("Failed to parse enrichment response")

        return data

    def _apply_enrichment(
        self, bottle: BottleMetadata, enriched_data: dict, missing_fields: list[str]
    ) -> BottleMetadata:
        """
        Apply enriched data to bottle.

        Args:
            bottle: Original bottle
            enriched_data: Data from LLM
            missing_fields: Fields that were requested

        Returns:
            Updated bottle metadata
        """
        # Create dict from bottle
        bottle_dict = bottle.model_dump()

        # Field sanitization rules
        string_fields_with_limits = {
            "beverage_type": 100,
            "country": 100,
            "region": 200,
            "style": 100,
        }

        int_fields_with_ranges = {
            "age_statement": (0, 150),
        }

        float_fields_with_ranges = {
            "abv": (0.0, 100.0),
            "proof": (0.0, 200.0),
        }

        # Update only the missing fields with robust sanitization
        for field in missing_fields:
            if field in enriched_data and enriched_data[field]:
                value = enriched_data[field]

                # Sanitize based on field type
                if field in string_fields_with_limits:
                    value = LLMResponseParser.sanitize_string(
                        value,
                        max_length=string_fields_with_limits[field],
                        field_name=field
                    )
                elif field in int_fields_with_ranges:
                    min_val, max_val = int_fields_with_ranges[field]
                    value = LLMResponseParser.sanitize_int(
                        value,
                        min_value=min_val,
                        max_value=max_val,
                        field_name=field
                    )
                elif field in float_fields_with_ranges:
                    min_val, max_val = float_fields_with_ranges[field]
                    value = LLMResponseParser.sanitize_float(
                        value,
                        min_value=min_val,
                        max_value=max_val,
                        field_name=field
                    )
                elif field == "variety":
                    value = _parse_variety_from_llm(value)
                elif isinstance(value, str):
                    # Generic string sanitization (no specific limit)
                    value = LLMResponseParser.sanitize_string(value, field_name=field)

                bottle_dict[field] = value

        # Mark as enriched
        bottle_dict["enriched"] = True

        # Create new bottle instance with robust error handling
        enriched_bottle = LLMResponseParser.safe_model_create(
            BottleMetadata,
            bottle_dict,
            context="metadata enrichment application",
            required_defaults={
                "producer": bottle.producer,
                "name": bottle.name,
                "type": bottle.type
            }
        )

        if not enriched_bottle:
            logger.error("Failed to create enriched bottle, returning original")
            return bottle

        return enriched_bottle

    def _sanitize_verified_data(self, verified_data: dict) -> dict:
        """
        Sanitize LLM-returned verification data to handle format issues.

        Converts 'MISSING' strings to None, validates types, handles edge cases.

        Args:
            verified_data: Raw data from LLM

        Returns:
            Sanitized data safe for Pydantic validation
        """
        sanitized = {}

        # Field type definitions for sanitization
        string_fields_with_limits = {
            "producer": 200,
            "name": 200,
            "beverage_type": 100,
            "country": 100,
            "region": 200,
            "style": 100,
            "vineyard": 200,
            "mash_bill": 200,
            "barrel_type": 100,
        }

        int_fields_with_ranges = {
            "age_statement": (0, 150),
        }

        float_fields_with_ranges = {
            "abv": (0.0, 100.0),
            "proof": (0.0, 200.0),
        }

        for field, value in verified_data.items():
            # Skip None values
            if value is None:
                continue

            # Handle 'MISSING' or empty strings -> convert to None
            if isinstance(value, str) and (value.upper() == 'MISSING' or value.strip() == ''):
                continue

            # Sanitize based on field type
            if field in string_fields_with_limits:
                sanitized[field] = LLMResponseParser.sanitize_string(
                    value,
                    max_length=string_fields_with_limits[field],
                    field_name=field
                )
            elif field in int_fields_with_ranges:
                min_val, max_val = int_fields_with_ranges[field]
                sanitized_value = LLMResponseParser.sanitize_int(
                    value,
                    min_value=min_val,
                    max_value=max_val,
                    field_name=field,
                    default=None
                )
                # Only include if we got a valid value (not None)
                if sanitized_value is not None:
                    sanitized[field] = sanitized_value
            elif field in float_fields_with_ranges:
                min_val, max_val = float_fields_with_ranges[field]
                sanitized_value = LLMResponseParser.sanitize_float(
                    value,
                    min_value=min_val,
                    max_value=max_val,
                    field_name=field,
                    default=None
                )
                # Only include if we got a valid value (not None)
                if sanitized_value is not None:
                    sanitized[field] = sanitized_value
            elif field == "variety":
                sanitized[field] = _parse_variety_from_llm(value)
            elif isinstance(value, str):
                # Generic string sanitization (no specific limit)
                sanitized[field] = LLMResponseParser.sanitize_string(
                    value,
                    field_name=field
                )
            else:
                # Pass through other types as-is (dicts, lists, etc.)
                sanitized[field] = value

        return sanitized

    def _build_search_query(self, bottle: BottleMetadata) -> str:
        """Build a targeted search query from bottle data."""
        # Extraction leaves producer as "Unknown Producer" when the label
        # doesn't show one — that placeholder poisons the web query.
        producer = bottle.producer if bottle.producer not in ("Unknown Producer", "Unknown") else None
        name = bottle.name if bottle.name != "Unknown" else None
        parts = [producer, name]
        if bottle.year:
            parts.append(str(bottle.year))
        parts.append(bottle.beverage_type or bottle.type)
        return " ".join(filter(None, parts))

    def _format_search_results(self, search_result: dict) -> str:
        """Format DuckDuckGo results into readable text for the prompt."""
        results = search_result.get("results", [])
        if not results:
            return "No search results found."
        lines = []
        for i, r in enumerate(results, 1):
            lines.append(f"[{i}] {r.get('title', '')}")
            lines.append(f"    URL: {r.get('url', '')}")
            lines.append(f"    {r.get('snippet', '')}")
        return "\n".join(lines)

    async def verify_bottle(
        self, bottle: BottleMetadata
    ) -> tuple[BottleMetadata, dict]:
        """
        Verify and correct ALL bottle metadata using web search.

        Searches DuckDuckGo directly, then makes a single LLM call with the
        results embedded in the prompt. This avoids two LLM round trips (the
        old tool-calling approach needed one call to decide to search and a
        second to process results).

        Args:
            bottle: Bottle to verify

        Returns:
            Tuple of (corrected bottle, verification metadata dict)
        """
        # Determine which fields to verify based on beverage type
        # Note: year is NOT verified - it's user-provided and used as context
        verify_fields = ["producer", "name", "beverage_type", "country", "region"]
        if bottle.type == "wine":
            verify_fields.extend(["abv", "variety", "vineyard"])
        else:  # whiskey and other spirits
            verify_fields.extend(["age_statement", "proof", "mash_bill", "barrel_type"])

        logger.info(
            f"Verifying {bottle.producer} - {bottle.name}: "
            f"{', '.join(verify_fields)}"
        )

        # Step 1: search ourselves — no LLM needed to decide what to search for
        query = self._build_search_query(bottle)
        logger.info(f"Searching: {query}")
        try:
            search_result = await asyncio.wait_for(
                asyncio.to_thread(self._searcher._web_search, {"query": query}),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"DuckDuckGo search timed out for: {query}")
            search_result = {"results": [], "query": query}
        results_text = self._format_search_results(search_result)

        # Step 2: build current-values block
        current_data = []
        for field in verify_fields:
            value = getattr(bottle, field, None)
            current_data.append(f"  {field}: {value if value is not None else 'MISSING'}")

        beverage_type = "wine" if bottle.type == "wine" else "whiskey"

        type_specific_fields = (
            '"abv": 14.5, "variety": ["Grape1", "Grape2"], "vineyard": "...",'
            if bottle.type == "wine"
            else '"age_statement": 12, "proof": 90, "mash_bill": "...", "barrel_type": "...",'
        )

        prompt = f"""You are a {beverage_type} expert. Using the web search results below, verify and correct the extracted metadata for this bottle.

**Web Search Results:**
{results_text}

**Extracted Metadata (may contain errors — verify against search results above):**
Producer: {bottle.producer}
Name: {bottle.name}
Vintage: {bottle.year or 'NV'}
Type: {bottle.beverage_type or bottle.type}

Fields to verify/complete:
{chr(10).join(current_data)}

**Instructions:**
- Use the search results to verify EACH field and correct any errors
- Fill in any MISSING fields using information from the results
- Return ALL fields, even ones that are already correct
- **CRITICAL — Producer vs Name are often swapped by OCR extraction:**
  * Producer = the winery/distillery (e.g., "Caymus Vineyards", "Buffalo Trace")
  * Name = the product label (e.g., "1858 Cabernet Sauvignon", "Eagle Rare 10 Year")
  * If they look swapped, correct BOTH fields
- beverage_type must be specific: "Red wine", "White wine", "Rosé", "Bourbon", "Rye", "Single Malt Scotch", etc.
- For wine: verify country, region/appellation, grape variety/blend, vineyard/estate, ABV
- For whiskey: verify distillery, beverage_type, country, state/region, age statement, proof, mash bill, barrel type
- Be precise: "Napa Valley" not "California"; "Burgundy" not "France"
- Do NOT return or modify the year field

**Return JSON only (no explanations before or after):**
{{
  "producer": "correct producer/winery/distillery",
  "name": "correct product name (not just grape variety)",
  "beverage_type": "specific type",
  "country": "country",
  "region": "region/appellation",
  {type_specific_fields}
  "confidence": "high/medium/low",
  "reasoning": "brief explanation of corrections made"
}}

/no_think"""

        # Step 3: single LLM call — no tools, results already in prompt
        try:
            response = await self.llm_gateway.complete(
                task_type="metadata_enrichment",
                prompt=prompt,
                tools=None,
                temperature=0.1,
                max_tokens=1500,
            )

            # Parse response
            verified_data = self._parse_llm_response(response.content)

            # Sanitize LLM output to handle any format issues (e.g., 'MISSING' strings)
            sanitized_data = self._sanitize_verified_data(verified_data)

            # Check what changed
            changes = {}
            for field in verify_fields:
                old_value = getattr(bottle, field, None)
                new_value = sanitized_data.get(field)

                if new_value and new_value != old_value:
                    changes[field] = {"old": old_value, "new": new_value}

            # Create updated bottle
            bottle_dict = bottle.model_dump()
            for field in verify_fields:
                if field in sanitized_data and sanitized_data[field]:
                    bottle_dict[field] = sanitized_data[field]

            # Use safe model creation to handle any remaining validation issues
            updated_bottle = LLMResponseParser.safe_model_create(
                BottleMetadata,
                bottle_dict,
                context="bottle verification",
                required_defaults={
                    "producer": bottle.producer,
                    "name": bottle.name,
                    "type": bottle.type
                }
            )

            if not updated_bottle:
                logger.error("Failed to create verified bottle, returning original")
                return bottle, {
                    "verified": False,
                    "error": "Validation failed after sanitization",
                    "changes": {}
                }

            metadata = {
                "verified": True,
                "changes": changes,
                "confidence": verified_data.get("confidence", "unknown"),
                "reasoning": verified_data.get("reasoning", ""),
                "tokens_used": response.tokens_used,
            }

            if changes:
                logger.info(
                    f"✓ Corrected {bottle.producer} - {bottle.name}: "
                    f"{len(changes)} field(s) updated"
                )
            else:
                logger.info(f"✓ Verified {bottle.producer} - {bottle.name}: all correct")

            return updated_bottle, metadata

        except Exception as e:
            logger.error(f"Failed to verify {bottle.producer} - {bottle.name}: {e}")
            return bottle, {"verified": False, "error": str(e)}

    async def verify_batch(
        self, bottles: list[BottleMetadata]
    ) -> tuple[list[BottleMetadata], dict]:
        """
        Verify and correct multiple bottles.

        Args:
            bottles: List of bottles to verify

        Returns:
            Tuple of (verified bottles, summary metadata)
        """
        verified_bottles = []
        total_corrections = 0
        total_tokens = 0
        errors = 0

        for bottle in bottles:
            verified_bottle, metadata = await self.verify_bottle(bottle)
            verified_bottles.append(verified_bottle)

            if metadata.get("verified"):
                total_corrections += len(metadata.get("changes", {}))
                total_tokens += metadata.get("tokens_used", 0)
            elif metadata.get("error"):
                errors += 1

        summary = {
            "total_bottles": len(bottles),
            "verified": len(bottles) - errors,
            "errors": errors,
            "total_corrections": total_corrections,
            "total_tokens": total_tokens,
        }

        logger.info(
            f"Batch verification complete: {summary['verified']}/{len(bottles)} bottles, "
            f"{total_corrections} corrections made"
        )

        return verified_bottles, summary

    async def enrich_batch(
        self, bottles: list[BottleMetadata], fields: Optional[list[str]] = None
    ) -> tuple[list[BottleMetadata], dict]:
        """
        Enrich multiple bottles.

        Args:
            bottles: List of bottles to enrich
            fields: Specific fields to enrich (default: all missing fields)

        Returns:
            Tuple of (enriched bottles, summary metadata)
        """
        enriched_bottles = []
        total_fields_added = 0
        total_tokens = 0
        skipped = 0
        errors = 0

        for bottle in bottles:
            enriched_bottle, metadata = await self.enrich_bottle(bottle, fields)
            enriched_bottles.append(enriched_bottle)

            if metadata.get("enriched"):
                total_fields_added += len(metadata.get("fields_added", []))
                total_tokens += metadata.get("tokens_used", 0)
            elif metadata.get("error"):
                errors += 1
            else:
                skipped += 1

        summary = {
            "total_bottles": len(bottles),
            "enriched": len(bottles) - skipped - errors,
            "skipped": skipped,
            "errors": errors,
            "total_fields_added": total_fields_added,
            "total_tokens": total_tokens,
        }

        logger.info(
            f"Batch enrichment complete: {summary['enriched']}/{len(bottles)} bottles, "
            f"{total_fields_added} fields added"
        )

        return enriched_bottles, summary
