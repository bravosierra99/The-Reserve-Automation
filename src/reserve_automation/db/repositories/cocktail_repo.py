"""SQLite repository implementation for cocktails."""

from datetime import date

from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_

from ...core.cocktail import CocktailRecipe, RecipeIngredient
from ...core.cocktail_tasting import CocktailTastingNote, CocktailTastingIngredient
from ..models.cocktail import (
    CocktailModel,
    RecipeIngredientModel,
    CocktailInstructionModel,
)
from ..models.cocktail_tasting import (
    CocktailTastingModel,
    CocktailTastingIngredientModel,
)
from ..converters import (
    cocktail_to_pydantic,
    pydantic_to_cocktail,
    cocktail_tasting_to_pydantic,
)


class SQLiteCocktailRepository:
    """SQLite-backed cocktail repository."""

    def __init__(self, db: Session):
        self.db = db

    def _eager_query(self):
        """Query with all relationships eagerly loaded."""
        return self.db.query(CocktailModel).options(
            joinedload(CocktailModel.ingredients),
            joinedload(CocktailModel.instructions),
            joinedload(CocktailModel.parent_cocktail),
        )

    def get_by_id(self, cocktail_id: int) -> CocktailRecipe | None:
        db_cocktail = self._eager_query().filter(CocktailModel.id == cocktail_id).first()
        if db_cocktail is None:
            return None
        return cocktail_to_pydantic(db_cocktail)

    def get_all(self) -> list[CocktailRecipe]:
        cocktails = (
            self._eager_query()
            .order_by(CocktailModel.name)
            .all()
        )
        return [cocktail_to_pydantic(c) for c in cocktails]

    def create(self, cocktail: CocktailRecipe) -> CocktailRecipe:
        # Resolve parent cocktail if specified
        parent_id = None
        if cocktail.parent_cocktail:
            parent = (
                self.db.query(CocktailModel)
                .filter(CocktailModel.name == cocktail.parent_cocktail)
                .first()
            )
            if parent:
                parent_id = parent.id

        db_cocktail = pydantic_to_cocktail(cocktail, parent_id=parent_id)
        self.db.add(db_cocktail)
        self.db.flush()  # Get the ID before adding children

        # Add ingredients
        for i, ing in enumerate(cocktail.ingredients):
            db_ing = RecipeIngredientModel(
                cocktail_id=db_cocktail.id,
                ingredient_name=ing.ingredient,
                amount=ing.amount,
                unit=ing.unit,
                notes=ing.notes,
                optional=ing.optional,
                sort_order=i,
            )
            self.db.add(db_ing)

        # Add instructions
        for i, instruction in enumerate(cocktail.instructions):
            db_inst = CocktailInstructionModel(
                cocktail_id=db_cocktail.id,
                step_number=i + 1,
                instruction=instruction,
            )
            self.db.add(db_inst)

        self.db.commit()
        self.db.refresh(db_cocktail)
        return cocktail_to_pydantic(db_cocktail)

    def update(self, cocktail_id: int, cocktail: CocktailRecipe) -> CocktailRecipe:
        db_cocktail = self.db.get(CocktailModel, cocktail_id)
        if db_cocktail is None:
            raise ValueError(f"Cocktail {cocktail_id} not found")

        # Resolve parent
        parent_id = None
        if cocktail.parent_cocktail:
            parent = (
                self.db.query(CocktailModel)
                .filter(CocktailModel.name == cocktail.parent_cocktail)
                .first()
            )
            if parent:
                parent_id = parent.id

        pydantic_to_cocktail(cocktail, parent_id=parent_id, existing=db_cocktail)

        # Replace ingredients
        self.db.query(RecipeIngredientModel).filter(
            RecipeIngredientModel.cocktail_id == cocktail_id
        ).delete()
        for i, ing in enumerate(cocktail.ingredients):
            db_ing = RecipeIngredientModel(
                cocktail_id=cocktail_id,
                ingredient_name=ing.ingredient,
                amount=ing.amount,
                unit=ing.unit,
                notes=ing.notes,
                optional=ing.optional,
                sort_order=i,
            )
            self.db.add(db_ing)

        # Replace instructions
        self.db.query(CocktailInstructionModel).filter(
            CocktailInstructionModel.cocktail_id == cocktail_id
        ).delete()
        for i, instruction in enumerate(cocktail.instructions):
            db_inst = CocktailInstructionModel(
                cocktail_id=cocktail_id,
                step_number=i + 1,
                instruction=instruction,
            )
            self.db.add(db_inst)

        self.db.commit()
        self.db.refresh(db_cocktail)
        return cocktail_to_pydantic(db_cocktail)

    def delete(self, cocktail_id: int) -> bool:
        db_cocktail = self.db.get(CocktailModel, cocktail_id)
        if db_cocktail is None:
            return False
        self.db.delete(db_cocktail)
        self.db.commit()
        return True

    def search(self, query: str) -> list[CocktailRecipe]:
        pattern = f"%{query}%"
        results = (
            self._eager_query()
            .filter(
                or_(
                    CocktailModel.name.ilike(pattern),
                    CocktailModel.description.ilike(pattern),
                    CocktailModel.style.ilike(pattern),
                    CocktailModel.id.in_(
                        self.db.query(RecipeIngredientModel.cocktail_id)
                        .filter(RecipeIngredientModel.ingredient_name.ilike(pattern))
                    ),
                )
            )
            .order_by(CocktailModel.name)
            .all()
        )
        return [cocktail_to_pydantic(c) for c in results]

    def get_by_name(self, name: str) -> CocktailRecipe | None:
        db_cocktail = (
            self._eager_query()
            .filter(CocktailModel.name == name)
            .first()
        )
        if db_cocktail is None:
            return None
        return cocktail_to_pydantic(db_cocktail)

    def get_tastings(self, cocktail_id: int) -> list[CocktailTastingNote]:
        tastings = (
            self.db.query(CocktailTastingModel)
            .options(joinedload(CocktailTastingModel.bottles_used))
            .filter(CocktailTastingModel.cocktail_id == cocktail_id)
            .order_by(CocktailTastingModel.tasting_date.desc())
            .all()
        )
        return [cocktail_tasting_to_pydantic(t) for t in tastings]

    def create_tasting(
        self, tasting: CocktailTastingNote, cocktail_id: int
    ) -> CocktailTastingNote:
        db_tasting = CocktailTastingModel(
            cocktail_id=cocktail_id,
            recipe_name=tasting.recipe_name,
            taster_name=tasting.taster_name,
            tasting_date=(
                date.fromisoformat(tasting.tasting_date)
                if isinstance(tasting.tasting_date, str)
                else tasting.tasting_date
            ),
            score=tasting.score,
            notes=tasting.notes,
            bartender=tasting.bartender,
        )
        self.db.add(db_tasting)
        self.db.flush()

        for bu in tasting.bottles_used:
            db_bu = CocktailTastingIngredientModel(
                cocktail_tasting_id=db_tasting.id,
                recipe_ingredient=bu.recipe_ingredient,
                actual_product=bu.actual_product,
            )
            self.db.add(db_bu)

        self.db.commit()
        self.db.refresh(db_tasting)
        return cocktail_tasting_to_pydantic(db_tasting)

    def delete_tasting(self, tasting_id: int) -> bool:
        db_tasting = self.db.get(CocktailTastingModel, tasting_id)
        if db_tasting is None:
            return False
        self.db.delete(db_tasting)
        self.db.commit()
        return True
