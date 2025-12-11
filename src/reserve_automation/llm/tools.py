"""LLM tool definitions for function calling."""

# Web search tool definition
WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Search the web for information. Returns search results with titles, URLs, and snippets.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query string"
                }
            },
            "required": ["query"]
        }
    }
}

# Fetch webpage tool
WEB_FETCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": "Fetch and read the content of a specific webpage. Returns the text content and any images found.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch"
                }
            },
            "required": ["url"]
        }
    }
}

# All available tools
AVAILABLE_TOOLS = {
    "web_search": WEB_SEARCH_TOOL,
    "web_fetch": WEB_FETCH_TOOL,
}

# Tool sets for different tasks
TOOL_SETS = {
    "web_research": [WEB_SEARCH_TOOL, WEB_FETCH_TOOL],
    "metadata_enrichment": [WEB_SEARCH_TOOL],
}


def get_tools_for_task(task_type: str) -> list[dict]:
    """Get appropriate tools for a given task type."""
    return TOOL_SETS.get(task_type, [])
