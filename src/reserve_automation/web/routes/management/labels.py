"""Label management routes - crop, download, upload, quality review."""

import hashlib
from pathlib import Path
from shutil import copyfile
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form, BackgroundTasks
from fastapi.responses import FileResponse, Response
from ...auth.dependencies import require
from loguru import logger
from PIL import Image
import io

from ....core.models import BottleMetadata

# Thumbnail cache directory
THUMBNAIL_CACHE_DIR = Path("/tmp/reserve-automation/thumbnails")

# Management label routes get labels.edit permission
# View/thumbnail routes get labels.view permission
router = APIRouter()


def clean_bottle_data(bottle_data: dict) -> dict:
    """
    Clean bottle data by converting empty strings/None to appropriate values.

    This handles the common issue where frontend forms send empty strings ("")
    or null values, but Pydantic expects None or typed values (int/float).

    Args:
        bottle_data: Raw bottle data dictionary (may contain empty strings or None)

    Returns:
        Cleaned bottle data dictionary
    """
    cleaned = bottle_data.copy()

    # Optional numeric fields - convert empty string or None to None
    optional_fields = ['year', 'price', 'abv', 'proof', 'vintage', 'age_statement', 'value_for_money']
    for field in optional_fields:
        if field in cleaned and (cleaned[field] == '' or cleaned[field] is None):
            cleaned[field] = None

    # Fields with defaults - remove if empty/None so Pydantic uses default
    fields_with_defaults = ['inventory', 'buy', 'confidence']
    for field in fields_with_defaults:
        if field in cleaned and (cleaned[field] == '' or cleaned[field] is None):
            del cleaned[field]

    return cleaned


def get_temp_label_dir(vault_path: str) -> Path:
    """
    Get temporary directory for label operations on a specific bottle.

    Uses /tmp to avoid cluttering Obsidian vault with intermediate files.
    Only final accepted label.jpg is saved to vault.

    Args:
        vault_path: The vault_path from BottleMetadata (e.g., "1_Wines/Producer - Name - Year")
    """
    # Use vault_path as unique identifier, replacing slashes with underscores
    safe_path = vault_path.replace("/", "_").replace(" ", "_")
    temp_dir = Path("/tmp/reserve-automation/labels") / safe_path
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir
@router.post("/api/v1/management/labels/crop-current", dependencies=[Depends(require("labels.edit"))])
async def crop_current_label(data: dict):
    """
    Crop the current label using improved detection.

    Creates a preview file that can be accepted or discarded.
    """
    from ... import app as app_module
    from ....llm.gateway import LLMGateway
    from ....utils.label_processor import LabelImageProcessor
    from pathlib import Path
    from shutil import copyfile

    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

    try:
        bottle_id = data.get("bottle_id")
        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        # Look up vault_path from registry
        if bottle_registry is None:
            raise HTTPException(status_code=500, detail="Bottle registry not initialized")

        vault_path = bottle_registry.get_path(bottle_id)
        if not vault_path:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        label_dir = core_config.vault_path / vault_path / "labels"
        current_label = label_dir / "label.jpg"
        if not current_label.exists():
            current_label = label_dir / "label.png"

        if not current_label.exists():
            raise HTTPException(status_code=404, detail="No label found")

        # Create preview path in /tmp (not in vault)
        temp_dir = get_temp_label_dir(vault_path)
        preview_path = temp_dir / "label_preview.jpg"

        # Copy current to preview
        copyfile(current_label, preview_path)

        # Crop the preview using improved detection
        llm = LLMGateway(core_config.llm)
        processor = LabelImageProcessor(llm)

        result = processor.crop_to_label(preview_path)

        if not result:
            raise HTTPException(status_code=500, detail="Cropping failed")

        return {
            "status": "success",
            "preview_path": str(preview_path)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Crop current label failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/accept-crop", dependencies=[Depends(require("labels.edit"))])
async def accept_label_crop(data: dict):
    """
    Accept the cropped preview and replace the original label.
    """
    from ... import app as app_module
    from pathlib import Path
    from shutil import copyfile

    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

    try:
        bottle_id = data.get("bottle_id")
        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        # Look up vault_path from registry
        if bottle_registry is None:
            raise HTTPException(status_code=500, detail="Bottle registry not initialized")

        vault_path = bottle_registry.get_path(bottle_id)
        if not vault_path:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        label_dir = core_config.vault_path / vault_path / "labels"
        temp_dir = get_temp_label_dir(vault_path)
        preview_path = temp_dir / "label_preview.jpg"

        if not preview_path.exists():
            raise HTTPException(status_code=404, detail="No preview found")

        # Determine current label extension
        current_label = label_dir / "label.jpg"
        if not current_label.exists():
            current_label = label_dir / "label.png"

        # Backup original
        backup_path = label_dir / f"label_original_{current_label.suffix}"
        if current_label.exists():
            copyfile(current_label, backup_path)

        # Replace with preview
        copyfile(preview_path, current_label)

        # Clean up preview
        preview_path.unlink()

        return {
            "status": "success",
            "message": "Cropped label accepted"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Accept crop failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/download-image", dependencies=[Depends(require("labels.edit"))])
async def download_label_image(data: dict):
    """
    Download image from URL and save as label_download.jpg (no cropping yet).
    """
    from ... import app as app_module
    from pathlib import Path
    import httpx

    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

    try:
        bottle_id = data.get("bottle_id")
        image_url = data.get("image_url")

        logger.info(f"Download request - bottle_id: {bottle_id}, URL: '{image_url}'")

        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        if not image_url:
            raise HTTPException(status_code=400, detail="Missing image URL")

        # Look up vault_path from registry
        if bottle_registry is None:
            raise HTTPException(status_code=500, detail="Bottle registry not initialized")

        vault_path = bottle_registry.get_path(bottle_id)
        if not vault_path:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        # Strip whitespace
        image_url = str(image_url).strip()

        if not image_url:
            raise HTTPException(status_code=400, detail="Image URL is empty")

        # Add protocol if missing
        if not image_url.startswith(('http://', 'https://')):
            logger.info(f"Adding https:// to URL: {image_url}")
            image_url = 'https://' + image_url

        logger.info(f"Final URL: {image_url}")

        # Save to /tmp instead of vault
        temp_dir = get_temp_label_dir(vault_path)

        # Download image
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            response = await client.get(image_url)
            response.raise_for_status()
            image_bytes = response.content

        # Save as downloaded image (NOT cropped) in /tmp
        download_path = temp_dir / "label_download.jpg"
        download_path.write_bytes(image_bytes)

        return {
            "status": "success",
            "download_path": str(download_path)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download image failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/crop-download", dependencies=[Depends(require("labels.edit"))])
async def crop_downloaded_image(data: dict):
    """
    Crop the downloaded image and save as label_download_cropped.jpg.
    """
    from ... import app as app_module
    from ....llm.gateway import LLMGateway
    from ....utils.label_processor import LabelImageProcessor
    from pathlib import Path
    from shutil import copyfile

    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

    try:
        bottle_id = data.get("bottle_id")
        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        # Look up vault_path from registry
        if bottle_registry is None:
            raise HTTPException(status_code=500, detail="Bottle registry not initialized")

        vault_path = bottle_registry.get_path(bottle_id)
        if not vault_path:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        # Use /tmp for intermediate files
        temp_dir = get_temp_label_dir(vault_path)
        download_path = temp_dir / "label_download.jpg"

        if not download_path.exists():
            raise HTTPException(status_code=404, detail="No downloaded image found")

        # Copy to cropped version in /tmp
        cropped_path = temp_dir / "label_download_cropped.jpg"
        copyfile(download_path, cropped_path)

        # Crop it
        llm = LLMGateway(core_config.llm)
        processor = LabelImageProcessor(llm)
        processor.crop_to_label(cropped_path)

        return {
            "status": "success",
            "cropped_path": str(cropped_path)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Crop download failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/use-downloaded", dependencies=[Depends(require("labels.edit"))])
async def use_downloaded_label(data: dict):
    """
    Use either the original downloaded or cropped version as the final label.
    """
    from ... import app as app_module
    from pathlib import Path
    from shutil import copyfile

    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

    try:
        bottle_id = data.get("bottle_id")
        use_cropped = data.get("use_cropped", False)

        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        # Look up vault_path from registry
        if bottle_registry is None:
            raise HTTPException(status_code=500, detail="Bottle registry not initialized")

        vault_path = bottle_registry.get_path(bottle_id)
        if not vault_path:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        label_dir = core_config.vault_path / vault_path / "labels"
        temp_dir = get_temp_label_dir(vault_path)

        # Choose source from /tmp
        if use_cropped:
            source_path = temp_dir / "label_download_cropped.jpg"
        else:
            source_path = temp_dir / "label_download.jpg"

        if not source_path.exists():
            raise HTTPException(status_code=404, detail="Downloaded image not found")

        # Backup current label if exists
        current_label = label_dir / "label.jpg"
        if not current_label.exists():
            current_label = label_dir / "label.png"

        if current_label.exists():
            backup_path = label_dir / "label_backup.jpg"
            copyfile(current_label, backup_path)

        # Create labels directory if it doesn't exist (for bottles with no label yet)
        label_dir.mkdir(parents=True, exist_ok=True)

        # Replace with chosen version (only final label.jpg goes to vault)
        final_label = label_dir / "label.jpg"
        copyfile(source_path, final_label)

        # Clean up temp files from /tmp
        (temp_dir / "label_download.jpg").unlink(missing_ok=True)
        (temp_dir / "label_download_cropped.jpg").unlink(missing_ok=True)

        return {
            "status": "success",
            "message": "Label replaced successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Use downloaded failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/manual-crop", dependencies=[Depends(require("labels.edit"))])
async def manual_crop_label(data: dict):
    """
    Crop label using exact pixel coordinates from manual selection.
    """
    from ... import app as app_module
    from pathlib import Path
    from PIL import Image
    from shutil import copyfile

    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

    try:
        bottle_id = data.get("bottle_id")
        x = data.get("x")
        y = data.get("y")
        width = data.get("width")
        height = data.get("height")

        if not bottle_id or x is None or y is None or width is None or height is None:
            raise HTTPException(status_code=400, detail="Missing bottle_id or coordinates")

        # Look up vault_path from registry
        if bottle_registry is None:
            raise HTTPException(status_code=500, detail="Bottle registry not initialized")

        vault_path = bottle_registry.get_path(bottle_id)
        if not vault_path:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        label_dir = core_config.vault_path / vault_path / "labels"
        current_label = label_dir / "label.jpg"
        if not current_label.exists():
            current_label = label_dir / "label.png"

        if not current_label.exists():
            raise HTTPException(status_code=404, detail="No label found")

        logger.info(f"Manual crop: x={x}, y={y}, w={width}, h={height}")

        # Backup original to /tmp (not vault)
        temp_dir = get_temp_label_dir(vault_path)
        backup_path = temp_dir / "label_manual_backup.jpg"
        copyfile(current_label, backup_path)

        # Crop using PIL
        img = Image.open(current_label)

        # CRITICAL: Normalize EXIF orientation BEFORE cropping
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
        logger.info(f"Image size after EXIF normalization: {img.size}")

        # Ensure coordinates are within image bounds
        img_width, img_height = img.size
        x = max(0, min(x, img_width))
        y = max(0, min(y, img_height))
        width = min(width, img_width - x)
        height = min(height, img_height - y)

        # Crop (left, top, right, bottom)
        cropped = img.crop((x, y, x + width, y + height))

        # Convert RGBA to RGB for JPEG (JPEG doesn't support transparency)
        if cropped.mode == 'RGBA':
            # Create white background
            background = Image.new('RGB', cropped.size, (255, 255, 255))
            background.paste(cropped, mask=cropped.split()[3])  # Use alpha channel as mask
            cropped = background
        elif cropped.mode != 'RGB':
            # Convert any other modes (P, L, etc.) to RGB
            cropped = cropped.convert('RGB')

        # Save as new label
        final_label = label_dir / "label.jpg"
        cropped.save(final_label, "JPEG", quality=95)

        logger.info(f"Manual crop complete: {final_label}")

        return {
            "status": "success",
            "message": "Label cropped successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Manual crop failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/upload-manual", dependencies=[Depends(require("labels.edit"))])
async def upload_manual_label(file: UploadFile, bottle: str = Form()):
    """
    Upload a manual label image file for a bottle.
    Saves as label_download.jpg so it can use the existing download workflow.
    """
    from ...app import core_config
    from ....core.models import BottleMetadata
    import json

    try:
        # Parse bottle data from form
        bottle_data = json.loads(bottle)
        bottle_obj = BottleMetadata(**bottle_data)

        if not bottle_obj.vault_path:
            raise HTTPException(status_code=400, detail="Bottle has no vault path")

        # Save uploaded file to /tmp (not vault)
        temp_dir = get_temp_label_dir(bottle_obj.vault_path)

        # Save uploaded file as label_download.jpg in /tmp
        download_path = temp_dir / "label_download.jpg"

        # Read and save file
        content = await file.read()
        with open(download_path, "wb") as f:
            f.write(content)

        logger.info(f"Manual label uploaded: {download_path}")

        return {
            "status": "success",
            "message": "Label uploaded successfully",
            "download_path": str(download_path)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Manual upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/manual-crop-downloaded", dependencies=[Depends(require("labels.edit"))])
async def manual_crop_downloaded_label(data: dict):
    """
    Crop downloaded label image using exact pixel coordinates from manual selection.
    Crops label_download.jpg and saves as label_download_cropped.jpg.
    """
    from ... import app as app_module
    from pathlib import Path
    from PIL import Image

    bottle_registry = app_module.bottle_registry

    try:
        bottle_id = data.get("bottle_id")
        x = data.get("x")
        y = data.get("y")
        width = data.get("width")
        height = data.get("height")

        if not bottle_id or x is None or y is None or width is None or height is None:
            raise HTTPException(status_code=400, detail="Missing bottle_id or coordinates")

        # Look up vault_path from registry
        if bottle_registry is None:
            raise HTTPException(status_code=500, detail="Bottle registry not initialized")

        vault_path = bottle_registry.get_path(bottle_id)
        if not vault_path:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        # Use /tmp for intermediate files
        temp_dir = get_temp_label_dir(vault_path)
        downloaded_label = temp_dir / "label_download.jpg"

        if not downloaded_label.exists():
            raise HTTPException(status_code=404, detail="No downloaded label found")

        logger.info(f"Manual crop downloaded: x={x}, y={y}, w={width}, h={height}")

        # Crop using PIL
        img = Image.open(downloaded_label)

        # CRITICAL: Normalize EXIF orientation BEFORE cropping
        # This fixes the bug where iPhone images have rotation metadata
        # and Cropper.js shows rotated view but PIL crops unrotated pixels
        from PIL import ImageOps
        img = ImageOps.exif_transpose(img)
        logger.info(f"Image size after EXIF normalization: {img.size}")

        # Ensure coordinates are within image bounds
        img_width, img_height = img.size
        x = max(0, min(x, img_width))
        y = max(0, min(y, img_height))
        width = min(width, img_width - x)
        height = min(height, img_height - y)

        # Crop (left, top, right, bottom)
        cropped = img.crop((x, y, x + width, y + height))

        # Save as cropped version in /tmp
        cropped_label = temp_dir / "label_download_cropped.jpg"
        cropped.save(cropped_label, "JPEG", quality=95)

        logger.info(f"Manual crop downloaded complete: {cropped_label}")

        return {
            "status": "success",
            "message": "Downloaded label cropped successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Manual crop downloaded failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Legacy routes (keep for compatibility but may remove later)
@router.post("/api/v1/management/labels/scan", dependencies=[Depends(require("labels.edit"))])
async def scan_label_quality(
    background_tasks: BackgroundTasks,
    show_all: bool = False,
    limit: Optional[int] = None
):
    """
    Scan all bottle labels and categorize them.

    Args:
        show_all: If True, return all labels including good ones
        limit: Optional limit on number of bottles to check

    Returns:
        dict: Prioritized list of label review candidates
    """
    from ...app import core_config
    from ...services.label_review_service import LabelReviewService
    from ....llm.gateway import LLMGateway

    try:
        # Create LLM gateway from config
        llm_gateway = LLMGateway(core_config.llm)
        service = LabelReviewService(llm_gateway, core_config.vault_path)

        # Scan labels and categorize
        candidates = await service.scan_all_labels(
            show_all=show_all,
            limit=limit
        )

        logger.info(f"Found {len(candidates)} labels in review queue")

        # For labels needing replacement, search for new images
        for candidate in candidates:
            if candidate.status == "needs_replacement":
                try:
                    search_results = await service.search_replacement_images(candidate)
                    candidate.search_results = search_results
                except Exception as e:
                    logger.error(f"Failed to search replacement images: {e}")
                    continue

        # Return candidates as JSON
        return {
            "candidates": [c.to_dict() for c in candidates],
            "count": len(candidates),
            "stats": {
                "needs_replacement": sum(1 for c in candidates if c.status == "needs_replacement"),
                "needs_cropping": sum(1 for c in candidates if c.status == "needs_cropping"),
                "good": sum(1 for c in candidates if c.status == "good")
            }
        }

    except Exception as e:
        logger.error(f"Label scan failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/accept", dependencies=[Depends(require("labels.edit"))])
async def accept_improved_label(data: dict):
    """
    Accept improved label crop and replace original.

    Args:
        data: dict with 'bottle' field containing bottle metadata

    Returns:
        dict: Success status
    """
    from ...app import core_config
    from ...services.label_review_service import LabelReviewService
    from ....llm.gateway import LLMGateway

    try:
        # Parse bottle from request
        bottle_data = data.get("bottle")
        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        # Create LLM gateway from config
        llm_gateway = LLMGateway(core_config.llm)
        service = LabelReviewService(llm_gateway, core_config.vault_path)

        success = await service.accept_improved_label(bottle)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to accept improved label")

        return {
            "status": "success",
            "message": "Improved label accepted"
        }

    except Exception as e:
        logger.error(f"Failed to accept improved label: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/keep", dependencies=[Depends(require("labels.edit"))])
async def keep_original_label(data: dict):
    """
    Keep original label and discard improved version.

    Args:
        data: dict with 'bottle' field containing bottle metadata

    Returns:
        dict: Success status
    """
    from ...app import core_config
    from ...services.label_review_service import LabelReviewService
    from ....llm.gateway import LLMGateway

    try:
        # Parse bottle from request
        bottle_data = data.get("bottle")
        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        # Create LLM gateway from config
        llm_gateway = LLMGateway(core_config.llm)
        service = LabelReviewService(llm_gateway, core_config.vault_path)

        success = await service.keep_original_label(bottle)

        if not success:
            raise HTTPException(status_code=500, detail="Failed to keep original")

        return {
            "status": "success",
            "message": "Original label kept"
        }

    except Exception as e:
        logger.error(f"Failed to keep original label: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/labels/view", dependencies=[Depends(require("labels.view"))])
async def view_label_image(path: Optional[str] = None, id: Optional[str] = None, file: Optional[str] = None):
    """
    Serve a label image for viewing.

    Args:
        path: Path to label image (legacy, will be deprecated). Can be:
              - Vault-relative path (e.g., "1_Wines/Producer/labels/label.jpg")
              - Full absolute path (e.g., "/mnt/.../Cellar/1_Wines/...")
              - Temp directory path (e.g., "/tmp/reserve-automation/...")
        id: Opaque bottle ID - preferred over path. Resolves to vault path internally.
        file: Optional filename within labels directory (default: "label.jpg").
              Used for temp files like "label_download.jpg" or "label_download_cropped.jpg".

    Returns:
        FileResponse: The image file
    """
    from pathlib import Path

    try:
        from ... import app as app_module
        core_config = app_module.core_config
        bottle_registry = app_module.bottle_registry
        vault_path = core_config.vault_path
        temp_path = Path("/tmp/reserve-automation")

        # Default filename
        label_filename = file if file else "label.jpg"

        logger.debug(f"View label request: id={id}, path={path}, bottle_registry={bottle_registry is not None}")

        # If id is provided, resolve it to a vault_path first
        if id:
            if bottle_registry is None:
                logger.error(f"Bottle registry not initialized, cannot resolve ID: {id}")
                raise HTTPException(status_code=500, detail="Bottle registry not initialized")
            resolved_vault_path = bottle_registry.get_path(id)
            if resolved_vault_path:
                # For temp files (label_download, label_download_cropped), check temp dir first
                if label_filename in ("label_download.jpg", "label_download_cropped.jpg"):
                    temp_dir = get_temp_label_dir(resolved_vault_path)
                    temp_file_path = temp_dir / label_filename
                    if temp_file_path.exists():
                        path = str(temp_file_path)
                        logger.debug(f"Resolved bottle ID {id} to temp path {path}")
                    else:
                        # Fall back to vault path
                        path = f"{resolved_vault_path}/labels/{label_filename}"
                        logger.debug(f"Temp file not found, using vault path {path}")
                else:
                    # Construct the label path from vault_path
                    path = f"{resolved_vault_path}/labels/{label_filename}"
                    logger.debug(f"Resolved bottle ID {id} to path {path}")
            else:
                raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {id}")
        elif not path:
            raise HTTPException(status_code=400, detail="Either 'path' or 'id' parameter is required")

        # Try to resolve the path - support both absolute and vault-relative paths
        image_path = Path(path)

        # If path doesn't exist as-is, try prepending vault path
        if not image_path.exists() and vault_path:
            relative_path = path.lstrip('/')
            vault_image_path = vault_path / relative_path
            if vault_image_path.exists():
                image_path = vault_image_path

        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        # Security check - ensure path is within vault or temp directory
        # (prevents directory traversal attacks)
        resolved_path = image_path.resolve()
        is_in_vault = False
        is_in_temp = False

        if vault_path:
            try:
                resolved_path.relative_to(vault_path.resolve())
                is_in_vault = True
            except ValueError:
                pass

        try:
            resolved_path.relative_to(temp_path.resolve())
            is_in_temp = True
        except ValueError:
            pass

        if not (is_in_vault or is_in_temp):
            raise HTTPException(status_code=403, detail="Access denied")

        return FileResponse(
            image_path,
            media_type="image/jpeg" if image_path.suffix.lower() == ".jpg" else "image/png",
            headers={
                "Cache-Control": "public, max-age=3600",  # 1 hour for full images
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve label image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/labels/thumbnail", dependencies=[Depends(require("labels.view"))])
async def get_label_thumbnail(path: Optional[str] = None, id: Optional[str] = None, size: int = 400, file: Optional[str] = None):
    """
    Serve a resized thumbnail of a label image.

    Thumbnails are cached on disk for performance. Cache is invalidated
    when the source file is modified.

    Args:
        path: Path to original label image (legacy, will be deprecated). Can be:
              - Vault-relative path (e.g., "1_Wines/Producer/labels/label.jpg")
              - Full absolute path (e.g., "/mnt/.../Cellar/1_Wines/...")
              - Temp directory path (e.g., "/tmp/reserve-automation/...")
        id: Opaque bottle ID - preferred over path. Resolves to vault path internally.
        size: Maximum dimension (width or height) in pixels. Default 400.
              Images are resized maintaining aspect ratio.
        file: Optional filename within labels directory (default: "label.jpg").

    Returns:
        Response: JPEG thumbnail with cache headers
    """
    from pathlib import Path as PathLib

    try:
        from ... import app as app_module
        core_config = app_module.core_config
        bottle_registry = app_module.bottle_registry
        vault_path = core_config.vault_path
        temp_path = PathLib("/tmp/reserve-automation")
        temp_uploads = PathLib("/tmp/reserve_uploads")

        # Default filename
        label_filename = file if file else "label.jpg"

        logger.debug(f"Thumbnail request: id={id}, path={path}")

        # If id is provided, resolve it to a vault_path first
        if id:
            if bottle_registry is None:
                logger.error(f"Bottle registry not initialized, cannot resolve ID: {id}")
                raise HTTPException(status_code=500, detail="Bottle registry not initialized")
            resolved_vault_path = bottle_registry.get_path(id)
            if resolved_vault_path:
                # Construct the label path from vault_path
                path = f"{resolved_vault_path}/labels/{label_filename}"
                logger.debug(f"Resolved bottle ID {id} to path {path}")
            else:
                raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {id}")
        elif not path:
            raise HTTPException(status_code=400, detail="Either 'path' or 'id' parameter is required")

        # Try to resolve the path - support both absolute and vault-relative paths
        image_path = PathLib(path)

        # If path doesn't exist as-is, try prepending vault path
        # This supports both:
        # - Full paths: /mnt/d/.../Cellar/1_Wines/...
        # - Vault-relative paths: 1_Wines/... or /1_Wines/...
        if not image_path.exists() and vault_path:
            # Strip leading slash if present for relative path
            relative_path = path.lstrip('/')
            vault_image_path = vault_path / relative_path
            if vault_image_path.exists():
                image_path = vault_image_path
                logger.debug(f"Thumbnail: resolved relative path {path} to {image_path}")

        logger.debug(f"Thumbnail request: path={path}, resolved={image_path}, exists={image_path.exists()}")

        if not image_path.exists():
            logger.warning(f"Thumbnail not found: {path} (tried vault-relative: {vault_path / path.lstrip('/') if vault_path else 'N/A'})")
            raise HTTPException(status_code=404, detail=f"Image not found: {path}")

        # Security check - ensure path is within vault or temp directory
        resolved_path = image_path.resolve()
        is_allowed = False

        for allowed_path in [vault_path, temp_path, temp_uploads]:
            if allowed_path is None:
                continue
            try:
                resolved_path.relative_to(allowed_path.resolve())
                is_allowed = True
                break
            except ValueError:
                pass

        if not is_allowed:
            raise HTTPException(status_code=403, detail="Access denied")

        # Clamp size to reasonable bounds
        size = max(100, min(size, 800))

        # Generate cache key from path + size + file modification time
        stat = image_path.stat()
        cache_key = hashlib.md5(
            f"{path}:{size}:{stat.st_mtime}".encode()
        ).hexdigest()

        # Check cache
        THUMBNAIL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path = THUMBNAIL_CACHE_DIR / f"{cache_key}.jpg"

        if cache_path.exists():
            # Serve from cache with long cache headers
            return FileResponse(
                cache_path,
                media_type="image/jpeg",
                headers={
                    "Cache-Control": "public, max-age=86400",  # 24 hours
                    "X-Thumbnail-Cache": "hit"
                }
            )

        # Generate thumbnail
        with Image.open(image_path) as img:
            # Handle EXIF orientation
            try:
                from PIL import ExifTags
                for orientation in ExifTags.TAGS.keys():
                    if ExifTags.TAGS[orientation] == 'Orientation':
                        break
                exif = img._getexif()
                if exif is not None:
                    orientation_value = exif.get(orientation)
                    if orientation_value == 3:
                        img = img.rotate(180, expand=True)
                    elif orientation_value == 6:
                        img = img.rotate(270, expand=True)
                    elif orientation_value == 8:
                        img = img.rotate(90, expand=True)
            except (AttributeError, KeyError, IndexError):
                pass

            # Convert to RGB if necessary (for PNG with transparency)
            if img.mode in ('RGBA', 'P'):
                img = img.convert('RGB')

            # Resize maintaining aspect ratio
            img.thumbnail((size, size), Image.Resampling.LANCZOS)

            # Save to cache
            img.save(cache_path, "JPEG", quality=85, optimize=True)

        # Serve the new thumbnail
        return FileResponse(
            cache_path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=86400",  # 24 hours
                "X-Thumbnail-Cache": "miss"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate thumbnail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
