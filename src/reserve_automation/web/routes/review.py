"""Review and approval endpoints."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from loguru import logger
from pydantic import BaseModel

from ..auth.dependencies import require
from ..services.extraction_service import ExtractionService
from ..services.review_service import ReviewService
from ..sessions import SessionManager
from ..templating import make_templates

router = APIRouter(dependencies=[Depends(require("upload.access"))])


def _get_review_service():
    from ...db.engine import get_db
    from ...db.repositories.bottle_repo import SQLiteBottleRepository
    from ...db.repositories.tasting_repo import SQLiteTastingRepository
    db = next(get_db())
    return ReviewService(SQLiteBottleRepository(db), SQLiteTastingRepository(db))

# Templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = make_templates(templates_dir)


@router.get("/review/{extraction_id}", include_in_schema=False)
async def review_page(request: Request, extraction_id: str):
    """Serve the review page."""
    return templates.TemplateResponse(request, "review.html", {
        "extraction_id": extraction_id
    })


class UpdateExtractionRequest(BaseModel):
    """Request body for updating extraction data."""
    extraction_data: dict


@router.get("/api/v1/extractions/{extraction_id}")
async def get_extraction(
    extraction_id: str,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """
    Get extraction data for review.

    Args:
        extraction_id: Extraction ID
        session_token: Session token from cookie

    Returns:
        Extraction data
    """
    from ..app import core_config, web_config

    if not core_config or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    # Read session
    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Verify extraction ID matches
    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    # Get extraction data
    extraction_data = session_data.get("extraction_data")
    if not extraction_data:
        raise HTTPException(status_code=404, detail="No extraction data in session")

    # Get bottle match previews
    extraction_service = ExtractionService(core_config)
    review_service = _get_review_service()

    extraction_result = extraction_service.from_dict(extraction_data)
    match_previews = review_service.preview_matches(extraction_result)

    return {
        "extraction_id": extraction_id,
        "extraction_type": "tasting",
        "upload_filename": session_data.get("upload_filename"),
        "template_type": extraction_data.get("template_type"),
        "data": extraction_data,
        "match_previews": match_previews
    }


@router.put("/api/v1/extractions/{extraction_id}")
async def update_extraction(
    extraction_id: str,
    request: UpdateExtractionRequest,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """
    Update extraction data.

    Args:
        extraction_id: Extraction ID
        request: Update request with new extraction data
        response: FastAPI response for updating cookie
        session_token: Session token from cookie

    Returns:
        Success status
    """
    from ..app import web_config

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    # Read session
    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Verify extraction ID matches
    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    # Update extraction data in session
    new_token = session_manager.update_session(
        token=session_token,
        updates={"extraction_data": request.extraction_data}
    )

    if not new_token:
        raise HTTPException(status_code=500, detail="Failed to update session")

    # Update session cookie
    response.set_cookie(
        key="session",
        value=new_token,
        max_age=web_config.sessions.max_age_hours * 3600,
        httponly=True,
        secure=True,
        samesite="lax"
    )

    logger.info(f"Updated extraction data for {extraction_id}")

    return {"status": "updated"}


@router.post("/api/v1/review/{extraction_id}/approve")
async def approve_extraction(
    extraction_id: str,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """
    Approve extraction and save to Obsidian vault.

    Args:
        extraction_id: Extraction ID
        response: FastAPI response for clearing cookie
        session_token: Session token from cookie

    Returns:
        Approval results
    """
    from ..app import core_config, upload_service, web_config

    if not upload_service or not core_config or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    # Read session
    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Verify extraction ID matches
    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    try:
        # Get extraction data
        extraction_data = session_data.get("extraction_data")
        if not extraction_data:
            raise HTTPException(status_code=404, detail="No extraction data")

        # Convert back to extraction result
        extraction_service = ExtractionService(core_config)
        extraction_result = extraction_service.from_dict(extraction_data)

        # Approve and save to vault
        review_service = _get_review_service()
        approval_result = await review_service.approve_extraction(extraction_result)

        # Clean up temp files
        upload_service.cleanup_session_files(extraction_id)

        # Clear session cookie
        response.delete_cookie(key="session")

        logger.info(
            f"Approved extraction {extraction_id}: "
            f"{len(approval_result['files_created'])} files created"
        )

        return {
            "status": "approved",
            **approval_result
        }

    except Exception as e:
        logger.error(f"Approval failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/review/{extraction_id}/reject")
async def reject_extraction(
    extraction_id: str,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """
    Reject extraction and clean up.

    Args:
        extraction_id: Extraction ID
        response: FastAPI response for clearing cookie
        session_token: Session token from cookie

    Returns:
        Rejection status
    """
    from ..app import upload_service, web_config

    if not upload_service or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    # Read session
    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Verify extraction ID matches
    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    # Clean up temp files
    upload_service.cleanup_session_files(extraction_id)

    # Clear session cookie
    response.delete_cookie(key="session")

    logger.info(f"Rejected extraction {extraction_id}")

    return {
        "status": "rejected",
        "message": "Extraction rejected and temp files deleted"
    }
