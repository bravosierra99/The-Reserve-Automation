"""Bottle upload and extraction endpoints - STATELESS (no sessions)."""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Request, Cookie
from ...auth.dependencies import require
from fastapi.templating import Jinja2Templates
from loguru import logger

from ...services.upload_service import UploadService
from ...services.extraction_service import ExtractionService
from ...sessions import SessionManager

router = APIRouter()

# Templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


@router.post("/api/v1/bottles/upload", dependencies=[Depends(require("bottles.create"))])
async def upload_bottle(
    file: UploadFile = File(...),
    upload_type: str = Form("bottle_image"),  # bottle_image or manifest
    beverage_type: str = Form("auto"),  # wine, whiskey, auto
    expected_count: Optional[int] = Form(None),  # Expected bottle count (optional)
    purchase_source: Optional[str] = Form(None),  # Where bottle was purchased
    inventory: int = Form(0),  # Number of bottles in inventory
):
    """
    Upload and extract bottle data from image or manifest.

    NO SESSIONS - Returns JSON with bottle data directly.
    Frontend stores in client-side state (Alpine.js).

    Args:
        file: Uploaded file
        upload_type: Type of upload (bottle_image or manifest)
        beverage_type: Type of beverage (wine, whiskey, auto)
        expected_count: Expected number of bottles (helps improve extraction accuracy)
        purchase_source: Where the bottle was purchased
        inventory: Number of bottles in inventory (default 0)

    Returns:
        {
            "upload_id": str,  # For temp file management
            "bottles": [...]    # Array of BottleMetadata objects as JSON
            "is_manifest": bool
        }
    """
    from ...app import upload_service, core_config

    if not upload_service or not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    logger.info(f"Processing bottle upload: {file.filename} (type: {upload_type}, beverage: {beverage_type}, expected_count: {expected_count})")

    try:
        # Generate upload ID for temp file management
        upload_id = str(uuid.uuid4())

        # Save uploaded file to /tmp/upload_{upload_id}/
        file_path = await upload_service.save_upload(file, upload_id)
        logger.info(f"Saved upload to: {file_path}")

        # Copy uploaded image to labels/label.jpg for display in modal
        from pathlib import Path
        import shutil
        upload_dir = Path(file_path).parent
        labels_dir = upload_dir / "labels"
        labels_dir.mkdir(exist_ok=True)

        # Copy the uploaded file as label.jpg
        label_path = labels_dir / "label.jpg"
        shutil.copy(file_path, label_path)
        logger.info(f"Copied label to: {label_path}")

        # Extract data based on upload type
        extraction_service = ExtractionService(core_config)

        if upload_type == "bottle_image":
            # Extract from single bottle label image
            bottle, extraction_meta = await extraction_service.extract_bottle_from_image(
                image_path=file_path,
                beverage_type=beverage_type
            )

            # Apply purchase info
            if purchase_source:
                bottle.purchase_source = purchase_source
            bottle.inventory = inventory

            bottles = [extraction_service.bottle_to_dict(bottle)]

        elif upload_type == "manifest":
            # Extract multiple bottles from manifest
            extracted_bottles = await extraction_service.extract_bottles_from_manifest(
                file_path=file_path,
                beverage_type=beverage_type,
                expected_count=expected_count
            )

            # Apply purchase info to all bottles
            for bottle in extracted_bottles:
                if purchase_source:
                    bottle.purchase_source = purchase_source
                bottle.inventory = inventory

            bottles = [extraction_service.bottle_to_dict(bottle) for bottle in extracted_bottles]

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported upload_type: {upload_type}"
            )

        logger.info(f"Extraction complete: {upload_id}, {len(bottles)} bottle(s)")

        # Return JSON directly - NO sessions!
        return {
            "upload_id": upload_id,
            "bottles": bottles,
            "is_manifest": upload_type == "manifest"
        }

    except Exception as e:
        logger.error(f"Bottle upload processing failed: {e}", exc_info=True)
        # Clean up on error
        if 'session_id' in locals():
            upload_service.cleanup_session_files(session_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/bottles/search", dependencies=[Depends(require("bottles.view"))])
async def search_bottles(
    q: str,
    beverage_type: Optional[str] = None,
    limit: int = 10,
    event_id: Optional[str] = None
):
    """
    Search for bottles in the vault.

    This is a read-only endpoint that searches the user's local vault.
    No authentication required - the vault is already accessible to anyone
    using the web interface (it's their own data).

    Args:
        q: Search query string
        beverage_type: Optional filter (whiskey, wine, spirit)
        limit: Maximum results to return
        event_id: Optional event ID (restricts to event bottles only)
    """
    from ....db.engine import get_db
    from ....db.repositories.bottle_repo import SQLiteBottleRepository
    from ....db.repositories.tasting_repo import SQLiteTastingRepository
    from ...services.tasting_service import TastingService

    db = next(get_db())
    tasting_service = TastingService(SQLiteBottleRepository(db), SQLiteTastingRepository(db))
    results = tasting_service.search_bottles(
        query=q,
        beverage_type=beverage_type,
        limit=limit,
        event_id=event_id
    )

    return {
        "query": q,
        "results": [r.model_dump() for r in results]
    }


# Removed deprecated session-based endpoint /api/v1/bottles/{extraction_id}
# The new stateless bottle upload returns data directly as JSON
# Frontend stores in Alpine.js client-side state (no session lookup needed)


