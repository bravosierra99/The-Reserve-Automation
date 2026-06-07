"""Bottle collection routes - public grid view accessible to all authenticated users."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from loguru import logger

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
