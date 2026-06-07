"""SQLAlchemy model for ingredients."""

from datetime import datetime

from sqlalchemy import (
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


class IngredientModel(Base):
    """Persistent storage for ingredients (tree structure via self-referential FK)."""

    __tablename__ = "ingredients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("ingredients.id", ondelete="SET NULL"), nullable=True
    )

    # Product fields
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_ml: Mapped[int | None] = mapped_column(Integer, nullable=True)
    abv: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    label_image_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now()
    )

    # Relationships
    parent: Mapped["IngredientModel | None"] = relationship(
        remote_side="IngredientModel.id",
        foreign_keys=[parent_id],
        back_populates="children",
    )
    children: Mapped[list["IngredientModel"]] = relationship(
        back_populates="parent",
        foreign_keys=[parent_id],
    )

    @property
    def is_product(self) -> bool:
        """True if any product field is set."""
        return any([
            self.cost is not None,
            self.volume_ml is not None,
            self.abv is not None,
            self.label_image_path is not None,
        ])

    def __repr__(self) -> str:
        return f"<Ingredient {self.id}: {self.name}>"
