"""SQLAlchemy models for tasting events."""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    Boolean,
    JSON,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base


class EventModel(Base):
    """Persistent storage for tasting events."""

    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID format
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    beverage_type: Mapped[str] = mapped_column(String(20), nullable=False)
    is_blind: Mapped[bool] = mapped_column(Boolean, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="setup")
    host_name: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str] = mapped_column(String(20), default="bottle")
    event_mode: Mapped[str] = mapped_column(String(20), default="standard")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relationships
    bottles: Mapped[list["EventBottleModel"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    cocktails: Mapped[list["EventCocktailModel"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    participants: Mapped[list["EventParticipantModel"]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Event {self.id}: {self.name}>"


class EventBottleModel(Base):
    """A bottle in a tasting event."""

    __tablename__ = "event_bottles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    bottle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bottles.id", ondelete="CASCADE"), nullable=False
    )
    bottle_name: Mapped[str] = mapped_column(String(300), nullable=False)  # Denormalized
    blind_number: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    event: Mapped["EventModel"] = relationship(back_populates="bottles")

    def __repr__(self) -> str:
        return f"<EventBottle {self.id}: {self.bottle_name}>"


class EventCocktailModel(Base):
    """A cocktail in a tasting event."""

    __tablename__ = "event_cocktails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    cocktail_name: Mapped[str] = mapped_column(String(200), nullable=False)
    recipe_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cocktails.id", ondelete="SET NULL"), nullable=True
    )
    bartender: Mapped[str | None] = mapped_column(String(100), nullable=True)
    blind_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relationships
    event: Mapped["EventModel"] = relationship(back_populates="cocktails")

    def __repr__(self) -> str:
        return f"<EventCocktail {self.id}: {self.cocktail_name}>"


class EventParticipantModel(Base):
    """A participant in a tasting event."""

    __tablename__ = "event_participants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # UUID
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Relationships
    event: Mapped["EventModel"] = relationship(back_populates="participants")
    tastings: Mapped[list["EventTastingModel"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan"
    )
    cocktail_ratings: Mapped[list["EventCocktailRatingModel"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Participant {self.id}: {self.name}>"


class EventTastingModel(Base):
    """A participant's tasting of a bottle in an event."""

    __tablename__ = "event_tastings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_participants.id", ondelete="CASCADE"), nullable=False
    )
    bottle_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bottles.id", ondelete="CASCADE"), nullable=False
    )
    tasting_data: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Relationships
    participant: Mapped["EventParticipantModel"] = relationship(back_populates="tastings")

    def __repr__(self) -> str:
        return f"<EventTasting {self.id}: participant={self.participant_id}>"


class EventCocktailRatingModel(Base):
    """A participant's rating of a cocktail in an event."""

    __tablename__ = "event_cocktail_ratings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    participant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("event_participants.id", ondelete="CASCADE"), nullable=False
    )
    cocktail_name: Mapped[str] = mapped_column(String(200), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    participant: Mapped["EventParticipantModel"] = relationship(
        back_populates="cocktail_ratings"
    )

    def __repr__(self) -> str:
        return f"<CocktailRating {self.id}: {self.cocktail_name}>"
