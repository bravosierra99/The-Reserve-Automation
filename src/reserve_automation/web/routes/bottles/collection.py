"""Bottle collection routes - public grid view accessible to all authenticated users."""

from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.responses import HTMLResponse
from loguru import logger

from ...auth.dependencies import require
from ....utils.vault_reader import VaultReader
from ..management.core import get_bottle_tastings_summary, get_bottle_tastings_list

router = APIRouter(dependencies=[Depends(require("bottles.view"))])


@router.get("/bottles", response_class=HTMLResponse)
async def bottles_page(request: Request):
    """Render the bottle collection grid page (accessible to all roles)."""
    from ...app import templates

    return templates.TemplateResponse(request, "bottles.html", {})


@router.get("/api/v1/bottles/collection")
async def get_bottle_collection():
    """
    Get all bottles for the collection grid view.

    Same data as management/bottles but with bottles.view permission
    so all authenticated users can browse the collection.

    Returns:
        dict: Contains list of bottles with their current metadata (with IDs)
    """
    from ... import app as app_module
    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

    try:
        vault_reader = VaultReader(core_config.vault_path, registry=bottle_registry)
        bottles = vault_reader.read_all_bottles()
        bottles_data = [bottle.model_dump(mode='json') for bottle in bottles]

        logger.info(f"Collection: loaded {len(bottles)} bottles")

        return {
            "bottles": bottles_data,
            "count": len(bottles)
        }

    except Exception as e:
        logger.error(f"Failed to load bottles for collection: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/tastings-summary")
async def bottles_tastings_summary(request: Request):
    """Proxy to management tastings-summary with bottles.view permission."""
    return await get_bottle_tastings_summary(request)


@router.post("/api/v1/bottles/tastings-list")
async def bottles_tastings_list(request: Request):
    """Proxy to management tastings-list with bottles.view permission."""
    return await get_bottle_tastings_list(request)
