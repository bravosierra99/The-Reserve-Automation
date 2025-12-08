"""Find bottle labels using LLM with web search tools."""

import json
import logging
from pathlib import Path
from typing import Optional

from ..core.models import BottleMetadata, LLMRequest
from ..llm.gateway import LLMGateway

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
        request = LLMRequest(
            prompt=prompt,
            task_type="web_search",  # Route to text model with tools
            max_tokens=2000,
            temperature=0.3,  # Lower temperature for more focused results
        )

        try:
            response = await self.llm.complete(request)

            # Parse JSON response
            images = self._parse_llm_response(response.content)

            logger.info(f"Found {len(images)} label images")
            return images

        except Exception as e:
            logger.error(f"Label search failed: {e}")
            return []

    def _create_search_prompt(self, bottle: BottleMetadata) -> str:
        """Create prompt that instructs LLM to search for bottle labels."""
        query = f"{bottle.producer} {bottle.name}"
        if bottle.year:
            query += f" {bottle.year}"
        query += f" {bottle.type} bottle"

        prompt = f"""You have access to web search tools. Use them to find high-quality bottle label images for this bottle:

**Bottle Information:**
- Producer: {bottle.producer}
- Name: {bottle.name}
- Year: {bottle.year or 'N/A'}
- Type: {bottle.type}

**Your Task:**
1. Search the web for "{query}"
2. Look for official product pages from:
   - Winery/distillery websites
   - Major retailers (wine.com, totalwine.com, etc.)
   - Review sites (vivino.com, wine-searcher.com, etc.)
3. Extract direct image URLs for bottle/label photos
4. Prioritize high-resolution product images

**Requirements:**
- Find 3-5 different image URLs
- Images should show the bottle label clearly
- Prefer official sources over user photos
- Include the source domain for each image

**Output Format:**
Return ONLY a JSON array (no other text):
```json
[
  {{
    "url": "https://example.com/bottle.jpg",
    "source": "wine.com",
    "description": "Official product image"
  }}
]
```

Use your web search tools to find these images now. Return ONLY the JSON array."""

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
