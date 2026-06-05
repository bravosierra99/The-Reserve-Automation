"""Label management routes - crop, download, upload, quality review."""

import hashlib
import io
import os
from pathlib import Path
from shutil import copyfile
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from loguru import logger
from PIL import Image

from ....core.models import BottleMetadata
from ....db.repositories import get_bottle_repo
from ....db.repositories.bottle_repo import SQLiteBottleRepository
from ...auth.dependencies import require

# Thumbnail cache directory
THUMBNAIL_CACHE_DIR = Path("/tmp/reserve-automation/thumbnails")

# Media directory for label storage
MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "data/media"))

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


def get_temp_label_dir(bottle_id: str) -> Path:
    """
    Get temporary directory for label operations on a specific bottle.

    Uses /tmp to avoid cluttering media directory with intermediate files.
    Only final accepted label.jpg is saved to media dir.

    Args:
        bottle_id: The bottle ID (e.g., "42")
    """
    safe_id = str(bottle_id).replace("/", "_").replace(" ", "_")
    temp_dir = Path("/tmp/reserve-automation/labels") / safe_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def _get_label_dir(bottle_id: str) -> Path:
    """Get the media label directory for a bottle, creating it if needed."""
    label_dir = MEDIA_DIR / "bottles" / str(bottle_id)
    label_dir.mkdir(parents=True, exist_ok=True)
    return label_dir


@router.post("/api/v1/management/labels/crop-current", dependencies=[Depends(require("labels.edit"))])
async def crop_current_label(
    data: dict,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Crop the current label using improved detection.

    Creates a preview file that can be accepted or discarded.
    """
    from shutil import copyfile

    from ....llm.gateway import LLMGateway
    from ....utils.label_processor import LabelImageProcessor
    from ... import app as app_module

    core_config = app_module.core_config

    try:
        bottle_id = data.get("bottle_id")
        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        bottle = bottle_repo.get_by_id(int(bottle_id))
        if not bottle:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        label_dir = _get_label_dir(bottle_id)
        current_label = label_dir / "label.jpg"
        if not current_label.exists():
            current_label = label_dir / "label.png"

        if not current_label.exists():
            raise HTTPException(status_code=404, detail="No label found")

        # Create preview path in /tmp (not in media dir)
        temp_dir = get_temp_label_dir(bottle_id)
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
async def accept_label_crop(
    data: dict,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Accept the cropped preview and replace the original label.
    """
    from shutil import copyfile

    try:
        bottle_id = data.get("bottle_id")
        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        bottle = bottle_repo.get_by_id(int(bottle_id))
        if not bottle:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        label_dir = _get_label_dir(bottle_id)
        temp_dir = get_temp_label_dir(bottle_id)
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
        final_label = label_dir / "label.jpg"
        copyfile(preview_path, final_label)

        # Update DB with label path
        bottle_repo.update_label_path(int(bottle_id), f"bottles/{bottle_id}/label.jpg")

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
async def download_label_image(
    data: dict,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Download image from URL and save as label_download.jpg (no cropping yet).
    """
    import httpx

    try:
        bottle_id = data.get("bottle_id")
        image_url = data.get("image_url")

        logger.info(f"Download request - bottle_id: {bottle_id}, URL: '{image_url}'")

        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        if not image_url:
            raise HTTPException(status_code=400, detail="Missing image URL")

        bottle = bottle_repo.get_by_id(int(bottle_id))
        if not bottle:
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

        # SSRF protection: validate URL doesn't target internal networks
        from ....utils.url_validation import validate_url_not_internal_async
        try:
            await validate_url_not_internal_async(image_url)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        # Save to /tmp instead of media dir
        temp_dir = get_temp_label_dir(bottle_id)

        # Download image — follow_redirects=False prevents redirect-based SSRF bypass
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=False) as client:
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
async def crop_downloaded_image(
    data: dict,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Crop the downloaded image and save as label_download_cropped.jpg.
    """
    from shutil import copyfile

    from ....llm.gateway import LLMGateway
    from ....utils.label_processor import LabelImageProcessor
    from ... import app as app_module

    core_config = app_module.core_config

    try:
        bottle_id = data.get("bottle_id")
        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        bottle = bottle_repo.get_by_id(int(bottle_id))
        if not bottle:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        # Use /tmp for intermediate files
        temp_dir = get_temp_label_dir(bottle_id)
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
async def use_downloaded_label(
    data: dict,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Use either the original downloaded or cropped version as the final label.
    """
    from shutil import copyfile

    try:
        bottle_id = data.get("bottle_id")
        use_cropped = data.get("use_cropped", False)

        if not bottle_id:
            raise HTTPException(status_code=400, detail="Missing bottle_id")

        bottle = bottle_repo.get_by_id(int(bottle_id))
        if not bottle:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        label_dir = _get_label_dir(bottle_id)
        temp_dir = get_temp_label_dir(bottle_id)

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

        # Replace with chosen version (only final label.jpg goes to media dir)
        final_label = label_dir / "label.jpg"
        copyfile(source_path, final_label)

        # Update DB with label path
        bottle_repo.update_label_path(int(bottle_id), f"bottles/{bottle_id}/label.jpg")

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
async def manual_crop_label(
    data: dict,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Crop label using exact pixel coordinates from manual selection.
    """
    from shutil import copyfile

    from PIL import Image

    try:
        bottle_id = data.get("bottle_id")
        x = data.get("x")
        y = data.get("y")
        width = data.get("width")
        height = data.get("height")

        if not bottle_id or x is None or y is None or width is None or height is None:
            raise HTTPException(status_code=400, detail="Missing bottle_id or coordinates")

        bottle = bottle_repo.get_by_id(int(bottle_id))
        if not bottle:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        label_dir = _get_label_dir(bottle_id)
        current_label = label_dir / "label.jpg"
        if not current_label.exists():
            current_label = label_dir / "label.png"

        if not current_label.exists():
            raise HTTPException(status_code=404, detail="No label found")

        logger.info(f"Manual crop: x={x}, y={y}, w={width}, h={height}")

        # Backup original to /tmp (not media dir)
        temp_dir = get_temp_label_dir(bottle_id)
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

        # Update DB with label path
        bottle_repo.update_label_path(int(bottle_id), f"bottles/{bottle_id}/label.jpg")

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
async def upload_manual_label(
    file: UploadFile,
    bottle: str = Form(),
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Upload a manual label image file for a bottle.
    Saves as label_download.jpg so it can use the existing download workflow.
    """
    import json

    try:
        # Parse bottle data from form to extract bottle_id
        bottle_data = json.loads(bottle)
        bottle_id = bottle_data.get("id")

        if not bottle_id:
            raise HTTPException(status_code=400, detail="Bottle data has no id")

        db_bottle = bottle_repo.get_by_id(int(bottle_id))
        if not db_bottle:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        # Save uploaded file to /tmp (not media dir)
        temp_dir = get_temp_label_dir(str(bottle_id))

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


@router.post("/api/v1/management/labels/upload-custom", dependencies=[Depends(require("labels.edit"))])
async def upload_custom_label(
    file: UploadFile,
    bottle: str = Form(),
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Upload a custom label image and commit it directly as the bottle's label.

    Single-step action for the "Upload Custom" button in the bottle editor modal
    (management mode). Unlike the download/search workflow there is no preview or
    accept step — the uploaded file becomes the label immediately:

    1. Normalize EXIF orientation (fixes rotated iPhone photos)
    2. Re-encode to JPEG and save as MEDIA_DIR/bottles/{id}/label.jpg
    3. Update the DB label path so the grid/modal pick it up
    """
    import json

    from PIL import ImageOps

    try:
        # Parse bottle data from form to extract bottle_id
        bottle_data = json.loads(bottle)
        bottle_id = bottle_data.get("id")

        if not bottle_id:
            raise HTTPException(status_code=400, detail="Bottle data has no id")

        db_bottle = bottle_repo.get_by_id(int(bottle_id))
        if not db_bottle:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        # Open + normalize orientation, then re-encode to a valid JPEG
        try:
            img = Image.open(io.BytesIO(content))
            img = ImageOps.exif_transpose(img)
        except Exception:
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid image")

        if img.mode == "RGBA":
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[3])
            img = background
        elif img.mode != "RGB":
            img = img.convert("RGB")

        label_dir = _get_label_dir(bottle_id)

        # Back up existing label before overwriting
        current_label = label_dir / "label.jpg"
        if current_label.exists():
            copyfile(current_label, label_dir / "label_backup.jpg")

        final_label = label_dir / "label.jpg"
        img.save(final_label, "JPEG", quality=95)

        # Update DB with label path so the grid and modal resolve the new image
        bottle_repo.update_label_path(int(bottle_id), f"bottles/{bottle_id}/label.jpg")

        logger.info(f"Custom label uploaded and committed: {final_label}")

        return {
            "status": "success",
            "message": "Custom label uploaded successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Custom label upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/labels/manual-crop-downloaded", dependencies=[Depends(require("labels.edit"))])
async def manual_crop_downloaded_label(
    data: dict,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Crop downloaded label image using exact pixel coordinates from manual selection.
    Crops label_download.jpg and saves as label_download_cropped.jpg.
    """
    from PIL import Image

    try:
        bottle_id = data.get("bottle_id")
        x = data.get("x")
        y = data.get("y")
        width = data.get("width")
        height = data.get("height")

        if not bottle_id or x is None or y is None or width is None or height is None:
            raise HTTPException(status_code=400, detail="Missing bottle_id or coordinates")

        bottle = bottle_repo.get_by_id(int(bottle_id))
        if not bottle:
            raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {bottle_id}")

        # Use /tmp for intermediate files
        temp_dir = get_temp_label_dir(bottle_id)
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


# TODO: Legacy routes - scan/accept/keep use LabelReviewService which scans the vault.
# These will need to be updated when LabelReviewService is migrated to use SQLite.
@router.post("/api/v1/management/labels/scan", dependencies=[Depends(require("labels.edit"))])
async def scan_label_quality(
    background_tasks: BackgroundTasks,
    show_all: bool = False,
    limit: Optional[int] = None
):
    """
    Scan all bottle labels and categorize them.

    TODO: This route uses LabelReviewService which scans the vault directly.
    It will not work correctly until LabelReviewService is updated to use SQLite/MEDIA_DIR.

    Args:
        show_all: If True, return all labels including good ones
        limit: Optional limit on number of bottles to check

    Returns:
        dict: Prioritized list of label review candidates
    """
    from ....llm.gateway import LLMGateway
    from ...app import core_config
    from ...services.label_review_service import LabelReviewService

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

    TODO: This route uses LabelReviewService which scans the vault directly.
    It will not work correctly until LabelReviewService is updated to use SQLite/MEDIA_DIR.

    Args:
        data: dict with 'bottle' field containing bottle metadata

    Returns:
        dict: Success status
    """
    from ....llm.gateway import LLMGateway
    from ...app import core_config
    from ...services.label_review_service import LabelReviewService

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

    TODO: This route uses LabelReviewService which scans the vault directly.
    It will not work correctly until LabelReviewService is updated to use SQLite/MEDIA_DIR.

    Args:
        data: dict with 'bottle' field containing bottle metadata

    Returns:
        dict: Success status
    """
    from ....llm.gateway import LLMGateway
    from ...app import core_config
    from ...services.label_review_service import LabelReviewService

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


# Filenames the temp-label workflow can produce. `path=` callers are restricted
# to these names so a client can't aim view_label_image at arbitrary files that
# happen to live under /tmp/reserve-automation.
_ALLOWED_TEMP_FILENAMES = frozenset({
    "label.jpg",
    "label_preview.jpg",
    "label_download.jpg",
    "label_download_cropped.jpg",
    "label_manual_backup.jpg",
})


@router.get("/api/v1/labels/view", dependencies=[Depends(require("labels.view"))])
async def view_label_image(
    path: Optional[str] = None,
    id: Optional[str] = None,
    file: Optional[str] = None,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Serve a label image for viewing.

    Preferred form: pass `id=` (+ optional `file=`). The route resolves to a
    label under MEDIA_DIR or the per-bottle temp dir.

    `path=` is still supported for the management UI's crop-preview workflow,
    but is restricted to absolute paths inside /tmp/reserve-automation pointing
    at an allowlisted temp filename. It cannot reach MEDIA_DIR (use id= for that).
    """
    try:
        temp_root = Path("/tmp/reserve-automation").resolve()

        label_filename = file if file else "label.jpg"

        logger.debug(f"View label request: id={id}, path={path}")

        if id:
            bottle = bottle_repo.get_by_id(int(id))
            if not bottle:
                raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {id}")

            if label_filename not in _ALLOWED_TEMP_FILENAMES:
                # Defensive: only allow the documented label filenames so a
                # caller can't aim `file=` at something else inside the temp dir.
                raise HTTPException(status_code=400, detail="Unsupported label filename")

            if label_filename in ("label_download.jpg", "label_download_cropped.jpg"):
                temp_dir = get_temp_label_dir(id)
                temp_file_path = temp_dir / label_filename
                if temp_file_path.exists():
                    image_path = temp_file_path
                else:
                    image_path = MEDIA_DIR / "bottles" / str(id) / label_filename
            elif label_filename == "label_preview.jpg":
                image_path = get_temp_label_dir(id) / label_filename
            else:
                if bottle.label_image_url:
                    image_path = MEDIA_DIR / bottle.label_image_url
                else:
                    image_path = MEDIA_DIR / "bottles" / str(id) / label_filename
        elif path:
            # `path=` mode: only honor absolute paths inside the temp root with
            # an allowlisted filename. Anything else fails closed.
            if not path.startswith("/") or ".." in Path(path).parts:
                raise HTTPException(status_code=400, detail="Invalid path")
            candidate = Path(path)
            if candidate.name not in _ALLOWED_TEMP_FILENAMES:
                raise HTTPException(status_code=400, detail="Unsupported label filename")
            try:
                candidate.resolve().relative_to(temp_root)
            except ValueError:
                raise HTTPException(status_code=403, detail="Access denied")
            image_path = candidate
        else:
            raise HTTPException(status_code=400, detail="Either 'path' or 'id' parameter is required")

        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        # Belt-and-braces containment check on the resolved path.
        resolved_path = image_path.resolve()
        try:
            resolved_path.relative_to(MEDIA_DIR.resolve())
        except ValueError:
            try:
                resolved_path.relative_to(temp_root)
            except ValueError:
                raise HTTPException(status_code=403, detail="Access denied")

        return FileResponse(
            image_path,
            media_type="image/jpeg" if image_path.suffix.lower() == ".jpg" else "image/png",
            headers={
                "Cache-Control": "public, max-age=3600",
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve label image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/labels/thumbnail", dependencies=[Depends(require("labels.view"))])
async def get_label_thumbnail(
    path: Optional[str] = None,
    id: Optional[str] = None,
    size: int = 400,
    file: Optional[str] = None,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Serve a resized thumbnail of a label image.

    Thumbnails are cached on disk for performance. Cache is invalidated
    when the source file is modified.

    Args:
        path: Path to original label image (legacy, will be deprecated). Can be:
              - Media-relative path (e.g., "bottles/42/label.jpg")
              - Full absolute path
              - Temp directory path (e.g., "/tmp/reserve-automation/...")
        id: Bottle ID - preferred over path. Resolves to media path internally.
        size: Maximum dimension (width or height) in pixels. Default 400.
              Images are resized maintaining aspect ratio.
        file: Optional filename within labels directory (default: "label.jpg").

    Returns:
        Response: JPEG thumbnail with cache headers
    """
    from pathlib import Path as PathLib

    try:
        temp_path = PathLib("/tmp/reserve-automation")
        temp_uploads = PathLib("/tmp/reserve_uploads")

        # Default filename
        label_filename = file if file else "label.jpg"

        logger.debug(f"Thumbnail request: id={id}, path={path}")

        # If id is provided, resolve it to a media path
        if id:
            bottle = bottle_repo.get_by_id(int(id))
            if not bottle:
                raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {id}")

            # Use label_image_url from DB if available, otherwise construct default
            if bottle.label_image_url:
                path = str(MEDIA_DIR / bottle.label_image_url)
            else:
                path = str(MEDIA_DIR / "bottles" / str(id) / label_filename)
            logger.debug(f"Resolved bottle ID {id} to path {path}")
        elif not path:
            raise HTTPException(status_code=400, detail="Either 'path' or 'id' parameter is required")

        # Try to resolve the path
        image_path = PathLib(path)

        # If path doesn't exist as-is, try prepending MEDIA_DIR
        if not image_path.exists():
            relative_path = path.lstrip('/')
            media_image_path = MEDIA_DIR / relative_path
            if media_image_path.exists():
                image_path = media_image_path
                logger.debug(f"Thumbnail: resolved relative path {path} to {image_path}")

        logger.debug(f"Thumbnail request: path={path}, resolved={image_path}, exists={image_path.exists()}")

        if not image_path.exists():
            logger.warning(f"Thumbnail not found: {path}")
            raise HTTPException(status_code=404, detail=f"Image not found: {path}")

        # Security check - ensure path is within MEDIA_DIR or temp directory
        resolved_path = image_path.resolve()
        is_allowed = False

        for allowed_path in [MEDIA_DIR, temp_path, temp_uploads]:
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
