"""Extraction prompts for bottle metadata."""

# System prompt for all extraction tasks
EXTRACTION_SYSTEM_PROMPT = """You are a wine and spirits expert specializing in extracting structured data from lists, catalogs, and labels.

Your task is to:
1. Identify all bottles mentioned in the input
2. Extract metadata for each bottle
3. Return well-structured JSON
4. Use null for missing information (never guess)
5. Maintain accuracy - only extract what is explicitly stated

Quality standards:
- Producer/distillery names should be capitalized correctly
- Years should be 4-digit integers
- Countries should use full names (not abbreviations unless they're part of the official name)
- Prices should be numeric values only (no currency symbols)
- If you're uncertain about a field, use null rather than guessing
"""

# JSON schema for wine extraction
WINE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "producer": {
                "type": "string",
                "description": "Winemaker/estate name",
            },
            "name": {
                "type": "string",
                "description": "Wine name (excluding producer and vintage)",
            },
            "year": {
                "type": ["integer", "null"],
                "description": "Vintage year (4 digits)",
            },
            "type": {
                "type": "string",
                "enum": ["wine"],
                "description": "MUST be exactly 'wine' (do not use 'Red wine' or other variants here)",
            },
            "beverage_type": {
                "type": ["string", "null"],
                "description": "Specific wine type: 'Red wine', 'White wine', 'Rosé', 'Champagne', 'Sparkling', etc.",
            },
            "variety": {
                "type": ["string", "null"],
                "description": "Grape variety or blend (e.g., 'Cabernet Sauvignon', 'Bordeaux Blend')",
            },
            "region": {
                "type": ["string", "null"],
                "description": "Wine region (e.g., 'Napa Valley', 'Bordeaux')",
            },
            "country": {
                "type": ["string", "null"],
                "description": "Country of origin",
            },
            "abv": {
                "type": ["number", "null"],
                "description": "Alcohol by volume percentage",
            },
            "price": {
                "type": ["number", "null"],
                "description": "Price in local currency (number only)",
            },
        },
        "required": ["producer", "name", "type"],
    },
}

# JSON schema for whiskey extraction
WHISKEY_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "producer": {
                "type": "string",
                "description": "Distillery name",
            },
            "name": {
                "type": "string",
                "description": "Whiskey name (excluding distillery and year)",
            },
            "year": {
                "type": ["integer", "null"],
                "description": "Release year (4 digits)",
            },
            "type": {
                "type": "string",
                "enum": ["whiskey"],
                "description": "MUST be exactly 'whiskey' (do not use 'Bourbon' or other variants here)",
            },
            "beverage_type": {
                "type": ["string", "null"],
                "description": "Specific whiskey type: 'Bourbon', 'Rye', 'Scotch', 'Irish', 'Japanese', etc.",
            },
            "age_statement": {
                "type": ["integer", "null"],
                "description": "Age in years (if stated on bottle)",
            },
            "proof": {
                "type": ["number", "null"],
                "description": "Proof (US measurement, e.g., 100)",
            },
            "region": {
                "type": ["string", "null"],
                "description": "Region/state (e.g., 'Kentucky', 'Islay')",
            },
            "country": {
                "type": ["string", "null"],
                "description": "Country of origin",
            },
            "abv": {
                "type": ["number", "null"],
                "description": "Alcohol by volume percentage",
            },
            "price": {
                "type": ["number", "null"],
                "description": "Price in local currency (number only)",
            },
        },
        "required": ["producer", "name", "type"],
    },
}


def build_extraction_prompt(text: str, beverage_type: str = "auto", expected_count: int = None) -> str:
    """
    Build extraction prompt for bottle data.

    Args:
        text: Text to extract from
        beverage_type: 'wine', 'whiskey', or 'auto'
        expected_count: Expected number of bottles (helps LLM validate completeness)

    Returns:
        Formatted prompt with schema
    """
    # Build expected count instruction if provided
    count_instruction = ""
    if expected_count is not None:
        count_instruction = f"\n- EXPECTED COUNT: This text should contain approximately {expected_count} bottles - make sure you extract all of them!"

    if beverage_type == "auto":
        # Use a combined schema that can handle both
        prompt = f"""Extract all wine and whiskey bottles from the following text.

Return a JSON array where each item is a bottle with this structure:

For WINES:
{_format_schema(WINE_SCHEMA["items"])}

For WHISKEYS:
{_format_schema(WHISKEY_SCHEMA["items"])}

CRITICAL - Read carefully:
- You MUST extract EVERY SINGLE bottle mentioned in the text from start to finish
- Do NOT stop after a few bottles - scan the ENTIRE text thoroughly
- Count the bottles before and after to ensure you got them all
- Missing even one bottle is considered a failure{count_instruction}

Important rules:
- REQUIRED FIELDS (producer, name, type) MUST NEVER be null - if you can't determine them, skip that bottle entirely
- Use null for OPTIONAL fields only (never guess)
- Infer type as "wine" or "whiskey" based on context
- For wines: year is the vintage
- For whiskeys: year is the release year (if mentioned)
- Standardize country names (e.g., "USA" → "United States", "UK" → "United Kingdom")
- Include price only if explicitly stated with a number
- beverage_type should be specific: "Red wine", "Bourbon", "Scotch", etc.

Text to extract from:
---
{text}
---

Return ONLY a JSON array, no other text. Format:
[
  {{"producer": "...", "name": "...", "type": "wine", ...}},
  {{"producer": "...", "name": "...", "type": "whiskey", ...}}
]"""

    elif beverage_type == "wine":
        schema = WINE_SCHEMA["items"]
        prompt = f"""Extract all wine bottles from the following text.

Return a JSON array where each item represents one wine with this exact structure:
{_format_schema(schema)}

CRITICAL - Read carefully:
- You MUST extract EVERY SINGLE wine mentioned in the text from start to finish
- Do NOT stop after a few wines - scan the ENTIRE text thoroughly
- Count the wines before and after to ensure you got them all
- Missing even one wine is considered a failure{count_instruction}

Important rules:
- REQUIRED FIELDS (producer, name, type) MUST NEVER be null - if you can't determine them, skip that bottle entirely
- Use null for OPTIONAL fields only
- year = vintage year (4 digits)
- Standardize country names
- beverage_type: "Red wine", "White wine", "Rosé", "Champagne", etc.

Text to extract from:
---
{text}
---

Return ONLY a JSON array, no other text."""

    else:  # whiskey
        schema = WHISKEY_SCHEMA["items"]
        prompt = f"""Extract all whiskey bottles from the following text.

Return a JSON array where each item represents one whiskey with this exact structure:
{_format_schema(schema)}

CRITICAL - Read carefully:
- You MUST extract EVERY SINGLE whiskey mentioned in the text from start to finish
- Do NOT stop after a few whiskeys - scan the ENTIRE text thoroughly
- Count the whiskeys before and after to ensure you got them all
- Missing even one whiskey is considered a failure{count_instruction}

Important rules:
- REQUIRED FIELDS (producer, name, type) MUST NEVER be null - if you can't determine them, skip that bottle entirely
- Use null for OPTIONAL fields only
- year = release year (if mentioned)
- age_statement = age in years (e.g., 12 for "12 Year Old")
- proof = US proof (e.g., 100, not 50% ABV)
- beverage_type: "Bourbon", "Rye", "Scotch", "Irish", "Japanese", etc.

Text to extract from:
---
{text}
---

Return ONLY a JSON array, no other text."""

    return prompt


def _format_schema(schema: dict) -> str:
    """Format JSON schema as readable text for prompt."""
    props = schema.get("properties", {})
    required = schema.get("required", [])

    lines = []
    for field, spec in props.items():
        field_type = spec.get("type", "string")
        if isinstance(field_type, list):
            field_type = " or ".join(field_type)

        description = spec.get("description", "")
        is_required = " (REQUIRED)" if field in required else " (optional)"

        lines.append(f"  - {field}: {field_type}{is_required} - {description}")

    return "\n".join(lines)


# Type detection prompt
TYPE_DETECTION_PROMPT = """Analyze the following text and determine if it primarily describes:
- "wine" (wine bottles, vintages, wineries)
- "whiskey" (whiskey bottles, distilleries, bourbon, scotch, rye, etc.)
- "mixed" (contains both wines and whiskeys)
- "unknown" (unclear or neither)

Consider mentions of:
- For wine: vintages, varietals (Cabernet, Chardonnay), wine regions, wineries
- For whiskey: proof, age statements, distilleries, bourbon/scotch/rye, barrels

Text:
---
{text}
---

Respond with ONLY one word: wine, whiskey, mixed, or unknown"""
