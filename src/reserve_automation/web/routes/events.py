"""Event management endpoints for multi-user tasting events."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.templating import Jinja2Templates
from loguru import logger

from ...db.repositories import get_bottle_repo, get_event_repo
from ...db.repositories.bottle_repo import SQLiteBottleRepository
from ...db.repositories.event_repo import SQLiteEventRepository
from ..auth.dependencies import require
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
    SubmitCocktailRatingRequest,
)

router = APIRouter()

# Set up templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


# ============================================================================
# PAGE ROUTES
# ============================================================================

@router.get("/events", include_in_schema=False, dependencies=[Depends(require("events.view"))])
async def events_list_page(request: Request):
    """Browse all available events."""
    return templates.TemplateResponse(request, "events.html")


@router.get("/events/{event_id}", include_in_schema=False, dependencies=[Depends(require("events.view"))])
async def event_detail_page(event_id: str, request: Request):
    """Event detail and participation page."""
    return templates.TemplateResponse(request, "event_detail.html", {
        "event_id": event_id
    })


@router.get("/events/{event_id}/results", include_in_schema=False, dependencies=[Depends(require("events.view"))])
async def event_results_page(event_id: str, request: Request):
    """Event results and rankings page."""
    return templates.TemplateResponse(request, "event_results.html", {
        "event_id": event_id
    })


# ============================================================================
# API ROUTES - EVENT CRUD
# ============================================================================

@router.post("/api/v1/events", dependencies=[Depends(require("events.create"))])
async def create_event(
    request_data: CreateEventRequest,
    repo: SQLiteEventRepository = Depends(get_event_repo),
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """Create a new tasting event."""
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

        # Validate bottles exist in database
        bottles = []
        for i, bottle_id in enumerate(request_data.bottle_ids):
            bottle = bottle_repo.get_by_id(int(bottle_id))
            if not bottle:
                raise HTTPException(
                    status_code=404,
                    detail=f"Bottle not found for ID: {bottle_id}"
                )

            # Build bottle name from metadata
            bottle_name = f"{bottle.producer} - {bottle.name}" if bottle.producer else bottle.name

            event_bottle = EventBottle(
                bottle_id=bottle_id,
                bottle_name=bottle_name,
                bottle_path=str(bottle_id),
                blind_number=request_data.blind_numbers[i] if request_data.is_blind else None
            )
            bottles.append(event_bottle)

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

        # Persist to database
        repo.create(event.model_dump())
        logger.info(f"Created event: {event_id} - {request_data.name} ({len(bottles)} bottles)")

        return event

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/events", dependencies=[Depends(require("events.view"))])
async def list_events(repo: SQLiteEventRepository = Depends(get_event_repo)):
    """Get all events."""
    try:
        events = repo.get_all()
        logger.debug(f"Retrieved {len(events)} events")
        return events

    except Exception as e:
        logger.error(f"Failed to list events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/events/{event_id}", dependencies=[Depends(require("events.view"))])
async def get_event(
    event_id: str,
    repo: SQLiteEventRepository = Depends(get_event_repo),
):
    """Get event details."""
    try:
        event = repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

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

@router.post("/api/v1/events/{event_id}/join", dependencies=[Depends(require("events.participate"))])
async def join_event(
    event_id: str,
    request_data: JoinEventRequest,
    request: Request,
    response: Response,
    repo: SQLiteEventRepository = Depends(get_event_repo),
):
    """Join an event as a participant."""

    try:
        event = repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        # Check if event is open
        if event["status"] == EventStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Event is closed")

        # Generate participant ID
        participant_id = str(uuid.uuid4())

        # Add participant via repo
        repo.add_participant(event_id, {
            "participant_id": participant_id,
            "name": request_data.participant_name,
        })
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
            secure=True,
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

@router.put("/api/v1/events/{event_id}/reveal", dependencies=[Depends(require("events.manage"))])
async def reveal_event(
    event_id: str,
    repo: SQLiteEventRepository = Depends(get_event_repo),
):
    """Reveal bottle names (transition from blind to revealed)."""
    try:
        event = repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        # Check if event is blind
        if not event["is_blind"]:
            raise HTTPException(status_code=400, detail="Event is not a blind tasting")

        # Check current status
        if event["status"] == EventStatus.REVEALED:
            return {"message": "Event already revealed", "event": event}

        if event["status"] == EventStatus.CLOSED:
            raise HTTPException(status_code=400, detail="Cannot reveal a closed event")

        # Update status
        updated_event = repo.update_status(event_id, EventStatus.REVEALED)
        logger.info(f"Event {event_id} revealed")

        return {"message": "Event revealed", "event": updated_event}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reveal event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/v1/events/{event_id}/close", dependencies=[Depends(require("events.manage"))])
async def close_event(
    event_id: str,
    repo: SQLiteEventRepository = Depends(get_event_repo),
):
    """Close an event (no more tastings allowed)."""
    try:
        event = repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

        # Check current status
        if event["status"] == EventStatus.CLOSED:
            return {"message": "Event already closed", "event": event}

        # Update status
        updated_event = repo.update_status(event_id, EventStatus.CLOSED)
        logger.info(f"Event {event_id} closed")

        return {"message": "Event closed", "event": updated_event}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to close event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/events/{event_id}", dependencies=[Depends(require("events.manage"))])
async def delete_event(
    event_id: str,
    repo: SQLiteEventRepository = Depends(get_event_repo),
):
    """Delete an event."""
    try:
        deleted = repo.delete(event_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Event not found")

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

@router.post("/api/v1/events/cocktail", dependencies=[Depends(require("events.create"))])
async def create_cocktail_event(
    request_data: CreateCocktailEventRequest,
    repo: SQLiteEventRepository = Depends(get_event_repo),
):
    """Create a cocktail tasting event (blind or flight mode)."""
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

        repo.create(event.model_dump())
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


@router.post("/api/v1/events/{event_id}/cocktails", dependencies=[Depends(require("events.participate"))])
async def add_event_cocktail(
    event_id: str,
    request_data: AddEventCocktailRequest,
    repo: SQLiteEventRepository = Depends(get_event_repo),
):
    """Add a cocktail to a flight event (flight mode only)."""
    try:
        event = repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

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

        repo.add_cocktail_to_event(event_id, cocktail.model_dump())
        logger.info(
            f"Added cocktail '{request_data.cocktail_name}' to event {event_id}"
        )

        return {"message": "Cocktail added", "cocktail": cocktail}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to add cocktail to event: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/events/{event_id}/cocktail-ratings", dependencies=[Depends(require("events.participate"))])
async def submit_cocktail_rating(
    event_id: str,
    request_data: SubmitCocktailRatingRequest,
    request: Request,
    repo: SQLiteEventRepository = Depends(get_event_repo),
):
    """Submit a rating for a cocktail in an event."""
    try:
        event = repo.get_by_id(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="Event not found")

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

        # Add/update rating via repo
        rating = CocktailRating(
            cocktail_name=request_data.cocktail_name,
            score=request_data.score,
            notes=request_data.notes,
        )

        repo.add_cocktail_rating(
            participant_id=participant_id,
            cocktail_name=request_data.cocktail_name,
            score=request_data.score,
            notes=request_data.notes,
        )

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
