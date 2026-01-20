#!/usr/bin/env python3
"""
Interactive Prompt Tuning Tool

This script helps you iterate on prompts for parsing LLMWhisperer table output.

Usage:
    # Extract table and save it
    python tests/test_prompt_tuning.py extract --fixture aws_wine_test_001

    # Test a prompt with saved table
    python tests/test_prompt_tuning.py test --table-file /tmp/table.txt --prompt "Your prompt here"

    # Or use interactive mode
    python tests/test_prompt_tuning.py interactive --fixture aws_wine_test_001
"""

import pytest
pytest.skip("This is an interactive prompt tuning script, not a test suite", allow_module_level=True)

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reserve_automation.core.config import Config
from reserve_automation.llm.gateway import LLMGateway
from reserve_automation.utils.llm_whisperer import extract_layout_text
from reserve_automation.core.tasting_note import TastingNote


def extract_table(fixture_name: str, output_file: Path = None):
    """Extract table from image using LLMWhisperer and save it."""
    config = Config.load()

    # Get paths
    fixtures_dir = Path(__file__).parent / "fixtures" / "extraction"
    json_path = fixtures_dir / f"{fixture_name}.json"

    if not json_path.exists():
        print(f"Error: Ground truth not found: {json_path}")
        return None

    with open(json_path, 'r') as f:
        ground_truth = json.load(f)

    image_file = ground_truth.get('image_file', f"{fixture_name}.jpg")
    image_path = fixtures_dir / image_file

    if not image_path.exists():
        print(f"Error: Image not found: {image_path}")
        return None

    print(f"Extracting table from {image_path}...")
    layout_text = extract_layout_text(image_path, config.extraction)

    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(layout_text)
        print(f"Table saved to: {output_file}")

    print("\n" + "="*80)
    print("EXTRACTED TABLE:")
    print("="*80)
    print(layout_text)
    print("="*80)

    return layout_text, ground_truth


async def test_prompt(table_text: str, prompt_template: str, ground_truth: dict = None):
    """Test a prompt with the table text."""
    config = Config.load()
    llm_gateway = LLMGateway(config.llm)

    # Format prompt
    prompt = prompt_template.format(layout_text=table_text)

    print("\n" + "="*80)
    print("TESTING PROMPT:")
    print("="*80)
    print(prompt[:500] + "..." if len(prompt) > 500 else prompt)
    print("="*80)

    # Call LLM
    print("\nCalling LLM...")
    try:
        llm_response = await llm_gateway.complete(
            task_type="structured_extraction",
            prompt=prompt
        )

        # Parse the JSON response into TastingNote
        print("\n" + "="*80)
        print("RAW LLM RESPONSE:")
        print("="*80)
        print(llm_response.content)
        print("="*80)

        # Extract JSON from response content
        import json as json_lib
        try:
            # Try to parse the entire response as JSON
            result_dict = json_lib.loads(llm_response.content)
        except json_lib.JSONDecodeError as e:
            # If that fails, try to extract JSON from markdown code blocks
            content = llm_response.content
            json_str = None

            if "```json" in content:
                json_str = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                json_str = content.split("```")[1].split("```")[0].strip()
            else:
                # Try to find JSON object in the content
                import re
                json_match = re.search(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', content, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    print(f"\n❌ ERROR: Could not find valid JSON in response")
                    print(f"JSON parse error: {e}")
                    print("\nResponse does not contain JSON. The LLM returned prose instead of JSON.")
                    print("Try adjusting your prompt to explicitly request JSON output only.")
                    return None

            if json_str:
                try:
                    result_dict = json_lib.loads(json_str)
                except json_lib.JSONDecodeError as e2:
                    print(f"\n❌ ERROR: Extracted text is not valid JSON")
                    print(f"Extracted text:\n{json_str}")
                    print(f"\nJSON parse error: {e2}")
                    return None
            else:
                print(f"\n❌ ERROR: Could not extract JSON from response")
                return None

        # Check if this is a multi-wine response or single wine
        if "tastings" in result_dict:
            # Multi-wine format
            taster_name = result_dict.get("taster_name")
            tasting_date = result_dict.get("tasting_date")
            place = result_dict.get("place")
            theme = result_dict.get("theme")
            tastings_data = result_dict.get("tastings", [])

            print("\n" + "="*80)
            print("EXTRACTED DATA:")
            print("="*80)
            print(f"Taster: {taster_name}")
            print(f"Date: {tasting_date}")
            print(f"Place: {place}")
            print(f"Theme: {theme}")
            print(f"\nNumber of wines: {len(tastings_data)}")

            # Create TastingNote objects for each wine
            results = []
            for i, tasting_data in enumerate(tastings_data, 1):
                # Merge shared metadata with individual tasting
                merged_data = {
                    "taster_name": taster_name,
                    "tasting_date": tasting_date,
                    "place": place,
                    "theme": theme,
                    **tasting_data
                }
                result = TastingNote(**merged_data)
                results.append(result)

                print(f"\n--- Wine {i}: {result.bottle_name} ---")
                print(f"Scores: App={result.wine_appearance}, Aroma={result.wine_aroma}, " +
                      f"Taste={result.wine_taste}, After={result.wine_aftertaste}, Overall={result.wine_overall}")
                print(f"Notes: Nose={result.nose_notes}")
        else:
            # Single wine format (backward compatibility)
            result = TastingNote(**result_dict)
            results = [result]

            print("\n" + "="*80)
            print("EXTRACTED DATA:")
            print("="*80)
            print(f"Wine: {result.bottle_name}")
            print(f"Taster: {result.taster_name}")
            print(f"Date: {result.tasting_date}")
            print(f"Place: {result.place}")
            print(f"\nScores:")
            print(f"  Appearance: {result.wine_appearance}")
            print(f"  Aroma: {result.wine_aroma}")
            print(f"  Taste: {result.wine_taste}")
            print(f"  Aftertaste: {result.wine_aftertaste}")
            print(f"  Overall: {result.wine_overall}")
            print(f"\nTasting Notes:")
            print(f"  Nose: {result.nose_notes}")
            print(f"  Palate: {result.palate_notes}")
            print(f"  Finish: {result.finish_notes}")
            print(f"  Overall: {result.overall_notes}")

        print("="*80)

        # If we have ground truth, show detailed comparison
        if ground_truth:
            print("\n" + "="*80)
            print("COMPARISON WITH EXPECTED:")
            print("="*80)

            expected = ground_truth['expected_output']

            # Compare metadata
            print("\nMetadata:")
            compare_and_print("taster_name", expected.get('taster_name'), results[0].taster_name if results else None)
            compare_and_print("tasting_date", expected.get('tasting_date'), str(results[0].tasting_date) if results else None)
            compare_and_print("place", expected.get('place'), results[0].place if results else None)

            # Compare all tastings
            expected_tastings = expected.get('tastings', [])
            print(f"\nExpected {len(expected_tastings)} wines, extracted {len(results)} wines")

            for i, exp_tasting in enumerate(expected_tastings):
                print(f"\n--- Wine {i+1} ---")
                if i < len(results):
                    result = results[i]
                    compare_and_print("bottle_name", exp_tasting.get('bottle_name'), result.bottle_name)

                    print("Scores:")
                    compare_and_print("  appearance", exp_tasting.get('wine_appearance'), result.wine_appearance)
                    compare_and_print("  aroma", exp_tasting.get('wine_aroma'), result.wine_aroma)
                    compare_and_print("  taste", exp_tasting.get('wine_taste'), result.wine_taste)
                    compare_and_print("  aftertaste", exp_tasting.get('wine_aftertaste'), result.wine_aftertaste)
                    compare_and_print("  overall", exp_tasting.get('wine_overall'), result.wine_overall)

                    print("Tasting Notes:")
                    compare_and_print("  nose", exp_tasting.get('nose_notes'), result.nose_notes)
                    compare_and_print("  palate", exp_tasting.get('palate_notes'), result.palate_notes)
                    compare_and_print("  finish", exp_tasting.get('finish_notes'), result.finish_notes)
                    compare_and_print("  overall", exp_tasting.get('overall_notes'), result.overall_notes)
                else:
                    print(f"✗ Wine {i+1} was NOT extracted (expected: {exp_tasting.get('bottle_name')})")

            # Calculate overall accuracy across all wines
            print("\n" + "="*80)
            total_matches = 0
            total_fields = 0

            for i, exp_tasting in enumerate(expected_tastings):
                if i < len(results):
                    result = results[i]
                    # Count matches for this wine
                    fields_to_check = ['bottle_name', 'wine_appearance', 'wine_aroma', 'wine_taste',
                                     'wine_aftertaste', 'wine_overall', 'nose_notes', 'palate_notes',
                                     'finish_notes', 'overall_notes']
                    for field in fields_to_check:
                        total_fields += 1
                        exp_val = exp_tasting.get(field)
                        act_val = getattr(result, field, None)
                        if compare_values(exp_val, act_val):
                            total_matches += 1

            # Add metadata fields
            total_fields += 3
            if results:
                if str(expected.get('taster_name')).lower().strip() == str(results[0].taster_name).lower().strip():
                    total_matches += 1
                if str(expected.get('tasting_date')) == str(results[0].tasting_date):
                    total_matches += 1
                if str(expected.get('place', '')).lower().strip() == str(results[0].place or '').lower().strip():
                    total_matches += 1

            accuracy = (total_matches / total_fields * 100) if total_fields > 0 else 0
            print(f"OVERALL ACCURACY: {accuracy:.1f}% ({total_matches}/{total_fields} fields correct)")
            print("="*80)

        return results if len(results) > 1 else (results[0] if results else None)

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        return None


def compare_values(expected, actual) -> bool:
    """Compare two values and return True if they match."""
    if expected is None and actual is None:
        return True
    if expected is None or actual is None:
        return False
    if isinstance(expected, list):
        expected_norm = sorted([str(x).lower().strip() for x in expected])
        actual_norm = sorted([str(x).lower().strip() for x in (actual or [])])
        return expected_norm == actual_norm
    if isinstance(expected, (int, float)):
        return abs(float(expected) - float(actual or 0)) < 0.1
    return str(expected).lower().strip() == str(actual).lower().strip()


def compare_and_print(field_name: str, expected, actual):
    """Helper to compare and print field values."""
    match = compare_values(expected, actual)
    status = "✓" if match else "✗"
    print(f"  {status} {field_name}: {expected} → {actual}")


def calculate_accuracy(result, ground_truth):
    """Quick accuracy calculation."""
    expected = ground_truth['expected_output']
    matches = 0
    total = 0

    # Check metadata
    for field in ['taster_name', 'tasting_date', 'place']:
        total += 1
        expected_val = expected.get(field)
        actual_val = getattr(result, field, None)
        if str(expected_val).lower().strip() == str(actual_val).lower().strip():
            matches += 1

    # Check first tasting if exists
    if expected.get('tastings') and len(expected['tastings']) > 0:
        exp_tasting = expected['tastings'][0]
        for field in ['bottle_name', 'wine_appearance', 'wine_aroma', 'wine_taste',
                     'wine_aftertaste', 'wine_overall']:
            total += 1
            expected_val = exp_tasting.get(field)
            actual_val = getattr(result, field, None)
            if expected_val is not None and actual_val is not None:
                if abs(float(expected_val) - float(actual_val)) < 0.1 if isinstance(expected_val, (int, float)) else str(expected_val).lower().strip() == str(actual_val).lower().strip():
                    matches += 1

    return (matches / total * 100) if total > 0 else 0


async def interactive_mode(fixture_name: str):
    """Interactive mode for testing prompts."""
    # Extract table
    result = extract_table(fixture_name)
    if not result:
        return

    table_text, ground_truth = result

    print("\n" + "="*80)
    print("INTERACTIVE PROMPT TESTING MODE")
    print("="*80)
    print("\nEnter your prompt template (use {layout_text} as placeholder)")
    print("Type 'quit' to exit, 'table' to see the table again")
    print("="*80)

    while True:
        print("\nPrompt> ", end="")
        user_input = input()

        if user_input.lower() == 'quit':
            break
        elif user_input.lower() == 'table':
            print("\n" + table_text)
            continue

        if '{layout_text}' not in user_input:
            print("Error: Prompt must contain {layout_text} placeholder")
            continue

        await test_prompt(table_text, user_input, ground_truth)


async def main():
    parser = argparse.ArgumentParser(description='Prompt tuning tool')
    subparsers = parser.add_subparsers(dest='command', help='Command to run')

    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract table from image')
    extract_parser.add_argument('--fixture', required=True, help='Fixture name')
    extract_parser.add_argument('--output', type=Path, default=Path('/tmp/llmwhisperer_table.txt'),
                              help='Output file for table')

    # Test command
    test_parser = subparsers.add_parser('test', help='Test a prompt with saved table')
    test_parser.add_argument('--table-file', type=Path, required=True, help='Path to saved table')
    test_parser.add_argument('--prompt-file', type=Path, help='File containing prompt template')
    test_parser.add_argument('--prompt', help='Prompt template string')
    test_parser.add_argument('--fixture', help='Optional fixture name for ground truth comparison')

    # Interactive command
    interactive_parser = subparsers.add_parser('interactive', help='Interactive mode')
    interactive_parser.add_argument('--fixture', required=True, help='Fixture name')

    args = parser.parse_args()

    if args.command == 'extract':
        extract_table(args.fixture, args.output)

    elif args.command == 'test':
        table_text = args.table_file.read_text()

        if args.prompt_file:
            prompt = args.prompt_file.read_text()
        elif args.prompt:
            prompt = args.prompt
        else:
            print("Error: Must provide either --prompt-file or --prompt")
            return

        # Load ground truth if fixture is provided
        ground_truth = None
        if args.fixture:
            fixtures_dir = Path(__file__).parent / "fixtures" / "extraction"
            json_path = fixtures_dir / f"{args.fixture}.json"
            if json_path.exists():
                with open(json_path, 'r') as f:
                    ground_truth = json.load(f)
            else:
                print(f"Warning: Fixture {args.fixture} not found at {json_path}")

        await test_prompt(table_text, prompt, ground_truth)

    elif args.command == 'interactive':
        await interactive_mode(args.fixture)

    else:
        parser.print_help()


if __name__ == '__main__':
    asyncio.run(main())
