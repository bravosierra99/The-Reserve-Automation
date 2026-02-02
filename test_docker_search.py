#!/usr/bin/env python3
"""Test web search functionality in Docker environment."""

import sys
from loguru import logger

# Configure logger to show debug messages
logger.remove()
logger.add(sys.stderr, level="DEBUG")

try:
    from ddgs import DDGS

    logger.info("Testing DuckDuckGo search in Docker environment...")

    test_query = "VECCHIA CANTINA UMBRIA ROSSO wine"
    logger.info(f"Search query: {test_query}")

    with DDGS() as ddgs:
        results = list(ddgs.text(test_query, max_results=5))

    if results:
        logger.success(f"✓ Search successful! Found {len(results)} results")
        for i, result in enumerate(results, 1):
            logger.info(f"  {i}. {result.get('title', 'No title')}")
            logger.debug(f"     URL: {result.get('href', 'No URL')}")
    else:
        logger.error("✗ Search returned no results")
        sys.exit(1)

except Exception as e:
    logger.error(f"✗ Search failed: {type(e).__name__}: {e}")
    import traceback
    logger.error(traceback.format_exc())
    sys.exit(1)
