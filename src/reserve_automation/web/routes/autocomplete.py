"""Autocomplete endpoints — return sorted unique field values for datalist suggestions."""

# #CLAUDE_REQ: BOTTLE_AUTOCOMPLETE_FIELDS must stay in sync with _BOTTLE_CLEANUP_FIELDS in management/core.py
# #CLAUDE_REQ: TASTING_AUTOCOMPLETE_FIELDS must stay in sync with _TASTING_CLEANUP_FIELDS in management/core.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..auth.dependencies import require
from ...db.engine import get_db
from ...db.models.bottle import BottleModel, TastingNoteModel

BOTTLE_AUTOCOMPLETE_FIELDS = frozenset([
    "producer", "region", "country", "beverage_type",
    "style", "vineyard", "purchase_source", "barrel_type",
])  # variety excluded: stored as JSON list, requires dedicated endpoint
TASTING_AUTOCOMPLETE_FIELDS = frozenset(["taster_name", "place", "theme"])

router = APIRouter(prefix="/api/v1/autocomplete")


def _dedup_casefold(rows: list[tuple]) -> list[str]:
    """Case-insensitive dedup: keep the highest-count variant for each lowercase key."""
    seen: dict[str, tuple[str, int]] = {}
    for value, cnt in rows:
        key = value.casefold()
        if key not in seen or cnt > seen[key][1]:
            seen[key] = (value, cnt)
    return sorted((v for v, _ in seen.values()), key=str.casefold)


@router.get("/bottles/{field}", dependencies=[Depends(require("bottles.view"))])
def autocomplete_bottles(field: str, q: str = "", db: Session = Depends(get_db)):
    if field not in BOTTLE_AUTOCOMPLETE_FIELDS:
        raise HTTPException(status_code=400, detail=f"Field '{field}' not supported")
    col = getattr(BottleModel, field)
    stmt = (
        select(col, func.count().label("cnt"))
        .where(col.isnot(None), col != "")
        .group_by(col)
        .order_by(func.count().desc())
    )
    if q:
        stmt = stmt.where(col.ilike(f"%{q}%"))
    return _dedup_casefold(db.execute(stmt).all())


@router.get("/tastings/{field}", dependencies=[Depends(require("tastings.view"))])
def autocomplete_tastings(field: str, q: str = "", db: Session = Depends(get_db)):
    if field not in TASTING_AUTOCOMPLETE_FIELDS:
        raise HTTPException(status_code=400, detail=f"Field '{field}' not supported")
    col = getattr(TastingNoteModel, field)
    stmt = (
        select(col, func.count().label("cnt"))
        .where(col.isnot(None), col != "")
        .group_by(col)
        .order_by(func.count().desc())
    )
    if q:
        stmt = stmt.where(col.ilike(f"%{q}%"))
    return _dedup_casefold(db.execute(stmt).all())
