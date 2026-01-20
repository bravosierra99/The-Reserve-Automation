"""Bottle routes - STATELESS (no sessions)."""

from fastapi import APIRouter
from . import extraction, serving, save, labels

# Create main router
router = APIRouter()

# Include sub-routers
router.include_router(extraction.router)  # Upload & extraction
router.include_router(serving.router)    # Image serving
router.include_router(save.router)       # Stateless save with duplicate detection
router.include_router(labels.router)     # Temp label operations (manual crop)

# REMOVED session-based routes:
# - enrichment.py (deprecated - enrichment now done in modal)
# - review.py (deprecated - approval/update now done via save endpoint)
