#CLAUDE_REQ: Cocktail model fields MUST match:
#CLAUDE_REQ: - FileClass (the-reserve/Cellar/8_FileClass/Cocktail.md) field definitions
#CLAUDE_REQ: - Jinja2 template (automation/templates/cocktail.md.j2) frontmatter fields
#CLAUDE_REQ: - Obsidian template (the-reserve/Cellar/9_Templates/Cocktail.md) frontmatter
#CLAUDE_REQ: - VaultReader.read_all_cocktails() parsing (utils/vault_reader.py)
#CLAUDE_REQ: - ObsidianGenerator cocktail generation (generators/obsidian.py)
#CLAUDE_REQ: - Cocktail API routes (web/routes/cocktails.py) field handling
#CLAUDE_REQ: - Ingredients field is YAML array - parsed with pyyaml, not simple line parser
"""Cocktail recipe model for the cocktail system."""

from typing import Optional

from pydantic import BaseModel, Field


class RecipeIngredient(BaseModel):
    """An ingredient in a cocktail recipe."""
    ingredient: str = Field(..., description="Name of ingredient from tree (any level)")
    amount: Optional[float] = Field(None, description="Quantity")
    unit: Optional[str] = Field(None, description="oz, ml, dash, splash, piece, wedge, barspoon")
    notes: Optional[str] = Field(None, description="Preparation notes, e.g. 'freshly squeezed'")
    optional: bool = Field(False, description="Whether this ingredient is optional")


class CocktailRecipe(BaseModel):
    """A cocktail recipe."""
    name: str = Field(..., description="Cocktail name")
    description: Optional[str] = Field(None, description="Brief description")
    parent_cocktail: Optional[str] = Field(None, description="Parent cocktail (for variations/riffs)")
    ingredients: list[RecipeIngredient] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list, description="Ordered preparation steps")
    garnish: Optional[str] = Field(None, description="Garnish description")
    glassware: Optional[str] = Field(None, description="Glass type")
    method: Optional[str] = Field(None, description="shaken, stirred, built, blended")
    style: Optional[str] = Field(None, description="classic, tiki, modern, sour, highball")
    serving_size: int = Field(1, description="Number of servings")
    stars: Optional[str] = Field(None, description="Star rating")
    photo: Optional[str] = Field(None, description="Path to photo")

    # Vault metadata
    id: Optional[str] = Field(None, description="Opaque ID")
    vault_path: Optional[str] = Field(None, exclude=True)

    def to_frontmatter_dict(self) -> dict:
        """Convert to dict suitable for YAML frontmatter."""
        ingredients_list = []
        for ing in self.ingredients:
            d = {"ingredient": ing.ingredient}
            if ing.amount is not None:
                d["amount"] = ing.amount
            if ing.unit:
                d["unit"] = ing.unit
            if ing.notes:
                d["notes"] = ing.notes
            if ing.optional:
                d["optional"] = True
            ingredients_list.append(d)

        return {
            "name": self.name,
            "description": self.description,
            "parent_cocktail": self.parent_cocktail,
            "ingredients": ingredients_list,
            "instructions": self.instructions,
            "garnish": self.garnish,
            "glassware": self.glassware,
            "method": self.method,
            "style": self.style,
            "serving_size": self.serving_size,
            "stars": self.stars,
            "photo": self.photo,
        }


class CreateCocktailRequest(BaseModel):
    """Request to create a new cocktail recipe."""
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    parent_cocktail: Optional[str] = None
    ingredients: list[RecipeIngredient] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)
    garnish: Optional[str] = None
    glassware: Optional[str] = None
    method: Optional[str] = None
    style: Optional[str] = None
    serving_size: int = 1


class UpdateCocktailRequest(BaseModel):
    """Request to update a cocktail recipe."""
    name: Optional[str] = Field(None, min_length=1)
    description: Optional[str] = None
    parent_cocktail: Optional[str] = None
    ingredients: Optional[list[RecipeIngredient]] = None
    instructions: Optional[list[str]] = None
    garnish: Optional[str] = None
    glassware: Optional[str] = None
    method: Optional[str] = None
    style: Optional[str] = None
    serving_size: Optional[int] = None
