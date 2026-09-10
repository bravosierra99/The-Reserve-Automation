"""Bottle collection routes - public grid view accessible to all authenticated users."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from ....core.models import BottleMetadata
from ....db.engine import get_db
from ....db.models.bottle import TastingNoteModel
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
    db: Session = Depends(get_db),
):
    """
    Get all bottles for the collection grid view.

    Each bottle carries a `tasting_count` so the grid can filter on "not yet
    rated" without a per-bottle round trip (the tastings-summary endpoint is
    one POST per bottle -- unusable for a 150-bottle grid). Counted with a
    single GROUP BY.

    "Rated" deliberately means `tasting_count > 0` -- any tasting row counts as
    feedback given, including hidden rows and rows saved with notes but no
    sub-scores. The question this answers is "have I said anything about this
    bottle yet", not "is the rating complete".

    Returns:
        dict: Contains list of bottles with their current metadata (with IDs)
    """
    try:
        bottles = bottle_repo.get_all()

        counts = dict(
            db.query(TastingNoteModel.bottle_id, func.count(TastingNoteModel.id))
            .group_by(TastingNoteModel.bottle_id)
            .all()
        )

        bottles_data = []
        for bottle in bottles:
            data = bottle.model_dump(mode='json')
            data["tasting_count"] = counts.get(int(bottle.id), 0) if bottle.id else 0
            bottles_data.append(data)

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
