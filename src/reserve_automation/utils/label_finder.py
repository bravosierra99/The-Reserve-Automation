"""Find and download bottle label images from the web."""

import logging
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus

import httpx

from ..core.bottle import BottleMetadata

logger = logging.getLogger(__name__)


class LabelImage:
    """Represents a found label image."""

    def __init__(self, url: str, title: str, source: str, thumbnail_url: Optional[str] = None):
        self.url = url
        self.title = title
        self.source = source
        self.thumbnail_url = thumbnail_url

    def __repr__(self):
        return f"LabelImage(url={self.url}, title={self.title})"


class LabelFinder:
    """Find bottle label images using web search."""

    def __init__(self, web_search_enabled: bool = True):
        self.web_search_enabled = web_search_enabled
        self.client = httpx.Client(timeout=30.0, follow_redirects=True)

    def construct_search_query(self, bottle: BottleMetadata) -> str:
        """
        Construct search query for finding bottle label images.

        Format: "{Producer} {Name} {Vintage} {Type} bottle label"
        Example: "Buffalo Trace Stagg Jr Batch 24D bourbon bottle label"
        """
        parts = []

        if bottle.producer:
            parts.append(bottle.producer)
        if bottle.name:
            parts.append(bottle.name)
        if bottle.vintage:
            parts.append(str(bottle.vintage))

        # Add beverage type for better results
        if bottle.type:
            parts.append(bottle.type)

        # Add "bottle label" to focus search
        parts.append("bottle label")

        query = " ".join(parts)
        logger.debug(f"Search query: {query}")
        return query

    def search_for_labels(
        self,
        bottle: BottleMetadata,
        max_results: int = 5,
    ) -> list[LabelImage]:
        """
        Search for bottle label images using web search + scraping.

        Strategy:
        1. Search web for bottle (distillery site, retailers, review sites)
        2. Fetch those pages and extract image URLs
        3. Filter for likely label images
        4. Return top candidates

        Args:
            bottle: Bottle to search for
            max_results: Maximum number of results to return

        Returns:
            List of LabelImage objects
        """
        query = self.construct_search_query(bottle)

        # This will be called by CLI which can use WebSearch and WebFetch tools
        # For now, construct search URLs that user can visit
        images = self._get_image_search_urls(query)

        logger.info(f"Generated {len(images)} search URLs for {bottle.producer} {bottle.name}")
        return images

    def _get_image_search_urls(self, query: str) -> list[LabelImage]:
        """
        Generate image search URLs for manual lookup.

        Returns LabelImage objects with search URLs that can be opened in browser.
        """
        encoded_query = quote_plus(query)

        search_engines = [
            {
                "url": f"https://www.google.com/search?q={encoded_query}&tbm=isch",
                "title": "Google Images",
                "source": "google",
            },
            {
                "url": f"https://www.bing.com/images/search?q={encoded_query}",
                "title": "Bing Images",
                "source": "bing",
            },
        ]

        images = []
        for engine in search_engines:
            images.append(
                LabelImage(
                    url=engine["url"],
                    title=f"{engine['title']} search for: {query}",
                    source=engine["source"],
                )
            )

        return images

    def download_image(self, image: LabelImage, output_path: Path) -> bool:
        """
        Download image from URL to local file.

        Args:
            image: LabelImage to download
            output_path: Path to save image

        Returns:
            True if successful, False otherwise
        """
        try:
            logger.info(f"Downloading image from {image.url}")

            response = self.client.get(image.url)
            response.raise_for_status()

            # Validate it's an image
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                logger.warning(f"URL does not appear to be an image: {content_type}")
                return False

            # Save to file
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)

            logger.info(f"Saved label image to {output_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to download image: {e}")
            return False

    def get_label_path(self, bottle_folder: Path) -> Path:
        """
        Get the standard path for a bottle's label image.

        Format: {bottle_folder}/labels/label.jpg
        """
        return bottle_folder / "labels" / "label.jpg"

    def has_label(self, bottle_folder: Path) -> bool:
        """Check if bottle already has a label image."""
        label_path = self.get_label_path(bottle_folder)
        return label_path.exists()

    def close(self):
        """Close HTTP client."""
        self.client.close()
