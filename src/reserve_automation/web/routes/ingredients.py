#CLAUDE_REQ: Ingredient routes depend on:
#CLAUDE_REQ: - Ingredient model (core/ingredient.py) for data structures
#CLAUDE_REQ: - SQLiteIngredientRepository (db/repositories/ingredient_repo.py) for CRUD
#CLAUDE_REQ: - get_ingredient_repo (db/repositories/__init__.py) for FastAPI Depends
"""Ingredient tree management endpoints."""

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger

from ...core.ingredient import (
    BulkSaveRequest,
    BulkSearchRequest,
    BulkSearchResult,
    CreateIngredientRequest,
    Ingredient,
    UpdateIngredientRequest,
)
from ...db.repositories import get_ingredient_repo
from ...db.repositories.ingredient_repo import SQLiteIngredientRepository
from ..auth.dependencies import require
from ..templating import make_templates

router = APIRouter()

# Set up templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = make_templates(templates_dir)


def _ingredient_to_dict(ing: Ingredient) -> dict:
    """Convert ingredient to API response dict."""
    return {
        "id": ing.id,
        "name": ing.name,
        "parent": ing.parent,
        "cost": ing.cost,
        "volume_ml": ing.volume_ml,
        "abv": ing.abv,
        "notes": ing.notes,
        "label_image": ing.label_image,
        "is_product": ing.is_product,
        "ancestors": ing.ancestors,
        "children": [_ingredient_to_dict(c) for c in ing.children],
    }


def _ingredient_flat_dict(ing: Ingredient) -> dict:
    """Convert ingredient to flat API response dict (no children)."""
    return {
        "id": ing.id,
        "name": ing.name,
        "parent": ing.parent,
        "cost": ing.cost,
        "volume_ml": ing.volume_ml,
        "abv": ing.abv,
        "notes": ing.notes,
        "label_image": ing.label_image,
        "is_product": ing.is_product,
        "ancestors": ing.ancestors,
    }


def _tree_to_dicts(roots: list[Ingredient]) -> list[dict]:
    """Convert tree to list of dicts with nested children."""
    return [_ingredient_to_dict(r) for r in roots]


# ============================================================================
# PAGE ROUTES
# ============================================================================

@router.get("/ingredients", include_in_schema=False, dependencies=[Depends(require("ingredients.view"))])
async def ingredients_page(request: Request):
    """Ingredients management page."""
    return templates.TemplateResponse(request, "ingredients.html")


# ============================================================================
# API ROUTES
# ============================================================================

@router.get("/api/v1/ingredients", dependencies=[Depends(require("ingredients.view"))])
async def list_ingredients(
    flat: bool = False,
    repo: SQLiteIngredientRepository = Depends(get_ingredient_repo),
):
    """
    Get all ingredients.

    Args:
        flat: If True, return flat list. If False, return tree structure.
    """
    try:
        if flat:
            ingredients = repo.get_all()
            return [_ingredient_flat_dict(ing) for ing in ingredients]
        else:
            roots = repo.get_tree()
            return _tree_to_dicts(roots)
    except Exception as e:
        logger.error(f"Failed to list ingredients: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/ingredients/search", dependencies=[Depends(require("ingredients.view"))])
async def search_ingredients(
    q: str = "",
    repo: SQLiteIngredientRepository = Depends(get_ingredient_repo),
):
    """Search ingredients by name. Returns tree structures with children."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    try:
        matches = repo.search(q)
        return _tree_to_dicts(matches)
    except Exception as e:
        logger.error(f"Failed to search ingredients: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/ingredients/{ingredient_id}", dependencies=[Depends(require("ingredients.view"))])
async def get_ingredient(
    ingredient_id: int,
    repo: SQLiteIngredientRepository = Depends(get_ingredient_repo),
):
    """Get a single ingredient with ancestors and children."""
    try:
        ing = repo.get_by_id(ingredient_id)
        if not ing:
            raise HTTPException(status_code=404, detail="Ingredient not found")

        return _ingredient_to_dict(ing)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get ingredient: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/ingredients/{ingredient_id}/descendants", dependencies=[Depends(require("ingredients.view"))])
async def get_ingredient_descendants(
    ingredient_id: int,
    repo: SQLiteIngredientRepository = Depends(get_ingredient_repo),
):
    """Get all descendants of an ingredient (for tasting bottle selection)."""
    try:
        ing = repo.get_by_id(ingredient_id)
        if not ing:
            raise HTTPException(status_code=404, detail="Ingredient not found")

        descendants = repo.get_descendants(ingredient_id)
        return [_ingredient_flat_dict(d) for d in descendants]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get descendants: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/ingredients", dependencies=[Depends(require("ingredients.create"))])
async def create_ingredient(
    request_data: CreateIngredientRequest,
    repo: SQLiteIngredientRepository = Depends(get_ingredient_repo),
):
    """Create a new ingredient."""
    try:
        # Check for duplicate name
        existing = repo.get_by_name(request_data.name)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Ingredient '{request_data.name}' already exists"
            )

        # Validate parent exists if specified
        if request_data.parent:
            parent = repo.get_by_name(request_data.parent)
            if not parent:
                raise HTTPException(
                    status_code=404,
                    detail=f"Parent ingredient '{request_data.parent}' not found"
                )

        ingredient = Ingredient(
            name=request_data.name,
            parent=request_data.parent,
            cost=request_data.cost,
            volume_ml=request_data.volume_ml,
            abv=request_data.abv,
            notes=request_data.notes,
        )

        created = repo.create(ingredient)
        logger.info(f"Created ingredient: {created.name} (id={created.id})")
        return _ingredient_flat_dict(created)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create ingredient: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/v1/ingredients/{ingredient_id}", dependencies=[Depends(require("ingredients.edit"))])
async def update_ingredient(
    ingredient_id: int,
    request_data: UpdateIngredientRequest,
    repo: SQLiteIngredientRepository = Depends(get_ingredient_repo),
):
    """Update an existing ingredient."""
    try:
        existing = repo.get_by_id(ingredient_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Ingredient not found")

        update_data = request_data.model_dump(exclude_unset=True)

        # If name changed, check for duplicates
        if "name" in update_data and update_data["name"] != existing.name:
            dup = repo.get_by_name(update_data["name"])
            if dup and str(dup.id) != str(ingredient_id):
                raise HTTPException(
                    status_code=409,
                    detail=f"Ingredient '{update_data['name']}' already exists"
                )

        # If parent changed, validate it exists
        if "parent" in update_data and update_data["parent"]:
            parent = repo.get_by_name(update_data["parent"])
            if not parent:
                raise HTTPException(
                    status_code=404,
                    detail=f"Parent ingredient '{update_data['parent']}' not found"
                )

        # Apply updates
        for key, value in update_data.items():
            setattr(existing, key, value)

        updated = repo.update(ingredient_id, existing)
        logger.info(f"Updated ingredient: {updated.name} (id={updated.id})")
        return _ingredient_flat_dict(updated)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update ingredient: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/ingredients/{ingredient_id}", dependencies=[Depends(require("ingredients.delete"))])
async def delete_ingredient(
    ingredient_id: int,
    repo: SQLiteIngredientRepository = Depends(get_ingredient_repo),
):
    """
    Delete an ingredient.

    Fails if the ingredient has children or is referenced by cocktail recipes.
    """
    try:
        ing = repo.get_by_id(ingredient_id)
        if not ing:
            raise HTTPException(status_code=404, detail="Ingredient not found")

        # Check for cocktail recipe references
        if repo.has_cocktail_references(ing.name):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete '{ing.name}': referenced by cocktail recipes"
            )

        # delete() checks for children internally and raises ValueError
        try:
            repo.delete(ingredient_id)
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e))

        logger.info(f"Deleted ingredient: {ing.name} (id={ingredient_id})")
        return {"status": "deleted", "name": ing.name, "id": str(ingredient_id)}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete ingredient: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# BULK IMPORT ENDPOINTS
# ============================================================================

@router.post("/api/v1/ingredients/bulk-search", dependencies=[Depends(require("ingredients.create"))])
async def bulk_search_ingredients(request_data: BulkSearchRequest):
    """
    Search for ingredients using web search + LLM.

    Accepts a natural language query (e.g., "vanilla vodkas") and returns
    a list of ingredient suggestions for review before saving.
    """
    try:
        from ...core.config import Config
        from ...llm.gateway import LLMGateway
        from ...llm.tool_executor import ToolExecutor

        config = Config.load()
        tool_executor = ToolExecutor()

        # Step 1: Web search for the query
        search_query = f"{request_data.query} brands products buy"
        search_results = tool_executor.execute("web_search", {"query": search_query})

        # Format search results for LLM
        search_text = ""
        for r in search_results.get("results", [])[:8]:
            search_text += f"- {r.get('title', '')}: {r.get('snippet', '')}\n"

        if not search_text:
            return {"results": [], "query": request_data.query}

        # Step 2: Use LLM to parse results into structured ingredients
        prompt = f"""Based on these web search results for "{request_data.query}", extract a list of specific product ingredients.

Search results:
{search_text}

Return a JSON array of products. Each product should have:
- "name": Full product name including brand (e.g., "Svedka Vanilla Vodka")
- "cost": Approximate price in USD (number or null)
- "volume_ml": Volume in ml (number or null, common sizes: 750, 1000, 1750)
- "abv": Alcohol by volume percentage (number or null)
- "notes": Brief description

Return ONLY the JSON array, no other text. Example:
[{{"name": "Svedka Vanilla Vodka", "cost": 12.99, "volume_ml": 750, "abv": 35.0, "notes": "Swedish vanilla flavored vodka"}}]"""

        gateway = LLMGateway(config.llm)
        response = await gateway.complete(
            task_type="metadata_enrichment",
            prompt=prompt,
            temperature=0.3,
            max_tokens=2000,
        )

        # Parse LLM response
        content = response.content.strip()
        # Extract JSON array from response (handle markdown code blocks)
        if "```" in content:
            json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, re.DOTALL)
            if json_match:
                content = json_match.group(1).strip()

        try:
            items = json.loads(content)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse LLM response as JSON: {content[:200]}")
            return {"results": [], "query": request_data.query, "error": "Failed to parse results"}

        # Convert to BulkSearchResult objects
        results = []
        for item in items:
            if isinstance(item, dict) and item.get("name"):
                results.append(BulkSearchResult(
                    name=item["name"],
                    cost=item.get("cost"),
                    volume_ml=item.get("volume_ml"),
                    abv=item.get("abv"),
                    notes=item.get("notes"),
                    selected=True,
                ))

        return {
            "results": [r.model_dump() for r in results],
            "query": request_data.query,
            "parent": request_data.parent,
        }

    except ImportError as e:
        logger.warning(f"LLM not available for bulk search: {e}")
        raise HTTPException(status_code=503, detail="LLM service not available")
    except Exception as e:
        logger.error(f"Bulk search failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/ingredients/bulk-save", dependencies=[Depends(require("ingredients.create"))])
async def bulk_save_ingredients(
    request_data: BulkSaveRequest,
    repo: SQLiteIngredientRepository = Depends(get_ingredient_repo),
):
    """Save reviewed bulk search results as ingredients."""
    try:
        # Validate parent exists if specified
        if request_data.parent:
            parent = repo.get_by_name(request_data.parent)
            if not parent:
                raise HTTPException(
                    status_code=404,
                    detail=f"Parent ingredient '{request_data.parent}' not found"
                )

        saved = []
        skipped = []

        for item in request_data.ingredients:
            if not item.selected:
                skipped.append({"name": item.name, "reason": "not selected"})
                continue

            # Check duplicate
            existing = repo.get_by_name(item.name)
            if existing:
                skipped.append({"name": item.name, "reason": "already exists"})
                continue

            ingredient = Ingredient(
                name=item.name,
                parent=request_data.parent,
                cost=item.cost,
                volume_ml=item.volume_ml,
                abv=item.abv,
                notes=item.notes,
            )

            try:
                created = repo.create(ingredient)
                saved.append(_ingredient_flat_dict(created))
            except Exception as e:
                skipped.append({"name": item.name, "reason": str(e)})

        logger.info(f"Bulk save: {len(saved)} saved, {len(skipped)} skipped")
        return {"saved": saved, "skipped": skipped}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk save failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
