"""FastAPI web application for The Reserve Automation."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from loguru import logger

from .config import load_web_config
from .logging_config import setup_web_logging
from .routes import upload, review, health, bottles, tastings, management, events, ingredients, cocktails
from .services.upload_service import UploadService
from ..core.bottle_registry import BottleRegistry


# Global services (initialized on startup)
upload_service: UploadService = None
core_config = None
web_config = None
event_store: dict[str, dict] = {}
bottle_registry: BottleRegistry = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global upload_service, core_config, web_config, event_store, bottle_registry

    # Startup - Initialize logging first
    # Read log level from environment variable, default to INFO for production
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    setup_web_logging(log_level=log_level)
    logger.info("Starting The Reserve Automation web application")

    # Load configuration
    core_config, web_config = load_web_config()
    logger.info(f"Loaded configuration: vault={core_config.vault_path}")

    # Initialize services
    upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions
    )

    # Initialize event store (in-memory)
    event_store = {}
    logger.info("Event store initialized")

    # Initialize bottle registry (in-memory mapping between opaque IDs and vault paths)
    bottle_registry = BottleRegistry()
    logger.info(f"Bottle registry initialized: {bottle_registry}, id={id(bottle_registry)}")

    # Verify the module-level variable is set
    import sys
    this_module = sys.modules[__name__]
    logger.info(f"app.py module name: {__name__}")
    logger.info(f"Module-level bottle_registry check: {getattr(this_module, 'bottle_registry', 'NOT FOUND')}, id={id(getattr(this_module, 'bottle_registry', None)) if getattr(this_module, 'bottle_registry', None) else 'None'}")

    # Clean up old temp files on startup
    deleted = upload_service.cleanup_old_files(
        max_age_hours=web_config.uploads.cleanup_age_hours
    )
    if deleted > 0:
        logger.info(f"Cleaned up {deleted} orphaned temp files")

    logger.info("Application startup complete")

    yield

    # Shutdown
    logger.info("Shutting down application")


# Create FastAPI app
app = FastAPI(
    title="The Reserve Automation",
    description="Mobile-first web interface for bottle and tasting management",
    version="0.1.0",
    lifespan=lifespan
)

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Set up templates
templates_dir = Path(__file__).parent / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)
# Disable template caching in development
templates.env.auto_reload = True
templates.env.cache = None

# Include routers
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(upload.router, tags=["upload"])  # Unified upload page (/upload) and /review-bottles routes
app.include_router(review.router, tags=["review"])  # Tasting card review page (/review) and API endpoints
app.include_router(bottles.router, tags=["bottles"])  # Bottle API endpoints (/api/v1/bottles/*)
app.include_router(tastings.router, tags=["tastings"])  # New tasting review workflow
app.include_router(management.router, tags=["management"])  # Management page for metadata updates
app.include_router(events.router, tags=["events"])  # Event system for multi-user tastings
app.include_router(ingredients.router, tags=["ingredients"])  # Ingredient tree management
app.include_router(cocktails.router, tags=["cocktails"])  # Cocktail recipe management


@app.get("/")
async def root():
    """Root endpoint - redirect to upload page."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/upload")


def main():
    """Entry point for running the web application."""
    import uvicorn

    # Load config
    _, web_cfg = load_web_config()

    # Run server
    uvicorn.run(
        "reserve_automation.web.app:app",
        host=web_cfg.host,
        port=web_cfg.port,
        reload=True,  # Enable auto-reload for development
        log_level="info"
    )


if __name__ == "__main__":
    main()
