"""FastAPI web application for The Reserve Automation."""

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from loguru import logger
from PIL import Image

from ..db.engine import init_db
from .config import load_auth_config, load_web_config
from .logging_config import setup_web_logging
from .routes import (
    autocomplete,
    bottles,
    cocktails,
    events,
    health,
    ingredients,
    management,
    review,
    tastings,
    upload,
)
from .services.upload_service import UploadService
from .templating import make_templates

# Cap the per-image pixel count so a maliciously-crafted decompression bomb
# (small file, huge pixel grid) can't OOM the container. 50 MP = ~150 MB at
# 3 bytes/pixel — well below the 2 GB container limit but large enough for any
# legitimate bottle-label photo. PIL raises Image.DecompressionBombError above
# this; we want that to bubble up as a 500 rather than silently allocating.
Image.MAX_IMAGE_PIXELS = 50_000_000


# Global services (initialized on startup)
upload_service: UploadService = None
core_config = None
web_config = None
auth_config = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global upload_service, core_config, web_config, auth_config

    # Startup - Initialize logging first
    # Read log level from environment variable, default to INFO for production
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    setup_web_logging(log_level=log_level)
    logger.info("Starting The Reserve Automation web application")

    # Load configuration
    core_config, web_config = load_web_config()
    logger.info("Loaded configuration")

    # Initialize database
    database_url = os.getenv("DATABASE_URL", "sqlite:///data/reserve.db")
    init_db(database_url)
    logger.info(f"Database initialized: {database_url}")

    # Load auth configuration
    auth_config = load_auth_config()
    app.state.auth_config = auth_config
    if auth_config.dev.enabled:
        logger.info("Auth: dev mode enabled (mock user bypass)")
    else:
        logger.info(f"Auth: Cloudflare Access mode (team={auth_config.cloudflare.team_domain})")

    # Initialize services
    upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions
    )

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


# Conditionally enable OpenAPI docs only in dev mode
_startup_auth_config = load_auth_config()
_docs_url = "/docs" if _startup_auth_config.dev.enabled else None
_redoc_url = "/redoc" if _startup_auth_config.dev.enabled else None
_openapi_url = "/openapi.json" if _startup_auth_config.dev.enabled else None

# Create FastAPI app
app = FastAPI(
    title="The Reserve Automation",
    description="Mobile-first web interface for bottle and tasting management",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

# Set auth config on app.state so middleware and dependencies can access it
# (lifespan may update this later, but this ensures it's always available)
app.state.auth_config = _startup_auth_config

# Register security headers middleware
from .middleware.security_headers import SecurityHeadersMiddleware  # noqa: E402

app.add_middleware(SecurityHeadersMiddleware)

# Register auth middleware (must be done before app starts, not in lifespan)
from .auth.middleware import AuthMiddleware  # noqa: E402

app.add_middleware(AuthMiddleware, auth_config=_startup_auth_config)

# Mount static files
static_path = Path(__file__).parent / "static"
static_path.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Set up templates
templates_dir = Path(__file__).parent / "templates"
templates_dir.mkdir(exist_ok=True)
templates = make_templates(templates_dir)
# Disable template caching in development
templates.env.auto_reload = True
templates.env.cache = None

# Include routers
# #CLAUDE_REQ: Every router included here MUST enforce auth via Depends(require(...)).
# Either at router level (APIRouter(dependencies=[Depends(require(...))])) or on each
# individual route. health.router is the only intentional exception: its public
# /health and /version routes are allowlisted in auth/middleware.py PUBLIC_PATHS.
# See config/auth.yaml for the full permission → role mapping.
# When adding a new router: grep its file for require() before including it here.
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(upload.router, tags=["upload"])  # Unified upload page (/upload)
app.include_router(review.router, tags=["review"])  # Tasting card review page (/review) and API endpoints
app.include_router(bottles.router, tags=["bottles"])  # Bottle API endpoints (/api/v1/bottles/*)
app.include_router(tastings.router, tags=["tastings"])  # New tasting review workflow
app.include_router(tastings.participant_router, tags=["tastings"])  # Manual-tasting wizard (guest-reachable for events)
app.include_router(management.router, tags=["management"])  # Management page for metadata updates
app.include_router(events.router, tags=["events"])  # Event system for multi-user tastings
app.include_router(ingredients.router, tags=["ingredients"])  # Ingredient tree management
app.include_router(cocktails.router, tags=["cocktails"])  # Cocktail recipe management
app.include_router(autocomplete.router, tags=["autocomplete"])  # Autocomplete suggestions for form fields


@app.get("/")
async def root():
    """Root endpoint - redirect to bottles (accessible to all roles)."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/bottles")


@app.exception_handler(403)
async def permission_denied_handler(request, exc):
    """Redirect page requests to /bottles on 403, return JSON for API."""
    from fastapi.responses import JSONResponse, RedirectResponse
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            status_code=403,
            content={"detail": str(exc.detail) if hasattr(exc, "detail") else "Permission denied"},
        )
    # Page request - redirect to bottles (accessible to all roles)
    return RedirectResponse(url="/bottles", status_code=303)


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
