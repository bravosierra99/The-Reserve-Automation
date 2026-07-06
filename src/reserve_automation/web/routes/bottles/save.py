"""Bottle save endpoint - unified save with duplicate detection."""

import os
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel

from ....core.models import BottleMetadata
from ....db.repositories import get_bottle_repo
from ....db.repositories.bottle_repo import SQLiteBottleRepository
from ...auth.dependencies import require
from ...services.duplicate_service import build_duplicate_matches

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "data/media"))

router = APIRouter(dependencies=[Depends(require("bottles.create"))])


def clean_bottle_data(bottle_data: dict) -> dict:
    """
    Clean bottle data by converting empty strings/None to appropriate values.

    This handles the common issue where frontend forms send empty strings ("")
    or null values, but Pydantic expects None or typed values (int/float).

    Args:
        bottle_data: Raw bottle data dictionary (may contain empty strings or None)

    Returns:
        Cleaned bottle data dictionary
    """
    cleaned = bottle_data.copy()

    # Optional numeric fields - convert empty string or None to None
    optional_fields = [
        'year', 'price', 'abv', 'proof', 'vintage', 'age_statement', 'value_for_money'
    ]
    for field in optional_fields:
        if field in cleaned and (cleaned[field] == '' or cleaned[field] is None):
            cleaned[field] = None

    # Fields with defaults - remove if empty/None so Pydantic uses default
    fields_with_defaults = ['inventory', 'buy', 'confidence']
    for field in fields_with_defaults:
        if field in cleaned and (cleaned[field] == '' or cleaned[field] is None):
            del cleaned[field]

    return cleaned


class SaveBottleRequest(BaseModel):
    """Request to save a bottle to the database."""
    bottle: dict  # BottleMetadata as dict
    upload_id: Optional[str] = None  # For accessing temp files
    temp_label_index: Optional[int] = None  # Which temp label to use (for manifest uploads)
    force_save: bool = False  # Skip duplicate check
    replace_vault_path: Optional[str] = None  # Legacy field (ignored)
    replace_bottle_id: Optional[str] = None  # Replace existing bottle with this ID


@router.post("/api/v1/bottles/save")
async def save_bottle(
    request: SaveBottleRequest,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Save bottle to database with duplicate detection.

    Workflow:
    1. Parse bottle metadata
    2. Check for duplicates (unless force_save=True)
    3. If duplicates found, return them for user decision
    4. If no duplicates OR force_save OR replace_bottle_id provided:
       - Save to database
       - Copy temp label to media directory (if available)

    Returns:
        {
            "status": "success" | "duplicate_found",
            "id": str (if success),
            "duplicates": [...] (if duplicate_found)
        }
    """
    try:
        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(request.bottle)

        # Parse bottle metadata
        bottle = BottleMetadata(**cleaned_bottle_data)

        logger.info(f"Save bottle request: {bottle.producer} - {bottle.name} ({bottle.year})")
        logger.info(f"  upload_id: {request.upload_id}")
        logger.info(f"  force_save: {request.force_save}")
        logger.info(f"  replace_bottle_id: {request.replace_bottle_id}")

        # Check for duplicates (unless force_save or replacing).
        # Candidate generation is deliberately broad — every bottle of the same
        # type — and build_duplicate_matches (fuzzy score + threshold) is the
        # single source of truth for what counts as a duplicate.
        if not request.force_save and not request.replace_bottle_id:
            candidates = bottle_repo.get_all(bottle.type)
            duplicates = build_duplicate_matches(bottle, candidates)

            if duplicates:
                logger.info(f"Found {len(duplicates)} potential duplicates")
                return {
                    "status": "duplicate_found",
                    "duplicates": duplicates,
                }

        # No duplicates (or force save) - proceed with save
        bottle_id: str

        if request.replace_bottle_id:
            # Replacing existing bottle
            existing = bottle_repo.get_by_id(int(request.replace_bottle_id))
            if existing:
                bottle_repo.update(int(request.replace_bottle_id), bottle)
                bottle_id = str(request.replace_bottle_id)
                logger.info(f"Updated existing bottle id={bottle_id}")
            else:
                # Old bottle doesn't exist - treat as new
                logger.warning(
                    f"Replace requested but bottle id={request.replace_bottle_id} "
                    "not found, creating new"
                )
                created = bottle_repo.create(bottle)
                bottle_id = str(created.id)
                logger.info(f"Created new bottle id={bottle_id}")
        elif request.force_save:
            # force_save: upsert — update exact match if one exists, otherwise create.
            # Prevents a DB UNIQUE constraint error when the user overrides detection
            # for a truly identical bottle (e.g. re-scanning the same label).
            exact = bottle_repo.find_exact(bottle.producer, bottle.name, bottle.year, bottle.type)
            if exact:
                bottle_repo.update(int(exact.id), bottle)
                bottle_id = str(exact.id)
                logger.info(f"force_save: updated exact-match bottle id={bottle_id}")
            else:
                created = bottle_repo.create(bottle)
                bottle_id = str(created.id)
                logger.info(f"force_save: created new bottle id={bottle_id}")
        else:
            # New bottle
            created = bottle_repo.create(bottle)
            bottle_id = str(created.id)
            logger.info(f"Created new bottle id={bottle_id}")

        # Copy label from temp directory (if available)
        if request.upload_id:
            temp_upload_dir = Path("/tmp/reserve_uploads") / request.upload_id
            temp_labels_dir = temp_upload_dir / "labels"

            # Determine which temp label to use
            if request.temp_label_index is not None:
                temp_label = temp_labels_dir / f"{request.temp_label_index}.jpg"
            else:
                temp_label = temp_labels_dir / "label.jpg"

            if temp_label.exists():
                # A bottle's label must be an actual image — manifest uploads used
                # to leave the source invoice PDF here (GROUND_TRUTH.md #4).
                from ....utils.image_validation import validate_label_image
                label_ok, label_detail = validate_label_image(temp_label, min_long_side=0)
                if not label_ok:
                    logger.warning(f"Skipping label copy for bottle {bottle_id}: {label_detail}")
                else:
                    label_dir = MEDIA_DIR / "bottles" / bottle_id
                    label_dir.mkdir(parents=True, exist_ok=True)
                    dest_label = label_dir / "label.jpg"
                    logger.info(f"Copying label: {temp_label} -> {dest_label}")
                    shutil.copy2(temp_label, dest_label)

                    # Update label path in DB
                    bottle_repo.update_label_path(int(bottle_id), f"bottles/{bottle_id}/label.jpg")
            else:
                logger.warning(f"Temp label not found: {temp_label}")
                if temp_upload_dir.exists():
                    dir_contents = list(temp_upload_dir.iterdir())
                else:
                    dir_contents = "directory does not exist"
                logger.warning(f"  Upload dir contents: {dir_contents}")

        logger.info(f"Bottle saved successfully: id={bottle_id}")

        return {
            "status": "success",
            "id": bottle_id,
            "message": f"Bottle saved: {bottle.producer} - {bottle.name}",
        }

    except Exception as e:
        logger.error(f"Save bottle failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/check-duplicates")
async def check_duplicates_manual(
    bottle_data: dict,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Manually check for duplicate bottles in the database.

    Used by the bottle editor modal to allow users to manually trigger
    duplicate detection at any time (not just on save).

    Args:
        bottle_data: Bottle metadata as dict

    Returns:
        {
            "status": "checked",
            "duplicates": [...] (with id, producer, name, year, confidence, reason),
            "count": int
        }
    """
    try:
        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(bottle_data)

        # Parse bottle metadata
        bottle = BottleMetadata(**cleaned_bottle_data)

        logger.info(f"Manual duplicate check: {bottle.producer} - {bottle.name} ({bottle.year})")
        logger.info(f"  Bottle type: {bottle.type}")

        # Broad candidate pool (same type); build_duplicate_matches fuzzy-scores
        # and thresholds — the single source of truth for duplicate detection.
        candidates = bottle_repo.get_all(bottle.type)
        duplicates = build_duplicate_matches(bottle, candidates)

        logger.info(f"Found {len(duplicates)} potential duplicates")

        return {
            "status": "checked",
            "duplicates": duplicates,
            "count": len(duplicates),
        }

    except Exception as e:
        logger.error(f"Manual duplicate check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
