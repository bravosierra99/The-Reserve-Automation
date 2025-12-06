"""Complete extraction pipeline from input file to structured bottles."""

import time
from pathlib import Path
from typing import Literal, Optional

from loguru import logger

from .core.models import ExtractionResult
from .extractors import BottleExtractor, ConfidenceAnalyzer
from .llm import LLMGateway
from .parsers import ParserDetector


async def extraction_pipeline(
    input_file: Path,
    config: dict,
    input_type: Literal["pdf", "image", "auto"] = "auto",
    beverage_type: Literal["wine", "whiskey", "auto"] = "auto",
) -> ExtractionResult:
    """
    Complete extraction pipeline: parse → extract → analyze confidence.

    Args:
        input_file: Path to input file (PDF or image)
        config: Application configuration
        input_type: Type of input file ('pdf', 'image', or 'auto')
        beverage_type: Type of beverage ('wine', 'whiskey', or 'auto')

    Returns:
        ExtractionResult with bottles and metadata

    Raises:
        Various exceptions from parsers/extractors
    """
    start_time = time.time()
    errors = []
    warnings = []

    logger.info(f"Starting extraction pipeline for: {input_file.name}")

    # Initialize LLM gateway early (needed for vision-based OCR)
    llm_config = config.get("llm", {})
    llm_gateway = LLMGateway(llm_config)

    # Step 1: Parse input file
    try:
        parser_config = config.get("parsers", {})
        parser_detector = ParserDetector(parser_config, llm_gateway=llm_gateway)

        if input_type == "auto":
            logger.debug("Auto-detecting input type...")
            parser_result = await parser_detector.parse(input_file)
        else:
            # Use specific parser
            if input_type == "pdf":
                from .parsers import PDFParser

                parser = PDFParser(use_ocr_fallback=parser_config.get("pdf", {}).get("use_ocr_fallback", True))
            else:  # image
                from .parsers import ImageParser

                image_config = parser_config.get("image", {})
                parser = ImageParser(
                    preprocess=image_config.get("preprocess", True),
                    language=image_config.get("ocr_language", "eng"),
                    ocr_method=image_config.get("ocr_method", "auto"),
                    llm_gateway=llm_gateway,
                )

            parser_result = await parser.parse(input_file)

        logger.info(f"Parsed {parser_result.source_type}: {len(parser_result.raw_text)} chars")

    except Exception as e:
        logger.error(f"Parsing failed: {e}")
        errors.append(f"Parsing failed: {e}")
        raise

    # Step 2: Extract bottles using LLM
    try:

        # Extract bottles
        extractor = BottleExtractor(llm_gateway)
        bottles = await extractor.extract(parser_result, beverage_type=beverage_type)

        logger.info(f"Extracted {len(bottles)} bottles")

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        errors.append(f"Extraction failed: {e}")
        raise

    # Step 3: Analyze confidence
    try:
        extraction_config = config.get("extraction", {})
        confidence_threshold = extraction_config.get("confidence_threshold", 0.7)

        analyzer = ConfidenceAnalyzer(review_threshold=confidence_threshold)
        high_confidence, needs_review = analyzer.analyze(bottles)

        logger.info(
            f"Confidence analysis: {len(high_confidence)} high, {len(needs_review)} need review"
        )

    except Exception as e:
        logger.error(f"Confidence analysis failed: {e}")
        errors.append(f"Confidence analysis failed: {e}")
        # Don't raise - this is not critical
        high_confidence = bottles
        needs_review = []

    # Calculate processing time
    processing_time = time.time() - start_time

    # Build result
    result = ExtractionResult(
        bottles=bottles,
        source_file=str(input_file),
        source_type=parser_result.source_type,
        total_extracted=len(bottles),
        high_confidence_count=len(high_confidence),
        needs_review_count=len(needs_review),
        high_confidence=high_confidence,
        needs_review=needs_review,
        processing_time_seconds=processing_time,
        errors=errors,
        warnings=warnings,
        # TODO: Track actual token usage from LLM responses
        total_tokens_used=0,
        total_cost=0.0,
    )

    logger.info(
        f"Pipeline complete: {len(bottles)} bottles in {processing_time:.2f}s"
    )

    return result
