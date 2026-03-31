"""Management routes for bottle metadata updates and admin functions."""

#CLAUDE_REQ: Bottle CRUD uses SQLiteBottleRepository (db/repositories/bottle_repo.py)
#CLAUDE_REQ: Tasting reads use SQLiteTastingRepository (db/repositories/tasting_repo.py)
#CLAUDE_REQ: BottleMetadata model (core/models.py) - fields must match DB schema
#CLAUDE_REQ: TastingNote model (core/tasting_note.py) - fields must match DB schema

from pathlib import Path
from typing import Dict, Optional
from fastapi import APIRouter, Depends, Request, HTTPException, BackgroundTasks
from ...auth.dependencies import require
from fastapi.responses import HTMLResponse
from loguru import logger

from ....core.models import BottleMetadata
from ....db.repositories import get_bottle_repo, get_tasting_repo
from ....db.repositories.bottle_repo import SQLiteBottleRepository
from ....db.repositories.tasting_repo import SQLiteTastingRepository
from ...services.extraction_service import ExtractionService

router = APIRouter(dependencies=[Depends(require("management.access"))])

# In-memory storage for verification results
# In production, this should be Redis or a database
verification_results: Dict[str, dict] = {}
batch_status: Dict[str, dict] = {}
task_results: Dict[str, dict] = {}  # Single task results (key: task_id)


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
    optional_fields = ['year', 'price', 'abv', 'proof', 'vintage', 'age_statement', 'value_for_money']
    for field in optional_fields:
        if field in cleaned and (cleaned[field] == '' or cleaned[field] is None):
            cleaned[field] = None

    # Fields with defaults - remove if empty/None so Pydantic uses default
    fields_with_defaults = ['inventory', 'buy', 'confidence']
    for field in fields_with_defaults:
        if field in cleaned and (cleaned[field] == '' or cleaned[field] is None):
            del cleaned[field]

    return cleaned


def get_temp_label_dir(vault_path: str) -> Path:
    """
    Get temporary directory for label operations on a specific bottle.

    Uses /tmp to avoid cluttering Obsidian vault with intermediate files.
    Only final accepted label.jpg is saved to vault.

    Args:
        vault_path: The vault_path from BottleMetadata (e.g., "1_Wines/Producer - Name - Year")
    """
    # Use vault_path as unique identifier, replacing slashes with underscores
    safe_path = vault_path.replace("/", "_").replace(" ", "_")
    temp_dir = Path("/tmp/reserve-automation/labels") / safe_path
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


@router.get("/management", response_class=HTMLResponse)
async def management_page(request: Request):
    """
    Render the management page.

    This page provides administrative functions including:
    - Update all bottle metadata
    """
    from ...app import templates

    return templates.TemplateResponse(request, "management.html", {})


@router.get("/api/v1/management/bottles")
async def get_all_vault_bottles(
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Get all bottles from the database.

    Returns:
        dict: Contains list of bottles with their current metadata
    """
    try:
        bottles = bottle_repo.get_all()
        bottles_data = [bottle.model_dump(mode='json') for bottle in bottles]

        logger.info(f"Loaded {len(bottles)} bottles from database")

        return {
            "bottles": bottles_data,
            "count": len(bottles)
        }

    except Exception as e:
        logger.error(f"Failed to load bottles from database: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/management/bottles/search")
async def search_bottles(
    q: str,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Search for bottles by name, producer, variety, or region.

    Args:
        q: Search query

    Returns:
        dict: List of matching bottles
    """
    try:
        matches = bottle_repo.search(q)
        bottles_data = [b.model_dump(mode='json') for b in matches]

        logger.info(f"Search for '{q}' returned {len(matches)} results")

        return {
            "bottles": bottles_data,
            "count": len(matches),
            "query": q
        }

    except Exception as e:
        logger.error(f"Failed to search bottles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/bottles/tastings-summary")
async def get_bottle_tastings_summary(
    request: Request,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
    tasting_repo: SQLiteTastingRepository = Depends(get_tasting_repo),
):
    """
    Get summary statistics for all tastings of a bottle.

    Returns:
    - tasting_count: Number of tastings
    - avg_score: Average total score across all tastings
    - max_score: Maximum possible score for bottle type
    - latest_date: Most recent tasting date
    - earliest_date: Oldest tasting date
    - tasters: List of unique taster names
    """
    try:
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        bottle_id = bottle.id
        if not bottle_id:
            raise HTTPException(status_code=400, detail="Bottle must have an id")

        summary = tasting_repo.get_summary_for_bottle(int(bottle_id))

        # Ensure max_score is set based on bottle type if not in summary
        if summary.get("max_score") is None:
            summary["max_score"] = 100 if bottle.type == "wine" else 10

        return summary

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tasting summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/bottles/tastings-list")
async def get_bottle_tastings_list(
    request: Request,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
    tasting_repo: SQLiteTastingRepository = Depends(get_tasting_repo),
):
    """
    Get full list of tastings for a bottle with all scores and notes.

    Returns list of tastings sorted by date descending (newest first).
    Each tasting includes individual scores, total score, and tasting notes.
    """
    try:
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        bottle_id = bottle.id
        if not bottle_id:
            raise HTTPException(status_code=400, detail="Bottle must have an id")

        tasting_notes = tasting_repo.get_by_bottle_id(int(bottle_id))

        if not tasting_notes:
            return {
                "tastings": [],
                "bottle_type": bottle.type
            }

        tastings = []
        for tn in tasting_notes:
            tasting_data = {
                "filename": f"Tasting-{tn.tasting_date}-{tn.taster_name}.md",
                "date": tn.tasting_date,
                "taster": tn.taster_name,
                "scores": {},
                "total_score": None,
                "max_score": 100 if bottle.type == "wine" else 10,
                "notes": {}
            }

            if bottle.type == "wine":
                tasting_data["scores"] = {
                    "appearance": tn.wine_appearance,
                    "aroma": tn.wine_aroma,
                    "taste": tn.wine_taste,
                    "aftertaste": tn.wine_aftertaste,
                    "overall": tn.wine_overall,
                }
                # Calculate total score from components
                component_values = [v for v in tasting_data["scores"].values() if v is not None]
                if component_values:
                    aws_score = sum(component_values)
                    tasting_data["aws_score"] = round(aws_score, 1)
                    tasting_data["total_score"] = round(50 + (aws_score / 20) * 50, 1)
                else:
                    tasting_data["aws_score"] = None

                tasting_data["notes"] = {
                    "appearance": tn.appearance_notes or [],
                    "aroma": tn.nose_notes or [],
                    "taste": tn.palate_notes or [],
                    "aftertaste": tn.finish_notes or [],
                    "overall": tn.overall_notes or ""
                }
            else:
                tasting_data["scores"] = {
                    "nose": tn.whiskey_nose,
                    "palate": tn.whiskey_palate,
                    "finish": tn.whiskey_finish,
                    "overall": tn.whiskey_overall,
                }
                tasting_data["days_from_crack"] = tn.days_from_crack
                tasting_data["fill_level"] = tn.fill_level

                # Calculate total score from components
                component_values = [v for v in tasting_data["scores"].values() if v is not None]
                if component_values:
                    tasting_data["total_score"] = round(sum(component_values), 2)

                tasting_data["notes"] = {
                    "nose": tn.nose_notes or [],
                    "palate": tn.palate_notes or [],
                    "finish": tn.finish_notes or [],
                    "overall": tn.overall_notes or ""
                }

            tastings.append(tasting_data)

        # Sort by date descending (newest first)
        tastings.sort(key=lambda t: t["date"], reverse=True)

        return {
            "tastings": tastings,
            "bottle_type": bottle.type
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tasting list: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/management/tastings")
async def get_all_tastings(
    request: Request,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
    tasting_repo: SQLiteTastingRepository = Depends(get_tasting_repo),
):
    """
    Get all tasting records across all bottles.

    Returns:
    - tastings: List of all tasting records, sorted newest-first
    - tasters: Sorted list of unique taster names
    - types: Sorted list of tasting types present
    """
    import math

    try:
        bottles = bottle_repo.get_all()
        tastings = []
        tasters: set = set()
        types: set = set()

        for bottle in bottles:
            bottle_id = int(bottle.id) if bottle.id else None
            if bottle_id is None:
                continue

            bottle_tastings = tasting_repo.get_by_bottle_id(bottle_id)

            for tn in bottle_tastings:
                tasting_type = tn.beverage_type or bottle.type or "whiskey"

                tasting_data: dict = {
                    "bottle_name": tn.bottle_name or f"{bottle.producer} - {bottle.name}",
                    "bottle_path": bottle.vault_path or "",
                    "date": tn.tasting_date,
                    "taster": tn.taster_name,
                    "type": tasting_type,
                    "total_score": None,
                    "max_score": None,
                    "aws_score": None,
                    "days_from_crack": tn.days_from_crack,
                    "fill_level": tn.fill_level,
                    "bartender": None,
                    "scores": {},
                    "notes": {},
                    # Bottle metadata from the bottle record
                    "producer": bottle.producer,
                    "variety": bottle.variety,
                    "country_region": f"{bottle.country} - {bottle.region}" if bottle.country and bottle.region else (bottle.country or bottle.region or None),
                    "style": bottle.style,
                    "wine_type": bottle.beverage_type if tasting_type == "wine" else None,
                    "vineyard": bottle.vineyard,
                    "abv": bottle.abv,
                    "price": bottle.price,
                    "purchase_source": bottle.purchase_source,
                    "vintage": bottle.year if tasting_type == "wine" else None,
                    "whiskey_type": bottle.beverage_type if tasting_type == "whiskey" else None,
                    "region_state": bottle.region if tasting_type == "whiskey" else None,
                    "proof": bottle.proof,
                    "age_statement": bottle.age_statement,
                    "mash_bill": bottle.mash_bill,
                    "barrel_type": bottle.barrel_type,
                }

                if tasting_type == "wine":
                    tasting_data["max_score"] = 100
                    tasting_data["scores"] = {
                        "appearance": tn.wine_appearance,
                        "aroma": tn.wine_aroma,
                        "taste": tn.wine_taste,
                        "aftertaste": tn.wine_aftertaste,
                        "overall": tn.wine_overall,
                    }
                    component_values = [v for v in tasting_data["scores"].values() if v is not None]
                    if component_values:
                        aws_score = sum(component_values)
                        tasting_data["aws_score"] = round(aws_score, 1)
                        tasting_data["total_score"] = round(50 + (aws_score / 20) * 50, 1)

                    tasting_data["notes"] = {
                        "appearance": tn.appearance_notes or [],
                        "aroma": tn.nose_notes or [],
                        "taste": tn.palate_notes or [],
                        "aftertaste": tn.finish_notes or [],
                        "overall": tn.overall_notes or ""
                    }

                elif tasting_type == "cocktail":
                    tasting_data["max_score"] = 10
                    # Cocktail tastings may store score in whiskey_overall or similar
                    score = tn.whiskey_overall
                    tasting_data["scores"] = {"score": score}
                    tasting_data["total_score"] = score
                    tasting_data["notes"] = {"notes": tn.overall_notes or ""}

                else:
                    # whiskey / spirit
                    tasting_data["max_score"] = 10
                    tasting_data["scores"] = {
                        "nose": tn.whiskey_nose,
                        "palate": tn.whiskey_palate,
                        "finish": tn.whiskey_finish,
                        "overall": tn.whiskey_overall,
                    }
                    component_values = [v for v in tasting_data["scores"].values() if v is not None]
                    if component_values:
                        tasting_data["total_score"] = round(sum(component_values), 2)

                    tasting_data["notes"] = {
                        "nose": tn.nose_notes or [],
                        "palate": tn.palate_notes or [],
                        "finish": tn.finish_notes or [],
                        "overall": tn.overall_notes or ""
                    }

                # Sanitize: replace any NaN/Inf with None
                for k, v in tasting_data.items():
                    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                        tasting_data[k] = None
                    elif isinstance(v, dict):
                        for sk, sv in v.items():
                            if isinstance(sv, float) and (math.isnan(sv) or math.isinf(sv)):
                                v[sk] = None

                tastings.append(tasting_data)
                tasters.add(tn.taster_name)
                types.add(tasting_type)

        tastings.sort(key=lambda t: t["date"], reverse=True)

        # Build filter options: unique non-null values for type-specific fields
        filter_options: dict = {
            "variety": sorted({t["variety"] for t in tastings if t.get("variety")}),
            "country_region": sorted({t["country_region"] for t in tastings if t.get("country_region")}),
            "style": sorted({t["style"] for t in tastings if t.get("style")}),
            "wine_type": sorted({t["wine_type"] for t in tastings if t.get("wine_type")}),
            "whiskey_type": sorted({t["whiskey_type"] for t in tastings if t.get("whiskey_type")}),
            "region_state": sorted({t["region_state"] for t in tastings if t.get("region_state")}),
            "barrel_type": sorted({t["barrel_type"] for t in tastings if t.get("barrel_type")}),
        }

        return {
            "tastings": tastings,
            "tasters": sorted(list(tasters)),
            "types": sorted(list(types)),
            "filter_options": filter_options,
        }

    except Exception as e:
        logger.error(f"Failed to get all tastings: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


def _parse_float(value) -> float | None:
    """Parse a value to float, returning None if invalid or NaN/Inf."""
    if value is None:
        return None
    try:
        import math
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except (ValueError, TypeError):
        return None


def _parse_int(value) -> int | None:
    """Parse a value to int, returning None if invalid."""
    if value is None:
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


def _parse_whiskey_notes(body_content: str) -> dict:
    """Parse tasting notes from whiskey tasting file body."""
    import re

    notes = {
        "nose": [],
        "palate": [],
        "finish": [],
        "overall": ""
    }

    # Split by sections
    sections = re.split(r'###\s+', body_content)

    for section in sections:
        section_lower = section.lower().strip()

        if section_lower.startswith("nose"):
            # Extract hashtags
            notes["nose"] = _extract_hashtags(section)
        elif section_lower.startswith("palate"):
            notes["palate"] = _extract_hashtags(section)
        elif section_lower.startswith("finish"):
            notes["finish"] = _extract_hashtags(section)
        elif section_lower.startswith("overall"):
            # Get text after the header line
            lines = section.split('\n', 1)
            if len(lines) > 1:
                notes["overall"] = lines[1].strip()

    return notes


def _parse_wine_notes(body_content: str) -> dict:
    """Parse tasting notes from wine tasting file body."""
    import re

    notes = {
        "appearance": [],
        "aroma": [],
        "taste": [],
        "aftertaste": [],
        "overall": ""
    }

    sections = re.split(r'###\s+', body_content)

    for section in sections:
        section_lower = section.lower().strip()

        if section_lower.startswith("appearance"):
            # Appearance may have plain text descriptions
            lines = section.split('\n', 1)
            if len(lines) > 1:
                text = lines[1].strip()
                if text:
                    notes["appearance"] = [line.strip() for line in text.split('\n') if line.strip()]
        elif section_lower.startswith("aroma"):
            notes["aroma"] = _extract_hashtags(section)
        elif section_lower.startswith("taste"):
            notes["taste"] = _extract_hashtags(section)
        elif section_lower.startswith("aftertaste"):
            notes["aftertaste"] = _extract_hashtags(section)
        elif section_lower.startswith("overall"):
            lines = section.split('\n', 1)
            if len(lines) > 1:
                notes["overall"] = lines[1].strip()

    return notes


def _extract_hashtags(text: str) -> list[str]:
    """Extract hashtag values from text, removing the # prefix."""
    import re
    hashtags = re.findall(r'#(\S+)', text)
    # Replace underscores with spaces for display
    return [tag.replace('_', ' ') for tag in hashtags]


@router.post("/api/v1/management/bottles/verify")
async def verify_bottle(request: Request, background_tasks: BackgroundTasks):
    """
    Verify and enrich metadata for a bottle (async with polling).

    Used by the unified bottle editor modal for both upload and management workflows.
    Returns immediately with a task_id - client should poll /api/v1/management/tasks/{task_id}/status

    Args:
        request: Request containing the bottle data
        background_tasks: FastAPI background tasks

    Returns:
        dict: Contains task_id and status
    """
    from ...app import core_config
    import uuid
    import time

    try:
        # Get the bottle data from request body
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Bottle data not provided")

        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(bottle_data)

        # Generate task ID
        task_id = str(uuid.uuid4())

        # Initialize task status
        task_results[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "created_at": time.time()
        }

        # Queue background verification
        background_tasks.add_task(
            verify_single_bottle_background,
            task_id,
            cleaned_bottle_data,
            core_config
        )

        logger.info(f"Started async verification task {task_id} for bottle")

        return {
            "task_id": task_id,
            "status": "queued"
        }

    except Exception as e:
        logger.error(f"Failed to queue verification task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/bottles/{bottle_index}/verify")
async def verify_bottle_metadata(bottle_index: int, request: Request, background_tasks: BackgroundTasks):
    """
    Verify and get updated metadata for a specific bottle (async with polling).

    Returns immediately with a task_id - client should poll /api/v1/management/tasks/{task_id}/status

    Args:
        bottle_index: Index of bottle in the vault bottles list
        request: Request containing the bottle data
        background_tasks: FastAPI background tasks

    Returns:
        dict: Contains task_id and status
    """
    from ...app import core_config
    import uuid
    import time

    try:
        # Get the bottle data from request body
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Bottle data not provided")

        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(bottle_data)

        # Generate task ID
        task_id = str(uuid.uuid4())

        # Initialize task status
        task_results[task_id] = {
            "task_id": task_id,
            "status": "queued",
            "bottle_index": bottle_index,
            "created_at": time.time()
        }

        # Queue background verification
        background_tasks.add_task(
            verify_single_bottle_background,
            task_id,
            cleaned_bottle_data,
            core_config
        )

        logger.info(f"Started async verification task {task_id} for bottle {bottle_index}")

        return {
            "task_id": task_id,
            "status": "queued",
            "bottle_index": bottle_index
        }

    except Exception as e:
        logger.error(f"Failed to queue verification task for bottle {bottle_index}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/bottles/{bottle_index}/update")
async def update_bottle_metadata(
    bottle_index: int,
    request: Request,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Apply approved metadata changes to a bottle in the database.

    Args:
        bottle_index: Index of bottle (used as bottle ID)
        request: Request containing the updated bottle data

    Returns:
        dict: Status of the update operation
    """
    try:
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Bottle data not provided")

        # Clean and convert to BottleMetadata
        cleaned_data = clean_bottle_data(bottle_data)
        bottle = BottleMetadata(**cleaned_data)

        # Use the bottle's own ID if available, otherwise use bottle_index
        bid = int(bottle.id) if bottle.id else bottle_index

        # Update in database
        result = bottle_repo.update(bid, bottle)

        logger.info(f"Updated bottle {bid}: {bottle.producer} - {bottle.name}")

        return {
            "status": "success",
            "bottle": result.model_dump(mode='json'),
        }

    except Exception as e:
        logger.error(f"Failed to update bottle {bottle_index}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


async def verify_bottle_background(batch_id: str, bottle_index: int, bottle_data: dict, core_config):
    """
    Background task to verify a single bottle's metadata.

    Args:
        batch_id: ID of the batch this bottle belongs to
        bottle_index: Index of the bottle
        bottle_data: Bottle metadata dict
        core_config: Core configuration
    """
    try:
        bottle = BottleMetadata(**bottle_data)
        extraction_service = ExtractionService(core_config)

        # Verify the bottle
        updated_bottle, metadata = await extraction_service.enrich_bottle(bottle)

        changes = metadata.get("changes", {})

        # Store result
        result_key = f"{batch_id}:{bottle_index}"
        verification_results[result_key] = {
            "bottle_index": bottle_index,
            "original": bottle_data,
            "updated": updated_bottle.model_dump(mode='json'),
            "changes": changes,
            "metadata": metadata,
            "status": "completed",
            "has_changes": len(changes) > 0
        }

        # Update batch status
        if batch_id in batch_status:
            batch_status[batch_id]["completed"] += 1
            if changes:
                batch_status[batch_id]["with_changes"] += 1

        logger.info(f"Batch {batch_id}: Verified bottle {bottle_index} - {len(changes)} changes found")

    except Exception as e:
        logger.error(f"Batch {batch_id}: Failed to verify bottle {bottle_index}: {e}", exc_info=True)

        # Store error
        result_key = f"{batch_id}:{bottle_index}"
        verification_results[result_key] = {
            "bottle_index": bottle_index,
            "original": bottle_data,
            "status": "error",
            "error": str(e)
        }

        # Update batch status
        if batch_id in batch_status:
            batch_status[batch_id]["completed"] += 1
            batch_status[batch_id]["errors"] += 1


async def verify_single_bottle_background(task_id: str, bottle_data: dict, core_config):
    """
    Background task to verify a single bottle's metadata (for single-bottle operations).

    Args:
        task_id: Unique task ID
        bottle_data: Bottle metadata dict
        core_config: Core configuration
    """
    import time

    try:
        # Update status to processing
        task_results[task_id]["status"] = "processing"
        task_results[task_id]["started_at"] = time.time()

        bottle = BottleMetadata(**bottle_data)
        extraction_service = ExtractionService(core_config)

        # Verify the bottle
        updated_bottle, metadata = await extraction_service.enrich_bottle(bottle)

        changes = metadata.get("changes", {})

        # Store result
        task_results[task_id] = {
            "task_id": task_id,
            "original": bottle_data,
            "updated": updated_bottle.model_dump(mode='json'),
            "changes": changes,
            "metadata": metadata,
            "status": "complete",
            "has_changes": len(changes) > 0,
            "completed_at": time.time()
        }

        logger.info(f"Task {task_id}: Verified bottle - {len(changes)} changes found")

    except Exception as e:
        logger.error(f"Task {task_id}: Failed to verify bottle: {e}", exc_info=True)

        # Store error
        task_results[task_id] = {
            "task_id": task_id,
            "original": bottle_data,
            "status": "failed",
            "error": str(e),
            "completed_at": time.time()
        }


def cleanup_expired_tasks(ttl_seconds: int = 3600):
    """
    Clean up expired task results older than TTL.

    Args:
        ttl_seconds: Time-to-live in seconds (default: 1 hour)
    """
    import time

    current_time = time.time()
    expired_tasks = []

    for task_id, task_data in task_results.items():
        # Check if task has completed_at timestamp
        completed_at = task_data.get("completed_at")
        if completed_at and current_time - completed_at > ttl_seconds:
            expired_tasks.append(task_id)

    # Remove expired tasks
    for task_id in expired_tasks:
        del task_results[task_id]
        logger.debug(f"Cleaned up expired task {task_id}")

    if expired_tasks:
        logger.info(f"Cleaned up {len(expired_tasks)} expired tasks")


@router.post("/api/v1/management/bottles/batch-verify")
async def start_batch_verification(
    background_tasks: BackgroundTasks,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Start batch verification of all bottles in the background.

    Returns:
        dict: Batch ID and initial status
    """
    from ...app import core_config
    import uuid

    try:
        bottles = bottle_repo.get_all()
        bottles_data = [bottle.model_dump(mode='json') for bottle in bottles]

        # Generate batch ID
        batch_id = str(uuid.uuid4())

        # Initialize batch status
        batch_status[batch_id] = {
            "batch_id": batch_id,
            "total": len(bottles_data),
            "completed": 0,
            "with_changes": 0,
            "errors": 0,
            "status": "processing"
        }

        # Start background verification for each bottle
        for idx, bottle_data in enumerate(bottles_data):
            background_tasks.add_task(
                verify_bottle_background,
                batch_id,
                idx,
                bottle_data,
                core_config
            )

        logger.info(f"Started batch verification {batch_id} for {len(bottles_data)} bottles")

        return {
            "batch_id": batch_id,
            "status": batch_status[batch_id]
        }

    except Exception as e:
        logger.error(f"Failed to start batch verification: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/management/batch/{batch_id}/status")
async def get_batch_status(batch_id: str):
    """
    Get status of a batch verification.

    Args:
        batch_id: ID of the batch

    Returns:
        dict: Batch status and completed results
    """
    if batch_id not in batch_status:
        raise HTTPException(status_code=404, detail="Batch not found")

    # Get all completed results for this batch
    results = []
    for key, result in verification_results.items():
        if key.startswith(f"{batch_id}:"):
            results.append(result)

    # Sort by bottle index
    results.sort(key=lambda r: r.get("bottle_index", 0))

    # Mark batch as complete if all bottles processed
    status = batch_status[batch_id]
    if status["completed"] >= status["total"]:
        status["status"] = "complete"

    return {
        "batch_id": batch_id,
        "status": status,
        "results": results
    }


@router.get("/api/v1/management/tasks/{task_id}/status")
async def get_task_status(task_id: str):
    """
    Get status of a single verification task.

    Args:
        task_id: ID of the task

    Returns:
        dict: Task status and result (if completed)
    """
    import time

    # Cleanup expired tasks (run on every status check)
    cleanup_expired_tasks()

    if task_id not in task_results:
        raise HTTPException(status_code=404, detail="Task not found")

    task = task_results[task_id]

    # Check for timeout (2 minutes)
    created_at = task.get("created_at", time.time())
    if time.time() - created_at > 120 and task["status"] not in ["complete", "failed"]:
        task["status"] = "failed"
        task["error"] = "Task timed out after 2 minutes"
        logger.warning(f"Task {task_id} timed out")

    return task


@router.post("/api/v1/management/bottles/update-fields")
async def update_bottle_fields(
    request: Request,
    bottle_repo: SQLiteBottleRepository = Depends(get_bottle_repo),
):
    """
    Update specific fields of a bottle (individual field approval).

    Request body:
        - bottle: Original bottle data (with id field for lookup)
        - updates: Dict of field names to new values

    Returns:
        dict: Status of the update operation
    """
    try:
        body = await request.json()
        bottle_data = body.get("bottle")
        updates = body.get("updates", {})

        logger.info(f"Received update request - bottle keys: {list(bottle_data.keys() if bottle_data else [])}")
        logger.info(f"Updates to apply: {updates}")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Bottle data not provided")

        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(bottle_data)

        bottle_id = cleaned_bottle_data.get("id")
        if not bottle_id:
            raise HTTPException(status_code=400, detail="Bottle must have an id")

        # Get existing bottle from database
        existing = bottle_repo.get_by_id(int(bottle_id))
        if not existing:
            raise HTTPException(status_code=404, detail="Bottle not found")

        # Apply updates to the existing bottle
        bottle_dict = existing.model_dump()
        for field, value in updates.items():
            if field in bottle_dict:
                old_value = bottle_dict[field]
                bottle_dict[field] = value
                logger.info(f"Applying update: {field}: {old_value} -> {value}")

        updated_bottle = BottleMetadata(**bottle_dict)
        result = bottle_repo.update(int(bottle_id), updated_bottle)

        logger.info(
            f"Updated bottle {existing.producer} - {existing.name} "
            f"with {len(updates)} field changes"
        )

        return {
            "status": "success",
            "bottle": result.model_dump(mode='json'),
            "updated_fields": list(updates.keys()),
            "moved": False  # No more filesystem moves
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update bottle fields: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Label Quality Review Routes - Simple grid-based workflow
# ============================================================================
