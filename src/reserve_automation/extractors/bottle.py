"""Bottle extractor using LLM integration."""

import json
from typing import List, Literal

from loguru import logger
from pydantic import ValidationError

from ..core.exceptions import ExtractionError
from ..core.models import BottleMetadata, ParserResult
from ..llm.gateway import LLMGateway
from ..llm.response_parser import LLMResponseParser
from ..llm.prompts.extraction import (
    EXTRACTION_SYSTEM_PROMPT,
    TYPE_DETECTION_PROMPT,
    build_extraction_prompt,
)


class BottleExtractor:
    """
    Extract structured bottle metadata using LLMs.

    Uses LLM Gateway to extract bottle information from parsed text,
    validates the data, and assigns confidence scores.
    """

    def __init__(self, llm_gateway: LLMGateway):
        """
        Initialize bottle extractor.

        Args:
            llm_gateway: Configured LLM gateway instance
        """
        self.llm = llm_gateway

    async def extract(
        self,
        parser_result: ParserResult,
        beverage_type: Literal["wine", "whiskey", "auto"] = "auto",
        expected_count: int = None,
    ) -> List[BottleMetadata]:
        """
        Extract bottle metadata from parsed input.

        Args:
            parser_result: Result from parser (contains raw text)
            beverage_type: Type of beverage to extract ('wine', 'whiskey', 'auto')
            expected_count: Expected number of bottles (helps improve extraction accuracy)

        Returns:
            List of BottleMetadata with confidence scores

        Raises:
            ExtractionError: If extraction fails
        """
        if not parser_result.raw_text.strip():
            logger.warning("Parser result has no text content")
            return []

        # Auto-detect beverage type if needed
        if beverage_type == "auto":
            beverage_type = await self._detect_beverage_type(parser_result.raw_text)
            logger.info(f"Auto-detected beverage type: {beverage_type}")

        # Build extraction prompt
        prompt = build_extraction_prompt(
            text=parser_result.raw_text,
            beverage_type=beverage_type if beverage_type != "mixed" else "auto",
            expected_count=expected_count,
        )

        # Request structured extraction from LLM
        try:
            logger.debug("Requesting bottle extraction from LLM...")
            response = await self.llm.complete(
                task_type="extraction",
                prompt=prompt,
                system=EXTRACTION_SYSTEM_PROMPT,
                response_format="json",
                max_tokens=4000,  # Allow ~200 tokens per bottle for up to 20 bottles
            )

            logger.debug(f"LLM response: {len(response.content)} chars, {response.tokens_used} tokens")

        except Exception as e:
            logger.error(f"LLM extraction request failed: {e}")
            raise ExtractionError(f"Failed to extract bottles: {e}") from e

        # Parse and validate JSON response
        bottles = self._parse_llm_response(
            response.content,
            parser_result.source_type,
        )

        logger.info(f"Extracted {len(bottles)} bottles from {parser_result.source_type}")

        return bottles

    async def _detect_beverage_type(self, text: str) -> str:
        """
        Auto-detect if text contains wine, whiskey, or both.

        Args:
            text: Text to analyze

        Returns:
            'wine', 'whiskey', 'mixed', or 'auto' (if uncertain)
        """
        # Use a small sample of text for detection (first 1000 chars)
        sample = text[:1000]

        prompt = TYPE_DETECTION_PROMPT.format(text=sample)

        try:
            response = await self.llm.complete(
                task_type="type_detection",
                prompt=prompt,
                max_tokens=10,
                temperature=0.0,
            )

            detected = response.content.strip().lower()

            if detected in ["wine", "whiskey", "mixed"]:
                return detected

            logger.warning(f"Type detection returned unexpected value: {detected}")
            return "auto"

        except Exception as e:
            logger.warning(f"Type detection failed, defaulting to auto: {e}")
            return "auto"

    def _parse_llm_response(
        self,
        llm_response: str,
        source_type: str,
    ) -> List[BottleMetadata]:
        """
        Parse and validate LLM JSON response.

        Args:
            llm_response: Raw LLM response text
            source_type: Type of source (for metadata)

        Returns:
            List of validated BottleMetadata objects

        Raises:
            ExtractionError: If JSON is invalid or unparseable
        """
        bottles = []

        # Parse JSON response with robust error handling
        bottles_data = LLMResponseParser.safe_parse_json(
            llm_response,
            context=f"bottle extraction ({source_type})"
        )

        if not bottles_data:
            logger.error("Failed to parse LLM response as JSON")
            raise ExtractionError("LLM did not return valid JSON")

        # Ensure it's a list
        if not isinstance(bottles_data, list):
            logger.warning("LLM response is not a JSON array, wrapping in list")
            bottles_data = [bottles_data]

        # Validate each bottle
        for i, bottle_dict in enumerate(bottles_data):
            # Sanitize all fields before model creation
            sanitized_dict = {
                "producer": LLMResponseParser.sanitize_string(
                    bottle_dict.get("producer"),
                    max_length=200,
                    field_name=f"bottle[{i}].producer",
                    default=f"Unknown_{i+1}"
                ),
                "name": LLMResponseParser.sanitize_string(
                    bottle_dict.get("name"),
                    max_length=200,
                    field_name=f"bottle[{i}].name",
                    default=f"Unknown_{i+1}"
                ),
                "beverage_type": LLMResponseParser.sanitize_string(
                    bottle_dict.get("beverage_type"),
                    max_length=100,
                    field_name=f"bottle[{i}].beverage_type"
                ),
                "country": LLMResponseParser.sanitize_string(
                    bottle_dict.get("country"),
                    max_length=100,
                    field_name=f"bottle[{i}].country"
                ),
                "region": LLMResponseParser.sanitize_string(
                    bottle_dict.get("region"),
                    max_length=200,
                    field_name=f"bottle[{i}].region"
                ),
                "variety": LLMResponseParser.sanitize_string(
                    bottle_dict.get("variety"),
                    field_name=f"bottle[{i}].variety"
                ),
                "style": LLMResponseParser.sanitize_string(
                    bottle_dict.get("style"),
                    max_length=100,
                    field_name=f"bottle[{i}].style"
                ),
                "year": LLMResponseParser.sanitize_int(
                    bottle_dict.get("year"),
                    min_value=1800,
                    max_value=2030,
                    field_name=f"bottle[{i}].year"
                ),
                "abv": LLMResponseParser.sanitize_float(
                    bottle_dict.get("abv"),
                    min_value=0.0,
                    max_value=100.0,
                    field_name=f"bottle[{i}].abv"
                ),
                "proof": LLMResponseParser.sanitize_float(
                    bottle_dict.get("proof"),
                    min_value=0.0,
                    max_value=200.0,
                    field_name=f"bottle[{i}].proof"
                ),
                "price": LLMResponseParser.sanitize_float(
                    bottle_dict.get("price"),
                    min_value=0.0,
                    field_name=f"bottle[{i}].price",
                    default=0.0
                ),
                "source": source_type,
            }

            # Copy over any type field if present
            if "type" in bottle_dict:
                sanitized_dict["type"] = bottle_dict["type"]

            # Copy over whiskey-specific fields
            if "age_statement" in bottle_dict:
                sanitized_dict["age_statement"] = LLMResponseParser.sanitize_int(
                    bottle_dict.get("age_statement"),
                    min_value=0,
                    max_value=150,
                    field_name=f"bottle[{i}].age_statement"
                )

            if "mash_bill" in bottle_dict:
                sanitized_dict["mash_bill"] = LLMResponseParser.sanitize_string(
                    bottle_dict.get("mash_bill"),
                    field_name=f"bottle[{i}].mash_bill"
                )

            if "barrel_type" in bottle_dict:
                sanitized_dict["barrel_type"] = LLMResponseParser.sanitize_string(
                    bottle_dict.get("barrel_type"),
                    field_name=f"bottle[{i}].barrel_type"
                )

            # Create bottle with robust error handling
            bottle = LLMResponseParser.safe_model_create(
                BottleMetadata,
                sanitized_dict,
                context=f"bottle extraction [#{i+1}]",
                required_defaults={
                    "producer": f"Unknown_{i+1}",
                    "name": f"Unknown_{i+1}",
                    "type": "other"
                }
            )

            if bottle:
                # Calculate confidence score
                bottle.confidence = self._calculate_confidence(bottle)
                bottles.append(bottle)
            else:
                logger.error(f"Failed to create bottle #{i+1}, skipping")

        return bottles

    def _calculate_confidence(self, bottle: BottleMetadata) -> float:
        """
        Calculate extraction confidence based on field completeness.

        Scoring (max 1.0):
        - Required fields present: 0.5
        - Year present and valid: 0.2
        - Type/variety specified: 0.15
        - Region/country specified: 0.1
        - Price present: 0.05

        Args:
            bottle: BottleMetadata to score

        Returns:
            Confidence score (0.0 - 1.0)
        """
        score = 0.0

        # Required fields present (0.5 points)
        if bottle.producer and bottle.name:
            score += 0.5

        # Year present and valid (0.2 points)
        if bottle.year and 1800 <= bottle.year <= 2030:
            score += 0.2

        # Type/variety specified (0.15 points)
        if bottle.beverage_type or bottle.variety:
            score += 0.15

        # Region/country specified (0.1 points)
        if bottle.region or bottle.country:
            score += 0.1

        # Price present (0.05 points)
        if bottle.price is not None and bottle.price > 0:
            score += 0.05

        return min(score, 1.0)
