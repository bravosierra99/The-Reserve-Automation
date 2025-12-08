"""Web-based image search for bottle labels using Task agent."""

import json
import logging
from pathlib import Path
from typing import Optional

import httpx

from ..core.models import BottleMetadata

logger = logging.getLogger(__name__)


class BottleLabelSearcher:
    """Search for bottle label images using web search and scraping."""

    def __init__(self):
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def construct_search_query(self, bottle: BottleMetadata) -> str:
        """Construct search query for bottle label."""
        parts = []
        if bottle.producer:
            parts.append(bottle.producer)
        if bottle.name:
            parts.append(bottle.name)
        if bottle.year:
            parts.append(str(bottle.year))
        if bottle.type:
            parts.append(bottle.type)
        parts.append("bottle")

        return " ".join(parts)

    def create_search_task_prompt(self, bottle: BottleMetadata) -> str:
        """
        Create prompt for Task agent to search for bottle label images.

        The Task agent has access to WebSearch and WebFetch tools.
        """
        query = self.construct_search_query(bottle)

        prompt = f"""
Find bottle label images for this bottle:

**Bottle Details:**
- Producer: {bottle.producer}
- Name: {bottle.name}
- Year: {bottle.year or 'N/A'}
- Type: {bottle.type}

**Task:**
1. Use WebSearch to find official product pages, retailer listings, or review sites for this bottle
2. Use WebFetch on the most promising URLs to extract image URLs
3. Look for high-quality bottle label/front images (not photos of glasses, people, etc.)
4. Prioritize official sources (distillery websites, major retailers like Total Wine, Binny's, etc.)

**Return Format:**
Return a JSON array of image URLs with metadata:
```json
[
  {{
    "url": "https://example.com/bottle.jpg",
    "source": "total-wine.com",
    "description": "Official product photo from Total Wine",
    "likely_quality": "high"
  }}
]
```

Search query: "{query}"

Focus on finding 3-5 high-quality label images from reputable sources.
"""
        return prompt

    def download_image(self, url: str, output_path: Path) -> bool:
        """Download image from URL."""
        try:
            logger.info(f"Downloading: {url}")
            response = self.client.get(url)
            response.raise_for_status()

            # Validate content type
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                logger.warning(f"Not an image: {content_type}")
                return False

            # Save image
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)

            file_size = len(response.content) / 1024  # KB
            logger.info(f"Saved {file_size:.1f}KB to {output_path}")
            return True

        except Exception as e:
            logger.error(f"Download failed: {e}")
            return False

    def get_label_folder(self, bottle_folder: Path) -> Path:
        """Get labels subfolder for bottle."""
        return bottle_folder / "labels"

    def get_label_path(self, bottle_folder: Path, filename: str = "label.jpg") -> Path:
        """Get path for label image."""
        return self.get_label_folder(bottle_folder) / filename

    def has_label(self, bottle_folder: Path) -> bool:
        """Check if bottle has any label images."""
        label_folder = self.get_label_folder(bottle_folder)
        if not label_folder.exists():
            return False
        return any(label_folder.glob("*.jpg")) or any(label_folder.glob("*.png"))

    def close(self):
        """Close HTTP client."""
        self.client.close()
