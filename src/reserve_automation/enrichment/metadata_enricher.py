"""Metadata enrichment service using LLM knowledge."""

import json
from typing import Optional

from loguru import logger

from ..core.models import BottleMetadata
from ..llm import LLMGateway


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

        # Call LLM
        try:
            response = await self.llm_gateway.complete(
                task_type="metadata_enrichment",
                prompt=prompt,
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

        prompt = f"""You are a {beverage_type} expert helping to complete metadata for a bottle.

Bottle Information:
Producer: {bottle.producer}
Name: {bottle.name}
{"Vintage: " + str(bottle.year) if bottle.year else "Vintage: NV"}
Type: {bottle.beverage_type or bottle.type}
{"Country: " + bottle.country if bottle.country else ""}
{"Region: " + bottle.region if bottle.region else ""}
Price: ${bottle.price}

Based on your knowledge of {beverage_type} regions, producers, and appellations, provide the following missing information:
{fields_str}

Consider the producer name, {beverage_type} name, and any regional indicators to make informed predictions.
If you're highly confident, mark confidence as "high". If it's an educated guess, use "medium". If very uncertain, use "low".

Format your response as JSON:
{{
  "country": "...",
  "region": "...",
  "variety": "...",
  {"\"vineyard\": \"...\"," if "vineyard" in missing_fields else ""}
  {"\"mash_bill\": \"...\"," if "mash_bill" in missing_fields else ""}
  {"\"barrel_type\": \"...\"," if "barrel_type" in missing_fields else ""}
  "confidence": "high/medium/low",
  "reasoning": "Brief explanation of how you determined these values"
}}

Only include fields that were requested. If you don't know a value, omit it or set it to null."""

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
