"""Routes for tasting upload and review workflow."""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter,
    Cookie,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.templating import Jinja2Templates
from loguru import logger
from pydantic import BaseModel

from ..auth.dependencies import require
from ..schemas.tasting import (
    ManualTastingMode,
    SaveManualTastingRequest,
    SelectMatchRequest,
    TastingSession,
    TastingSessionItem,
    TastingStatus,
)
from ..services.extraction_service import ExtractionService
from ..services.tasting_service import TastingService
from ..sessions import SessionManager  # Still used for extraction workflow

# ACCEPTED RISK: No rate limiting on this router.
# LLM-touching endpoints (upload-card) require "tastings.submit" which is
# admin+family only — a small, trusted set of users. Guests cannot reach
# any endpoint in this router (router-level "tastings.view" gates all of them).
router = APIRouter(dependencies=[Depends(require("tastings.view"))])

# The manual-tasting wizard doubles as the EVENT participant capture UI, so it
# is gated at "events.participate" (includes guests). Non-event (Obsidian)
# saves re-check "tastings.submit" inside the handler, and the only LLM-touching
# endpoint the wizard uses (upload-card) stays admin+family on the router above.
participant_router = APIRouter(dependencies=[Depends(require("events.participate"))])

# Templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


def _get_tasting_service():
    """Create a DB-backed TastingService."""
    from ...db.engine import get_db
    from ...db.repositories.bottle_repo import SQLiteBottleRepository
    from ...db.repositories.tasting_repo import SQLiteTastingRepository
    db = next(get_db())
    return TastingService(SQLiteBottleRepository(db), SQLiteTastingRepository(db))


# ============================================================================
# Page Routes
# ============================================================================

@router.get("/review-tastings/{extraction_id}", include_in_schema=False)
async def review_tastings_page(request: Request, extraction_id: str):
    """Serve the new tasting review page."""
    return templates.TemplateResponse(request, "review_tastings.html", {
        "extraction_id": extraction_id
    })


# ============================================================================
# API Routes - Session Management
# ============================================================================

@router.get("/api/v1/tastings/{extraction_id}")
async def get_tasting_session(
    extraction_id: str,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """
    Get the current tasting session state.

    Returns the full session with all tastings, match candidates, and stats.
    """
    from ..app import core_config, web_config

    if not core_config or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    # Get or create tasting session
    tasting_session = session_data.get("tasting_session")
    if not tasting_session:
        logger.info("No tasting_session in session data, creating from extraction_data")
        # Convert old-style extraction data to new session format
        extraction_data = session_data.get("extraction_data")
        if not extraction_data:
            logger.error(f"No extraction_data in session for {extraction_id}")
            raise HTTPException(status_code=404, detail="No extraction data in session")

        try:
            logger.debug("Converting extraction_data to TastingExtractionResult")
            extraction_service = ExtractionService(core_config)
            extraction_result = extraction_service.from_dict(extraction_data)
            logger.debug(f"Successfully converted extraction_data, got {len(extraction_result.tastings)} tastings")

            logger.debug("Creating tasting session from extraction")
            tasting_service = _get_tasting_service()
            tasting_session = tasting_service.create_session_from_extraction(
                extraction_id=extraction_id,
                extraction_result=extraction_result,
                expected_count=session_data.get("expected_count"),
                upload_filename=session_data.get("upload_filename"),
                event_id=session_data.get("event_id")
            )
            logger.debug("Successfully created tasting session")

            # Store back to session (we'll update below)
            logger.debug("Converting tasting session to dict for storage")
            tasting_session = tasting_session.model_dump(mode='json')
            logger.debug("Successfully converted tasting session to dict")

            # Save the new tasting session to the cookie
            logger.info("Saving tasting session to cookie")
            new_token = session_manager.update_session(
                token=session_token,
                updates={"tasting_session": tasting_session}
            )
            if new_token:
                logger.info("Generated new token, setting cookie")
                response.set_cookie(
                    key="session",
                    value=new_token,
                    max_age=web_config.sessions.max_age_hours * 3600,
                    httponly=True,
                    samesite="lax"
                )
                logger.info("Successfully saved tasting session to cookie")
            else:
                logger.error("Failed to generate new token when updating session with tasting_session")
        except Exception as e:
            logger.error(f"Failed to create tasting session from extraction: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")

    # Get stats
    try:
        logger.debug("Getting session stats")
        tasting_service = _get_tasting_service()
        session_obj = TastingSession(**tasting_session) if isinstance(tasting_session, dict) else tasting_session
        stats = tasting_service.get_session_stats(session_obj)
        logger.debug(f"Successfully got stats: {stats}")

        # Find current index (first non-approved/skipped tasting)
        current_index = 0
        tastings = tasting_session.get("tastings", []) if isinstance(tasting_session, dict) else tasting_session.tastings
        for i, t in enumerate(tastings):
            status = t.get("status") if isinstance(t, dict) else t.status
            if status not in [TastingStatus.APPROVED.value, TastingStatus.SKIPPED.value, TastingStatus.APPROVED, TastingStatus.SKIPPED]:
                current_index = i
                break
        logger.debug(f"Current index: {current_index}")

        response_data = {
            "extraction_id": extraction_id,
            "beverage_type": tasting_session.get("beverage_type") if isinstance(tasting_session, dict) else tasting_session.beverage_type,
            "template_type": tasting_session.get("template_type") if isinstance(tasting_session, dict) else tasting_session.template_type,
            "expected_count": tasting_session.get("expected_count") if isinstance(tasting_session, dict) else tasting_session.expected_count,
            "actual_count": tasting_session.get("actual_count") if isinstance(tasting_session, dict) else tasting_session.actual_count,
            "count_mismatch": tasting_session.get("count_mismatch") if isinstance(tasting_session, dict) else tasting_session.count_mismatch,
            "current_index": current_index,
            "tastings": tastings,
            "stats": stats
        }
        logger.debug("Successfully built response data")
        logger.debug("=== RETURNING TASTING SESSION ===")
        logger.debug(f"Number of tastings: {len(tastings)}")
        if tastings and len(tastings) > 0:
            first_tasting = tastings[0]
            logger.debug(f"First tasting type: {type(first_tasting)}")
            if isinstance(first_tasting, dict):
                logger.debug(f"First tasting keys: {first_tasting.keys()}")
                logger.debug(f"First tasting match_candidates: {len(first_tasting.get('match_candidates', []))} items")
                logger.debug(f"First tasting selected_match: {first_tasting.get('selected_match')}")
            else:
                logger.debug(f"First tasting: {first_tasting}")
        return response_data
    except Exception as e:
        logger.error(f"Failed to build response: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build response: {str(e)}")


@router.get("/api/v1/tastings/{extraction_id}/{index}")
async def get_single_tasting(
    extraction_id: str,
    index: int,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Get a single tasting by index."""
    from ..app import web_config

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    tasting_session = session_data.get("tasting_session")
    if not tasting_session:
        raise HTTPException(status_code=404, detail="No tasting session")

    tastings = tasting_session.get("tastings", [])
    if index < 0 or index >= len(tastings):
        raise HTTPException(status_code=404, detail="Tasting index out of range")

    return tastings[index]


# ============================================================================
# API Routes - Tasting Updates
# ============================================================================

class UpdateTastingDataRequest(BaseModel):
    """Request to update tasting data fields."""
    tasting_data: dict


@router.put("/api/v1/tastings/{extraction_id}/{index}", dependencies=[Depends(require("tastings.submit"))])
async def update_tasting(
    extraction_id: str,
    index: int,
    request: UpdateTastingDataRequest,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Update a single tasting's data."""
    from ..app import web_config

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    tasting_session = session_data.get("tasting_session")
    if not tasting_session:
        raise HTTPException(status_code=404, detail="No tasting session")

    tastings = tasting_session.get("tastings", [])
    if index < 0 or index >= len(tastings):
        raise HTTPException(status_code=404, detail="Tasting index out of range")

    # Update tasting data
    tastings[index]["tasting_data"] = request.tasting_data
    tasting_session["tastings"] = tastings

    # Save back to session
    new_token = session_manager.update_session(
        token=session_token,
        updates={"tasting_session": tasting_session}
    )

    if not new_token:
        raise HTTPException(status_code=500, detail="Failed to update session")

    response.set_cookie(
        key="session",
        value=new_token,
        max_age=web_config.sessions.max_age_hours * 3600,
        httponly=True,
        secure=True,
        samesite="lax"
    )

    logger.info(f"Updated tasting {index} data for {extraction_id}")
    return {"status": "updated", "tasting": tastings[index]}


@router.post("/api/v1/tastings/{extraction_id}/{index}/match", dependencies=[Depends(require("tastings.submit"))])
async def select_match(
    extraction_id: str,
    index: int,
    request: SelectMatchRequest,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Select a bottle match for a tasting."""
    from ..app import web_config

    logger.debug("=== SELECT MATCH ENDPOINT ===")
    logger.debug(f"extraction_id: {extraction_id}, index: {index}, bottle_path: {request.bottle_path}")

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        logger.error("No session token")
        raise HTTPException(status_code=401, detail="No active session")

    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        logger.error("Invalid session")
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if session_data.get("extraction_id") != extraction_id:
        logger.error(f"Extraction ID mismatch: {session_data.get('extraction_id')} != {extraction_id}")
        raise HTTPException(status_code=404, detail="Extraction not found")

    tasting_session = session_data.get("tasting_session")
    if not tasting_session:
        logger.error("No tasting session in session data")
        raise HTTPException(status_code=404, detail="No tasting session")

    tastings = tasting_session.get("tastings", [])
    logger.debug(f"Session has {len(tastings)} tastings")
    if index < 0 or index >= len(tastings):
        logger.error(f"Index {index} out of range (0-{len(tastings)-1})")
        raise HTTPException(status_code=404, detail="Tasting index out of range")

    logger.debug(f"Tasting before update: {tastings[index].get('selected_match')}")

    # Update selected match
    tastings[index]["selected_match"] = request.bottle_path
    tastings[index]["status"] = TastingStatus.MATCHED.value

    logger.debug(f"Tasting after update: {tastings[index].get('selected_match')}")

    # Check for duplicate
    tasting_service = _get_tasting_service()
    tasting_data = tastings[index].get("tasting_data", {})
    duplicate_warning = tasting_service.check_duplicate_tasting(
        bottle_path=request.bottle_path,
        taster=tasting_data.get("taster_name", ""),
        tasting_date=tasting_data.get("tasting_date", "")
    )
    tastings[index]["duplicate_warning"] = duplicate_warning

    tasting_session["tastings"] = tastings

    # Save back to session
    new_token = session_manager.update_session(
        token=session_token,
        updates={"tasting_session": tasting_session}
    )

    if not new_token:
        raise HTTPException(status_code=500, detail="Failed to update session")

    response.set_cookie(
        key="session",
        value=new_token,
        max_age=web_config.sessions.max_age_hours * 3600,
        httponly=True,
        secure=True,
        samesite="lax"
    )

    logger.info(f"Selected match for tasting {index}: {request.bottle_path}")
    return {
        "status": "matched",
        "selected_match": request.bottle_path,
        "duplicate_warning": duplicate_warning
    }


# ============================================================================
# API Routes - Approve/Skip
# ============================================================================

@router.post("/api/v1/tastings/{extraction_id}/{index}/approve", dependencies=[Depends(require("tastings.submit"))])
async def approve_tasting(
    extraction_id: str,
    index: int,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Approve and save a single tasting."""
    from ..app import upload_service, web_config

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    tasting_session = session_data.get("tasting_session")
    if not tasting_session:
        raise HTTPException(status_code=404, detail="No tasting session")

    tastings = tasting_session.get("tastings", [])
    if index < 0 or index >= len(tastings):
        raise HTTPException(status_code=404, detail="Tasting index out of range")

    tasting_item = tastings[index]
    selected_match = tasting_item.get("selected_match")

    if not selected_match:
        raise HTTPException(status_code=400, detail="No bottle selected for this tasting")

    # Save the tasting
    tasting_service = _get_tasting_service()

    # Get event context if present
    event_id = session_data.get("event_id")
    participant_id = session_data.get("participant_id")

    # Convert dict to TastingSessionItem
    session_item = TastingSessionItem(**tasting_item)
    success, file_path, error = await tasting_service.save_tasting(
        session_item,
        selected_match,
        event_id=event_id,
        participant_id=participant_id
    )

    if not success:
        raise HTTPException(status_code=500, detail=f"Failed to save tasting: {error}")

    # Mark as approved
    tastings[index]["status"] = TastingStatus.APPROVED.value
    tasting_session["tastings"] = tastings

    # Check if all done
    stats = tasting_service.get_session_stats(TastingSession(**tasting_session))

    # If all done, clean up
    if stats["all_done"]:
        if upload_service:
            upload_service.cleanup_session_files(extraction_id)
        response.delete_cookie(key="session")
        logger.info(f"All tastings processed for {extraction_id}, session cleaned up")
    else:
        # Save back to session
        new_token = session_manager.update_session(
            token=session_token,
            updates={"tasting_session": tasting_session}
        )

        if new_token:
            response.set_cookie(
                key="session",
                value=new_token,
                max_age=web_config.sessions.max_age_hours * 3600,
                httponly=True,
                samesite="lax"
            )

    logger.info(f"Approved tasting {index} for {extraction_id}")
    return {
        "status": "approved",
        "file_created": file_path,
        "stats": stats
    }


@router.post("/api/v1/tastings/{extraction_id}/{index}/skip", dependencies=[Depends(require("tastings.submit"))])
async def skip_tasting(
    extraction_id: str,
    index: int,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Skip a single tasting without saving."""
    from ..app import upload_service, web_config

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    tasting_session = session_data.get("tasting_session")
    if not tasting_session:
        raise HTTPException(status_code=404, detail="No tasting session")

    tastings = tasting_session.get("tastings", [])
    if index < 0 or index >= len(tastings):
        raise HTTPException(status_code=404, detail="Tasting index out of range")

    # Mark as skipped
    tastings[index]["status"] = TastingStatus.SKIPPED.value
    tasting_session["tastings"] = tastings

    # Check if all done
    tasting_service = _get_tasting_service()
    stats = tasting_service.get_session_stats(TastingSession(**tasting_session))

    # If all done, clean up
    if stats["all_done"]:
        if upload_service:
            upload_service.cleanup_session_files(extraction_id)
        response.delete_cookie(key="session")
        logger.info(f"All tastings processed for {extraction_id}, session cleaned up")
    else:
        # Save back to session
        new_token = session_manager.update_session(
            token=session_token,
            updates={"tasting_session": tasting_session}
        )

        if new_token:
            response.set_cookie(
                key="session",
                value=new_token,
                max_age=web_config.sessions.max_age_hours * 3600,
                httponly=True,
                samesite="lax"
            )

    logger.info(f"Skipped tasting {index} for {extraction_id}")
    return {
        "status": "skipped",
        "stats": stats
    }


@router.post("/api/v1/tastings/{extraction_id}/reject-all", dependencies=[Depends(require("tastings.submit"))])
async def reject_all_tastings(
    extraction_id: str,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Reject all tastings and clean up."""
    from ..app import upload_service, web_config

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    # Clean up
    if upload_service:
        upload_service.cleanup_session_files(extraction_id)

    response.delete_cookie(key="session")

    logger.info(f"Rejected all tastings for {extraction_id}")
    return {"status": "rejected"}


# ============================================================================
# API Routes - Re-extraction
# ============================================================================
# NOTE: Bottle search endpoint moved to bottles.py to fix route ordering issue

@router.post("/api/v1/tastings/{extraction_id}/refresh-matches")
async def refresh_matches(
    extraction_id: str,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Re-run bottle matching for all tastings in the session."""
    from ..app import web_config

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    if session_data.get("extraction_id") != extraction_id:
        raise HTTPException(status_code=404, detail="Extraction not found")

    tasting_session = session_data.get("tasting_session")
    if not tasting_session:
        raise HTTPException(status_code=404, detail="No tasting session")

    tasting_service = _get_tasting_service()
    tastings = tasting_session.get("tastings", [])

    # Re-run matching for each tasting that hasn't been approved
    for i, tasting in enumerate(tastings):
        status = tasting.get("status")
        if status in [TastingStatus.APPROVED.value, TastingStatus.APPROVED]:
            continue

        tasting_data = tasting.get("tasting_data", {})
        candidates = tasting_service.get_match_candidates(
            bottle_name=tasting_data.get("bottle_name", ""),
            beverage_type=tasting_data.get("beverage_type", "wine"),
            limit=5
        )

        tastings[i]["match_candidates"] = [c.model_dump() for c in candidates]

        # Auto-select if high confidence
        if candidates and candidates[0].confidence >= 0.8:
            tastings[i]["selected_match"] = candidates[0].bottle_path
            tastings[i]["status"] = TastingStatus.MATCHED.value
        else:
            tastings[i]["selected_match"] = None
            tastings[i]["status"] = TastingStatus.EXTRACTED.value

    tasting_session["tastings"] = tastings

    # Save back to session
    new_token = session_manager.update_session(
        token=session_token,
        updates={"tasting_session": tasting_session}
    )

    if not new_token:
        raise HTTPException(status_code=500, detail="Failed to update session")

    response.set_cookie(
        key="session",
        value=new_token,
        max_age=web_config.sessions.max_age_hours * 3600,
        httponly=True,
        secure=True,
        samesite="lax"
    )

    logger.info(f"Refreshed matches for {extraction_id}")
    return {"status": "refreshed", "tastings": tastings}


# ============================================================================
# Tasting Card Upload (accessible to family + admin via tastings.submit)
# ============================================================================


@router.post("/api/v1/tastings/upload-card", dependencies=[Depends(require("tastings.submit"))])
async def upload_tasting_card(
    response: Response,
    request: Request,
    file: UploadFile = File(...),
    expected_count: Optional[int] = Form(None),
):
    """
    Upload a tasting card image for extraction.

    This endpoint is separate from /api/v1/upload so that family members
    (who have tastings.submit but not upload.access) can upload tasting cards.
    """
    from ..app import core_config, upload_service, web_config

    if not upload_service or not core_config or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    logger.info(f"Processing tasting card upload: {file.filename}")

    try:
        session_id = str(uuid.uuid4())

        # Save uploaded file
        file_path = await upload_service.save_upload(file, session_id)
        logger.info(f"Saved tasting card upload to: {file_path}")

        # Extract tasting notes
        extraction_service = ExtractionService(core_config)
        extraction_result = await extraction_service.extract_tasting_card(
            image_path=file_path,
            template_type=None  # Auto-detect
        )

        extraction_data = extraction_service.to_dict(extraction_result)

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
            "expected_count": expected_count,
        }

        session_token = session_manager.create_session(session_data)

        response.set_cookie(
            key="session",
            value=session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            samesite="lax"
        )

        logger.info(f"Tasting card extraction complete: {session_id}")

        return {
            "status": "completed",
            "extraction_id": session_id,
            "tastings_count": len(extraction_result.tastings),
            "template_type": extraction_result.template_type,
        }

    except Exception as e:
        logger.error(f"Tasting card upload failed: {e}", exc_info=True)
        if 'session_id' in locals():
            upload_service.cleanup_session_files(session_id)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Manual Tasting (Sessionless - frontend manages wizard state)
# ============================================================================


@participant_router.get("/manual-tasting", include_in_schema=False)
async def manual_tasting_page(request: Request):
    """Serve manual tasting wizard page."""
    return templates.TemplateResponse(request, "manual_tasting.html")


@participant_router.post("/api/v1/manual-tasting/save")
async def save_manual_tasting(
    request_data: SaveManualTastingRequest,
    request: Request,
):
    """
    Save a manual tasting.

    All wizard state is managed in the frontend (Alpine.js).
    This endpoint just receives the complete data and saves it.
    No server-side session needed.
    """
    from ...db.engine import get_db
    from ...db.repositories.bottle_repo import SQLiteBottleRepository
    from ...db.repositories.event_repo import SQLiteEventRepository

    try:
        db = next(get_db())
        bottle_repo = SQLiteBottleRepository(db)

        # Resolve bottle ID to path if needed
        selected_bottle_path = request_data.selected_bottle_path
        if not selected_bottle_path and request_data.selected_bottle_id:
            bottle = bottle_repo.get_by_id(int(request_data.selected_bottle_id))
            if not bottle:
                raise HTTPException(status_code=404, detail=f"Bottle not found for ID: {request_data.selected_bottle_id}")
            selected_bottle_path = str(request_data.selected_bottle_id)

        # Validate required fields
        if not request_data.taster_name:
            raise HTTPException(status_code=400, detail="Taster name is required")
        if not request_data.tasting_date:
            raise HTTPException(status_code=400, detail="Tasting date is required")
        if not selected_bottle_path and not request_data.selected_bottle_id:
            raise HTTPException(status_code=400, detail="Bottle selection is required (provide selected_bottle_id or selected_bottle_path)")

        # Save based on mode
        if request_data.mode == ManualTastingMode.OBSIDIAN:
            # Personal (non-event) tastings stay admin+family only; the router
            # gate is events.participate so guests can submit EVENT tastings.
            require("tastings.submit")(request)
            tasting_service = _get_tasting_service()
            success, file_path, error = await tasting_service.save_manual_tasting_direct(
                taster_name=request_data.taster_name,
                tasting_date=request_data.tasting_date,
                beverage_type=request_data.beverage_type,
                selected_bottle_path=selected_bottle_path,
                tasting_data=request_data.tasting_data,
            )

            if not success:
                raise HTTPException(status_code=500, detail=f"Failed to save tasting: {error}")

            logger.info(f"Saved manual tasting to Obsidian: {file_path}")
            return {"status": "saved", "file_path": str(file_path)}

        elif request_data.mode == ManualTastingMode.EVENT:
            # Validate event mode requirements
            if not request_data.event_id:
                raise HTTPException(status_code=400, detail="Event ID required for event mode")
            if not request_data.participant_id:
                raise HTTPException(status_code=400, detail="Participant ID required for event mode")

            event_repo = SQLiteEventRepository(db)
            event = event_repo.get_by_id(request_data.event_id)
            if not event:
                raise HTTPException(status_code=404, detail="Event not found")

            if request_data.participant_id not in event["participants"]:
                raise HTTPException(status_code=404, detail="Participant not found in event")

            # The selected_bottle_id IS the DB bottle ID now. The search API
            # returns that ID in the candidate's bottle_path field, and the
            # wizard sends it as selected_bottle_path — accept either.
            bottle_id = request_data.selected_bottle_id or selected_bottle_path
            if not bottle_id:
                raise HTTPException(status_code=400, detail="Bottle ID required for event mode")
            try:
                int(bottle_id)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid bottle ID for event mode: {bottle_id}")

            # Check if tasting already exists for this participant + bottle (for editing)
            existing_tasting = None
            from ...db.models.event import EventTastingModel
            existing_tasting = (
                db.query(EventTastingModel)
                .filter(
                    EventTastingModel.participant_id == request_data.participant_id,
                    EventTastingModel.bottle_id == int(bottle_id),
                )
                .first()
            )

            if existing_tasting:
                # Update existing tasting
                existing_tasting.tasting_data = request_data.tasting_data
                db.commit()
                logger.info(f"Updated tasting for bottle {bottle_id}")
            else:
                # Add new tasting via repo
                event_repo.add_tasting(
                    participant_id=request_data.participant_id,
                    tasting_data={
                        "bottle_id": bottle_id,
                        "tasting_data": request_data.tasting_data,
                    },
                )
                logger.info(f"Added new tasting for bottle {bottle_id}")

            logger.info(f"Saved manual tasting to event {request_data.event_id}")
            return {"status": "saved", "event_id": request_data.event_id}

        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {request_data.mode}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to save manual tasting", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
