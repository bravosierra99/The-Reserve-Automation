"""Label finding and processing service for web application."""

from pathlib import Path
from typing import Dict, List, Optional

import httpx
from loguru import logger

from reserve_automation.core.models import BottleMetadata
from reserve_automation.llm.gateway import LLMGateway
from reserve_automation.utils.llm_label_finder import LLMLabelFinder
from reserve_automation.utils.label_processor import LabelImageProcessor


class LabelService:
    """Service for finding and processing bottle label images."""

    def __init__(self, llm_gateway: LLMGateway):
        """
        Initialize label service.

        Args:
            llm_gateway: LLM gateway instance
        """
        self.llm_gateway = llm_gateway
        self.label_finder = LLMLabelFinder(llm_gateway)
        self.label_processor = LabelImageProcessor(llm_gateway)
        self.http_client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)

    async def find_labels(self, bottle: BottleMetadata) -> List[Dict]:
        """
        Find label images for a bottle using LLM web search.

        Args:
            bottle: Bottle to find labels for

        Returns:
            List of label candidates with URLs and metadata
        """
        logger.info(f"Finding labels for: {bottle.producer} - {bottle.name}")

        try:
            # Use LLM to find label images via web search
            images = await self.label_finder.find_label_images(bottle)

            logger.info(f"Found {len(images)} label candidates")

            return images

        except Exception as e:
            logger.error(f"Label finding failed: {e}", exc_info=True)
            return []

    async def download_and_crop_label(
        self,
        image_url: str,
        output_path: Path,
        crop: bool = True
    ) -> Optional[Path]:
        """
        Download an image and optionally crop it to just the label.

        Args:
            image_url: URL of the image to download
            output_path: Path to save the image
            crop: Whether to crop the image to just the label

        Returns:
            Path to saved image, or None if download failed
        """
        logger.info(f"Downloading label from: {image_url}")

        try:
            # Download image
            response = await self.http_client.get(image_url)
            response.raise_for_status()

            # Validate it's an image
            content_type = response.headers.get("content-type", "")
            if not content_type.startswith("image/"):
                logger.warning(f"URL does not appear to be an image: {content_type}")
                return None

            # Save original
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(response.content)

            logger.info(f"Saved label image to {output_path}")

            # Optionally crop to just the label
            if crop:
                try:
                    cropped = await self.label_processor.crop_to_label(output_path)
                    if cropped:
                        logger.info("Successfully cropped label")
                    else:
                        logger.info("Could not detect label boundaries, using original")
                except Exception as e:
                    logger.warning(f"Label cropping failed, using original: {e}")

            return output_path

        except Exception as e:
            logger.error(f"Failed to download label: {e}")
            return None

    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()
