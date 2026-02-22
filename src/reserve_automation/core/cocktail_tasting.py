#CLAUDE_REQ: Cocktail tasting model fields MUST match:
#CLAUDE_REQ: - FileClass (the-reserve/Cellar/8_FileClass/Cocktail Tasting.md) field definitions
#CLAUDE_REQ: - Jinja2 template (automation/templates/cocktail_tasting.md.j2) frontmatter fields
#CLAUDE_REQ: - Obsidian template (the-reserve/Cellar/9_Templates/Cocktail Tasting.md) frontmatter
#CLAUDE_REQ: - VaultReader cocktail tasting parsing (utils/vault_reader.py)
#CLAUDE_REQ: - ObsidianGenerator cocktail tasting generation (generators/obsidian.py)
#CLAUDE_REQ: - Cocktail API tasting routes (web/routes/cocktails.py)
#CLAUDE_REQ: - Cocktail recipe template DataviewJS query (templates/cocktail.md.j2) expects fileClass "Cocktail Tasting"
"""Cocktail tasting note model."""

from typing import Optional

from pydantic import BaseModel, Field


class CocktailTastingIngredient(BaseModel):
    """Records which specific product was used for a recipe ingredient slot."""
    recipe_ingredient: str = Field(..., description="Which ingredient slot from the recipe")
    actual_product: str = Field(..., description="Specific product or bottle used")


class CocktailTastingNote(BaseModel):
    """A tasting note for a cocktail recipe."""
    recipe_name: str = Field(..., description="Links to cocktail in 3_Cocktails/")
    taster_name: str = Field(..., description="Who tasted the cocktail")
    tasting_date: str = Field(..., description="YYYY-MM-DD")
    bottles_used: list[CocktailTastingIngredient] = Field(default_factory=list)
    score: Optional[float] = Field(None, description="1-10 score", ge=1, le=10)
    notes: Optional[str] = Field(None, description="Free-text tasting notes")
    bartender: Optional[str] = Field(None, description="Who made the cocktail")

    # Vault metadata
    id: Optional[str] = Field(None, description="Opaque ID")
    vault_path: Optional[str] = Field(None, exclude=True)


class CreateCocktailTastingRequest(BaseModel):
    """Request to create a cocktail tasting note."""
    taster_name: str = Field(..., min_length=1)
    score: Optional[float] = Field(None, ge=1, le=10)
    notes: Optional[str] = None
    bartender: Optional[str] = None
    bottles_used: list[CocktailTastingIngredient] = Field(default_factory=list)
