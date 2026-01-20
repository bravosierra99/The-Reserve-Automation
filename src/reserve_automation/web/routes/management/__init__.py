"""Management routes - unified router combining core and label modules."""

from fastapi import APIRouter
from . import core, labels

# Create main router
router = APIRouter()

# Include sub-routers
router.include_router(core.router)
router.include_router(labels.router)

# Re-export in-memory storage for backward compatibility
verification_results = core.verification_results
batch_status = core.batch_status
