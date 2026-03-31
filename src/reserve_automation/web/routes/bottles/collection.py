"""Bottle collection routes - public grid view accessible to all authenticated users."""

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from loguru import logger

from ...auth.dependencies import require
from ....db.repositories import get_bottle_repo
from ....db.repositories.bottle_repo import SQLiteBottleRepository
from ..management.core import get_bottle_tastings_summary, get_bottle_tastings_list

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
async def bottles_tastings_summary(request: Request):
    """Proxy to management tastings-summary, requires tastings.view (admin + family)."""
    return await get_bottle_tastings_summary(request)


@router.post("/api/v1/bottles/tastings-list", dependencies=[Depends(require("tastings.view"))])
async def bottles_tastings_list(request: Request):
    """Proxy to management tastings-list, requires tastings.view (admin + family)."""
    return await get_bottle_tastings_list(request)
