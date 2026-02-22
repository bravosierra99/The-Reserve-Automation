#CLAUDE_REQ: Ingredient model fields MUST match:
#CLAUDE_REQ: - FileClass (the-reserve/Cellar/8_FileClass/Ingredient.md) field definitions
#CLAUDE_REQ: - Jinja2 template (automation/templates/ingredient.md.j2) frontmatter fields
#CLAUDE_REQ: - Obsidian template (the-reserve/Cellar/9_Templates/Ingredient.md) frontmatter
#CLAUDE_REQ: - VaultReader.read_all_ingredients() parsing (utils/vault_reader.py)
#CLAUDE_REQ: - ObsidianGenerator ingredient generation (generators/obsidian.py)
#CLAUDE_REQ: - Ingredient API routes (web/routes/ingredients.py) field handling
"""Unified ingredient tree model for cocktail recipe system."""

from typing import Optional

from pydantic import BaseModel, Field


class Ingredient(BaseModel):
    """
    Unified ingredient node in the ingredient tree.

    Every node is an ingredient - whether general (e.g., "Vodka") or specific
    (e.g., "Svedka Vanilla Vodka"). Product fields distinguish the two:
    if any product field is set, is_product is True.

    The tree is entirely user-built. Users create root nodes and build
    the hierarchy by assigning parents.
    """

    name: str = Field(..., description="Ingredient name, e.g. 'Vodka' or 'Svedka Vanilla Vodka'")
    parent: Optional[str] = Field(None, description="Name of parent ingredient node (None = root)")

    # Product fields - filled in for specific/purchasable items, empty for general categories
    cost: Optional[float] = Field(None, description="Cost in dollars")
    volume_ml: Optional[int] = Field(None, description="Volume in milliliters")
    abv: Optional[float] = Field(None, description="Alcohol by volume percentage")
    notes: Optional[str] = Field(None, description="Free-form notes")
    label_image: Optional[str] = Field(None, description="Path to label image")

    # Computed at read time (not stored in frontmatter)
    is_product: bool = Field(False, description="True if any product field is set")
    children: list["Ingredient"] = Field(default_factory=list, description="Child ingredient nodes")
    ancestors: list[str] = Field(default_factory=list, description="Path from root to this node")

    # Vault metadata
    id: Optional[str] = Field(None, description="Opaque ID generated from vault path")
    vault_path: Optional[str] = Field(None, exclude=True, description="Relative vault path")

    def compute_is_product(self) -> None:
        """Set is_product based on whether any product field has a value."""
        self.is_product = any([
            self.cost is not None,
            self.volume_ml is not None,
            self.abv is not None,
            self.label_image is not None,
        ])

    def to_obsidian_dict(self) -> dict:
        """Convert to dict for Obsidian frontmatter rendering."""
        return {
            "name": self.name,
            "parent": self.parent,
            "cost": self.cost,
            "volume_ml": self.volume_ml,
            "abv": self.abv,
            "notes": self.notes,
            "label_image": self.label_image,
        }


class CreateIngredientRequest(BaseModel):
    """Request to create a new ingredient."""
    name: str = Field(..., min_length=1, description="Ingredient name")
    parent: Optional[str] = Field(None, description="Parent ingredient name (None = root)")
    cost: Optional[float] = None
    volume_ml: Optional[int] = None
    abv: Optional[float] = None
    notes: Optional[str] = None


class UpdateIngredientRequest(BaseModel):
    """Request to update an ingredient."""
    name: Optional[str] = Field(None, min_length=1)
    parent: Optional[str] = None
    cost: Optional[float] = None
    volume_ml: Optional[int] = None
    abv: Optional[float] = None
    notes: Optional[str] = None


class BulkSearchRequest(BaseModel):
    """Request to search for ingredients via LLM + web search."""
    query: str = Field(..., min_length=1, description="Natural language query, e.g. 'vanilla vodkas'")
    parent: Optional[str] = Field(None, description="Parent ingredient name to place results under")


class BulkSearchResult(BaseModel):
    """A single result from bulk ingredient search."""
    name: str
    cost: Optional[float] = None
    volume_ml: Optional[int] = None
    abv: Optional[float] = None
    notes: Optional[str] = None
    selected: bool = True


class BulkSaveRequest(BaseModel):
    """Request to save bulk search results as ingredients."""
    parent: Optional[str] = Field(None, description="Parent ingredient name")
    ingredients: list[BulkSearchResult] = Field(..., min_length=1)


def build_ingredient_tree(ingredients: list[Ingredient]) -> list[Ingredient]:
    """
    Build a tree from a flat list of ingredients by resolving parent links.

    Args:
        ingredients: Flat list of ingredients with parent names set.

    Returns:
        List of root ingredients (parent=None) with children populated.
    """
    by_name: dict[str, Ingredient] = {}
    for ing in ingredients:
        by_name[ing.name] = ing
        ing.children = []
        ing.ancestors = []

    roots: list[Ingredient] = []

    for ing in ingredients:
        if ing.parent and ing.parent in by_name:
            by_name[ing.parent].children.append(ing)
        else:
            roots.append(ing)

    # Compute ancestors for each node
    def _set_ancestors(node: Ingredient, ancestor_path: list[str]) -> None:
        node.ancestors = ancestor_path
        for child in node.children:
            _set_ancestors(child, ancestor_path + [node.name])

    for root in roots:
        _set_ancestors(root, [])

    return roots


def flatten_tree(roots: list[Ingredient]) -> list[Ingredient]:
    """Flatten a tree back into a list (depth-first)."""
    result: list[Ingredient] = []

    def _walk(node: Ingredient) -> None:
        result.append(node)
        for child in node.children:
            _walk(child)

    for root in roots:
        _walk(root)

    return result


def get_descendants(node: Ingredient) -> list[Ingredient]:
    """Get all descendants of a node (excluding the node itself)."""
    result: list[Ingredient] = []

    def _walk(n: Ingredient) -> None:
        for child in n.children:
            result.append(child)
            _walk(child)

    _walk(node)
    return result
