#CLAUDE_REQ: Ingredient routes depend on:
#CLAUDE_REQ: - Ingredient model (core/ingredient.py) for data structures
#CLAUDE_REQ: - VaultReader.read_all_ingredients() (utils/vault_reader.py) for reading
#CLAUDE_REQ: - ObsidianGenerator.generate_ingredient_file() (generators/obsidian.py) for writing
#CLAUDE_REQ: - FileClass (the-reserve/Cellar/8_FileClass/Ingredient.md) for field names
#CLAUDE_REQ: - Vault structure: 2_Ingredients/{Name}/{Name}.md
"""Ingredient tree management endpoints."""

import re
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from ..auth.dependencies import require
from fastapi.templating import Jinja2Templates
from loguru import logger

from ...core.bottle_registry import BottleRegistry
from ...core.ingredient import (
    BulkSaveRequest,
    BulkSearchRequest,
    BulkSearchResult,
    CreateIngredientRequest,
    Ingredient,
    UpdateIngredientRequest,
    build_ingredient_tree,
    flatten_tree,
    get_descendants,
)
from ...generators.obsidian import ObsidianGenerator
from ...utils.vault_reader import VaultReader

router = APIRouter()

# Set up templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


def _get_services():
    """Get initialized services from app module."""
    from .. import app as app_module
    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry
    if core_config is None:
        raise HTTPException(status_code=500, detail="Service not initialized")
    return core_config, bottle_registry


def _read_ingredients(core_config, bottle_registry) -> list[Ingredient]:
    """Read all ingredients from vault as flat list."""
    reader = VaultReader(core_config.vault_path, registry=bottle_registry)
    return reader.read_all_ingredients(as_tree=False)


def _read_ingredient_tree(core_config, bottle_registry) -> list[Ingredient]:
    """Read all ingredients from vault as tree."""
    reader = VaultReader(core_config.vault_path, registry=bottle_registry)
    return reader.read_all_ingredients(as_tree=True)


def _find_ingredient_by_id(ingredients: list[Ingredient], ingredient_id: str):
    """Find an ingredient by its opaque ID."""
    for ing in ingredients:
        if ing.id == ingredient_id:
            return ing
    return None


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


def _sanitize_filename(name: str) -> str:
    """Remove/replace invalid filename characters."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


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
async def list_ingredients(flat: bool = False):
    """
    Get all ingredients.

    Args:
        flat: If True, return flat list. If False, return tree structure.
    """
    core_config, bottle_registry = _get_services()

    try:
        if flat:
            ingredients = _read_ingredients(core_config, bottle_registry)
            # Build tree to compute ancestors, then flatten
            roots = build_ingredient_tree(ingredients)
            all_flat = flatten_tree(roots)
            return [_ingredient_flat_dict(ing) for ing in all_flat]
        else:
            roots = _read_ingredient_tree(core_config, bottle_registry)
            return _tree_to_dicts(roots)
    except Exception as e:
        logger.error(f"Failed to list ingredients: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/ingredients/search", dependencies=[Depends(require("ingredients.view"))])
async def search_ingredients(q: str = ""):
    """Search ingredients by name. Returns tree structures with children."""
    core_config, bottle_registry = _get_services()

    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    try:
        ingredients = _read_ingredients(core_config, bottle_registry)
        # Build tree to compute ancestors
        roots = build_ingredient_tree(ingredients)
        all_flat = flatten_tree(roots)

        query_lower = q.lower()
        matches = [
            ing for ing in all_flat
            if query_lower in ing.name.lower()
        ]

        # Return tree structures (with children) instead of flat list
        return _tree_to_dicts(matches)
    except Exception as e:
        logger.error(f"Failed to search ingredients: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/ingredients/{ingredient_id}", dependencies=[Depends(require("ingredients.view"))])
async def get_ingredient(ingredient_id: str):
    """Get a single ingredient with ancestors and children."""
    core_config, bottle_registry = _get_services()

    try:
        ingredients = _read_ingredients(core_config, bottle_registry)
        roots = build_ingredient_tree(ingredients)
        all_flat = flatten_tree(roots)

        ing = _find_ingredient_by_id(all_flat, ingredient_id)
        if not ing:
            raise HTTPException(status_code=404, detail="Ingredient not found")

        return _ingredient_to_dict(ing)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get ingredient: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/ingredients/{ingredient_id}/descendants", dependencies=[Depends(require("ingredients.view"))])
async def get_ingredient_descendants(ingredient_id: str):
    """Get all descendants of an ingredient (for tasting bottle selection)."""
    core_config, bottle_registry = _get_services()

    try:
        ingredients = _read_ingredients(core_config, bottle_registry)
        roots = build_ingredient_tree(ingredients)
        all_flat = flatten_tree(roots)

        ing = _find_ingredient_by_id(all_flat, ingredient_id)
        if not ing:
            raise HTTPException(status_code=404, detail="Ingredient not found")

        descendants = get_descendants(ing)
        return [_ingredient_flat_dict(d) for d in descendants]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get descendants: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/ingredients", dependencies=[Depends(require("ingredients.create"))])
async def create_ingredient(request_data: CreateIngredientRequest):
    """Create a new ingredient."""
    core_config, bottle_registry = _get_services()

    try:
        ingredients_dir = core_config.vault_path / "2_Ingredients"

        # Check for duplicate name
        existing = _read_ingredients(core_config, bottle_registry)
        for ing in existing:
            if ing.name.lower() == request_data.name.lower():
                raise HTTPException(
                    status_code=409,
                    detail=f"Ingredient '{request_data.name}' already exists"
                )

        # Validate parent exists if specified
        if request_data.parent:
            parent_found = any(
                ing.name == request_data.parent for ing in existing
            )
            if not parent_found:
                raise HTTPException(
                    status_code=404,
                    detail=f"Parent ingredient '{request_data.parent}' not found"
                )

        # Create ingredient and generate file
        ingredient = Ingredient(
            name=request_data.name,
            parent=request_data.parent,
            cost=request_data.cost,
            volume_ml=request_data.volume_ml,
            abv=request_data.abv,
            notes=request_data.notes,
        )
        ingredient.compute_is_product()

        # Generate and write the file
        template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(
            vault_path=core_config.vault_path,
            template_dir=template_dir,
        )

        obsidian_file = generator.generate_ingredient_file(ingredient)
        generator.write_file(obsidian_file)

        # Register and get ID
        vault_path = str(obsidian_file.file_path.parent.relative_to(core_config.vault_path))
        if bottle_registry is not None:
            ingredient.id = bottle_registry.register(vault_path)
        else:
            ingredient.id = BottleRegistry.generate_id(vault_path)
        ingredient.vault_path = vault_path

        logger.info(f"Created ingredient: {ingredient.name} (id={ingredient.id})")
        return _ingredient_flat_dict(ingredient)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create ingredient: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/v1/ingredients/{ingredient_id}", dependencies=[Depends(require("ingredients.edit"))])
async def update_ingredient(ingredient_id: str, request_data: UpdateIngredientRequest):
    """Update an existing ingredient."""
    core_config, bottle_registry = _get_services()

    try:
        ingredients = _read_ingredients(core_config, bottle_registry)
        ing = _find_ingredient_by_id(ingredients, ingredient_id)
        if not ing:
            raise HTTPException(status_code=404, detail="Ingredient not found")

        old_name = ing.name
        vault_path = ing.vault_path

        # Apply updates
        update_data = request_data.model_dump(exclude_unset=True)

        # If name changed, check for duplicates
        if "name" in update_data and update_data["name"] != old_name:
            for other in ingredients:
                if other.name.lower() == update_data["name"].lower() and other.id != ingredient_id:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Ingredient '{update_data['name']}' already exists"
                    )

        # If parent changed, validate it exists
        if "parent" in update_data and update_data["parent"]:
            parent_found = any(
                i.name == update_data["parent"] for i in ingredients
            )
            if not parent_found:
                raise HTTPException(
                    status_code=404,
                    detail=f"Parent ingredient '{update_data['parent']}' not found"
                )

        # Update fields
        for key, value in update_data.items():
            setattr(ing, key, value)
        ing.compute_is_product()

        # Regenerate the file
        template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(
            vault_path=core_config.vault_path,
            template_dir=template_dir,
        )

        # If name changed, need to move the directory
        if "name" in update_data and update_data["name"] != old_name:
            old_dir = core_config.vault_path / vault_path
            new_folder_name = _sanitize_filename(ing.name)
            new_dir = core_config.vault_path / "2_Ingredients" / new_folder_name

            if old_dir.exists():
                shutil.move(str(old_dir), str(new_dir))

            # Unregister old path
            if bottle_registry is not None:
                bottle_registry.unregister(vault_path)

            vault_path = f"2_Ingredients/{new_folder_name}"
            ing.vault_path = vault_path

            # Delete old md file and generate new one
            old_md = new_dir / f"{old_name}.md"
            if old_md.exists():
                old_md.unlink()

            # Update all children to reference the new parent name
            children = [i for i in ingredients if i.parent == old_name]
            for child in children:
                child.parent = ing.name
                child_file = generator.generate_ingredient_file(child)
                generator.write_file(child_file)
                logger.info(f"Updated child reference: {child.name} -> parent {ing.name}")

        obsidian_file = generator.generate_ingredient_file(ing)
        generator.write_file(obsidian_file)

        # Re-register with new path
        if bottle_registry is not None:
            ing.id = bottle_registry.register(vault_path)

        logger.info(f"Updated ingredient: {ing.name} (id={ing.id})")
        return _ingredient_flat_dict(ing)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update ingredient: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/ingredients/{ingredient_id}", dependencies=[Depends(require("ingredients.delete"))])
async def delete_ingredient(ingredient_id: str):
    """
    Delete an ingredient.

    Fails if the ingredient has children (must delete children first).
    """
    core_config, bottle_registry = _get_services()

    try:
        ingredients = _read_ingredients(core_config, bottle_registry)
        ing = _find_ingredient_by_id(ingredients, ingredient_id)
        if not ing:
            raise HTTPException(status_code=404, detail="Ingredient not found")

        # Check for children
        children = [i for i in ingredients if i.parent == ing.name]
        if children:
            child_names = [c.name for c in children]
            raise HTTPException(
                status_code=409,
                detail=f"Cannot delete '{ing.name}': has children: {child_names}"
            )

        # Check for cocktail recipe references (Phase 3 guard)
        cocktails_dir = core_config.vault_path / "3_Cocktails"
        if cocktails_dir.exists():
            import yaml
            for cocktail_dir in cocktails_dir.iterdir():
                if not cocktail_dir.is_dir():
                    continue
                cocktail_file = cocktail_dir / f"{cocktail_dir.name}.md"
                if cocktail_file.exists():
                    try:
                        content = cocktail_file.read_text(encoding="utf-8")
                        match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL | re.MULTILINE)
                        if match:
                            frontmatter = yaml.safe_load(match.group(1))
                            recipe_ingredients = frontmatter.get("Ingredients", [])
                            if recipe_ingredients:
                                for ri in recipe_ingredients:
                                    if isinstance(ri, dict) and ri.get("ingredient") == ing.name:
                                        raise HTTPException(
                                            status_code=409,
                                            detail=f"Cannot delete '{ing.name}': referenced by cocktail '{cocktail_dir.name}'"
                                        )
                    except HTTPException:
                        raise
                    except Exception:
                        pass  # Skip unparseable files

        # Delete the directory
        vault_path = ing.vault_path
        full_path = core_config.vault_path / vault_path
        if full_path.exists():
            shutil.rmtree(full_path)

        # Unregister
        if bottle_registry is not None:
            bottle_registry.unregister(vault_path)

        logger.info(f"Deleted ingredient: {ing.name} (id={ingredient_id})")
        return {"status": "deleted", "name": ing.name, "id": ingredient_id}

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
        from ...llm.gateway import LLMGateway
        from ...llm.tool_executor import ToolExecutor
        from ...core.config import Config

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
        import json
        content = response.content.strip()
        # Extract JSON array from response (handle markdown code blocks)
        if "```" in content:
            import re as _re
            json_match = _re.search(r'```(?:json)?\s*\n?(.*?)\n?```', content, _re.DOTALL)
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
async def bulk_save_ingredients(request_data: BulkSaveRequest):
    """Save reviewed bulk search results as ingredients in the vault."""
    core_config, bottle_registry = _get_services()

    try:
        # Validate parent exists if specified
        existing = _read_ingredients(core_config, bottle_registry)
        if request_data.parent:
            parent_found = any(i.name == request_data.parent for i in existing)
            if not parent_found:
                raise HTTPException(
                    status_code=404,
                    detail=f"Parent ingredient '{request_data.parent}' not found"
                )

        existing_names = {i.name.lower() for i in existing}

        template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(
            vault_path=core_config.vault_path,
            template_dir=template_dir,
        )

        saved = []
        skipped = []

        for item in request_data.ingredients:
            if not item.selected:
                skipped.append({"name": item.name, "reason": "not selected"})
                continue

            if item.name.lower() in existing_names:
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
            ingredient.compute_is_product()

            try:
                obsidian_file = generator.generate_ingredient_file(ingredient)
                generator.write_file(obsidian_file)

                vault_path = str(obsidian_file.file_path.parent.relative_to(core_config.vault_path))
                if bottle_registry is not None:
                    ingredient.id = bottle_registry.register(vault_path)
                else:
                    ingredient.id = BottleRegistry.generate_id(vault_path)

                existing_names.add(item.name.lower())
                saved.append(_ingredient_flat_dict(ingredient))
            except Exception as e:
                skipped.append({"name": item.name, "reason": str(e)})

        logger.info(f"Bulk save: {len(saved)} saved, {len(skipped)} skipped")
        return {"saved": saved, "skipped": skipped}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Bulk save failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
