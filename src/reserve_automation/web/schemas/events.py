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


class EventBottle(BaseModel):
    """A bottle in a tasting event."""
    bottle_id: str = Field(..., description="Opaque bottle ID")
    bottle_name: str = Field(..., description="Full bottle name")
    bottle_path: str = Field(..., description="Vault path for bottle image retrieval")
    blind_number: Optional[int] = Field(None, description="Bottle number for blind tastings")


class ParticipantTasting(BaseModel):
    """A tasting submitted by a participant."""
    bottle_id: str = Field(..., description="Opaque ID of bottle that was tasted")
    tasting_data: dict = Field(..., description="TastingData as dict")


class Participant(BaseModel):
    """An event participant."""
    participant_id: str = Field(..., description="Unique participant ID")
    name: str = Field(..., description="Participant name")
    tastings: list[ParticipantTasting] = Field(default_factory=list)


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


# Request/Response models

class CreateEventRequest(BaseModel):
    """Request to create a new event."""
    name: str = Field(..., min_length=1, description="Event name")
    beverage_type: str = Field(..., description="wine or whiskey")
    is_blind: bool = Field(default=False, description="Enable blind tasting mode")
    host_name: str = Field(..., min_length=1, description="Host name")
    bottle_ids: list[str] = Field(..., min_length=1, description="List of opaque bottle IDs")
    blind_numbers: Optional[list[int]] = Field(None, description="Bottle numbers (required if is_blind)")


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
