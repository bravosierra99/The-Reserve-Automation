"""Event management endpoints for multi-user tasting events."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

from fastapi import APIRouter, HTTPException, Request, Response, Cookie
from fastapi.templating import Jinja2Templates
from loguru import logger

from ..schemas.events import (
    CreateEventRequest,
    Event,
    EventBottle,
    EventStatus,
    JoinEventRequest,
    Participant,
    ParticipantSession,
)

router = APIRouter()

# Set up templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


# ============================================================================
# PAGE ROUTES
# ============================================================================

@router.get("/events", include_in_schema=False)
async def events_list_page(request: Request):
    """Browse all available events."""
    return templates.TemplateResponse("events.html", {"request": request})


@router.get("/events/{event_id}", include_in_schema=False)
async def event_detail_page(event_id: str, request: Request):
    """Event detail and participation page."""
    return templates.TemplateResponse("event_detail.html", {
        "request": request,
        "event_id": event_id
    })


@router.get("/events/{event_id}/results", include_in_schema=False)
async def event_results_page(event_id: str, request: Request):
    """Event results and rankings page."""
    return templates.TemplateResponse("event_results.html", {
        "request": request,
        "event_id": event_id
    })


# ============================================================================
# API ROUTES - EVENT CRUD
# ============================================================================

@router.post("/api/v1/events")
async def create_event(request_data: CreateEventRequest):
    """Create a new tasting event."""
    from ..app import event_store, core_config

    if event_store is None or core_config is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Validate blind numbers if blind mode
        if request_data.is_blind:
            if not request_data.blind_numbers:
                raise HTTPException(
                    status_code=400,
                    detail="Blind numbers required when is_blind=True"
                )
            if len(request_data.blind_numbers) != len(request_data.bottle_paths):
                raise HTTPException(
                    status_code=400,
                    detail="Number of blind_numbers must match bottle_paths"
                )

        # Validate bottles exist in vault
        vault_path = core_config.vault_path
        bottles = []
        for i, bottle_path in enumerate(request_data.bottle_paths):
            full_path = vault_path / bottle_path
            if not full_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Bottle not found: {bottle_path}"
                )

            # Extract bottle name from path (folder name)
            bottle_name = bottle_path.split('/')[-1]

            bottle = EventBottle(
                bottle_path=bottle_path,
                bottle_name=bottle_name,
                blind_number=request_data.blind_numbers[i] if request_data.is_blind else None
            )
            bottles.append(bottle)

        # Create event
        event_id = str(uuid.uuid4())
        event = Event(
            event_id=event_id,
            name=request_data.name,
            beverage_type=request_data.beverage_type,
            is_blind=request_data.is_blind,
            status=EventStatus.OPEN,
            host_name=request_data.host_name,
            created_at=datetime.now(),
            bottles=bottles,
            participants={}
        )

        # Store in event_store
        event_store[event_id] = event.dict()
        logger.info(f"Created event: {event_id} - {request_data.name} ({len(bottles)} bottles)")

        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/events")
async def list_events():
    """Get all events."""
    from ..app import event_store

    if event_store is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Return all events
        events = list(event_store.values())
        logger.debug(f"Retrieved {len(events)} events")
        return events

    except Exception as e:
        logger.error(f"Failed to list events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/events/{event_id}")
async def get_event(event_id: str):
    """Get event details."""
    from ..app import event_store

    if event_store is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        if event_id not in event_store:
            raise HTTPException(status_code=404, detail="Event not found")

        event = event_store[event_id]
        logger.debug(f"Retrieved event: {event_id}")
        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# API ROUTES - PARTICIPANT MANAGEMENT
# ============================================================================

@router.post("/api/v1/events/{event_id}/join")
async def join_event(
    event_id: str,
    request_data: JoinEventRequest,
    request: Request,
    response: Response
):
    """Join an event as a participant."""
    from ..app import event_store, web_config

    if event_store is None or web_config is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        if event_id not in event_store:
            raise HTTPException(status_code=404, detail="Event not found")

        event = event_store[event_id]

        # Check if event is open
        if event["status"] == EventStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Event is closed")

        # Generate participant ID
        participant_id = str(uuid.uuid4())

        # Create participant
        participant = Participant(
            participant_id=participant_id,
            name=request_data.participant_name,
            tastings=[]
        )

        # Add to event
        event["participants"][participant_id] = participant.dict()
        logger.info(f"Participant {request_data.participant_name} joined event {event_id}")

        # Read existing multi-event session cookie
        existing_sessions = {}
        if "participant_sessions" in request.cookies:
            try:
                cookie_value = request.cookies["participant_sessions"]
                decoded_value = unquote(cookie_value)
                existing_sessions = json.loads(decoded_value)
            except Exception as e:
                logger.warning(f"Failed to parse existing participant_sessions cookie: {e}")
                existing_sessions = {}

        # Add this event's session to the multi-event cookie
        existing_sessions[event_id] = {
            "participant_id": participant_id,
            "participant_name": request_data.participant_name
        }

        # Set multi-event participant sessions cookie
        # Note: httponly=False so JavaScript can read it for auto-filling forms
        # URL-encode the JSON to avoid escaping issues
        cookie_value = quote(json.dumps(existing_sessions))
        response.set_cookie(
            key="participant_sessions",
            value=cookie_value,
            path="/",  # Must be "/" so cookie is sent on all paths
            max_age=7 * 24 * 3600,  # 7 days (longer since it covers multiple events)
            httponly=False,  # Must be False so JavaScript can access it
            samesite="lax"
        )

        return {
            "participant_id": participant_id,
            "participant_name": request_data.participant_name,
            "event_id": event_id
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to join event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# API ROUTES - EVENT STATUS MANAGEMENT
# ============================================================================

@router.put("/api/v1/events/{event_id}/reveal")
async def reveal_event(event_id: str):
    """Reveal bottle names (transition from blind to revealed)."""
    from ..app import event_store

    if event_store is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        if event_id not in event_store:
            raise HTTPException(status_code=404, detail="Event not found")

        event = event_store[event_id]

        # Check if event is blind
        if not event["is_blind"]:
            raise HTTPException(status_code=400, detail="Event is not a blind tasting")

        # Check current status
        if event["status"] == EventStatus.REVEALED:
            return {"message": "Event already revealed", "event": event}

        if event["status"] == EventStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Cannot reveal a closed event")

        # Update status
        event["status"] = EventStatus.REVEALED
        logger.info(f"Event {event_id} revealed")

        return {"message": "Event revealed", "event": event}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reveal event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/v1/events/{event_id}/close")
async def close_event(event_id: str):
    """Close an event (no more tastings allowed)."""
    from ..app import event_store

    if event_store is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        if event_id not in event_store:
            raise HTTPException(status_code=404, detail="Event not found")

        event = event_store[event_id]

        # Check current status
        if event["status"] == EventStatus.CLOSED:
            return {"message": "Event already closed", "event": event}

        # Update status
        event["status"] = EventStatus.CLOSED
        logger.info(f"Event {event_id} closed")

        return {"message": "Event closed", "event": event}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to close event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/events/{event_id}")
async def delete_event(event_id: str):
    """Delete an event."""
    from ..app import event_store

    if event_store is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        if event_id not in event_store:
            raise HTTPException(status_code=404, detail="Event not found")

        # Delete event
        del event_store[event_id]
        logger.info(f"Deleted event: {event_id}")

        return {"status": "deleted", "event_id": event_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
