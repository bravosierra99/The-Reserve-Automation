"""Extraction service for processing uploaded images."""

import logging
from pathlib import Path
from typing import Literal, Optional

from reserve_automation.core.config import Config
from reserve_automation.core.tasting_note import TastingExtractionResult
from reserve_automation.extractors.tasting_extractor import TastingExtractor
from reserve_automation.llm.gateway import LLMGateway

logger = logging.getLogger(__name__)


class ExtractionService:
    """Service for extracting data from uploaded images."""

    def __init__(self, core_config: Config):
        """
        Initialize extraction service.

        Args:
            core_config: Core application configuration
        """
        self.config = core_config
        self.llm_gateway = LLMGateway(core_config.llm)
        self.tasting_extractor = TastingExtractor(self.llm_gateway)

    async def extract_tasting_card(
        self,
        image_path: Path,
        template_type: Optional[Literal["aws_wine", "bourbon"]] = None
    ) -> TastingExtractionResult:
        """
        Extract tasting notes from a tasting card image.

        Args:
            image_path: Path to uploaded image
            template_type: Type of tasting card (auto-detected if None)

        Returns:
            TastingExtractionResult with extracted tastings

        Raises:
            Exception: If extraction fails
        """
        logger.info(f"Starting tasting card extraction for {image_path}")

        try:
            # Use existing tasting extractor
            result = await self.tasting_extractor.extract_from_image(
                image_path=image_path,
                template_type=template_type
            )

            logger.info(
                f"Extraction complete: {len(result.tastings)} tastings extracted "
                f"(template: {result.template_type})"
            )

            return result

        except Exception as e:
            logger.error(f"Extraction failed: {e}", exc_info=True)
            raise

    def to_dict(self, result: TastingExtractionResult) -> dict:
        """
        Convert extraction result to dictionary for JSON serialization.

        Args:
            result: Extraction result

        Returns:
            Dictionary representation
        """
        return {
            "template_type": result.template_type,
            "tastings": [
                tasting.model_dump(mode='json') for tasting in result.tastings
            ]
        }

    def from_dict(self, data: dict) -> TastingExtractionResult:
        """
        Reconstruct extraction result from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            TastingExtractionResult
        """
        from reserve_automation.core.tasting_note import TastingNote

        return TastingExtractionResult(
            template_type=data["template_type"],
            tastings=[TastingNote(**t) for t in data["tastings"]]
        )
