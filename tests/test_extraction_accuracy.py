#!/usr/bin/env python3
"""
Extraction Accuracy Test Suite

This module provides a framework for testing and validating tasting card extraction
against known ground truth data. Use this to:

1. Test new LLM models for extraction accuracy
2. Validate prompt changes don't regress quality
3. Test new tasting form templates
4. Generate accuracy metrics and reports

Usage:
    # Run all tests
    pytest tests/test_extraction_accuracy.py -v

    # Run with detailed report
    python tests/test_extraction_accuracy.py --report

    # Test specific fixture
    python tests/test_extraction_accuracy.py --fixture aws_wine_test_001
"""

import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reserve_automation.core.config import Config
from reserve_automation.extractors.tasting_extractor import TastingExtractor
from reserve_automation.llm.gateway import LLMGateway


@dataclass
class FieldComparison:
    """Comparison result for a single field."""
    field_name: str
    expected: Any
    actual: Any
    match: bool
    error: str = None


@dataclass
class TastingComparison:
    """Comparison result for a single tasting."""
    row: int
    fields: List[FieldComparison] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        """Calculate accuracy percentage for this tasting."""
        if not self.fields:
            return 0.0
        matches = sum(1 for f in self.fields if f.match)
        return (matches / len(self.fields)) * 100


@dataclass
class ExtractionTestResult:
    """Complete test result for one ground truth file."""
    test_name: str
    fixture_file: str
    template_type: str
    tastings: List[TastingComparison] = field(default_factory=list)
    metadata_fields: List[FieldComparison] = field(default_factory=list)

    @property
    def overall_accuracy(self) -> float:
        """Calculate overall accuracy across all fields."""
        all_fields = self.metadata_fields + [
            f for t in self.tastings for f in t.fields
        ]
        if not all_fields:
            return 0.0
        matches = sum(1 for f in all_fields if f.match)
        return (matches / len(all_fields)) * 100

    @property
    def tasting_notes_accuracy(self) -> float:
        """Calculate accuracy for tasting notes fields only."""
        note_fields = [
            f for t in self.tastings for f in t.fields
            if 'notes' in f.field_name
        ]
        if not note_fields:
            return 0.0
        matches = sum(1 for f in note_fields if f.match)
        return (matches / len(note_fields)) * 100


class ExtractionTester:
    """Test framework for extraction accuracy."""

    def __init__(self, fixtures_dir: Path = None):
        self.fixtures_dir = fixtures_dir or Path(__file__).parent / "fixtures" / "extraction"

        # Load application config
        config = Config.load()

        # Initialize LLM gateway with the llm config dict
        self.llm_gateway = LLMGateway(config.llm)
        self.extractor = TastingExtractor(self.llm_gateway, config.extraction)

    def load_ground_truth(self, fixture_name: str) -> Dict[str, Any]:
        """Load ground truth JSON file."""
        json_path = self.fixtures_dir / f"{fixture_name}.json"
        if not json_path.exists():
            raise FileNotFoundError(f"Ground truth not found: {json_path}")

        with open(json_path, 'r') as f:
            return json.load(f)

    def get_image_path(self, fixture_name: str, ground_truth: Dict) -> Path:
        """Get path to test image."""
        image_file = ground_truth.get('image_file', f"{fixture_name}.jpg")
        return self.fixtures_dir / image_file

    async def extract_from_fixture(self, fixture_name: str) -> Any:
        """Run extraction on a test fixture."""
        ground_truth = self.load_ground_truth(fixture_name)
        image_path = self.get_image_path(fixture_name, ground_truth)

        if not image_path.exists():
            raise FileNotFoundError(f"Test image not found: {image_path}")

        # Run extraction
        result = await self.extractor.extract_from_image(
            image_path,
            template_type=ground_truth.get('template_type', 'aws_wine')
        )

        return result

    def compare_lists(self, expected: List, actual: List) -> bool:
        """Compare two lists with fuzzy matching for strings."""
        if expected is None and actual is None:
            return True
        if expected is None or actual is None:
            return False

        # Normalize both lists
        expected_norm = sorted([str(x).lower().strip() for x in expected])
        actual_norm = sorted([str(x).lower().strip() for x in actual])

        return expected_norm == actual_norm

    def compare_field(self, field_name: str, expected: Any, actual: Any) -> FieldComparison:
        """Compare a single field value."""
        # Handle None/null
        if expected is None and actual is None:
            return FieldComparison(field_name, expected, actual, True)

        if expected is None or actual is None:
            return FieldComparison(
                field_name, expected, actual, False,
                f"One value is None: expected={expected}, actual={actual}"
            )

        # Handle lists (tasting notes)
        if isinstance(expected, list):
            match = self.compare_lists(expected, actual)
            return FieldComparison(field_name, expected, actual, match)

        # Handle numbers (scores)
        if isinstance(expected, (int, float)):
            match = abs(float(expected) - float(actual)) < 0.01
            return FieldComparison(field_name, expected, actual, match)

        # Handle strings
        expected_str = str(expected).lower().strip()
        actual_str = str(actual).lower().strip()
        match = expected_str == actual_str

        return FieldComparison(field_name, expected, actual, match)

    def compare_tasting(self, expected: Dict, actual: Any) -> TastingComparison:
        """Compare a single tasting."""
        comparison = TastingComparison(row=expected.get('row', 0))

        fields_to_check = [
            'bottle_name', 'price', 'wine_appearance', 'wine_aroma',
            'wine_taste', 'wine_aftertaste', 'wine_overall', 'total_score',
            'nose_notes', 'palate_notes', 'finish_notes', 'overall_notes'
        ]

        for field in fields_to_check:
            expected_val = expected.get(field)
            actual_val = getattr(actual, field, None) if hasattr(actual, field) else getattr(actual.tasting_data if hasattr(actual, 'tasting_data') else actual, field, None)

            field_comp = self.compare_field(field, expected_val, actual_val)
            comparison.fields.append(field_comp)

        return comparison

    async def test_fixture(self, fixture_name: str) -> ExtractionTestResult:
        """Test extraction against a ground truth fixture."""
        print(f"\nTesting fixture: {fixture_name}")

        # Load ground truth
        ground_truth = self.load_ground_truth(fixture_name)
        expected = ground_truth['expected_output']

        # Run extraction
        result = await self.extract_from_fixture(fixture_name)

        # Create test result
        test_result = ExtractionTestResult(
            test_name=ground_truth.get('test_name', fixture_name),
            fixture_file=ground_truth.get('image_file', f"{fixture_name}.jpg"),
            template_type=ground_truth.get('template_type', 'aws_wine')
        )

        # Compare metadata fields
        metadata_fields = ['taster_name', 'tasting_date', 'place', 'theme']
        for field in metadata_fields:
            expected_val = expected.get(field)
            actual_val = getattr(result.tastings[0] if result.tastings else None, field, None)
            field_comp = self.compare_field(field, expected_val, actual_val)
            test_result.metadata_fields.append(field_comp)

        # Compare tastings
        expected_tastings = expected.get('tastings', [])
        actual_tastings = result.tastings

        for i, expected_tasting in enumerate(expected_tastings):
            if i < len(actual_tastings):
                tasting_comp = self.compare_tasting(expected_tasting, actual_tastings[i])
                test_result.tastings.append(tasting_comp)
            else:
                # Missing tasting
                comp = TastingComparison(row=expected_tasting.get('row', i+1))
                comp.fields.append(FieldComparison(
                    'missing_tasting', expected_tasting, None, False,
                    f"Tasting {i+1} not extracted"
                ))
                test_result.tastings.append(comp)

        return test_result

    def print_report(self, result: ExtractionTestResult):
        """Print detailed test report."""
        print("\n" + "="*80)
        print(f"EXTRACTION TEST REPORT: {result.test_name}")
        print("="*80)
        print(f"Fixture: {result.fixture_file}")
        print(f"Template: {result.template_type}")
        print(f"\nOVERALL ACCURACY: {result.overall_accuracy:.1f}%")
        print(f"Tasting Notes Accuracy: {result.tasting_notes_accuracy:.1f}%")

        # Metadata
        print("\n" + "-"*80)
        print("METADATA FIELDS")
        print("-"*80)
        for field in result.metadata_fields:
            status = "✓" if field.match else "✗"
            print(f"{status} {field.field_name}: {field.expected} → {field.actual}")

        # Tastings
        for i, tasting in enumerate(result.tastings, 1):
            print("\n" + "-"*80)
            print(f"TASTING {tasting.row} (Accuracy: {tasting.accuracy:.1f}%)")
            print("-"*80)

            # Group by category
            basic_fields = [f for f in tasting.fields if 'notes' not in f.field_name]
            note_fields = [f for f in tasting.fields if 'notes' in f.field_name]

            print("\nBasic Fields:")
            for field in basic_fields:
                status = "✓" if field.match else "✗"
                print(f"  {status} {field.field_name}: {field.expected} → {field.actual}")

            print("\nTasting Notes:")
            for field in note_fields:
                status = "✓" if field.match else "✗"
                print(f"  {status} {field.field_name}:")
                print(f"      Expected: {field.expected}")
                print(f"      Actual:   {field.actual}")

        print("\n" + "="*80)


async def main():
    """Run extraction tests."""
    import argparse

    parser = argparse.ArgumentParser(description='Test extraction accuracy')
    parser.add_argument('--fixture', help='Test specific fixture (e.g., aws_wine_test_001)')
    parser.add_argument('--report', action='store_true', help='Show detailed report')
    args = parser.parse_args()

    tester = ExtractionTester()

    # Get list of fixtures
    if args.fixture:
        fixtures = [args.fixture]
    else:
        fixtures = [
            f.stem for f in tester.fixtures_dir.glob("*.json")
        ]

    results = []
    for fixture in fixtures:
        result = await tester.test_fixture(fixture)
        results.append(result)

        if args.report:
            tester.print_report(result)
        else:
            print(f"{fixture}: {result.overall_accuracy:.1f}% accuracy")

    # Summary
    if len(results) > 1:
        avg_accuracy = sum(r.overall_accuracy for r in results) / len(results)
        print(f"\nAverage accuracy across {len(results)} tests: {avg_accuracy:.1f}%")


if __name__ == '__main__':
    asyncio.run(main())
