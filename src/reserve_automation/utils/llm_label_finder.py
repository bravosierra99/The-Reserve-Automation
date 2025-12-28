"""Find bottle labels using LLM with web search tools."""

import json
import logging
from pathlib import Path
from typing import Optional

from ..core.models import BottleMetadata
from ..llm.gateway import LLMGateway
from ..llm.tools import get_tools_for_task

logger = logging.getLogger(__name__)


class LLMLabelFinder:
    """Find bottle labels using LLM with tool-calling (web search) capabilities."""

    def __init__(self, llm_gateway: LLMGateway):
        self.llm = llm_gateway

    async def find_label_images(self, bottle: BottleMetadata) -> list[dict]:
        """
        Use LLM with web search tools to find bottle label images.

        Args:
            bottle: Bottle to search for

        Returns:
            List of dicts with image URLs and metadata:
            [{"url": "...", "source": "...", "description": "..."}]
        """
        prompt = self._create_search_prompt(bottle)

        logger.info(f"Searching for labels: {bottle.producer} {bottle.name}")

        # Send request to LLM (which has web search tools)
        try:
            # Get web research tools
            tools = get_tools_for_task("web_research")

            response = await self.llm.complete(
                task_type="web_research",  # Route to text model with tools
                prompt=prompt,
                tools=tools,  # Pass web search and fetch tools
                max_tokens=2000,
                temperature=0.3,  # Lower temperature for more focused results
            )

            # Log raw response for debugging
            logger.debug(f"LLM raw response: {response.content[:500]}")

            # Parse JSON response
            images = self._parse_llm_response(response.content)

            logger.info(f"Found {len(images)} label images")

            # Log found URLs for verification
            for img in images:
                logger.debug(f"  URL: {img['url']} from {img['source']}")

            return images

        except Exception as e:
            logger.error(f"Label search failed: {e}")
            return []

    def _create_search_prompt(self, bottle: BottleMetadata) -> str:
        """Create prompt that instructs LLM to search for bottle labels."""
        # Build search query with ALL relevant metadata
        query = f"{bottle.producer} {bottle.name}"
        if bottle.year:
            query += f" {bottle.year}"

        # Add variety/mash_bill for specificity
        if bottle.variety and bottle.variety != "MISSING":
            query += f" {bottle.variety}"
        elif bottle.mash_bill and bottle.mash_bill != "MISSING":
            query += f" {bottle.mash_bill}"

        # Add region for wines
        if bottle.region and bottle.region != "MISSING":
            query += f" {bottle.region}"

        query += f" {bottle.type} bottle label"

        # Build detailed bottle description for prompt
        bottle_desc = f"{bottle.producer} {bottle.name}"
        if bottle.year:
            bottle_desc += f" {bottle.year}"
        if bottle.variety and bottle.variety != "MISSING":
            bottle_desc += f" ({bottle.variety})"
        elif bottle.mash_bill and bottle.mash_bill != "MISSING":
            bottle_desc += f" ({bottle.mash_bill})"
        if bottle.region and bottle.region != "MISSING":
            bottle_desc += f" from {bottle.region}"
        if bottle.vineyard and bottle.vineyard != "MISSING":
            bottle_desc += f" - {bottle.vineyard}"
        if bottle.age_statement and bottle.age_statement != "MISSING":
            bottle_desc += f" - {bottle.age_statement}"
        bottle_desc += f" {bottle.type}"

        prompt = f"""CRITICAL: You MUST use your web search tool to find REAL URLs. Do NOT make up or guess URLs.

**Task: Find bottle label image URLs**

Bottle: {bottle_desc}

**REQUIRED STEPS:**
1. USE WEB SEARCH TOOL to search: "{query}"
2. From search results, visit 3-5 promising pages (wine.com, totalwine.com, vivino.com, wine-searcher.com, winery sites)
3. Extract ACTUAL image URLs from those pages (look for <img> tags, product photos)
4. Verify each URL starts with http:// or https://
5. Return ONLY real URLs you found

**DO NOT:**
- Make up placeholder URLs
- Return example.com URLs
- Guess at URL patterns
- Return URLs you didn't find via search

**Output Format:**
Return ONLY valid JSON with REAL URLs you found:
```json
[
  {{
    "url": "https://ACTUAL-DOMAIN.com/path/to/REAL-image.jpg",
    "source": "ACTUAL-DOMAIN.com",
    "description": "What you see on the page"
  }}
]
```

If you cannot find any images, return an empty array: []

NOW: Use your web search tool and find REAL image URLs."""

        return prompt

    def _parse_llm_response(self, content: str) -> list[dict]:
        """Parse LLM response to extract image URLs."""
        try:
            # Remove markdown code blocks if present
            content = content.strip()
            if content.startswith("```"):
                # Extract content between ```json and ```
                lines = content.split("\n")
                content = "\n".join(lines[1:-1])

            # Parse JSON
            images = json.loads(content)

            # Validate structure
            if not isinstance(images, list):
                logger.warning("LLM response is not a list")
                return []

            # Validate each image entry
            valid_images = []
            for img in images:
                if isinstance(img, dict) and "url" in img:
                    valid_images.append({
                        "url": img.get("url"),
                        "source": img.get("source", "unknown"),
                        "description": img.get("description", ""),
                    })

            return valid_images

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {e}")
            logger.debug(f"Response content: {content}")
            return []
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}")
            return []

    async def find_and_score_label_images(
        self, bottle: BottleMetadata, label_processor
    ) -> list[dict]:
        """
        Find label images and score them by quality.

        Args:
            bottle: Bottle to search for
            label_processor: LabelImageProcessor instance for quality scoring

        Returns:
            List of scored images sorted by quality (highest first)
            Each dict has: {"url": "...", "source": "...", "description": "...", "score": 7.5}
        """
        # Find candidate images using existing method
        images = await self.find_label_images(bottle)

        if not images:
            return []

        logger.info(f"Scoring {len(images)} candidate images...")

        # Score each image
        scored_images = []

        for img in images:
            try:
                # Download image to memory for scoring
                import httpx

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(img["url"])
                    response.raise_for_status()
                    image_bytes = response.content

                # Score quality
                score = await label_processor.score_label_quality(image_bytes, bottle)

                if score is not None:
                    img["score"] = score
                    scored_images.append(img)
                    logger.info(f"  {img['source']}: {score:.1f}/10")
                else:
                    logger.warning(f"  {img['source']}: scoring failed, skipping")

            except Exception as e:
                logger.warning(f"  {img['source']}: download/score failed - {e}")
                continue

        # Filter to quality threshold (>= 7.0)
        quality_images = [img for img in scored_images if img["score"] >= 7.0]

        # Sort by score descending
        quality_images.sort(key=lambda x: x["score"], reverse=True)

        logger.info(
            f"Found {len(quality_images)} high-quality images (>= 7.0) "
            f"out of {len(images)} total"
        )

        return quality_images
