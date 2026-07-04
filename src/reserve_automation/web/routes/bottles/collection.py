"""Bottle collection routes - public grid view accessible to all authenticated users."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel

from ....core.models import BottleMetadata
from ....db.repositories import get_bottle_repo, get_tasting_repo
from ....db.repositories.bottle_repo import SQLiteBottleRepository
from ....db.repositories.tasting_repo import SQLiteTastingRepository
from ...auth.dependencies import require
from ..management.core import get_bottle_tastings_list, get_bottle_tastings_summary

router = APIRouter(dependencies=[Depends(require("bottles.view"))])


@router.get("/bottles", response_class=HTMLResponse)
async def bottles_page(request: Request):
    """Render the bottle collection grid page (accessible to all roles)."""
    from ...app import templates

    return templates.TemplateResponse(request, "bottles.html", {})


@router.get("/api/v1/bottles/collection")
async def get_bottle_collection(
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Get all bottles for the collection grid view.

    Returns:
        dict: Contains list of bottles with their current metadata (with IDs)
    """
    try:
        bottles = bottle_repo.get_all()
        bottles_data = [bottle.model_dump(mode='json') for bottle in bottles]

        logger.info(f"Collection: loaded {len(bottles)} bottles")

        return {
            "bottles": bottles_data,
            "count": len(bottles)
        }

    except Exception as e:
        logger.error(f"Failed to load bottles for collection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class BottleNotesUpdate(BaseModel):
    """Body for the shared bottle-notes update."""
    notes: str | None = None


@router.put("/api/v1/bottles/{bottle_id}/notes", dependencies=[Depends(require("bottles.notes.edit"))])
async def update_bottle_notes(
    bottle_id: int,
    body: BottleNotesUpdate,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """Update a bottle's shared free-text notes.

    Separate from the admin-only field editor so family members can record
    serving/decanting/cocktail notes on any bottle. This endpoint is the ONE
    path that updates notes on existing bottles.
    """
    existing = bottle_repo.get_by_id(bottle_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Bottle not found")

    notes = (body.notes or "").strip() or None
    bottle_dict = existing.model_dump()
    bottle_dict["notes"] = notes
    updated = bottle_repo.update(bottle_id, BottleMetadata(**bottle_dict))

    logger.info(f"Updated notes for bottle {bottle_id} ({existing.producer} - {existing.name})")
    return {"status": "success", "notes": updated.notes}


@router.post("/api/v1/bottles/tastings-summary", dependencies=[Depends(require("tastings.view"))])
async def bottles_tastings_summary(
    request: Request,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
    tasting_repo: SQLiteTastingRepository = Depends(get_tasting_repo),
):
    """Proxy to management tastings-summary, requires tastings.view (admin + family)."""
    return await get_bottle_tastings_summary(request, bottle_repo, tasting_repo)


@router.post("/api/v1/bottles/tastings-list", dependencies=[Depends(require("tastings.view"))])
async def bottles_tastings_list(
    request: Request,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
    tasting_repo: SQLiteTastingRepository = Depends(get_tasting_repo),
):
    """Proxy to management tastings-list, requires tastings.view (admin + family)."""
    return await get_bottle_tastings_list(request, bottle_repo, tasting_repo)
