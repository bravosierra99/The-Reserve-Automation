"""Execute LLM tool calls locally."""

import json
from typing import Any

import httpx
from ddgs import DDGS
from loguru import logger


class ToolExecutor:
    """Execute tool calls from LLM responses."""

    def __init__(self, max_results: int = 10):
        # Add User-Agent to avoid blocking
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        self.http_client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers=headers
        )
        self.max_results = max_results
        self.call_count = 0  # Total execute() calls (useful for benchmarking)

    def execute(self, tool_name: str, arguments: dict) -> dict:
        """
        Execute a tool call and return the results.

        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments for the tool

        Returns:
            Dict with tool execution results
        """
        logger.info(f"Executing tool: {tool_name} with args: {arguments}")
        self.call_count += 1

        try:
            if tool_name == "web_search":
                return self._web_search(arguments)
            elif tool_name == "web_fetch":
                return self._web_fetch(arguments)
            else:
                return {"error": f"Unknown tool: {tool_name}"}

        except Exception as e:
            logger.error(f"Tool execution failed: {e}")
            return {"error": str(e)}

    def _web_search(self, arguments: dict) -> dict:
        """
        Execute web search using DuckDuckGo.

        Args:
            arguments: {"query": "search query"}

        Returns:
            {"results": [{"title": "...", "url": "...", "snippet": "..."}]}
        """
        query = arguments.get("query", "")
        if not query:
            return {"error": "No query provided"}

        logger.info(f"DuckDuckGo search: {query}")

        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=self.max_results))

            # Format results
            formatted_results = []
            for r in results:
                formatted_results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })

            logger.info(f"Found {len(formatted_results)} search results")

            return {
                "results": formatted_results,
                "query": query,
            }

        except Exception as e:
            logger.error(f"DuckDuckGo search failed: {e}")
            return {"error": f"Search failed: {str(e)}"}

    def _web_fetch(self, arguments: dict) -> dict:
        """
        Fetch webpage content.

        Args:
            arguments: {"url": "https://..."}

        Returns:
            {"content": "...", "url": "...", "images": [...]}
        """
        url = arguments.get("url", "")
        if not url:
            return {"error": "No URL provided"}

        logger.info(f"Fetching: {url}")

        try:
            response = self.http_client.get(url)
            response.raise_for_status()

            content = response.text
            content_type = response.headers.get("content-type", "")

            # Extract image URLs (focus on product/bottle images)
            import re

            # Find img tags with src attributes
            img_pattern = r'<img[^>]+src=["\']([^"\']+)["\']'
            images = re.findall(img_pattern, content)

            # Filter for likely product images (larger, jpg/png, not icons)
            likely_products = []
            for img_url in images:
                lower = img_url.lower()
                # Skip small icons, social media, sprites
                if any(skip in lower for skip in ['icon', 'logo', 'sprite', 'svg', 'gif', 'thumb']):
                    continue
                # Prioritize jpg/png/webp
                if any(ext in lower for ext in ['.jpg', '.jpeg', '.png', '.webp']):
                    likely_products.append(img_url)

            # Return focused results - just the images found
            return {
                "url": url,
                "images_found": len(likely_products),
                "images": likely_products[:15],  # Top 15 likely product images
                "note": f"Found {len(likely_products)} likely product images (filtered from {len(images)} total)"
            }

        except Exception as e:
            logger.error(f"Web fetch failed: {e}")
            return {"error": f"Fetch failed: {str(e)}"}

    def close(self):
        """Close HTTP client."""
        self.http_client.close()
