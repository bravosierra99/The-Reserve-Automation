"""Metadata enrichment service using LLM knowledge."""

import json
from typing import Optional

from loguru import logger

from ..core.models import BottleMetadata
from ..llm import LLMGateway
from ..llm.tools import get_tools_for_task


class MetadataEnricher:
    """
    Enrich bottle metadata using LLM knowledge.

    Uses language models to fill in missing metadata fields like country,
    region, and variety based on the producer name, wine name, and context.
    """

    def __init__(self, llm_gateway: LLMGateway):
        """
        Initialize metadata enricher.

        Args:
            llm_gateway: LLM gateway for making requests
        """
        self.llm_gateway = llm_gateway

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
                max_tokens=800,
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
        # Define enrichable fields
        enrichable = {
            "country": bottle.country,
            "region": bottle.region,
            "variety": bottle.variety,
        }

        # Add type-specific fields
        if bottle.type == "wine":
            enrichable["vineyard"] = bottle.vineyard
        elif bottle.type == "whiskey":
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
        if "country" in missing_fields:
            field_desc.append("- Country of origin")
        if "region" in missing_fields:
            field_desc.append(
                "- Region (wine region, appellation, DOC/IGT for wine; state/country for whiskey)"
            )
        if "variety" in missing_fields:
            if bottle.type == "wine":
                field_desc.append("- Grape variety or blend composition")
            else:
                field_desc.append("- Whiskey type (bourbon, rye, scotch, etc.)")
        if "vineyard" in missing_fields:
            field_desc.append("- Vineyard or estate name (if known)")
        if "mash_bill" in missing_fields:
            field_desc.append("- Mash bill composition")
        if "barrel_type" in missing_fields:
            field_desc.append("- Barrel type (ex-bourbon, new oak, sherry, etc.)")

        fields_str = "\n".join(field_desc)

        prompt = f"""You are a {beverage_type} expert. Use web search to find accurate, current metadata for this bottle.

Bottle Information:
Producer: {bottle.producer}
Name: {bottle.name}
{"Vintage: " + str(bottle.year) if bottle.year else "Vintage: NV"}
Type: {bottle.beverage_type or bottle.type}
{"Country: " + bottle.country if bottle.country else ""}
{"Region: " + bottle.region if bottle.region else ""}
Price: ${bottle.price}

**Task:** Search the web to find the following missing information:
{fields_str}

**Instructions:**
1. Use web_search to find the producer's website, wine databases, or retailer pages
2. Look for official product information about this specific {beverage_type}
3. For wine: Search for the specific vintage and vineyard if applicable
4. For whiskey: Search for mash bill, barrel type, and distillery location
5. Verify information from multiple sources when possible

**Confidence levels:**
- "high": Found on official producer website or multiple reliable sources
- "medium": Found on one reliable source (wine-searcher, vivino, retailer)
- "low": Inferred from producer's typical style or general region knowledge

Format your response as JSON:
{{
  "country": "...",
  "region": "...",
  "variety": "...",
  {"\"vineyard\": \"...\"," if "vineyard" in missing_fields else ""}
  {"\"mash_bill\": \"...\"," if "mash_bill" in missing_fields else ""}
  {"\"barrel_type\": \"...\"," if "barrel_type" in missing_fields else ""}
  "confidence": "high/medium/low",
  "reasoning": "Brief explanation citing your sources"
}}

Only include fields that were requested. Use web search to find real data - don't guess."""

        return prompt

    def _parse_llm_response(self, response_text: str) -> dict:
        """
        Parse LLM response to extract metadata.

        Args:
            response_text: Raw LLM response

        Returns:
            Dictionary with enriched metadata

        Raises:
            ValueError: If response cannot be parsed
        """
        try:
            # Try to extract JSON from response (might be wrapped in markdown)
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1

            if json_start < 0 or json_end <= json_start:
                raise ValueError("No JSON found in response")

            json_str = response_text[json_start:json_end]
            data = json.loads(json_str)

            return data

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from LLM response: {e}")
            logger.debug(f"Response was: {response_text}")
            raise ValueError(f"Invalid JSON in response: {e}")

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

        # Update only the missing fields
        for field in missing_fields:
            if field in enriched_data and enriched_data[field]:
                bottle_dict[field] = enriched_data[field]

        # Mark as enriched
        bottle_dict["enriched"] = True

        # Create new bottle instance
        return BottleMetadata(**bottle_dict)

    async def verify_bottle(
        self, bottle: BottleMetadata
    ) -> tuple[BottleMetadata, dict]:
        """
        Verify and correct ALL bottle metadata using web search.

        Unlike enrich_bottle which only fills missing fields, this method
        verifies existing data and corrects any inaccuracies.

        Args:
            bottle: Bottle to verify

        Returns:
            Tuple of (corrected bottle, verification metadata dict)
        """
        # Determine which fields to verify based on beverage type
        verify_fields = ["country", "region", "variety"]
        if bottle.type == "wine":
            verify_fields.append("vineyard")
        else:
            verify_fields.extend(["mash_bill", "barrel_type"])

        logger.info(
            f"Verifying {bottle.producer} - {bottle.name}: "
            f"{', '.join(verify_fields)}"
        )

        # Build verification prompt with current values
        current_data = []
        for field in verify_fields:
            value = getattr(bottle, field, None)
            current_data.append(f"{field.title()}: {value or 'MISSING'}")

        beverage_type = "wine" if bottle.type == "wine" else "whiskey"

        prompt = f"""You are a {beverage_type} expert. Use web search to verify and correct the metadata for this bottle.

**Bottle Information:**
Producer: {bottle.producer}
Name: {bottle.name}
Vintage: {bottle.year or 'NV'}
Type: {bottle.beverage_type or bottle.type}

**Current Metadata (TO BE VERIFIED):**
{chr(10).join(current_data)}

**Task:**
1. Search the web for this specific {beverage_type} bottle
2. Find official sources (producer website, wine-searcher, vivino, reputable retailers)
3. Verify EACH field above is correct
4. Return the correct value for EVERY field (even if already correct)

**Instructions:**
- Use web_search to find authoritative information
- For wine: verify country, region (appellation/DOC), grape variety/blend, and vineyard/estate
- For whiskey: verify distillery country, region/state, whiskey type, mash bill %, and barrel type
- Cross-reference multiple sources when possible
- Be precise: "Napa Valley" is different from "California"
- Return ALL fields, not just corrections

**Return JSON:**
{{
  "country": "correct country name",
  "region": "correct region/appellation",
  "variety": "correct variety or blend",
  {"\"vineyard\": \"vineyard or estate name\"," if bottle.type == "wine" else ""}
  {"\"mash_bill\": \"mash bill composition\"," if bottle.type == "whiskey" else ""}
  {"\"barrel_type\": \"barrel type\"," if bottle.type == "whiskey" else ""}
  "confidence": "high/medium/low",
  "reasoning": "Brief explanation citing your sources"
}}

Use web search to find accurate, current data - don't guess."""

        # Get web search tools
        tools = get_tools_for_task("metadata_enrichment")

        # Call LLM with web search
        try:
            response = await self.llm_gateway.complete(
                task_type="metadata_enrichment",
                prompt=prompt,
                tools=tools,
                temperature=0.1,  # Very deterministic for verification
                max_tokens=1000,
            )

            # Parse response
            verified_data = self._parse_llm_response(response.content)

            # Check what changed
            changes = {}
            for field in verify_fields:
                old_value = getattr(bottle, field, None)
                new_value = verified_data.get(field)

                if new_value and new_value != old_value:
                    changes[field] = {"old": old_value, "new": new_value}

            # Create updated bottle
            bottle_dict = bottle.model_dump()
            for field in verify_fields:
                if field in verified_data and verified_data[field]:
                    bottle_dict[field] = verified_data[field]

            updated_bottle = BottleMetadata(**bottle_dict)

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
