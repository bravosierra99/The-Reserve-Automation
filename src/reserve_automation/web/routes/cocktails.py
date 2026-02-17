#CLAUDE_REQ: Cocktail routes depend on:
#CLAUDE_REQ: - CocktailRecipe model (core/cocktail.py) for data structures
#CLAUDE_REQ: - CocktailTastingNote model (core/cocktail_tasting.py) for tasting data structures
#CLAUDE_REQ: - VaultReader.read_all_cocktails() (utils/vault_reader.py) for reading cocktails
#CLAUDE_REQ: - VaultReader.read_cocktail_tastings() (utils/vault_reader.py) for reading tastings
#CLAUDE_REQ: - ObsidianGenerator.generate_cocktail_file() (generators/obsidian.py) for writing cocktails
#CLAUDE_REQ: - ObsidianGenerator.generate_cocktail_tasting_file() (generators/obsidian.py) for writing tastings
#CLAUDE_REQ: - FileClass (the-reserve/Cellar/8_FileClass/Cocktail.md) for cocktail field names
#CLAUDE_REQ: - FileClass (the-reserve/Cellar/8_FileClass/Cocktail Tasting.md) for tasting field names
#CLAUDE_REQ: - Vault structure: 3_Cocktails/{Name}/{Name}.md for cocktails
#CLAUDE_REQ: - Vault structure: 3_Cocktails/{Name}/Tasting-{date}-{taster}.md for tastings
"""Cocktail recipe management endpoints."""

import re
import shutil
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.templating import Jinja2Templates
from loguru import logger

from ...core.bottle_registry import BottleRegistry
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
from ...generators.obsidian import ObsidianGenerator
from ...utils.vault_reader import VaultReader

router = APIRouter()

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


def _read_cocktails(core_config, bottle_registry) -> list[CocktailRecipe]:
    """Read all cocktails from vault."""
    reader = VaultReader(core_config.vault_path, registry=bottle_registry)
    return reader.read_all_cocktails()


def _find_cocktail_by_id(cocktails: list[CocktailRecipe], cocktail_id: str):
    """Find a cocktail by its opaque ID."""
    for c in cocktails:
        if c.id == cocktail_id:
            return c
    return None


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


def _sanitize_filename(name: str) -> str:
    """Remove/replace invalid filename characters."""
    name = re.sub(r'[<>:"/\\|?*]', '', name)
    name = re.sub(r'\s+', ' ', name)
    return name.strip()


# ============================================================================
# PAGE ROUTES
# ============================================================================

@router.get("/cocktails", include_in_schema=False)
async def cocktails_page(request: Request):
    """Cocktail recipes page."""
    return templates.TemplateResponse(request, "cocktails.html")


@router.get("/cocktails/{cocktail_id}/detail", include_in_schema=False)
async def cocktail_detail_page(cocktail_id: str, request: Request):
    """Cocktail detail page."""
    return templates.TemplateResponse(request, "cocktail_detail.html", {
        "cocktail_id": cocktail_id
    })


# ============================================================================
# API ROUTES
# ============================================================================

@router.get("/api/v1/cocktails")
async def list_cocktails(q: str = None):
    """List all cocktails, optionally filtered by search query."""
    core_config, bottle_registry = _get_services()

    try:
        cocktails = _read_cocktails(core_config, bottle_registry)

        if q:
            query_lower = q.lower()
            cocktails = [
                c for c in cocktails
                if query_lower in c.name.lower()
                or any(query_lower in i.ingredient.lower() for i in c.ingredients)
                or (c.method and query_lower in c.method.lower())
                or (c.style and query_lower in c.style.lower())
            ]

        return [_cocktail_to_dict(c) for c in cocktails]
    except Exception as e:
        logger.error(f"Failed to list cocktails: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/cocktails/search")
async def search_cocktails(q: str = ""):
    """Search cocktails by name or ingredient."""
    if not q.strip():
        raise HTTPException(status_code=400, detail="Query parameter 'q' is required")

    core_config, bottle_registry = _get_services()
    try:
        cocktails = _read_cocktails(core_config, bottle_registry)
        query_lower = q.lower()
        matches = [
            c for c in cocktails
            if query_lower in c.name.lower()
            or any(query_lower in i.ingredient.lower() for i in c.ingredients)
        ]
        return [_cocktail_to_dict(c) for c in matches]
    except Exception as e:
        logger.error(f"Failed to search cocktails: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/cocktails/{cocktail_id}")
async def get_cocktail(cocktail_id: str):
    """Get a single cocktail recipe."""
    core_config, bottle_registry = _get_services()

    try:
        cocktails = _read_cocktails(core_config, bottle_registry)
        cocktail = _find_cocktail_by_id(cocktails, cocktail_id)
        if not cocktail:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        return _cocktail_to_dict(cocktail)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get cocktail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/cocktails")
async def create_cocktail(request_data: CreateCocktailRequest):
    """Create a new cocktail recipe."""
    core_config, bottle_registry = _get_services()

    try:
        # Check for duplicate name
        existing = _read_cocktails(core_config, bottle_registry)
        for c in existing:
            if c.name.lower() == request_data.name.lower():
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

        template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(
            vault_path=core_config.vault_path,
            template_dir=template_dir,
        )

        obsidian_file = generator.generate_cocktail_file(cocktail)
        generator.write_file(obsidian_file)

        vault_path = str(obsidian_file.file_path.parent.relative_to(core_config.vault_path))
        if bottle_registry is not None:
            cocktail.id = bottle_registry.register(vault_path)
        else:
            cocktail.id = BottleRegistry.generate_id(vault_path)
        cocktail.vault_path = vault_path

        logger.info(f"Created cocktail: {cocktail.name} (id={cocktail.id})")
        return _cocktail_to_dict(cocktail)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create cocktail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/api/v1/cocktails/{cocktail_id}")
async def update_cocktail(cocktail_id: str, request_data: UpdateCocktailRequest):
    """Update a cocktail recipe."""
    core_config, bottle_registry = _get_services()

    try:
        cocktails = _read_cocktails(core_config, bottle_registry)
        cocktail = _find_cocktail_by_id(cocktails, cocktail_id)
        if not cocktail:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        old_name = cocktail.name
        vault_path = cocktail.vault_path

        update_data = request_data.model_dump(exclude_unset=True)

        # Check for duplicate name
        if "name" in update_data and update_data["name"] != old_name:
            for c in cocktails:
                if c.name.lower() == update_data["name"].lower() and c.id != cocktail_id:
                    raise HTTPException(
                        status_code=409,
                        detail=f"Cocktail '{update_data['name']}' already exists"
                    )

        # Apply updates
        for key, value in update_data.items():
            if key == "ingredients" and value is not None:
                cocktail.ingredients = [RecipeIngredient(**i) if isinstance(i, dict) else i for i in value]
            else:
                setattr(cocktail, key, value)

        template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(
            vault_path=core_config.vault_path,
            template_dir=template_dir,
        )

        # Move directory if name changed
        if "name" in update_data and update_data["name"] != old_name:
            old_dir = core_config.vault_path / vault_path
            new_folder_name = _sanitize_filename(cocktail.name)
            new_dir = core_config.vault_path / "3_Cocktails" / new_folder_name

            if old_dir.exists():
                shutil.move(str(old_dir), str(new_dir))

            if bottle_registry is not None:
                bottle_registry.unregister(vault_path)

            vault_path = f"3_Cocktails/{new_folder_name}"
            cocktail.vault_path = vault_path

            old_md = new_dir / f"{old_name}.md"
            if old_md.exists():
                old_md.unlink()

        obsidian_file = generator.generate_cocktail_file(cocktail)
        generator.write_file(obsidian_file)

        if bottle_registry is not None:
            cocktail.id = bottle_registry.register(vault_path)

        logger.info(f"Updated cocktail: {cocktail.name} (id={cocktail.id})")
        return _cocktail_to_dict(cocktail)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update cocktail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/api/v1/cocktails/{cocktail_id}")
async def delete_cocktail(cocktail_id: str):
    """Delete a cocktail recipe."""
    core_config, bottle_registry = _get_services()

    try:
        cocktails = _read_cocktails(core_config, bottle_registry)
        cocktail = _find_cocktail_by_id(cocktails, cocktail_id)
        if not cocktail:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        vault_path = cocktail.vault_path
        full_path = core_config.vault_path / vault_path
        if full_path.exists():
            shutil.rmtree(full_path)

        if bottle_registry is not None:
            bottle_registry.unregister(vault_path)

        logger.info(f"Deleted cocktail: {cocktail.name} (id={cocktail_id})")
        return {"status": "deleted", "name": cocktail.name, "id": cocktail_id}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete cocktail: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# COCKTAIL TASTING ROUTES
# ============================================================================

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


@router.post("/api/v1/cocktails/{cocktail_id}/tastings")
async def create_cocktail_tasting(
    cocktail_id: str, request_data: CreateCocktailTastingRequest
):
    """Create a tasting note for a cocktail."""
    from datetime import date

    core_config, bottle_registry = _get_services()

    try:
        # Look up the cocktail
        cocktails = _read_cocktails(core_config, bottle_registry)
        cocktail = _find_cocktail_by_id(cocktails, cocktail_id)
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

        template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(
            vault_path=core_config.vault_path,
            template_dir=template_dir,
        )

        obsidian_file = generator.generate_cocktail_tasting_file(tasting)
        generator.write_file(obsidian_file)

        # Generate ID for the tasting
        tasting_vault_path = str(
            obsidian_file.file_path.relative_to(core_config.vault_path)
        )
        if bottle_registry is not None:
            tasting.id = bottle_registry.register(tasting_vault_path)
        else:
            tasting.id = BottleRegistry.generate_id(tasting_vault_path)
        tasting.vault_path = tasting_vault_path

        logger.info(
            f"Created cocktail tasting for {cocktail.name} "
            f"by {tasting.taster_name} (id={tasting.id})"
        )
        return _tasting_to_dict(tasting)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create cocktail tasting: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/cocktails/{cocktail_id}/tastings")
async def list_cocktail_tastings(cocktail_id: str):
    """List all tasting notes for a cocktail."""
    core_config, bottle_registry = _get_services()

    try:
        cocktails = _read_cocktails(core_config, bottle_registry)
        cocktail = _find_cocktail_by_id(cocktails, cocktail_id)
        if not cocktail:
            raise HTTPException(status_code=404, detail="Cocktail not found")

        reader = VaultReader(core_config.vault_path, registry=bottle_registry)
        tastings = reader.read_cocktail_tastings(cocktail.name)

        return [_tasting_to_dict(t) for t in tastings]

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list cocktail tastings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
