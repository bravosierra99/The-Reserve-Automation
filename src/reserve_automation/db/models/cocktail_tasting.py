"""SQLAlchemy models for cocktail tasting notes."""

from datetime import datetime, date

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..base import Base


class CocktailTastingModel(Base):
    """Persistent storage for cocktail tasting notes."""

    __tablename__ = "cocktail_tastings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    cocktail_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cocktails.id", ondelete="CASCADE"), nullable=False
    )
    recipe_name: Mapped[str] = mapped_column(String(200), nullable=False)  # Denormalized
    taster_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tasting_date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    bartender: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Hidden: excluded from score aggregations and default views
    hidden: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    # Relationships
    cocktail: Mapped["CocktailModel"] = relationship(back_populates="tastings")
    bottles_used: Mapped[list["CocktailTastingIngredientModel"]] = relationship(
        back_populates="tasting", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<CocktailTasting {self.id}: {self.recipe_name} by {self.taster_name}>"


class CocktailTastingIngredientModel(Base):
    """Records which specific product was used for a recipe ingredient slot."""

    __tablename__ = "cocktail_tasting_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cocktail_tasting_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cocktail_tastings.id", ondelete="CASCADE"), nullable=False
    )
    recipe_ingredient: Mapped[str] = mapped_column(String(200), nullable=False)
    actual_product: Mapped[str] = mapped_column(String(200), nullable=False)

    # Relationships
    tasting: Mapped["CocktailTastingModel"] = relationship(back_populates="bottles_used")

    def __repr__(self) -> str:
        return f"<CocktailTastingIngredient {self.id}: {self.recipe_ingredient}>"


# Avoid circular import - CocktailModel is imported in cocktail.py
from .cocktail import CocktailModel  # noqa: E402, F401
