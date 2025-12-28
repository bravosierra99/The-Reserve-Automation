"""Schemas for tasting upload and review workflow."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class TastingStatus(str, Enum):
    """Status of a tasting in the review workflow."""
    EXTRACTED = "extracted"
    MATCHED = "matched"
    APPROVED = "approved"
    SKIPPED = "skipped"


class MatchCandidate(BaseModel):
    """A potential bottle match for a tasting."""
    bottle_path: str = Field(..., description="Relative path to bottle folder in vault")
    bottle_name: str = Field(..., description="Full bottle name (Producer - Name - Year)")
    producer: str = Field(..., description="Bottle producer")
    vintage: Optional[int] = Field(None, description="Bottle vintage year")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Match confidence score")
    thumbnail_url: Optional[str] = Field(None, description="URL to bottle label thumbnail")
    beverage_type: str = Field(..., description="wine or whiskey")


class TastingData(BaseModel):
    """Extracted tasting data that can be edited."""
    bottle_name: str = Field(..., description="Bottle name from tasting card")
    taster_name: str = Field(..., description="Name of the taster")
    tasting_date: str = Field(..., description="Date of tasting (YYYY-MM-DD)")
    beverage_type: str = Field(..., description="wine or whiskey")

    # Wine-specific scores
    wine_appearance: Optional[float] = None
    wine_aroma: Optional[float] = None
    wine_taste: Optional[float] = None
    wine_aftertaste: Optional[float] = None
    wine_overall: Optional[float] = None

    # Whiskey-specific scores
    whiskey_nose: Optional[float] = None
    whiskey_palate: Optional[float] = None
    whiskey_finish: Optional[float] = None
    whiskey_overall: Optional[float] = None

    # Whiskey-specific metadata
    days_from_crack: Optional[int] = None
    fill_level: Optional[int] = None
    color: Optional[str] = None  # Color observation (bourbon)

    # Additional metadata
    place: Optional[str] = None  # Location of tasting
    theme: Optional[str] = None  # Tasting theme/event

    # Notes
    appearance_notes: Optional[list[str]] = Field(default_factory=list)  # Wine-specific
    nose_notes: Optional[list[str]] = Field(default_factory=list)
    palate_notes: Optional[list[str]] = Field(default_factory=list)
    finish_notes: Optional[list[str]] = Field(default_factory=list)
    overall_notes: Optional[str] = None

    class Config:
        extra = "allow"  # Allow additional fields from extraction


class TastingSessionItem(BaseModel):
    """A single tasting within a session."""
    index: int = Field(..., description="Index of this tasting in the batch")
    status: TastingStatus = Field(default=TastingStatus.EXTRACTED)
    tasting_data: TastingData = Field(..., description="Extracted/edited tasting data")
    match_candidates: list[MatchCandidate] = Field(
        default_factory=list,
        description="Potential bottle matches, sorted by confidence"
    )
    selected_match: Optional[str] = Field(
        None,
        description="Path to selected bottle (from match_candidates or manual search)"
    )
    duplicate_warning: Optional[str] = Field(
        None,
        description="Warning if this tasting might be a duplicate"
    )


class TastingSession(BaseModel):
    """Session containing extracted tastings for review."""
    extraction_id: str = Field(..., description="Unique extraction ID")
    beverage_type: str = Field(..., description="wine or whiskey (detected or specified)")
    template_type: str = Field(..., description="Template type (aws_wine, bourbon)")
    expected_count: Optional[int] = Field(None, description="User-specified expected count")
    actual_count: int = Field(..., description="Number of tastings extracted")
    count_mismatch: bool = Field(default=False, description="True if expected != actual")
    tastings: list[TastingSessionItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    upload_filename: Optional[str] = Field(None, description="Original uploaded filename")
    event_id: Optional[str] = Field(None, description="Event ID if event-based tasting")


# Request/Response models for API endpoints

class ExtractTastingsRequest(BaseModel):
    """Request to extract tastings from uploaded image."""
    expected_count: Optional[int] = Field(
        None,
        ge=1,
        le=4,
        description="Expected number of tastings on the card"
    )


class UpdateTastingRequest(BaseModel):
    """Request to update a single tasting's data."""
    tasting_data: TastingData


class SelectMatchRequest(BaseModel):
    """Request to select a bottle match for a tasting."""
    bottle_path: str = Field(..., description="Path to bottle folder in vault")


class SearchBottlesRequest(BaseModel):
    """Request to search for bottles in the vault."""
    query: str = Field(..., min_length=1, description="Search query")
    beverage_type: Optional[str] = Field(None, description="Filter by beverage type")
    limit: int = Field(default=10, ge=1, le=50, description="Max results to return")


class TastingSessionResponse(BaseModel):
    """Response containing the current tasting session state."""
    extraction_id: str
    beverage_type: str
    template_type: str
    expected_count: Optional[int]
    actual_count: int
    count_mismatch: bool
    current_index: int = Field(default=0, description="Currently active tasting index")
    tastings: list[TastingSessionItem]
    stats: dict = Field(
        default_factory=dict,
        description="Summary stats (approved, skipped, remaining)"
    )


class ApprovalResult(BaseModel):
    """Result of approving a single tasting."""
    success: bool
    file_created: Optional[str] = None
    bottle_matched: Optional[str] = None
    error: Optional[str] = None


class BatchApprovalResult(BaseModel):
    """Result of approving all tastings in session."""
    total: int
    approved: int
    skipped: int
    failed: int
    files_created: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ============================================================================
# Manual Tasting Wizard Schemas
# ============================================================================


class ManualTastingMode(str, Enum):
    """Mode for manual tasting entry."""
    OBSIDIAN = "obsidian"  # Save to Obsidian vault
    EVENT = "event"        # Transient event-based tasting


class ManualTastingWizardStep(str, Enum):
    """Steps in the manual tasting wizard."""
    TASTER_INFO = "taster_info"           # Step 1 (Obsidian only)
    BOTTLE_SELECTION = "bottle_selection"  # Step 2 (Obsidian) or Step 1 (Event)
    TASTING_FORM = "tasting_form"         # Step 3 (Obsidian) or Step 2 (Event)


class ManualTastingSession(BaseModel):
    """Session for manual tasting entry wizard."""
    session_id: str
    mode: ManualTastingMode
    beverage_type: str = Field(..., description="wine or whiskey")
    current_step: ManualTastingWizardStep
    created_at: datetime = Field(default_factory=datetime.now)

    # Obsidian-specific fields (populated in Step 1)
    taster_name: Optional[str] = None
    tasting_date: Optional[str] = None  # YYYY-MM-DD

    # Event-specific fields
    event_id: Optional[str] = None
    event_name: Optional[str] = None
    participant_id: Optional[str] = None  # Participant ID for event mode

    # Wizard progress
    selected_bottle_path: Optional[str] = None  # Set in Step 2
    tasting_data: Optional[dict] = None  # Set in Step 3 (dict, not TastingData - missing required fields)


class CreateManualTastingRequest(BaseModel):
    """Request to start a manual tasting session."""
    mode: ManualTastingMode = Field(default=ManualTastingMode.OBSIDIAN)
    beverage_type: str = Field(..., description="wine or whiskey")
    # Event-specific (future):
    event_id: Optional[str] = None


class UpdateWizardStepRequest(BaseModel):
    """Request to update wizard step data."""
    step: ManualTastingWizardStep
    data: dict  # Step-specific data


class SaveManualTastingRequest(BaseModel):
    """Request to save completed manual tasting."""
    pass  # No body needed - all data is in session
