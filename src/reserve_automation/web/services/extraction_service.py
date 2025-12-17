"""Extraction service for processing uploaded images."""

from pathlib import Path
from typing import Dict, List, Literal, Optional, Tuple

from loguru import logger

from reserve_automation.core.config import Config
from reserve_automation.core.models import BottleMetadata, ParserResult
from reserve_automation.core.tasting_note import TastingExtractionResult
from reserve_automation.enrichment.metadata_enricher import MetadataEnricher
from reserve_automation.extractors.bottle import BottleExtractor
from reserve_automation.extractors.image_extractor import ImageMetadataExtractor
from reserve_automation.extractors.tasting_extractor import TastingExtractor
from reserve_automation.llm.gateway import LLMGateway
from reserve_automation.parsers.image import ImageParser
from reserve_automation.parsers.pdf import PDFParser


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
        logger.info(f"ExtractionService initialized - LLM Gateway is: {type(self.llm_gateway)} - {self.llm_gateway is not None}")
        self.tasting_extractor = TastingExtractor(self.llm_gateway)
        self.image_extractor = ImageMetadataExtractor(self.llm_gateway)
        self.bottle_extractor = BottleExtractor(self.llm_gateway)
        self.enricher = MetadataEnricher(self.llm_gateway)

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

    async def extract_bottle_from_image(
        self,
        image_path: Path,
        beverage_type: Literal["wine", "whiskey", "auto"] = "auto"
    ) -> Tuple[BottleMetadata, Dict]:
        """
        Extract bottle metadata from a label image.

        Args:
            image_path: Path to uploaded image
            beverage_type: Type of beverage (auto-detected if "auto")

        Returns:
            Tuple of (BottleMetadata, extraction_metadata dict)

        Raises:
            Exception: If extraction fails
        """
        logger.info(f"Starting bottle extraction from image: {image_path}")

        try:
            # Use image extractor for direct label extraction
            bottle, extraction_meta = await self.image_extractor.extract_from_image(
                image_path=image_path,
                beverage_type=beverage_type
            )

            logger.info(
                f"Extraction complete: {bottle.producer} - {bottle.name} "
                f"(confidence: {extraction_meta.get('confidence', 'unknown')})"
            )

            return bottle, extraction_meta

        except Exception as e:
            logger.error(f"Bottle extraction failed: {e}", exc_info=True)
            raise

    async def extract_bottles_from_manifest(
        self,
        file_path: Path,
        beverage_type: Literal["wine", "whiskey", "auto"] = "auto",
        expected_count: Optional[int] = None
    ) -> List[BottleMetadata]:
        """
        Extract multiple bottles from a manifest (PDF or image).

        Args:
            file_path: Path to uploaded manifest file
            beverage_type: Type of beverage (auto-detected if "auto")
            expected_count: Expected number of bottles (helps improve extraction accuracy)

        Returns:
            List of BottleMetadata objects

        Raises:
            Exception: If extraction fails
        """
        logger.info(f"Starting manifest extraction from: {file_path} (expected_count: {expected_count})")

        try:
            # Choose parser based on file extension
            suffix = file_path.suffix.lower()
            if suffix == '.pdf':
                parser = PDFParser()
            else:
                parser = ImageParser(llm_gateway=self.llm_gateway)

            # Parse the document
            parser_result = await parser.parse(file_path)

            if not parser_result.raw_text.strip():
                logger.warning("No text extracted from manifest")
                return []

            # Extract bottles using bottle extractor
            bottles = await self.bottle_extractor.extract(
                parser_result=parser_result,
                beverage_type=beverage_type,
                expected_count=expected_count
            )

            logger.info(f"Manifest extraction complete: {len(bottles)} bottles found")

            return bottles

        except Exception as e:
            logger.error(f"Manifest extraction failed: {e}", exc_info=True)
            raise

    async def enrich_bottle(
        self,
        bottle: BottleMetadata
    ) -> Tuple[BottleMetadata, Dict]:
        """
        Enrich bottle metadata using web search.

        Args:
            bottle: Bottle metadata to enrich

        Returns:
            Tuple of (enriched BottleMetadata, enrichment_metadata dict)

        Raises:
            Exception: If enrichment fails
        """
        logger.info(f"Enriching bottle: {bottle.producer} - {bottle.name}")

        try:
            enriched_bottle, enrich_meta = await self.enricher.verify_bottle(bottle)

            changes = enrich_meta.get("changes", {})
            logger.info(
                f"Enrichment complete: {len(changes)} fields updated "
                f"(verified: {enrich_meta.get('verified', False)})"
            )

            return enriched_bottle, enrich_meta

        except Exception as e:
            logger.error(f"Bottle enrichment failed: {e}", exc_info=True)
            raise

    def bottle_to_dict(self, bottle: BottleMetadata) -> dict:
        """
        Convert bottle metadata to dictionary for JSON serialization.

        Args:
            bottle: Bottle metadata

        Returns:
            Dictionary representation
        """
        return bottle.model_dump(mode='json')

    def bottle_from_dict(self, data: dict) -> BottleMetadata:
        """
        Reconstruct bottle metadata from dictionary.

        Args:
            data: Dictionary representation

        Returns:
            BottleMetadata
        """
        return BottleMetadata(**data)
