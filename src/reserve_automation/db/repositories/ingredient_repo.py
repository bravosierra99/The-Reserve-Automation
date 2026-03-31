"""SQLite repository implementation for ingredients."""

from sqlalchemy.orm import Session, joinedload

from ...core.ingredient import Ingredient, build_ingredient_tree, flatten_tree
from ..models.ingredient import IngredientModel
from ..converters import ingredient_to_pydantic, pydantic_to_ingredient


class SQLiteIngredientRepository:
    """SQLite-backed ingredient repository."""

    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, ingredient_id: int) -> Ingredient | None:
        db_ing = (
            self.db.query(IngredientModel)
            .options(joinedload(IngredientModel.parent))
            .filter(IngredientModel.id == ingredient_id)
            .first()
        )
        if db_ing is None:
            return None
        ing = ingredient_to_pydantic(db_ing)

        # Populate direct children
        children_db = (
            self.db.query(IngredientModel)
            .options(joinedload(IngredientModel.parent))
            .filter(IngredientModel.parent_id == ingredient_id)
            .order_by(IngredientModel.name)
            .all()
        )
        ing.children = [ingredient_to_pydantic(c) for c in children_db]

        # Compute ancestors by walking parent chain
        ancestors = []
        current = db_ing
        while current.parent is not None:
            ancestors.insert(0, current.parent.name)
            current = current.parent
        ing.ancestors = ancestors

        return ing

    def _get_all_raw(self) -> list[Ingredient]:
        """Get all ingredients as a flat list (no ancestors computed)."""
        ingredients = (
            self.db.query(IngredientModel)
            .options(joinedload(IngredientModel.parent))
            .order_by(IngredientModel.name)
            .all()
        )
        return [ingredient_to_pydantic(i) for i in ingredients]

    def get_tree(self) -> list[Ingredient]:
        """Get all ingredients organized as a tree (ancestors computed)."""
        flat = self._get_all_raw()
        return build_ingredient_tree(flat)

    def get_all(self) -> list[Ingredient]:
        """Get all ingredients as a flat list with ancestors computed."""
        roots = self.get_tree()
        return flatten_tree(roots)

    def get_by_name(self, name: str) -> Ingredient | None:
        db_ing = (
            self.db.query(IngredientModel)
            .options(joinedload(IngredientModel.parent))
            .filter(IngredientModel.name == name)
            .first()
        )
        if db_ing is None:
            return None
        return ingredient_to_pydantic(db_ing)

    def get_descendants(self, ingredient_id: int) -> list[Ingredient]:
        """Get all descendants of an ingredient (recursive)."""
        result = []
        self._collect_descendants(ingredient_id, result)
        return result

    def _collect_descendants(self, parent_id: int, result: list[Ingredient]):
        children = (
            self.db.query(IngredientModel)
            .options(joinedload(IngredientModel.parent))
            .filter(IngredientModel.parent_id == parent_id)
            .all()
        )
        for child in children:
            result.append(ingredient_to_pydantic(child))
            self._collect_descendants(child.id, result)

    def create(self, ingredient: Ingredient) -> Ingredient:
        # Resolve parent by name
        parent_id = None
        if ingredient.parent:
            parent = (
                self.db.query(IngredientModel)
                .filter(IngredientModel.name == ingredient.parent)
                .first()
            )
            if parent:
                parent_id = parent.id

        db_ing = pydantic_to_ingredient(ingredient, parent_id=parent_id)
        self.db.add(db_ing)
        self.db.commit()
        self.db.refresh(db_ing)
        return ingredient_to_pydantic(db_ing)

    def update(self, ingredient_id: int, ingredient: Ingredient) -> Ingredient:
        db_ing = self.db.get(IngredientModel, ingredient_id)
        if db_ing is None:
            raise ValueError(f"Ingredient {ingredient_id} not found")

        # Resolve parent by name
        parent_id = None
        if ingredient.parent:
            parent = (
                self.db.query(IngredientModel)
                .filter(IngredientModel.name == ingredient.parent)
                .first()
            )
            if parent:
                parent_id = parent.id

        pydantic_to_ingredient(ingredient, parent_id=parent_id, existing=db_ing)
        self.db.commit()
        self.db.refresh(db_ing)
        return ingredient_to_pydantic(db_ing)

    def delete(self, ingredient_id: int) -> bool:
        db_ing = self.db.get(IngredientModel, ingredient_id)
        if db_ing is None:
            return False

        # Check for children
        child_count = (
            self.db.query(IngredientModel)
            .filter(IngredientModel.parent_id == ingredient_id)
            .count()
        )
        if child_count > 0:
            raise ValueError(
                f"Cannot delete ingredient with {child_count} children. "
                "Delete or reparent children first."
            )

        self.db.delete(db_ing)
        self.db.commit()
        return True

    def search(self, query: str) -> list[Ingredient]:
        pattern = f"%{query}%"
        results = (
            self.db.query(IngredientModel)
            .options(joinedload(IngredientModel.parent))
            .filter(IngredientModel.name.ilike(pattern))
            .order_by(IngredientModel.name)
            .all()
        )
        return [ingredient_to_pydantic(i) for i in results]

    def has_cocktail_references(self, ingredient_name: str) -> bool:
        """Check if any cocktail recipes reference this ingredient."""
        from ..models.cocktail import RecipeIngredientModel

        count = (
            self.db.query(RecipeIngredientModel)
            .filter(RecipeIngredientModel.ingredient_name == ingredient_name)
            .count()
        )
        return count > 0
