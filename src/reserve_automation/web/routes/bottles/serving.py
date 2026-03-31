"""Bottle image serving endpoints - serve images from media directory."""

import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from ...auth.dependencies import require
from fastapi.responses import FileResponse
from loguru import logger

from ....db.repositories import get_bottle_repo
from ....db.repositories.bottle_repo import SQLiteBottleRepository

router = APIRouter(dependencies=[Depends(require("bottles.view"))])

# Media directory for images (configurable via MEDIA_DIR env var)
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "data/media"))


@router.get("/api/v1/bottle-label/{bottle_id}")
async def serve_bottle_label(
    bottle_id: int,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Serve label image for a bottle by ID.

    Args:
        bottle_id: Database ID of the bottle

    Returns:
        Image file response
    """
    try:
        bottle = bottle_repo.get_by_id(bottle_id)
        if bottle is None:
            raise HTTPException(status_code=404, detail="Bottle not found")

        if not bottle.label_image_url:
            raise HTTPException(status_code=404, detail="No label image")

        label_path = MEDIA_DIR / bottle.label_image_url

        # Try PNG if JPG doesn't exist
        if not label_path.exists() and label_path.suffix == ".jpg":
            label_path = label_path.with_suffix(".png")

        if not label_path.exists():
            raise HTTPException(status_code=404, detail="Label file not found")

        # Security: Ensure path is within media directory
        if not label_path.resolve().is_relative_to(MEDIA_DIR.resolve()):
            raise HTTPException(status_code=403, detail="Invalid path")

        return FileResponse(
            path=label_path,
            media_type="image/jpeg" if label_path.suffix == ".jpg" else "image/png",
            headers={"Cache-Control": "public, max-age=3600"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve bottle label: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/media/{file_path:path}")
async def serve_media_file(file_path: str):
    """
    Serve any media file by relative path within the media directory.

    Args:
        file_path: Relative path within media/ (e.g., "bottles/1/label.jpg")

    Returns:
        Image file response
    """
    try:
        image_path = MEDIA_DIR / file_path

        # Security: Ensure path is within media directory
        if not image_path.resolve().is_relative_to(MEDIA_DIR.resolve()):
            raise HTTPException(status_code=403, detail="Invalid path")

        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        # Determine media type
        suffix = image_path.suffix.lower()
        media_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        media_type = media_types.get(suffix, "application/octet-stream")

        return FileResponse(
            path=image_path,
            media_type=media_type,
            headers={"Cache-Control": "public, max-age=3600"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve media file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
