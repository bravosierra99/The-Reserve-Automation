"""SQLAlchemy models for bottles and tasting notes."""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base


class BottleModel(Base):
    """Persistent storage for bottle metadata."""

    __tablename__ = "bottles"
    __table_args__ = (
        UniqueConstraint("producer", "name", "year", "type", name="uq_bottle_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Core identifiers
    producer: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # BeverageType value

    # Optional core
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    beverage_type: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Geographic
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Wine-specific
    variety: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON-encoded list
    vineyard: Mapped[str | None] = mapped_column(String(200), nullable=True)
    style: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Whiskey-specific
    age_statement: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proof: Mapped[float | None] = mapped_column(Float, nullable=True)
    mash_bill: Mapped[str | None] = mapped_column(String(500), nullable=True)
    barrel_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    batch_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bottle_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bottle_opened_date: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Common
    abv: Mapped[float | None] = mapped_column(Float, nullable=True)
    price: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Inventory and purchase
    purchase_source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    purchase_link: Mapped[str | None] = mapped_column(String(500), nullable=True)
    inventory: Mapped[int] = mapped_column(Integer, default=0)
    buy: Mapped[int] = mapped_column(Integer, default=0)

    # Ratings
    stars: Mapped[str | None] = mapped_column(String(50), nullable=True)
    value_for_money: Mapped[float | None] = mapped_column(Float, nullable=True)
    points: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Extraction metadata
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")
    extracted_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    enriched: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Image storage (relative path in media/)
    label_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    # Relationships
    tastings: Mapped[list["TastingNoteModel"]] = relationship(
        back_populates="bottle", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Bottle {self.id}: {self.producer} - {self.name}>"


class TastingNoteModel(Base):
    """Persistent storage for bottle tasting notes."""

    __tablename__ = "tasting_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Link to bottle
    bottle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bottles.id", ondelete="CASCADE"), nullable=False
    )
    bottle_name: Mapped[str] = mapped_column(String(300), nullable=False)  # Denormalized

    # Identification
    taster_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tasting_date: Mapped[date] = mapped_column(Date, nullable=False)
    beverage_type: Mapped[str] = mapped_column(String(10), nullable=False)

    # Wine-specific scoring (AWS 20-point)
    wine_appearance: Mapped[float | None] = mapped_column(Float, nullable=True)
    wine_aroma: Mapped[float | None] = mapped_column(Float, nullable=True)
    wine_taste: Mapped[float | None] = mapped_column(Float, nullable=True)
    wine_aftertaste: Mapped[float | None] = mapped_column(Float, nullable=True)
    wine_overall: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Whiskey-specific scoring (10-point)
    whiskey_nose: Mapped[float | None] = mapped_column(Float, nullable=True)
    whiskey_palate: Mapped[float | None] = mapped_column(Float, nullable=True)
    whiskey_finish: Mapped[float | None] = mapped_column(Float, nullable=True)
    whiskey_overall: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Tasting notes (stored as JSON arrays)
    appearance_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    nose_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    palate_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    finish_notes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    overall_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Additional metadata
    days_from_crack: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fill_level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    place: Mapped[str | None] = mapped_column(String(200), nullable=True)
    theme: Mapped[str | None] = mapped_column(String(200), nullable=True)
    price: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Confidence
    confidence: Mapped[float] = mapped_column(Float, default=1.0)

    # Hidden: excluded from score aggregations and default views
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relationships
    bottle: Mapped["BottleModel"] = relationship(back_populates="tastings")

    def __repr__(self) -> str:
        return f"<Tasting {self.id}: {self.bottle_name} by {self.taster_name}>"
