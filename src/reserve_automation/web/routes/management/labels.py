"""Label management routes - crop, download, upload, quality review."""

from pathlib import Path
from shutil import copyfile
from typing import Optional
from fastapi import APIRouter, HTTPException, UploadFile, Form, BackgroundTasks
from fastapi.responses import FileResponse
from loguru import logger
from ....core.models import BottleMetadata

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
@router.post("/api/v1/management/labels/crop-current")
async def crop_current_label(data: dict):
    """
    Crop the current label using improved detection.

    Creates a preview file that can be accepted or discarded.
    """
    from ...app import core_config
    from ....llm.gateway import LLMGateway
    from ....utils.label_processor import LabelImageProcessor
    from ....core.models import BottleMetadata
    from pathlib import Path
    from shutil import copyfile

    try:
        bottle_data = data.get("bottle")
        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        # Get current label path
        if not bottle.vault_path:
            raise HTTPException(status_code=400, detail="Bottle has no vault path")

        label_dir = core_config.vault_path / bottle.vault_path / "labels"
        current_label = label_dir / "label.jpg"
        if not current_label.exists():
            current_label = label_dir / "label.png"

        if not current_label.exists():
            raise HTTPException(status_code=404, detail="No label found")

        # Create preview path in /tmp (not in vault)
        temp_dir = get_temp_label_dir(bottle.vault_path)
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


@router.post("/api/v1/management/labels/accept-crop")
async def accept_label_crop(data: dict):
    """
    Accept the cropped preview and replace the original label.
    """
    from ...app import core_config
    from ....core.models import BottleMetadata
    from pathlib import Path
    from shutil import copyfile

    try:
        bottle_data = data.get("bottle")
        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        if not bottle.vault_path:
            raise HTTPException(status_code=400, detail="Bottle has no vault path")

        label_dir = core_config.vault_path / bottle.vault_path / "labels"
        temp_dir = get_temp_label_dir(bottle.vault_path)
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


@router.post("/api/v1/management/labels/download-image")
async def download_label_image(data: dict):
    """
    Download image from URL and save as label_download.jpg (no cropping yet).
    """
    from ...app import core_config
    from ....core.models import BottleMetadata
    from pathlib import Path
    import httpx

    try:
        bottle_data = data.get("bottle")
        image_url = data.get("image_url")

        logger.info(f"Download request - URL: '{image_url}' (type: {type(image_url)})")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        if not image_url:
            raise HTTPException(status_code=400, detail="Missing image URL")

        # Strip whitespace
        image_url = str(image_url).strip()

        if not image_url:
            raise HTTPException(status_code=400, detail="Image URL is empty")

        # Add protocol if missing
        if not image_url.startswith(('http://', 'https://')):
            logger.info(f"Adding https:// to URL: {image_url}")
            image_url = 'https://' + image_url

        logger.info(f"Final URL: {image_url}")

        bottle = BottleMetadata(**bottle_data)

        if not bottle.vault_path:
            raise HTTPException(status_code=400, detail="Bottle has no vault path")

        # Save to /tmp instead of vault
        temp_dir = get_temp_label_dir(bottle.vault_path)

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


@router.post("/api/v1/management/labels/crop-download")
async def crop_downloaded_image(data: dict):
    """
    Crop the downloaded image and save as label_download_cropped.jpg.
    """
    from ...app import core_config
    from ....llm.gateway import LLMGateway
    from ....utils.label_processor import LabelImageProcessor
    from ....core.models import BottleMetadata
    from pathlib import Path
    from shutil import copyfile

    try:
        bottle_data = data.get("bottle")
        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        if not bottle.vault_path:
            raise HTTPException(status_code=400, detail="Bottle has no vault path")

        # Use /tmp for intermediate files
        temp_dir = get_temp_label_dir(bottle.vault_path)
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


@router.post("/api/v1/management/labels/use-downloaded")
async def use_downloaded_label(data: dict):
    """
    Use either the original downloaded or cropped version as the final label.
    """
    from ...app import core_config
    from ....core.models import BottleMetadata
    from pathlib import Path
    from shutil import copyfile

    try:
        bottle_data = data.get("bottle")
        use_cropped = data.get("use_cropped", False)

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        if not bottle.vault_path:
            raise HTTPException(status_code=400, detail="Bottle has no vault path")

        label_dir = core_config.vault_path / bottle.vault_path / "labels"
        temp_dir = get_temp_label_dir(bottle.vault_path)

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


@router.post("/api/v1/management/labels/manual-crop")
async def manual_crop_label(data: dict):
    """
    Crop label using exact pixel coordinates from manual selection.
    """
    from ...app import core_config
    from ....core.models import BottleMetadata
    from pathlib import Path
    from PIL import Image
    from shutil import copyfile

    try:
        bottle_data = data.get("bottle")
        x = data.get("x")
        y = data.get("y")
        width = data.get("width")
        height = data.get("height")

        if not bottle_data or x is None or y is None or width is None or height is None:
            raise HTTPException(status_code=400, detail="Missing data or coordinates")

        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(bottle_data)
        bottle = BottleMetadata(**cleaned_bottle_data)

        if not bottle.vault_path:
            raise HTTPException(status_code=400, detail="Bottle has no vault path")

        label_dir = core_config.vault_path / bottle.vault_path / "labels"
        current_label = label_dir / "label.jpg"
        if not current_label.exists():
            current_label = label_dir / "label.png"

        if not current_label.exists():
            raise HTTPException(status_code=404, detail="No label found")

        logger.info(f"Manual crop: x={x}, y={y}, w={width}, h={height}")

        # Backup original to /tmp (not vault)
        temp_dir = get_temp_label_dir(bottle.vault_path)
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


@router.post("/api/v1/management/labels/upload-manual")
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


@router.post("/api/v1/management/labels/manual-crop-downloaded")
async def manual_crop_downloaded_label(data: dict):
    """
    Crop downloaded label image using exact pixel coordinates from manual selection.
    Crops label_download.jpg and saves as label_download_cropped.jpg.
    """
    from ...app import core_config
    from ....core.models import BottleMetadata
    from pathlib import Path
    from PIL import Image

    try:
        bottle_data = data.get("bottle")
        x = data.get("x")
        y = data.get("y")
        width = data.get("width")
        height = data.get("height")

        if not bottle_data or x is None or y is None or width is None or height is None:
            raise HTTPException(status_code=400, detail="Missing data or coordinates")

        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(bottle_data)
        bottle = BottleMetadata(**cleaned_bottle_data)

        if not bottle.vault_path:
            raise HTTPException(status_code=400, detail="Bottle has no vault path")

        # Use /tmp for intermediate files
        temp_dir = get_temp_label_dir(bottle.vault_path)
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
@router.post("/api/v1/management/labels/scan")
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


@router.post("/api/v1/management/labels/accept")
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


@router.post("/api/v1/management/labels/keep")
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


@router.get("/api/v1/labels/view")
async def view_label_image(path: str):
    """
    Serve a label image for viewing.

    Args:
        path: Path to label image

    Returns:
        FileResponse: The image file
    """
    from pathlib import Path

    try:
        image_path = Path(path)

        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        # Security check - ensure path is within vault or temp directory
        # (prevents directory traversal attacks)
        from ...app import core_config
        vault_path = core_config.vault_path
        temp_path = Path("/tmp/reserve-automation")

        resolved_path = image_path.resolve()
        is_in_vault = False
        is_in_temp = False

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
            media_type="image/jpeg" if image_path.suffix.lower() == ".jpg" else "image/png"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve label image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
