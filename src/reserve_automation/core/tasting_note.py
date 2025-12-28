#CLAUDE_REQ: Field names MUST match Obsidian fileClass definitions in the-reserve/Cellar/8_FileClass/
#CLAUDE_REQ: Wine fields map to "Wine Tasting" fileClass: Appearance, Aroma, Taste, Aftertaste, Overall, AWS Score, 100pt Scale
#CLAUDE_REQ: Whiskey fields map to "Tasting" fileClass: Nose, Palate, Finish, Overall, TotalScore, DaysFromCrack, FillLevel
#CLAUDE_REQ: Wine uses AWS 20-point scale (3+6+6+3+2); Whiskey uses 10-point scale (3+3+3+1)
#CLAUDE_REQ: Notes fields (appearance_notes [wine only], nose_notes, palate_notes, finish_notes, overall_notes) populate template sections
"""Data models for tasting notes."""

from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TastingNote(BaseModel):
    """Represents a single tasting note for a wine or whiskey."""

    # Identification
    bottle_name: str = Field(description="Name of the bottle being tasted")
    taster_name: str = Field(description="Name of the person tasting")
    tasting_date: date = Field(description="Date of the tasting")

    # Type
    beverage_type: Literal["wine", "whiskey"] = Field(description="Type of beverage")

    # Wine-specific fields (AWS 20-point scale)
    wine_appearance: Optional[float] = Field(default=None, ge=0, le=3, description="Appearance score (0-3)")
    wine_aroma: Optional[float] = Field(default=None, ge=0, le=6, description="Aroma/Bouquet score (0-6)")
    wine_taste: Optional[float] = Field(default=None, ge=0, le=6, description="Taste/Texture score (0-6)")
    wine_aftertaste: Optional[float] = Field(default=None, ge=0, le=3, description="Aftertaste score (0-3)")
    wine_overall: Optional[float] = Field(default=None, ge=0, le=2, description="Overall impression (0-2)")

    # Whiskey-specific fields (10-point scale matching user's format)
    whiskey_nose: Optional[float] = Field(default=None, ge=0, le=3, description="Nose score (0-3)")
    whiskey_palate: Optional[float] = Field(default=None, ge=0, le=3, description="Palate score (0-3)")
    whiskey_finish: Optional[float] = Field(default=None, ge=0, le=3, description="Finish score (0-3)")
    whiskey_overall: Optional[float] = Field(default=None, ge=0, le=1, description="Overall score (0-1)")

    # Tasting notes (free text)
    appearance_notes: Optional[list[str]] = Field(default=None, description="Appearance descriptors (wine-specific)")
    nose_notes: Optional[list[str]] = Field(default=None, description="Nose/aroma descriptors")
    palate_notes: Optional[list[str]] = Field(default=None, description="Palate/taste descriptors")
    finish_notes: Optional[list[str]] = Field(default=None, description="Finish descriptors")
    overall_notes: Optional[str] = Field(default=None, description="Overall impression text")

    # Additional metadata (from Obsidian FileClass)
    days_from_crack: Optional[int] = Field(default=None, ge=0, description="Days since bottle was opened")
    fill_level: Optional[int] = Field(default=None, ge=0, le=100, description="Bottle fill percentage (0-100)")

    # Additional metadata (not in FileClass, used for extraction/display)
    place: Optional[str] = Field(default=None, description="Location of tasting")
    theme: Optional[str] = Field(default=None, description="Tasting theme/event")
    price: Optional[str] = Field(default=None, description="Price of bottle (for wine lists)")
    color: Optional[str] = Field(default=None, description="Color observation (bourbon)")

    # Confidence scoring
    confidence: float = Field(default=1.0, ge=0, le=1, description="Extraction confidence")

    def total_score(self) -> float:
        """Calculate total score based on beverage type."""
        if self.beverage_type == "wine":
            scores = [
                self.wine_appearance or 0,
                self.wine_aroma or 0,
                self.wine_taste or 0,
                self.wine_aftertaste or 0,
                self.wine_overall or 0,
            ]
            return sum(scores)
        else:  # whiskey
            scores = [
                self.whiskey_nose or 0,
                self.whiskey_palate or 0,
                self.whiskey_finish or 0,
                self.whiskey_overall or 0,
            ]
            return sum(scores)

    def max_score(self) -> int:
        """Return maximum possible score for this beverage type."""
        return 20 if self.beverage_type == "wine" else 10


class TastingExtractionResult(BaseModel):
    """Result of extracting tastings from an image/PDF."""

    tastings: list[TastingNote] = Field(description="List of extracted tasting notes")
    template_type: Literal["aws_wine", "bourbon"] = Field(description="Type of template detected")
    raw_text: Optional[str] = Field(default=None, description="Raw OCR text")
    confidence: float = Field(default=1.0, ge=0, le=1, description="Overall extraction confidence")
