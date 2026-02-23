"""Bottle image serving endpoints - serve images from vault."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from ...auth.dependencies import require
from fastapi.responses import FileResponse
from loguru import logger

router = APIRouter(dependencies=[Depends(require("bottles.view"))])


@router.get("/api/v1/bottle-label/{bottle_path:path}")
async def serve_bottle_label(bottle_path: str):
    """
    Serve label image from a bottle's labels folder.

    Args:
        bottle_path: Relative path to bottle folder (e.g., "1_Whiskeys/Bottle Name")

    Returns:
        Image file response
    """
    from ...app import core_config

    if not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Construct path to label
        bottle_folder = core_config.vault_path / bottle_path
        label_path = bottle_folder / "labels" / "label.jpg"

        # Try PNG if JPG doesn't exist
        if not label_path.exists():
            label_path = bottle_folder / "labels" / "label.png"

        # Check if file exists
        if not label_path.exists():
            raise HTTPException(status_code=404, detail="Label not found")

        # Security: Ensure path is within vault
        if not label_path.resolve().is_relative_to(core_config.vault_path.resolve()):
            raise HTTPException(status_code=403, detail="Invalid path")

        # Serve the image
        return FileResponse(
            path=label_path,
            media_type="image/jpeg" if label_path.suffix == ".jpg" else "image/png",
            headers={"Cache-Control": "no-cache"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve bottle label: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/vault-images/{bottle_type}/{filename}")
async def serve_vault_image(bottle_type: str, filename: str):
    """
    Serve image from vault by bottle type and filename.

    Args:
        bottle_type: Type folder (e.g., "1_Wines", "1_Whiskeys")
        filename: Relative path within type folder

    Returns:
        Image file response
    """
    from ...app import core_config

    if not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Construct path
        image_path = core_config.vault_path / bottle_type / filename

        # Security: Ensure path is within vault
        if not image_path.resolve().is_relative_to(core_config.vault_path.resolve()):
            raise HTTPException(status_code=403, detail="Invalid path")

        # Check if file exists
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        # Determine media type
        media_type = "image/jpeg"
        if image_path.suffix.lower() in [".png"]:
            media_type = "image/png"
        elif image_path.suffix.lower() in [".gif"]:
            media_type = "image/gif"
        elif image_path.suffix.lower() in [".webp"]:
            media_type = "image/webp"

        # Serve the image
        return FileResponse(
            path=image_path,
            media_type=media_type,
            headers={"Cache-Control": "no-cache"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve vault image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
