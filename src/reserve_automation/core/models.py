"""Data models for The Reserve Automation."""

#CLAUDE_REQ: When adding/modifying BottleMetadata fields, verify coherence with:
#CLAUDE_REQ: - SQLAlchemy model (db/models/bottle.py BottleModel)
#CLAUDE_REQ: - DB converter (db/converters.py bottle_model_to_metadata / metadata_to_bottle_model)
#CLAUDE_REQ: - Field name mapping (web/routes/management/labels.py and management/__init__.py field_name_map)

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class BeverageType(str, Enum):
    """Beverage categories."""

    WINE = "wine"
    WHISKEY = "whiskey"
    VODKA = "vodka"
    GIN = "gin"
    RUM = "rum"
    TEQUILA = "tequila"
    BRANDY = "brandy"
    OTHER = "other"


class BottleMetadata(BaseModel):
    """
    Extracted bottle information with confidence scoring.

    All metadata extracted from PDFs, images, or other sources.
    """

    # Core identifiers (required)
    producer: str = Field(
        ..., description="Producer/Winery/Distillery name", min_length=1, max_length=200
    )
    name: str = Field(..., description="Product name", min_length=1, max_length=200)
    type: BeverageType = Field(..., description="Beverage category (wine, whiskey, vodka, gin, rum, tequila, brandy, other)")

    # Optional core fields
    year: Optional[int] = Field(None, description="Vintage/release year", ge=1800, le=2030)
    beverage_type: Optional[str] = Field(
        None, description="Specific type (Red wine, Bourbon, etc.)", max_length=100
    )

    # Geographic
    country: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=200)

    # Wine-specific
    variety: Optional[list[str]] = Field(None, description="Grape variety or blend; list allows blends")
    vineyard: Optional[str] = None
    style: Optional[str] = Field(None, description="Wine style", max_length=100)

    # Whiskey-specific
    age_statement: Optional[int] = Field(None, ge=0, le=100)
    proof: Optional[float] = Field(None, ge=0, le=200)
    mash_bill: Optional[str] = None
    barrel_type: Optional[str] = None
    batch_number: Optional[str] = Field(None, description="Batch number", max_length=100)
    bottle_number: Optional[str] = Field(None, description="Bottle number", max_length=100)
    bottle_opened_date: Optional[str] = Field(None, description="Date bottle was opened", max_length=50)

    # Common
    abv: Optional[float] = Field(None, ge=0, le=100)
    price: Optional[float] = Field(None, ge=0)

    # Inventory and purchase info
    purchase_source: Optional[str] = Field(None, description="Where the bottle was purchased", max_length=200)
    purchase_link: Optional[str] = Field(None, description="Purchase URL", max_length=500)
    inventory: int = Field(0, description="Number of bottles in inventory", ge=0)
    buy: int = Field(0, description="Quantity to purchase", ge=0)

    # Rating fields
    stars: Optional[str] = Field(None, description="Star rating (e.g., ⭐️⭐️⭐️)", max_length=50)
    value_for_money: Optional[float] = Field(None, description="Value for money rating (0-5)", ge=0, le=5)
    points: Optional[str] = Field(None, description="Points/score", max_length=50)

    # Vault location (for bottles read from vault)
    # Note: vault_path is excluded from JSON serialization to hide filesystem paths from frontend
    vault_path: Optional[str] = Field(None, exclude=True, description="Relative path in vault (e.g., '1_Whiskeys/Distiller - Name - Year')")

    # Opaque identifier for external/API use (generated from vault_path hash)
    id: Optional[str] = Field(None, description="Opaque bottle identifier for API use")

    # Metadata
    confidence: float = Field(
        0.0, description="Extraction confidence (0-1)", ge=0.0, le=1.0
    )
    source: str = Field(..., description="Source of extraction (pdf, image, etc.)")
    extracted_at: datetime = Field(default_factory=datetime.now)

    # Enrichment
    enriched: bool = False
    label_image_url: Optional[str] = None
    notes: Optional[str] = Field(None, description="Extraction notes or warnings")

    model_config = {"use_enum_values": True}

    @field_validator("variety", mode="before")
    @classmethod
    def coerce_variety_to_list(cls, v):
        """Accept a plain string (legacy) or list; always returns list[str] | None."""
        if v is None or v == "":
            return None
        if isinstance(v, list):
            items = [s.strip() for s in v if isinstance(s, str) and s.strip()]
            return items or None
        if isinstance(v, str):
            import re as _re
            items = [s.strip() for s in _re.split(r"\s*[,/]\s*", v) if s.strip()]
            return items or None
        return v

    @field_validator("producer", "name")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Clean up string fields."""
        return v.strip() if v else v

    def to_obsidian_dict(self) -> dict:
        """Convert to Obsidian frontmatter format."""
        data = {
            "Name": f"{self.producer} - {self.name}",
        }

        # Set producer field name based on beverage type
        if self.type == "wine":
            data["Winemaker"] = self.producer
        elif self.type == "whiskey":
            data["Distiller"] = self.producer
        else:
            data["Producer"] = self.producer

        # Set year field name based on beverage type
        if self.year:
            if self.type == "wine":
                data["Vintage"] = self.year
            else:
                data["Year"] = self.year

        # Add purchase source if provided
        if self.purchase_source:
            data["PurchaseSource"] = self.purchase_source

        # Always add inventory (defaults to 0)
        data["Inventory"] = self.inventory

        # Add non-null fields
        excluded_fields = ["producer", "name", "year", "type", "purchase_source", "inventory", "vault_path", "id"]
        for field_name in self.model_fields:
            value = getattr(self, field_name)
            if value is not None and field_name not in excluded_fields:
                # Convert field_name to Title Case with hyphens
                obsidian_key = field_name.replace("_", "-").title()
                data[obsidian_key] = value

        return data


class ExtractionResult(BaseModel):
    """Complete result from extraction pipeline."""

    bottles: list[BottleMetadata]
    source_file: str
    source_type: Literal["pdf", "image", "screenshot"]

    # Statistics
    total_extracted: int
    high_confidence_count: int
    needs_review_count: int

    # Categorized bottles
    high_confidence: list[BottleMetadata] = []
    needs_review: list[BottleMetadata] = []

    # Processing metadata
    processing_time_seconds: float
    errors: list[str] = []
    warnings: list[str] = []

    # LLM usage
    total_tokens_used: int = 0
    total_cost: float = 0.0

    created_at: datetime = Field(default_factory=datetime.now)

    @field_validator("total_extracted")
    @classmethod
    def validate_counts(cls, v: int, info) -> int:
        """Ensure counts match bottle list."""
        if "bottles" in info.data:
            actual_count = len(info.data["bottles"])
            if v != actual_count:
                raise ValueError(
                    f"total_extracted ({v}) doesn't match bottles ({actual_count})"
                )
        return v


class ObsidianFile(BaseModel):
    """Generated Obsidian markdown file."""

    file_path: str = Field(..., description="Absolute path to file")
    content: str = Field(..., description="Markdown content")
    bottle: BottleMetadata

    created_at: datetime = Field(default_factory=datetime.now)

    def write(self) -> None:
        """Write file to disk."""
        from pathlib import Path

        path = Path(self.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.content, encoding="utf-8")


class ProcessingJob(BaseModel):
    """Job tracking for async processing (future phases)."""

    job_id: str
    status: Literal["pending", "processing", "completed", "failed"]
    input_file: str
    result: Optional[ExtractionResult] = None
    error: Optional[str] = None

    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class ParserResult(BaseModel):
    """Result from input parsing (PDF, image, etc.)."""

    raw_text: str = Field(..., description="Extracted text content")
    images: list[bytes] = Field(default_factory=list, description="Extracted images")
    metadata: dict = Field(default_factory=dict, description="Parser metadata")
    source_type: str = Field(..., description="Type of source (pdf, image, etc.)")


class LLMRequest(BaseModel):
    """Unified LLM request format."""

    prompt: str
    system: Optional[str] = None
    images: Optional[list[bytes]] = None
    max_tokens: int = 2000
    temperature: float = 0.2
    response_format: Optional[Literal["json", "text"]] = None
    tools: Optional[list[dict]] = None  # Tool definitions for function calling


class LLMResponse(BaseModel):
    """Unified LLM response format."""

    content: str
    provider: str
    model: str
    tokens_used: int
    cost: float = 0.0
    latency_ms: float
