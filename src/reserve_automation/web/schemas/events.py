"""Schemas for tasting event system."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EventStatus(str, Enum):
    """Status of a tasting event."""
    OPEN = "open"
    REVEALED = "revealed"
    CLOSED = "closed"


class EventType(str, Enum):
    """Type of tasting event."""
    BOTTLE = "bottle"
    COCKTAIL = "cocktail"


class EventMode(str, Enum):
    """Mode of a tasting event."""
    STANDARD = "standard"  # Normal bottle tasting
    BLIND = "blind"        # Blind tasting (bottles or cocktails)
    FLIGHT = "flight"      # Open flight (cocktails added dynamically)


class EventBottle(BaseModel):
    """A bottle in a tasting event."""
    bottle_id: str = Field(..., description="Opaque bottle ID")
    bottle_name: str = Field(..., description="Full bottle name")
    bottle_path: str = Field(..., description="Vault path for bottle image retrieval")
    blind_number: Optional[int] = Field(None, description="Bottle number for blind tastings")


class EventCocktail(BaseModel):
    """A cocktail in a cocktail tasting event."""
    cocktail_name: str = Field(..., description="Name of the cocktail")
    recipe_id: Optional[str] = Field(None, description="Opaque ID of cocktail recipe")
    bartender: Optional[str] = Field(None, description="Who made this cocktail")
    blind_number: Optional[int] = Field(None, description="Number for blind tastings")
    added_at: Optional[datetime] = Field(default_factory=datetime.now)


class CocktailRating(BaseModel):
    """A rating for a cocktail in an event."""
    cocktail_name: str = Field(..., description="Name of the cocktail being rated")
    score: float = Field(..., ge=1, le=10, description="Score from 1-10")
    notes: Optional[str] = Field(None, description="Tasting notes")


class ParticipantTasting(BaseModel):
    """A tasting submitted by a participant."""
    bottle_id: str = Field(..., description="Opaque ID of bottle that was tasted")
    tasting_data: dict = Field(..., description="TastingData as dict")


class Participant(BaseModel):
    """An event participant."""
    participant_id: str = Field(..., description="Unique participant ID")
    name: str = Field(..., description="Participant name")
    tastings: list[ParticipantTasting] = Field(default_factory=list)
    cocktail_ratings: list[CocktailRating] = Field(default_factory=list)


class Event(BaseModel):
    """A tasting event."""
    event_id: str = Field(..., description="Unique event ID")
    name: str = Field(..., description="Event name")
    beverage_type: str = Field(..., description="wine or whiskey")
    is_blind: bool = Field(..., description="Whether this is a blind tasting")
    status: EventStatus = Field(default=EventStatus.OPEN)
    host_name: str = Field(..., description="Name of event host")
    created_at: datetime = Field(default_factory=datetime.now)
    bottles: list[EventBottle] = Field(default_factory=list)
    participants: dict[str, Participant] = Field(default_factory=dict)
    # Cocktail event fields (backward compatible defaults)
    event_type: EventType = Field(default=EventType.BOTTLE)
    event_mode: EventMode = Field(default=EventMode.STANDARD)
    cocktails: list[EventCocktail] = Field(default_factory=list)


# Request/Response models

class CreateEventRequest(BaseModel):
    """Request to create a new event."""
    name: str = Field(..., min_length=1, description="Event name")
    beverage_type: str = Field(..., description="wine or whiskey")
    is_blind: bool = Field(default=False, description="Enable blind tasting mode")
    host_name: str = Field(..., min_length=1, description="Host name")
    bottle_ids: list[str] = Field(..., min_length=1, description="List of opaque bottle IDs")
    blind_numbers: Optional[list[int]] = Field(None, description="Bottle numbers (required if is_blind)")


class CreateCocktailEventRequest(BaseModel):
    """Request to create a cocktail tasting event."""
    name: str = Field(..., min_length=1, description="Event name")
    host_name: str = Field(..., min_length=1, description="Host name")
    event_mode: EventMode = Field(default=EventMode.FLIGHT, description="blind or flight")
    cocktails: list[EventCocktail] = Field(
        default_factory=list,
        description="Cocktails (required for blind, optional for flight)"
    )


class AddEventBottleRequest(BaseModel):
    """Request to add a bottle to an existing bottle event."""
    bottle_id: str = Field(..., min_length=1, description="Opaque bottle ID")
    blind_number: Optional[int] = Field(
        None,
        description="Blind number for blind events; defaults to the next unused number"
    )


class AddEventCocktailRequest(BaseModel):
    """Request to add a cocktail to a flight event."""
    cocktail_name: str = Field(..., min_length=1, description="Name of the cocktail")
    recipe_id: Optional[str] = Field(None, description="Opaque ID of cocktail recipe")
    bartender: Optional[str] = Field(None, description="Who made this cocktail")


class SubmitCocktailRatingRequest(BaseModel):
    """Request to submit a rating for a cocktail in an event."""
    cocktail_name: str = Field(..., min_length=1, description="Name of the cocktail")
    score: float = Field(..., ge=1, le=10, description="Score from 1-10")
    notes: Optional[str] = Field(None, description="Tasting notes")


class JoinEventRequest(BaseModel):
    """Request to join an event."""
    participant_name: str = Field(..., min_length=1, description="Participant name")


class ParticipantSession(BaseModel):
    """Participant session data stored in cookie."""
    participant_id: str
    event_id: str
    participant_name: str


class EventResponse(BaseModel):
    """Response containing event data."""
    event_id: str
    name: str
    beverage_type: str
    is_blind: bool
    status: EventStatus
    host_name: str
    created_at: datetime
    bottles: list[EventBottle]
    participants: dict[str, Participant]
    event_type: EventType = EventType.BOTTLE
    event_mode: EventMode = EventMode.STANDARD
    cocktails: list[EventCocktail] = Field(default_factory=list)
