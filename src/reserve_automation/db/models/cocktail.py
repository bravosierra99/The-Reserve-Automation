"""SQLAlchemy models for cocktail recipes."""

from datetime import datetime

from sqlalchemy import (
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


class CocktailModel(Base):
    """Persistent storage for cocktail recipes."""

    __tablename__ = "cocktails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_cocktail_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("cocktails.id", ondelete="SET NULL"), nullable=True
    )
    garnish: Mapped[str | None] = mapped_column(String(200), nullable=True)
    glassware: Mapped[str | None] = mapped_column(String(100), nullable=True)
    method: Mapped[str | None] = mapped_column(String(50), nullable=True)
    style: Mapped[str | None] = mapped_column(String(50), nullable=True)
    serving_size: Mapped[int] = mapped_column(Integer, default=1)
    stars: Mapped[str | None] = mapped_column(String(50), nullable=True)
    photo_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    # Relationships
    parent_cocktail: Mapped["CocktailModel | None"] = relationship(
        remote_side="CocktailModel.id", foreign_keys=[parent_cocktail_id]
    )
    ingredients: Mapped[list["RecipeIngredientModel"]] = relationship(
        back_populates="cocktail",
        cascade="all, delete-orphan",
        order_by="RecipeIngredientModel.sort_order",
    )
    instructions: Mapped[list["CocktailInstructionModel"]] = relationship(
        back_populates="cocktail",
        cascade="all, delete-orphan",
        order_by="CocktailInstructionModel.step_number",
    )
    tastings: Mapped[list["CocktailTastingModel"]] = relationship(
        back_populates="cocktail", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Cocktail {self.id}: {self.name}>"


class RecipeIngredientModel(Base):
    """An ingredient in a cocktail recipe."""

    __tablename__ = "recipe_ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cocktail_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cocktails.id", ondelete="CASCADE"), nullable=False
    )
    ingredient_name: Mapped[str] = mapped_column(String(200), nullable=False)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    optional: Mapped[bool] = mapped_column(Boolean, default=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    # Relationships
    cocktail: Mapped["CocktailModel"] = relationship(back_populates="ingredients")

    def __repr__(self) -> str:
        return f"<RecipeIngredient {self.id}: {self.ingredient_name}>"


class CocktailInstructionModel(Base):
    """An instruction step in a cocktail recipe."""

    __tablename__ = "cocktail_instructions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cocktail_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cocktails.id", ondelete="CASCADE"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    instruction: Mapped[str] = mapped_column(Text, nullable=False)

    # Relationships
    cocktail: Mapped["CocktailModel"] = relationship(back_populates="instructions")

    def __repr__(self) -> str:
        return f"<Instruction {self.id}: step {self.step_number}>"


# Forward reference for CocktailTastingModel
from .cocktail_tasting import CocktailTastingModel  # noqa: E402, F401
