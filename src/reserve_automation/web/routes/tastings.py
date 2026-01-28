"""Routes for tasting upload and review workflow."""

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Response, Request
from fastapi.templating import Jinja2Templates
from loguru import logger
from pydantic import BaseModel

from ..sessions import SessionManager  # Still used for extraction workflow
from ..services.extraction_service import ExtractionService
from ..services.tasting_service import TastingService
from ..schemas.tasting import (
    TastingStatus,
    TastingData,
    TastingSession,
    TastingSessionItem,
    SelectMatchRequest,
    SearchBottlesRequest,
    MatchCandidate,
    ManualTastingMode,
    SaveManualTastingRequest,
)

router = APIRouter()

# Templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


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
        logger.info(f"No tasting_session in session data, creating from extraction_data")
        # Convert old-style extraction data to new session format
        extraction_data = session_data.get("extraction_data")
        if not extraction_data:
            logger.error(f"No extraction_data in session for {extraction_id}")
            raise HTTPException(status_code=404, detail="No extraction data in session")

        try:
            logger.debug(f"Converting extraction_data to TastingExtractionResult")
            extraction_service = ExtractionService(core_config)
            extraction_result = extraction_service.from_dict(extraction_data)
            logger.debug(f"Successfully converted extraction_data, got {len(extraction_result.tastings)} tastings")

            logger.debug(f"Creating tasting session from extraction")
            tasting_service = TastingService(core_config)
            tasting_session = tasting_service.create_session_from_extraction(
                extraction_id=extraction_id,
                extraction_result=extraction_result,
                expected_count=session_data.get("expected_count"),
                upload_filename=session_data.get("upload_filename"),
                event_id=session_data.get("event_id")
            )
            logger.debug(f"Successfully created tasting session")

            # Store back to session (we'll update below)
            logger.debug(f"Converting tasting session to dict for storage")
            tasting_session = tasting_session.model_dump(mode='json')
            logger.debug(f"Successfully converted tasting session to dict")

            # Save the new tasting session to the cookie
            logger.info(f"Saving tasting session to cookie")
            new_token = session_manager.update_session(
                token=session_token,
                updates={"tasting_session": tasting_session}
            )
            if new_token:
                logger.info(f"Generated new token, setting cookie")
                response.set_cookie(
                    key="session",
                    value=new_token,
                    max_age=web_config.sessions.max_age_hours * 3600,
                    httponly=True,
                    samesite="lax"
                )
                logger.info(f"Successfully saved tasting session to cookie")
            else:
                logger.error(f"Failed to generate new token when updating session with tasting_session")
        except Exception as e:
            logger.error(f"Failed to create tasting session from extraction: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to create session: {str(e)}")

    # Get stats
    try:
        logger.debug(f"Getting session stats")
        tasting_service = TastingService(core_config)
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
        logger.debug(f"Successfully built response data")
        logger.debug(f"=== RETURNING TASTING SESSION ===")
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


@router.put("/api/v1/tastings/{extraction_id}/{index}")
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
        samesite="lax"
    )

    logger.info(f"Updated tasting {index} data for {extraction_id}")
    return {"status": "updated", "tasting": tastings[index]}


@router.post("/api/v1/tastings/{extraction_id}/{index}/match")
async def select_match(
    extraction_id: str,
    index: int,
    request: SelectMatchRequest,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Select a bottle match for a tasting."""
    from ..app import core_config, web_config

    logger.debug(f"=== SELECT MATCH ENDPOINT ===")
    logger.debug(f"extraction_id: {extraction_id}, index: {index}, bottle_path: {request.bottle_path}")

    if not core_config or not web_config:
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
    tasting_service = TastingService(core_config)
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

@router.post("/api/v1/tastings/{extraction_id}/{index}/approve")
async def approve_tasting(
    extraction_id: str,
    index: int,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Approve and save a single tasting."""
    from ..app import core_config, web_config, upload_service

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
    tasting_service = TastingService(core_config)

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


@router.post("/api/v1/tastings/{extraction_id}/{index}/skip")
async def skip_tasting(
    extraction_id: str,
    index: int,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Skip a single tasting without saving."""
    from ..app import core_config, web_config, upload_service

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
    tasting_service = TastingService(core_config)
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


@router.post("/api/v1/tastings/{extraction_id}/reject-all")
async def reject_all_tastings(
    extraction_id: str,
    response: Response,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Reject all tastings and clean up."""
    from ..app import web_config, upload_service

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

    tasting_session = session_data.get("tasting_session")
    if not tasting_session:
        raise HTTPException(status_code=404, detail="No tasting session")

    tasting_service = TastingService(core_config)
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
        samesite="lax"
    )

    logger.info(f"Refreshed matches for {extraction_id}")
    return {"status": "refreshed", "tastings": tastings}


# ============================================================================
# Manual Tasting (Sessionless - frontend manages wizard state)
# ============================================================================


@router.get("/manual-tasting", include_in_schema=False)
async def manual_tasting_page(request: Request):
    """Serve manual tasting wizard page."""
    return templates.TemplateResponse(request, "manual_tasting.html")


@router.post("/api/v1/manual-tasting/save")
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
    from ..app import core_config, event_store

    try:
        if not core_config:
            raise HTTPException(status_code=500, detail="Service not initialized")

        # Validate required fields
        if not request_data.taster_name:
            raise HTTPException(status_code=400, detail="Taster name is required")
        if not request_data.tasting_date:
            raise HTTPException(status_code=400, detail="Tasting date is required")
        if not request_data.selected_bottle_path:
            raise HTTPException(status_code=400, detail="Bottle selection is required")

        # Save based on mode
        if request_data.mode == ManualTastingMode.OBSIDIAN:
            tasting_service = TastingService(core_config)
            success, file_path, error = await tasting_service.save_manual_tasting_direct(
                taster_name=request_data.taster_name,
                tasting_date=request_data.tasting_date,
                beverage_type=request_data.beverage_type,
                selected_bottle_path=request_data.selected_bottle_path,
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

            if event_store is None:
                raise HTTPException(status_code=500, detail="Event store not initialized")

            if request_data.event_id not in event_store:
                raise HTTPException(status_code=404, detail="Event not found")

            event = event_store[request_data.event_id]

            if request_data.participant_id not in event["participants"]:
                raise HTTPException(status_code=404, detail="Participant not found in event")

            participant = event["participants"][request_data.participant_id]

            # Check if tasting already exists (for editing)
            existing_index = None
            for i, t in enumerate(participant["tastings"]):
                if t["bottle_path"] == request_data.selected_bottle_path:
                    existing_index = i
                    break

            tasting_entry = {
                "bottle_path": request_data.selected_bottle_path,
                "tasting_data": request_data.tasting_data
            }

            if existing_index is not None:
                participant["tastings"][existing_index] = tasting_entry
                logger.info(f"Updated tasting for bottle {request_data.selected_bottle_path}")
            else:
                participant["tastings"].append(tasting_entry)
                logger.info(f"Added new tasting for bottle {request_data.selected_bottle_path}")

            logger.info(f"Saved manual tasting to event {request_data.event_id}")
            return {"status": "saved", "event_id": request_data.event_id}

        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {request_data.mode}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to save manual tasting", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
