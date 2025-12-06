"""Confidence analysis for extraction results."""

from typing import List, Tuple

from loguru import logger

from ..core.models import BottleMetadata


class ConfidenceAnalyzer:
    """
    Analyze extraction confidence and categorize bottles.

    Splits bottles into high-confidence (ready to use) and
    needs-review (low confidence, requires human validation).
    """

    # Default threshold for review
    DEFAULT_REVIEW_THRESHOLD = 0.7

    def __init__(self, review_threshold: float = DEFAULT_REVIEW_THRESHOLD):
        """
        Initialize confidence analyzer.

        Args:
            review_threshold: Confidence threshold (0-1).
                              Bottles below this need review.
        """
        if not 0 <= review_threshold <= 1:
            raise ValueError("Review threshold must be between 0 and 1")

        self.review_threshold = review_threshold
        logger.debug(f"Confidence analyzer initialized (threshold: {review_threshold})")

    def analyze(
        self, bottles: List[BottleMetadata]
    ) -> Tuple[List[BottleMetadata], List[BottleMetadata]]:
        """
        Split bottles into high-confidence and needs-review categories.

        Args:
            bottles: List of bottles to analyze

        Returns:
            Tuple of (high_confidence, needs_review) lists
        """
        high_confidence = []
        needs_review = []

        for bottle in bottles:
            if bottle.confidence >= self.review_threshold:
                high_confidence.append(bottle)
            else:
                needs_review.append(bottle)

        logger.info(
            f"Analyzed {len(bottles)} bottles: "
            f"{len(high_confidence)} high-confidence, "
            f"{len(needs_review)} need review"
        )

        return high_confidence, needs_review

    def get_statistics(self, bottles: List[BottleMetadata]) -> dict:
        """
        Get statistical summary of confidence scores.

        Args:
            bottles: List of bottles to analyze

        Returns:
            Dictionary with statistics
        """
        if not bottles:
            return {
                "count": 0,
                "mean": 0.0,
                "min": 0.0,
                "max": 0.0,
                "high_confidence_count": 0,
                "needs_review_count": 0,
            }

        confidences = [b.confidence for b in bottles]

        high_conf, needs_rev = self.analyze(bottles)

        return {
            "count": len(bottles),
            "mean": sum(confidences) / len(confidences),
            "min": min(confidences),
            "max": max(confidences),
            "high_confidence_count": len(high_conf),
            "needs_review_count": len(needs_rev),
            "threshold": self.review_threshold,
        }

    def get_low_confidence_reasons(self, bottle: BottleMetadata) -> List[str]:
        """
        Identify reasons why a bottle has low confidence.

        Args:
            bottle: Bottle to analyze

        Returns:
            List of reason strings
        """
        reasons = []

        if not bottle.producer or not bottle.name:
            reasons.append("Missing producer or name")

        if not bottle.year:
            reasons.append("Missing year/vintage")
        elif bottle.year < 1800 or bottle.year > 2030:
            reasons.append(f"Invalid year: {bottle.year}")

        if not bottle.beverage_type and not bottle.variety:
            reasons.append("Missing beverage type or variety")

        if not bottle.region and not bottle.country:
            reasons.append("Missing region and country")

        if bottle.price is None:
            reasons.append("Missing price information")

        return reasons
