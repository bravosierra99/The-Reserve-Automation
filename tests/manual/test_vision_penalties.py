#!/usr/bin/env python3
"""Test if penalties are causing vision model issues.

Usage:
    # Test WITH penalties (current code)
    uv run python tests/manual/test_vision_penalties.py

    # Test WITHOUT penalties (after commenting them out)
    uv run python tests/manual/test_vision_penalties.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from reserve_automation.extractors.image_extractor import ImageMetadataExtractor
from reserve_automation.llm.gateway import LLMGateway


async def main():
    # Find a test bottle image
    test_images = list(Path("tests/fixtures/images").glob("*.jpg"))
    if not test_images:
        test_images = list(Path("tests/fixtures/images").glob("*.png"))

    if not test_images:
        print("ERROR: No test images found in tests/fixtures/images/")
        print("Please add a bottle image there to test")
        return

    test_image = test_images[0]
    print(f"Testing with image: {test_image}")
    print("=" * 80)

    # Configure gateway to use local vision model
    config = {
        "providers": {
            "lm_studio_vision": {
                "provider": "lm_studio",
                "base_url": "http://localhost:1234/v1",
                "model": "qwen/qwen3-vl-8b",  # or whatever is loaded
                "timeout": 180,
                "max_retries": 1,
            }
        },
        "routing": {
            "ocr": "lm_studio_vision",
        },
        "fallback": {"enabled": False},
    }

    gateway = LLMGateway(config)
    extractor = ImageMetadataExtractor(gateway)

    try:
        bottle, metadata = await extractor.extract_from_image(test_image)

        print("\n" + "=" * 80)
        print("RESULT:")
        print("=" * 80)
        if bottle:
            print("✓ SUCCESS")
            print(f"  Producer: {bottle.producer}")
            print(f"  Name: {bottle.name}")
            print(f"  Year: {bottle.year or 'N/A'}")
            print(f"  Type: {bottle.beverage_type}")
            print(f"  Tokens: {metadata.get('tokens_used', 'N/A')}")
        else:
            print(f"✗ FAILED: {metadata.get('error', 'Unknown error')}")
        print("=" * 80)

    except Exception as e:
        print(f"\n✗ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
