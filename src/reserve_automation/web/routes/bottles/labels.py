"""Label operations for upload workflow (temp files)."""

import io
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from loguru import logger
from PIL import Image, ImageOps
from pydantic import BaseModel

from ...auth.dependencies import require

router = APIRouter(dependencies=[Depends(require("bottles.create"))])


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


class ManualCropTempRequest(BaseModel):
    """Request to manually crop a temporary label."""
    upload_id: str
    label_index: int = 0  # For manifest uploads with multiple bottles
    x: int
    y: int
    width: int
    height: int


class AutoCropTempRequest(BaseModel):
    """Request to auto-crop a temporary label (upload workflow)."""
    upload_id: str
    label_index: int = 0  # For manifest uploads with multiple bottles


def _resolve_temp_label(upload_id: str, label_index: int) -> Path:
    """Locate the temp label image for an upload, raising 4xx if absent.

    Shared by the manual and auto crop temp endpoints. Validates upload_id
    against path traversal and falls back from {index}.jpg to label.jpg.
    """
    if not upload_id or "/" in upload_id or ".." in upload_id:
        raise HTTPException(status_code=400, detail="Invalid upload_id")

    temp_labels_dir = Path("/tmp/reserve_uploads") / upload_id / "labels"
    if not temp_labels_dir.exists():
        raise HTTPException(status_code=404, detail="Temp labels directory not found")

    source_label = temp_labels_dir / f"{label_index}.jpg"
    if not source_label.exists():
        source_label = temp_labels_dir / "label.jpg"
    if not source_label.exists():
        raise HTTPException(status_code=404, detail=f"Temp label not found at index {label_index}")
    return source_label


@router.post("/api/v1/bottles/auto-crop-temp")
async def auto_crop_temp_label(request: AutoCropTempRequest):
    """Auto-crop a temporary uploaded label (upload workflow).

    Upload-mode analogue of management's crop-current. Because the upload flow
    has no committed label yet, this mirrors manual-crop-temp: it runs the
    LLM/CV label detection directly on /tmp/reserve_uploads/{upload_id}/labels/
    label.jpg and overwrites it in place (no separate preview/accept step). The
    modal refreshes its cache-busted temp preview on success.
    """
    from ....llm.gateway import LLMGateway
    from ....utils.label_processor import LabelImageProcessor
    from ...app import core_config

    if not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    source_label = _resolve_temp_label(request.upload_id, request.label_index)

    try:
        logger.info(f"Auto-crop temp: {source_label}")
        processor = LabelImageProcessor(LLMGateway(core_config.llm))
        # crop_to_label normalizes EXIF, auto-detects the label bounds, and
        # overwrites source_label with the crop (or returns None on failure).
        result = processor.crop_to_label(source_label)
        if not result:
            raise HTTPException(status_code=500, detail="Auto-crop failed to detect a label")

        return {
            "status": "success",
            "cropped_path": str(source_label),
            "message": "Label auto-cropped successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Auto-crop temp failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/manual-crop-temp")
async def manual_crop_temp_label(request: ManualCropTempRequest):
    """
    Manual crop for temporary uploaded label (upload workflow).

    Workflow:
    1. Load temp label from /tmp/reserve_uploads/{upload_id}/labels/{label_index}.jpg
    2. Apply EXIF normalization (fixes rotated iPhone photos)
    3. Crop using PIL with exact pixel coordinates
    4. Save as /tmp/reserve_uploads/{upload_id}/labels/{label_index}_cropped.jpg
    5. Return cropped path for preview

    Args:
        request: Crop request with upload_id, label_index, and crop coordinates

    Returns:
        {
            "status": "success",
            "cropped_path": str,
            "message": "Label cropped successfully"
        }
    """
    try:
        # Validate upload_id (basic security check)
        if not request.upload_id or "/" in request.upload_id or ".." in request.upload_id:
            raise HTTPException(status_code=400, detail="Invalid upload_id")

        # Construct temp label path
        temp_labels_dir = Path("/tmp/reserve_uploads") / request.upload_id / "labels"

        if not temp_labels_dir.exists():
            raise HTTPException(status_code=404, detail="Temp labels directory not found")

        # Determine source label path
        source_label = temp_labels_dir / f"{request.label_index}.jpg"

        # Also check for alternative names
        if not source_label.exists():
            source_label = temp_labels_dir / "label.jpg"

        if not source_label.exists():
            raise HTTPException(status_code=404, detail=f"Temp label not found at index {request.label_index}")

        logger.info(f"Manual crop temp: {source_label}")
        logger.info(f"  Crop coordinates: x={request.x}, y={request.y}, w={request.width}, h={request.height}")

        # Open image with PIL
        img = Image.open(source_label)

        # CRITICAL: Normalize EXIF orientation BEFORE cropping
        # This fixes issues with rotated photos from iPhones/cameras
        img = ImageOps.exif_transpose(img)
        logger.info(f"  Image size after EXIF normalization: {img.size}")

        # Ensure coordinates are within image bounds
        img_width, img_height = img.size
        x = max(0, min(request.x, img_width))
        y = max(0, min(request.y, img_height))
        width = min(request.width, img_width - x)
        height = min(request.height, img_height - y)

        logger.info(f"  Adjusted coordinates: x={x}, y={y}, w={width}, h={height}")

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

        # Save cropped image as label.jpg (replace the original)
        # This ensures the modal displays the cropped version after timestamp refresh
        cropped_path = temp_labels_dir / "label.jpg"
        cropped.save(cropped_path, "JPEG", quality=95)

        logger.info(f"  Saved cropped label: {cropped_path}")

        return {
            "status": "success",
            "cropped_path": str(cropped_path),
            "message": "Label cropped successfully"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Manual crop temp failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/upload-custom-label")
async def upload_custom_label_temp(
    file: UploadFile,
    upload_id: str = Form(),
    bottle: str = Form(None),
):
    """
    Upload a custom label during the new-bottle upload workflow (upload mode).

    The bottle has no DB id yet, so the label lives in the temp upload dir where
    upload-mode readers (serve_temp_image, manual-crop-temp) look for it:
    /tmp/reserve_uploads/{upload_id}/labels/label.jpg

    Single-step: the uploaded file becomes the label immediately, normalized and
    re-encoded to JPEG. The bottle's label is committed to MEDIA_DIR later when
    the bottle is saved.
    """
    try:
        # Validate upload_id (basic security check)
        if not upload_id or "/" in upload_id or ".." in upload_id:
            raise HTTPException(status_code=400, detail="Invalid upload_id")

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

        temp_labels_dir = Path("/tmp/reserve_uploads") / upload_id / "labels"
        temp_labels_dir.mkdir(parents=True, exist_ok=True)

        label_path = temp_labels_dir / "label.jpg"
        img.save(label_path, "JPEG", quality=95)

        logger.info(f"Custom label uploaded (upload mode): {label_path}")

        return {
            "status": "success",
            "message": "Custom label uploaded successfully",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Custom label upload (temp) failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/temp-images/{upload_id}/{filename}")
async def serve_temp_image(upload_id: str, filename: str):
    """
    Serve temporary image files for preview in upload workflow.

    Security:
    - Validates upload_id format
    - Only serves from /tmp/reserve_uploads/{upload_id}/labels/ directory
    - Prevents directory traversal attacks

    Args:
        upload_id: Upload session ID
        filename: Image filename (e.g., "label.jpg", "0.jpg", "0_cropped.jpg")

    Returns:
        Image file content
    """
    try:
        # Validate inputs (security)
        if not upload_id or "/" in upload_id or ".." in upload_id:
            raise HTTPException(status_code=400, detail="Invalid upload_id")

        if not filename or "/" in filename or ".." in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")

        # Construct safe path
        temp_labels_dir = Path("/tmp/reserve_uploads") / upload_id / "labels"
        image_path = temp_labels_dir / filename

        # Ensure path is within temp directory (prevent directory traversal)
        if not str(image_path.resolve()).startswith(str(temp_labels_dir.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")

        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        # Return image file
        from fastapi.responses import FileResponse
        return FileResponse(image_path)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Serve temp image failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/search-labels")
async def search_labels_for_bottle(request: Request):
    """
    Search for label images for a bottle (used by management interface).

    Uses the EXACT same label finding logic as the upload flow.

    Request body: BottleMetadata dict

    Returns:
        List of label image candidates
    """
    from ....core.models import BottleMetadata
    from ...app import core_config
    from ...services.extraction_service import ExtractionService
    from ...services.label_service import LabelService

    if not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get bottle data from request body
        bottle_data = await request.json()

        logger.info("=== LABEL SEARCH REQUEST ===")
        logger.info(f"Producer: {bottle_data.get('producer')}")
        logger.info(f"Name: {bottle_data.get('name')}")
        logger.info(f"Year: {bottle_data.get('year')}")
        logger.info(f"Variety: {bottle_data.get('variety')}")
        logger.info(f"Region: {bottle_data.get('region')}")
        logger.info(f"Vineyard: {bottle_data.get('vineyard')}")
        logger.info(f"Type: {bottle_data.get('type')}")

        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(bottle_data)

        # Convert to BottleMetadata
        bottle = BottleMetadata(**cleaned_bottle_data)

        # Find labels using LLM web search (SAME code as upload flow)
        extraction_service = ExtractionService(core_config)
        label_service = LabelService(extraction_service.llm_gateway)
        label_candidates = await label_service.find_labels(bottle)

        logger.info(f"Found {len(label_candidates)} label candidates")
        for i, candidate in enumerate(label_candidates[:3]):
            logger.info(f"  [{i+1}] {candidate.get('url')} from {candidate.get('source')}")

        return {"images": label_candidates}

    except Exception as e:
        logger.error(f"Failed to search labels: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
