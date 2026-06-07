"""
LLMWhisperer API client for layout-preserving text extraction.

LLMWhisperer specializes in extracting text from documents while preserving
spatial layout, which is perfect for table extraction where column position matters.
"""

import os
from pathlib import Path

from unstract.llmwhisperer import LLMWhispererClientV2


def extract_layout_text(image_path: Path, config: dict) -> str:
    """
    Convenience function to extract layout-preserving text.

    Args:
        image_path: Path to image
        config: Config dict with llm_whisperer settings

    Returns:
        ASCII-formatted text with layout preserved
    """
    whisperer_config = config.get("llm_whisperer", {})

    # Get API key from config or environment
    api_key = whisperer_config.get("api_key") or os.getenv("LLMWHISPERER_API_KEY")
    if not api_key:
        raise ValueError("LLMWhisperer API key is required")

    # Initialize official client
    client = LLMWhispererClientV2(
        base_url=whisperer_config.get("base_url", "https://llmwhisperer-api.us-central.unstract.com/api/v2"),
        api_key=api_key,
    )

    # Call the whisper API
    result = client.whisper(
        file_path=str(image_path),
        mode=whisperer_config.get("mode", "table"),  # "table", "form", or "text"
        output_mode=whisperer_config.get("output_mode", "layout_preserving"),
        wait_for_completion=True,
        wait_timeout=whisperer_config.get("timeout", 60),
    )

    # Extract the text from the result
    # The result structure is: {"extraction": {"result_text": "..."}}
    if "extraction" in result and "result_text" in result["extraction"]:
        return result["extraction"]["result_text"]
    return ""
