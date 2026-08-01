"""SQLAlchemy models for tasting events."""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
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
    # Python-side default (not func.now()): SQLite CURRENT_TIMESTAMP has
    # 1-second granularity, so events created back-to-back tied and sorted
    # nondeterministically in get_all() (flaked the events_list contract test).
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    # Relationships. All ordered deterministically: without order_by, SQLite
    # returns rows in index order — for participants that's the random UUID
    # PK, so display order (and the contract snapshots in tests/contract/)
    # varied arbitrarily. Participants have no join-timestamp column, so
    # alphabetical by name; the rest use insertion (id) order.
    bottles: Mapped[list["EventBottleModel"]] = relationship(
        back_populates="event", cascade="all, delete-orphan",
        order_by="EventBottleModel.id",
    )
    cocktails: Mapped[list["EventCocktailModel"]] = relationship(
        back_populates="event", cascade="all, delete-orphan",
        order_by="EventCocktailModel.id",
    )
    participants: Mapped[list["EventParticipantModel"]] = relationship(
        back_populates="event", cascade="all, delete-orphan",
        order_by="[EventParticipantModel.name, EventParticipantModel.id]",
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
        back_populates="participant", cascade="all, delete-orphan",
        order_by="EventTastingModel.id",
    )
    cocktail_ratings: Mapped[list["EventCocktailRatingModel"]] = relationship(
        back_populates="participant", cascade="all, delete-orphan",
        order_by="EventCocktailRatingModel.id",
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
