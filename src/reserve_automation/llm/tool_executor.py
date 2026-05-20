"""Execute LLM tool calls locally."""

import json
from typing import Any

import httpx
from ddgs import DDGS
from loguru import logger


class ToolExecutor:
    """Execute tool calls from LLM responses."""

    # Hard cap on follow-by-hand redirects so a malicious site can't bounce us forever.
    _MAX_REDIRECTS = 5

    def __init__(self, max_results: int = 10):
        # Add User-Agent to avoid blocking
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        # follow_redirects=False because httpx would otherwise follow a redirect
        # to a private IP without re-validating it against validate_url_not_internal.
        # We follow redirects manually in _fetch_with_validated_redirects, calling
        # validate_url_not_internal on every Location target.
        self.http_client = httpx.Client(
            timeout=30.0,
            follow_redirects=False,
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
            response = self._fetch_with_validated_redirects(url)
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

    def _fetch_with_validated_redirects(self, url: str) -> httpx.Response:
        """GET `url`, manually following redirects while re-validating every hop
        against validate_url_not_internal. Raises ValueError if any hop targets
        a private/internal address, and httpx errors for transport failures.

        Re-validating per-hop prevents a search-result-poisoning SSRF: even if
        the originally-supplied URL is public, a 30x to http://169.254.169.254
        (or any RFC1918 host) is rejected before we make the follow-up request.
        """
        from urllib.parse import urljoin
        from ..utils.url_validation import validate_url_not_internal

        current_url = url
        for hop in range(self._MAX_REDIRECTS + 1):
            validate_url_not_internal(current_url)
            response = self.http_client.get(current_url)
            if not response.is_redirect:
                return response

            location = response.headers.get("location")
            if not location:
                return response

            # Resolve relative redirects against the URL we just hit.
            current_url = urljoin(str(response.url), location)
            logger.info(f"Following redirect ({hop + 1}): {current_url}")

        raise ValueError(f"Too many redirects (>{self._MAX_REDIRECTS}) starting from {url}")

    def close(self):
        """Close HTTP client."""
        self.http_client.close()
