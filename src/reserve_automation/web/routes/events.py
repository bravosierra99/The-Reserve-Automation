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
    AddEventCocktailRequest,
    CocktailRating,
    CreateCocktailEventRequest,
    CreateEventRequest,
    Event,
    EventBottle,
    EventCocktail,
    EventMode,
    EventStatus,
    EventType,
    JoinEventRequest,
    Participant,
    ParticipantSession,
    SubmitCocktailRatingRequest,
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
    return templates.TemplateResponse(request, "events.html")


@router.get("/events/{event_id}", include_in_schema=False)
async def event_detail_page(event_id: str, request: Request):
    """Event detail and participation page."""
    return templates.TemplateResponse(request, "event_detail.html", {
        "event_id": event_id
    })


@router.get("/events/{event_id}/results", include_in_schema=False)
async def event_results_page(event_id: str, request: Request):
    """Event results and rankings page."""
    return templates.TemplateResponse(request, "event_results.html", {
        "event_id": event_id
    })


# ============================================================================
# API ROUTES - EVENT CRUD
# ============================================================================

@router.post("/api/v1/events")
async def create_event(request_data: CreateEventRequest):
    """Create a new tasting event."""
    from .. import app as app_module
    event_store = app_module.event_store
    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

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
            if len(request_data.blind_numbers) != len(request_data.bottle_ids):
                raise HTTPException(
                    status_code=400,
                    detail="Number of blind_numbers must match bottle_ids"
                )

        # Validate bottles exist in vault by resolving IDs to paths
        vault_path = core_config.vault_path
        bottles = []
        for i, bottle_id in enumerate(request_data.bottle_ids):
            # Resolve bottle ID to vault path
            bottle_vault_path = None
            if bottle_registry:
                bottle_vault_path = bottle_registry.get_path(bottle_id)

            if not bottle_vault_path:
                raise HTTPException(
                    status_code=404,
                    detail=f"Bottle not found for ID: {bottle_id}"
                )

            full_path = vault_path / bottle_vault_path
            if not full_path.exists():
                raise HTTPException(
                    status_code=404,
                    detail=f"Bottle not found in vault: {bottle_id}"
                )

            # Extract bottle name from path (folder name)
            bottle_name = bottle_vault_path.split('/')[-1]

            bottle = EventBottle(
                bottle_id=bottle_id,
                bottle_name=bottle_name,
                bottle_path=bottle_vault_path,
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


# ============================================================================
# API ROUTES - COCKTAIL EVENTS
# ============================================================================

@router.post("/api/v1/events/cocktail")
async def create_cocktail_event(request_data: CreateCocktailEventRequest):
    """Create a cocktail tasting event (blind or flight mode)."""
    from .. import app as app_module
    event_store = app_module.event_store

    if event_store is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Validate: blind mode requires cocktails upfront
        if request_data.event_mode == EventMode.BLIND:
            if not request_data.cocktails:
                raise HTTPException(
                    status_code=400,
                    detail="Cocktails required for blind mode"
                )
            # Ensure blind numbers are set
            for i, c in enumerate(request_data.cocktails):
                if c.blind_number is None:
                    c.blind_number = i + 1

        event_id = str(uuid.uuid4())
        event = Event(
            event_id=event_id,
            name=request_data.name,
            beverage_type="cocktail",
            is_blind=(request_data.event_mode == EventMode.BLIND),
            status=EventStatus.OPEN,
            host_name=request_data.host_name,
            created_at=datetime.now(),
            bottles=[],
            participants={},
            event_type=EventType.COCKTAIL,
            event_mode=request_data.event_mode,
            cocktails=request_data.cocktails,
        )

        event_store[event_id] = event.model_dump()
        logger.info(
            f"Created cocktail event: {event_id} - {request_data.name} "
            f"({request_data.event_mode.value} mode, "
            f"{len(request_data.cocktails)} cocktails)"
        )

        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create cocktail event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/events/{event_id}/cocktails")
async def add_event_cocktail(event_id: str, request_data: AddEventCocktailRequest):
    """Add a cocktail to a flight event (flight mode only)."""
    from ..app import event_store

    if event_store is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        if event_id not in event_store:
            raise HTTPException(status_code=404, detail="Event not found")

        event = event_store[event_id]

        if event.get("event_type") != EventType.COCKTAIL:
            raise HTTPException(status_code=400, detail="Not a cocktail event")

        if event.get("event_mode") != EventMode.FLIGHT:
            raise HTTPException(
                status_code=400,
                detail="Can only add cocktails to flight mode events"
            )

        if event["status"] == EventStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Event is closed")

        cocktail = EventCocktail(
            cocktail_name=request_data.cocktail_name,
            recipe_id=request_data.recipe_id,
            bartender=request_data.bartender,
            added_at=datetime.now(),
        )

        event["cocktails"].append(cocktail.model_dump())
        logger.info(
            f"Added cocktail '{request_data.cocktail_name}' to event {event_id}"
        )

        return {"message": "Cocktail added", "cocktail": cocktail}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add cocktail to event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/events/{event_id}/cocktail-ratings")
async def submit_cocktail_rating(
    event_id: str,
    request_data: SubmitCocktailRatingRequest,
    request: Request,
):
    """Submit a rating for a cocktail in an event."""
    from ..app import event_store

    if event_store is None:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        if event_id not in event_store:
            raise HTTPException(status_code=404, detail="Event not found")

        event = event_store[event_id]

        if event.get("event_type") != EventType.COCKTAIL:
            raise HTTPException(status_code=400, detail="Not a cocktail event")

        if event["status"] == EventStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Event is closed")

        # Find participant from cookie
        participant_id = None
        if "participant_sessions" in request.cookies:
            try:
                decoded = unquote(request.cookies["participant_sessions"])
                sessions = json.loads(decoded)
                session = sessions.get(event_id)
                if session:
                    participant_id = session.get("participant_id")
            except Exception:
                pass

        if not participant_id or participant_id not in event["participants"]:
            raise HTTPException(
                status_code=403, detail="Must join event first"
            )

        # Verify the cocktail exists in the event
        cocktail_names = [c["cocktail_name"] for c in event["cocktails"]]
        if request_data.cocktail_name not in cocktail_names:
            raise HTTPException(
                status_code=404,
                detail=f"Cocktail '{request_data.cocktail_name}' not in this event"
            )

        # Add rating to participant
        participant = event["participants"][participant_id]
        rating = CocktailRating(
            cocktail_name=request_data.cocktail_name,
            score=request_data.score,
            notes=request_data.notes,
        )

        # Initialize cocktail_ratings list if missing (backward compat)
        if "cocktail_ratings" not in participant:
            participant["cocktail_ratings"] = []

        # Replace existing rating for same cocktail, or add new
        existing_idx = None
        for i, r in enumerate(participant["cocktail_ratings"]):
            if r.get("cocktail_name") == request_data.cocktail_name:
                existing_idx = i
                break

        if existing_idx is not None:
            participant["cocktail_ratings"][existing_idx] = rating.model_dump()
        else:
            participant["cocktail_ratings"].append(rating.model_dump())

        logger.info(
            f"Rating submitted for '{request_data.cocktail_name}' "
            f"in event {event_id} by participant {participant_id}"
        )

        return {"message": "Rating submitted", "rating": rating}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to submit cocktail rating: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
