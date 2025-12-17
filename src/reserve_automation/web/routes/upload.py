"""Upload endpoints."""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Response, Cookie, HTTPException, Request
from fastapi.templating import Jinja2Templates
from loguru import logger
from sse_starlette.sse import EventSourceResponse

from ..sessions import SessionManager
from ..services.upload_service import UploadService
from ..services.extraction_service import ExtractionService

router = APIRouter()

# Templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


@router.get("/upload", include_in_schema=False)
async def upload_page(request: Request):
    """Serve the unified upload page."""
    return templates.TemplateResponse("upload.html", {"request": request})


@router.get("/review-bottles/{extraction_id}", include_in_schema=False)
async def review_bottles_page(extraction_id: str, request: Request):
    """Serve the bottle review page."""
    return templates.TemplateResponse("review_bottles.html", {"request": request})


@router.post("/api/v1/upload")
async def upload_file(
    response: Response,
    file: UploadFile = File(...),
    upload_type: str = Form("tasting_card"),
    expected_count: Optional[int] = Form(None),
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """
    Upload and process an image.

    Args:
        response: FastAPI response for setting cookies
        file: Uploaded file
        upload_type: Type of upload (tasting_card, bottle_label, auto)
        session_token: Existing session token (if any)

    Returns:
        Upload result with extraction_id
    """
    from ..app import upload_service, core_config, web_config

    if not upload_service or not core_config or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    logger.info(f"Processing upload: {file.filename} (type: {upload_type})")

    try:
        # Generate session ID
        session_id = str(uuid.uuid4())

        # Save uploaded file
        file_path = await upload_service.save_upload(file, session_id)
        logger.info(f"Saved upload to: {file_path}")

        # Extract data based on upload type
        extraction_service = ExtractionService(core_config)

        if upload_type in ["tasting_card", "auto"]:
            # Extract tasting notes
            extraction_result = await extraction_service.extract_tasting_card(
                image_path=file_path,
                template_type=None  # Auto-detect
            )

            # Serialize extraction result for session
            extraction_data = extraction_service.to_dict(extraction_result)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported upload_type: {upload_type}"
            )

        # Create session with extraction data
        session_manager = SessionManager(
            secret_key=web_config.sessions.secret_key,
            max_age_hours=web_config.sessions.max_age_hours
        )

        session_data = {
            "extraction_id": session_id,
            "upload_filename": file.filename,
            "temp_file_path": str(file_path),
            "extraction_data": extraction_data,
            "expected_count": expected_count  # Store for new review page
        }

        session_token = session_manager.create_session(session_data)

        # Set session cookie
        response.set_cookie(
            key="session",
            value=session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            samesite="lax"
        )

        logger.info(f"Extraction complete: {session_id}")

        return {
            "status": "completed",
            "extraction_id": session_id,
            "tastings_count": len(extraction_result.tastings),
            "template_type": extraction_result.template_type
        }

    except Exception as e:
        logger.error(f"Upload processing failed: {e}", exc_info=True)
        # Clean up on error
        if 'session_id' in locals():
            upload_service.cleanup_session_files(session_id)
        raise HTTPException(status_code=500, detail=str(e))
