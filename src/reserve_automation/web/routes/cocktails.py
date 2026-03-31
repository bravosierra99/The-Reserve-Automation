"""Cocktail recipe management endpoints."""

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from ..auth.dependencies import require
from fastapi.templating import Jinja2Templates
from loguru import logger
from pydantic import BaseModel, Field

from ...core.cocktail import (
    CocktailRecipe,
    CreateCocktailRequest,
    RecipeIngredient,
    UpdateCocktailRequest,
)
from ...core.cocktail_tasting import (
    CocktailTastingNote,
    CreateCocktailTastingRequest,
)
from ...db.repositories import get_cocktail_repo
from ...db.repositories.cocktail_repo import SQLiteCocktailRepository

router = APIRouter()

templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


def _cocktail_to_dict(c: CocktailRecipe) -> dict:
    """Convert cocktail to API response dict."""
    return {
        "id": c.id,
        "name": c.name,
        "description": c.description,
        "ingredients": [
            {
                "ingredient": i.ingredient,
                "amount": i.amount,
                "unit": i.unit,
                "notes": i.notes,
                "optional": i.optional,
            }
            for i in c.ingredients
        ],
        "instructions": c.instructions,
        "garnish": c.garnish,
        "glassware": c.glassware,
        "method": c.method,
        "style": c.style,
        "serving_size": c.serving_size,
        "stars": c.stars,
        "photo": c.photo,
    }


def _tasting_to_dict(t: CocktailTastingNote) -> dict:
    """Convert cocktail tasting note to API response dict."""
    return {
        "id": t.id,
        "recipe_name": t.recipe_name,
        "taster_name": t.taster_name,
        "tasting_date": t.tasting_date,
        "score": t.score,
        "notes": t.notes,
        "bartender": t.bartender,
        "bottles_used": [
            {
                "recipe_ingredient": bu.recipe_ingredient,
                "actual_product": bu.actual_product,
            }
            for bu in t.bottles_used
        ],
    }


# ============================================================================
# PAGE ROUTES
# ============================================================================

@router.get("/cocktails", include_in_schema=False, dependencies=[Depends(require("cocktails.view"))])
async def cocktails_page(request: Request):
    """Cocktail recipes page."""
    return templates.TemplateResponse(request, "cocktails.html")


@router.get("/cocktails/{cocktail_id}/detail", include_in_schema=False, dependencies=[Depends(require("cocktails.view"))])
async def cocktail_detail_page(cocktail_id: str, request: Request):
    """Cocktail detail page."""
    return templates.TemplateResponse(request, "cocktail_detail.html", {
        "cocktail_id": cocktail_id
    })


# ============================================================================
# API ROUTES
# ============================================================================

@router.get("/api/v1/cocktails", dependencies=[Depends(require("cocktails.view"))])
async def list_cocktails(
    q: str = None,
    repo: SQLiteCocktailRepository = Depends(get_cocktail_repo),
):
    """List all cocktails, optionally filtered by search query."""
    try:
        if q:
            cocktails = repo.search(q)
        else:
            cocktails = repo.get_all()

        return [_cocktail_to_dict(c) for c in cocktails]
    except Exception as e:
        logger.error(f"Failed to list cocktails: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/cocktails/search", dependencies=[Depends(require("cocktails.view"))])
async def search_cocktails(
    q: str = "",
    repo: SQLiteCocktailRepository = Depends(get_cocktail_repo),
):
    """Search cocktails by name or ingredient."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    try:
        cocktails = repo.search(q)
        return [_cocktail_to_dict(c) for c in cocktails]
    except Exception as e:
        logger.error(f"Failed to search cocktails: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/cocktails/{cocktail_id}", dependencies=[Depends(require("cocktails.view"))])
async def get_cocktail(
    cocktail_id: int,
    repo: SQLiteCocktailRepository = Depends(get_cocktail_repo),
):
    """Get a single cocktail recipe."""
    try:
        cocktail = repo.get_by_id(cocktail_id)
        if not cocktail:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        return _cocktail_to_dict(cocktail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cocktail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/cocktails", dependencies=[Depends(require("cocktails.create"))])
async def create_cocktail(
    request_data: CreateCocktailRequest,
    repo: SQLiteCocktailRepository = Depends(get_cocktail_repo),
):
    """Create a new cocktail recipe."""
    try:
        # Check for duplicate name
        existing = repo.get_by_name(request_data.name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Cocktail '{request_data.name}' already exists"
            )

        cocktail = CocktailRecipe(
            name=request_data.name,
            description=request_data.description,
            ingredients=request_data.ingredients,
            instructions=request_data.instructions,
            garnish=request_data.garnish,
            glassware=request_data.glassware,
            method=request_data.method,
            style=request_data.style,
            serving_size=request_data.serving_size,
        )

        created = repo.create(cocktail)
        logger.info(f"Created cocktail: {created.name} (id={created.id})")
        return _cocktail_to_dict(created)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create cocktail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/v1/cocktails/{cocktail_id}", dependencies=[Depends(require("cocktails.edit"))])
async def update_cocktail(
    cocktail_id: int,
    request_data: UpdateCocktailRequest,
    repo: SQLiteCocktailRepository = Depends(get_cocktail_repo),
):
    """Update a cocktail recipe."""
    try:
        existing = repo.get_by_id(cocktail_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        update_data = request_data.model_dump(exclude_unset=True)

        # Check for duplicate name
        if "name" in update_data and update_data["name"] != existing.name:
            dup = repo.get_by_name(update_data["name"])
            if dup and dup.id != str(cocktail_id):
                raise HTTPException(
                    status_code=409,
                    detail=f"Cocktail '{update_data['name']}' already exists"
                )

        # Apply updates to Pydantic model
        for key, value in update_data.items():
            if key == "ingredients" and value is not None:
                existing.ingredients = [RecipeIngredient(**i) if isinstance(i, dict) else i for i in value]
            else:
                setattr(existing, key, value)

        updated = repo.update(cocktail_id, existing)
        logger.info(f"Updated cocktail: {updated.name} (id={updated.id})")
        return _cocktail_to_dict(updated)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update cocktail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/cocktails/{cocktail_id}", dependencies=[Depends(require("cocktails.delete"))])
async def delete_cocktail(
    cocktail_id: int,
    repo: SQLiteCocktailRepository = Depends(get_cocktail_repo),
):
    """Delete a cocktail recipe."""
    try:
        cocktail = repo.get_by_id(cocktail_id)
        if not cocktail:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        repo.delete(cocktail_id)
        logger.info(f"Deleted cocktail: {cocktail.name} (id={cocktail_id})")
        return {"status": "deleted", "name": cocktail.name, "id": str(cocktail_id)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete cocktail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# COCKTAIL TASTING ROUTES
# ============================================================================

@router.post("/api/v1/cocktails/{cocktail_id}/tastings", dependencies=[Depends(require("cocktail_tastings.submit"))])
async def create_cocktail_tasting(
    cocktail_id: int,
    request_data: CreateCocktailTastingRequest,
    repo: SQLiteCocktailRepository = Depends(get_cocktail_repo),
):
    """Create a tasting note for a cocktail."""
    from datetime import date

    try:
        cocktail = repo.get_by_id(cocktail_id)
        if not cocktail:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        tasting = CocktailTastingNote(
            recipe_name=cocktail.name,
            taster_name=request_data.taster_name,
            tasting_date=date.today().isoformat(),
            score=request_data.score,
            notes=request_data.notes,
            bartender=request_data.bartender,
            bottles_used=request_data.bottles_used,
        )

        created = repo.create_tasting(tasting, cocktail_id)
        logger.info(f"Created cocktail tasting for {cocktail.name} by {created.taster_name}")
        return _tasting_to_dict(created)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create cocktail tasting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/cocktails/{cocktail_id}/tastings", dependencies=[Depends(require("cocktail_tastings.view"))])
async def list_cocktail_tastings(
    cocktail_id: int,
    repo: SQLiteCocktailRepository = Depends(get_cocktail_repo),
):
    """List all tasting notes for a cocktail."""
    try:
        cocktail = repo.get_by_id(cocktail_id)
        if not cocktail:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        tastings = repo.get_tastings(cocktail_id)
        return [_tasting_to_dict(t) for t in tastings]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list cocktail tastings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/cocktails/{cocktail_id}/tastings/{tasting_id}", dependencies=[Depends(require("cocktail_tastings.delete"))])
async def delete_cocktail_tasting(
    cocktail_id: int,
    tasting_id: int,
    repo: SQLiteCocktailRepository = Depends(get_cocktail_repo),
):
    """Delete a cocktail tasting note."""
    try:
        cocktail = repo.get_by_id(cocktail_id)
        if not cocktail:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        deleted = repo.delete_tasting(tasting_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Tasting not found")

        logger.info(f"Deleted cocktail tasting {tasting_id}")
        return {"status": "deleted", "id": str(tasting_id)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete cocktail tasting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# RECIPE SEARCH
# ============================================================================

class RecipeSearchRequest(BaseModel):
    """Request to search for a cocktail recipe."""
    query: str = Field(..., min_length=1, description="Cocktail name to search for")


@router.post("/api/v1/cocktails/search-recipe", dependencies=[Depends(require("cocktails.create"))])
async def search_cocktail_recipe(request_data: RecipeSearchRequest):
    """
    Search for a cocktail recipe using LLM.

    Accepts a cocktail name and returns a structured recipe.
    """
    try:
        from ...llm.gateway import LLMGateway
        from ...core.config import Config

        config = Config.load()

        prompt = f"""Provide a classic recipe for the cocktail: {request_data.query}

Return a JSON object with the following structure:
{{
  "name": "Cocktail Name",
  "description": "Brief description of the cocktail",
  "method": "shaken/stirred/built/blended",
  "style": "classic/modern/tiki/sour/highball",
  "glassware": "Type of glass (e.g., coupe, rocks, highball)",
  "garnish": "Garnish description",
  "ingredients": [
    {{"ingredient": "Ingredient name", "amount": 2.0, "unit": "oz", "notes": "optional notes"}},
    {{"ingredient": "Ingredient name", "amount": 0.75, "unit": "oz"}}
  ],
  "instructions": [
    "Step 1",
    "Step 2"
  ]
}}

Use standard measurements (oz for spirits, dash for bitters). Return ONLY valid JSON, no other text."""

        gateway = LLMGateway(config.llm)
        response = await gateway.complete(
            task_type="metadata_enrichment",
            prompt=prompt,
            temperature=0.3,
            max_tokens=1500,
        )

        # Parse JSON response
        recipe_text = response.content.strip()
        # Remove markdown code blocks if present
        if recipe_text.startswith("```"):
            recipe_text = recipe_text.split("```")[1]
            if recipe_text.startswith("json"):
                recipe_text = recipe_text[4:]
            recipe_text = recipe_text.strip()

        recipe_data = json.loads(recipe_text)

        return recipe_data

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse recipe JSON: {e}")
        raise HTTPException(status_code=500, detail="Failed to parse recipe from LLM response")
    except Exception as e:
        logger.error(f"Failed to search recipe: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
