"""Management routes for bottle metadata updates and admin functions."""

#CLAUDE_REQ: When adding/modifying field_name_map, verify coherence with:
#CLAUDE_REQ: - BottleMetadata model (core/models.py) - model field names on left
#CLAUDE_REQ: - Obsidian FileClass (the-reserve/Cellar/8_FileClass/*.md) - Obsidian field names on right
#CLAUDE_REQ: - Wine: Winemaker/WineName/Vintage/Country-Region/ABV/Variety/Vineyard
#CLAUDE_REQ: - Whiskey: Distiller/WhiskeyName/Year/Region-State/Proof/AgeStatement/MashBill/BarrelType
#CLAUDE_REQ: - Composite Name field updates when producer/name/year change (see line ~597)

import asyncio
import re
from pathlib import Path
from shutil import copyfile
from typing import Dict, Optional
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks, UploadFile, Form
from fastapi.responses import HTMLResponse, FileResponse
from loguru import logger

from ....utils.vault_reader import VaultReader
from ...services.extraction_service import ExtractionService

router = APIRouter()

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
    - Update all bottle metadata from vault
    """
    import os
    from ...app import templates, web_config, core_config

    # Debug: check environment variable and config
    env_vault = os.getenv("RESERVE_VAULT_PATH")
    logger.info(f"Management page: RESERVE_VAULT_PATH env = {env_vault}")
    logger.info(f"Management page: core_config.paths = {core_config.paths}")
    logger.info(f"Management page: core_config.vault_path = {core_config.vault_path}")

    return templates.TemplateResponse(request, "management.html", {})


@router.get("/api/v1/management/bottles")
async def get_all_vault_bottles():
    """
    Get all bottles from the vault for metadata update.

    Returns:
        dict: Contains list of bottles with their current metadata (with IDs, without vault_paths)
    """
    from ... import app as app_module
    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

    logger.info(f"get_all_vault_bottles: bottle_registry={bottle_registry}, is None={bottle_registry is None}")

    try:
        # Pass registry so bottles get registered and assigned IDs
        vault_reader = VaultReader(core_config.vault_path, registry=bottle_registry)
        bottles = vault_reader.read_all_bottles()

        # Convert to dict format
        bottles_data = [bottle.model_dump(mode='json') for bottle in bottles]

        logger.info(f"Loaded {len(bottles)} bottles from vault for metadata update")

        return {
            "bottles": bottles_data,
            "count": len(bottles)
        }

    except Exception as e:
        logger.error(f"Failed to load bottles from vault: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/management/bottles/search")
async def search_bottles(q: str):
    """
    Search for bottles by name or producer.

    Args:
        q: Search query

    Returns:
        dict: List of matching bottles (with IDs, without vault_paths)
    """
    from ... import app as app_module
    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry

    try:
        # Pass registry so bottles get registered and assigned IDs
        vault_reader = VaultReader(core_config.vault_path, registry=bottle_registry)
        all_bottles = vault_reader.read_all_bottles()

        # Filter bottles by search query
        query_lower = q.lower()
        matches = []
        for idx, bottle in enumerate(all_bottles):
            if (query_lower in bottle.producer.lower() or
                query_lower in bottle.name.lower() or
                (bottle.year and str(bottle.year) in query_lower)):
                bottle_dict = bottle.model_dump(mode='json')
                bottle_dict['_index'] = idx  # Add index for later reference
                matches.append(bottle_dict)

        logger.info(f"Search for '{q}' returned {len(matches)} results")

        return {
            "bottles": matches,
            "count": len(matches),
            "query": q
        }

    except Exception as e:
        logger.error(f"Failed to search bottles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/bottles/tastings-summary")
async def get_bottle_tastings_summary(request: Request):
    """
    Get summary statistics for all tastings of a bottle.

    Returns:
    - tasting_count: Number of tasting files
    - avg_score: Average total score across all tastings
    - max_score: Maximum possible score for bottle type
    - latest_date: Most recent tasting date
    - earliest_date: Oldest tasting date
    - tasters: List of unique taster names
    """
    from ... import app as app_module
    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry
    from ....core.models import BottleMetadata
    from pathlib import Path
    import re
    from datetime import datetime

    try:
        # Get bottle data from request body
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        # Resolve vault_path from bottle ID if not provided directly
        vault_path_str = bottle.vault_path
        if not vault_path_str and bottle.id and bottle_registry:
            vault_path_str = bottle_registry.get_path(bottle.id)

        if not vault_path_str:
            raise HTTPException(status_code=404, detail="Bottle has no vault path and ID could not be resolved")

        # Get bottle folder path
        bottle_folder = core_config.vault_path / vault_path_str

        if not bottle_folder.exists():
            raise HTTPException(status_code=404, detail="Bottle folder not found")

        # Find all tasting files (pattern: Tasting-YYYY-MM-DD-TasterName.md)
        tasting_files = list(bottle_folder.glob("Tasting-*.md"))

        if not tasting_files:
            return {
                "tasting_count": 0,
                "avg_score": None,
                "max_score": 100 if bottle.type == "wine" else 10,
                "latest_date": None,
                "earliest_date": None,
                "tasters": []
            }

        # Parse each tasting file for scores and metadata
        scores = []
        dates = []
        tasters = set()

        for tasting_file in tasting_files:
            try:
                # Extract taster and date from filename: Tasting-YYYY-MM-DD-TasterName.md
                match = re.match(r'Tasting-(\d{4}-\d{2}-\d{2})-(.+)\.md', tasting_file.name)
                if match:
                    date_str, taster = match.groups()
                    dates.append(date_str)
                    tasters.add(taster)

                # Read file to get score from frontmatter
                content = tasting_file.read_text(encoding='utf-8')

                # Parse frontmatter for score fields
                if bottle.type == "wine":
                    # Look for 100pt Scale (preferred) or fall back to AWS Score
                    # YAML frontmatter uses single colon, Dataview inline uses double colons
                    scale_100_match = re.search(r'^100pt Scale::?\s*(\d+(?:\.\d+)?)', content, re.MULTILINE)
                    if scale_100_match:
                        scores.append(float(scale_100_match.group(1)))
                    else:
                        # Fall back to AWS Score if 100pt Scale not found
                        aws_match = re.search(r'^AWS Score::?\s*(\d+(?:\.\d+)?)', content, re.MULTILINE)
                        if aws_match:
                            # Convert AWS Score (0-20) to 100pt scale
                            scores.append(round(50 + (float(aws_match.group(1)) / 20) * 50, 1))
                        else:
                            # Backstop: calculate from component scores if Obsidian hasn't run
                            # Appearance: /3, Aroma: /6, Taste: /6, Aftertaste: /3, Overall: /2
                            wine_components = ['Appearance', 'Aroma', 'Taste', 'Aftertaste', 'Overall']
                            aws_sum = 0.0
                            found_any = False
                            for comp in wine_components:
                                comp_match = re.search(rf'^{comp}::?\s*(\d+(?:\.\d+)?)', content, re.MULTILINE)
                                if comp_match:
                                    aws_sum += float(comp_match.group(1))
                                    found_any = True
                            if found_any:
                                scores.append(round(50 + (aws_sum / 20) * 50, 1))
                else:
                    # Look for TotalScore (whiskey 10-point scale)
                    # YAML frontmatter uses single colon, Dataview inline uses double colons
                    total_match = re.search(r'^TotalScore::?\s*(\d+(?:\.\d+)?)', content, re.MULTILINE)
                    if total_match:
                        scores.append(float(total_match.group(1)))
                    else:
                        # Backstop: calculate from component scores if Obsidian hasn't run
                        # Nose: /3, Palate: /3, Finish: /3, Overall: /1
                        whiskey_components = ['Nose', 'Palate', 'Finish', 'Overall']
                        total_sum = 0.0
                        found_any = False
                        for comp in whiskey_components:
                            comp_match = re.search(rf'^{comp}::?\s*(\d+(?:\.\d+)?)', content, re.MULTILINE)
                            if comp_match:
                                total_sum += float(comp_match.group(1))
                                found_any = True
                        if found_any:
                            scores.append(round(total_sum, 2))

            except Exception as e:
                logger.warning(f"Failed to parse tasting file {tasting_file.name}: {e}")
                continue

        # Calculate summary stats
        avg_score = sum(scores) / len(scores) if scores else None
        max_score = 100 if bottle.type == "wine" else 10

        return {
            "tasting_count": len(tasting_files),
            "avg_score": round(avg_score, 1) if avg_score is not None else None,
            "max_score": max_score,
            "latest_date": max(dates) if dates else None,
            "earliest_date": min(dates) if dates else None,
            "tasters": sorted(list(tasters))
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tasting summary: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/management/bottles/tastings-list")
async def get_bottle_tastings_list(request: Request):
    """
    Get full list of tastings for a bottle with all scores and notes.

    Returns list of tastings sorted by date descending (newest first).
    Each tasting includes individual scores, total score, and tasting notes.
    """
    from ... import app as app_module
    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry
    from ....core.models import BottleMetadata
    import re

    try:
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Missing bottle data")

        bottle = BottleMetadata(**bottle_data)

        # Resolve vault_path from bottle ID if not provided directly
        vault_path_str = bottle.vault_path
        if not vault_path_str and bottle.id and bottle_registry:
            vault_path_str = bottle_registry.get_path(bottle.id)

        if not vault_path_str:
            raise HTTPException(status_code=404, detail="Bottle has no vault path and ID could not be resolved")

        bottle_folder = core_config.vault_path / vault_path_str

        if not bottle_folder.exists():
            raise HTTPException(status_code=404, detail="Bottle folder not found")

        tasting_files = list(bottle_folder.glob("Tasting-*.md"))

        if not tasting_files:
            return {
                "tastings": [],
                "bottle_type": bottle.type
            }

        tastings = []

        for tasting_file in tasting_files:
            try:
                # Extract date and taster from filename
                match = re.match(r'Tasting-(\d{4}-\d{2}-\d{2})-(.+)\.md', tasting_file.name)
                if not match:
                    continue

                date_str, taster = match.groups()
                content = tasting_file.read_text(encoding='utf-8')

                # Parse frontmatter
                frontmatter_match = re.match(r'^---\n(.*?)\n---\n(.*)$', content, re.DOTALL)
                if not frontmatter_match:
                    continue

                frontmatter_text = frontmatter_match.group(1)
                body_content = frontmatter_match.group(2)

                # Parse frontmatter into dict
                frontmatter = {}
                for line in frontmatter_text.split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        frontmatter[key.strip()] = value.strip().strip('"')

                tasting_data = {
                    "filename": tasting_file.name,
                    "date": date_str,
                    "taster": taster,
                    "scores": {},
                    "total_score": None,
                    "max_score": 100 if bottle.type == "wine" else 10,
                    "notes": {}
                }

                if bottle.type == "wine":
                    # Wine scores
                    tasting_data["scores"] = {
                        "appearance": _parse_float(frontmatter.get("Appearance")),
                        "aroma": _parse_float(frontmatter.get("Aroma")),
                        "taste": _parse_float(frontmatter.get("Taste")),
                        "aftertaste": _parse_float(frontmatter.get("Aftertaste")),
                        "overall": _parse_float(frontmatter.get("Overall"))
                    }
                    # Wine uses 100-point scale as primary display
                    tasting_data["total_score"] = _parse_float(frontmatter.get("100pt Scale"))
                    tasting_data["aws_score"] = _parse_float(frontmatter.get("AWS Score"))
                    tasting_data["max_score"] = 100

                    # Backstop: calculate AWS Score and 100pt Scale from components if Obsidian hasn't run
                    if tasting_data["aws_score"] is None:
                        component_sum = sum(v for v in tasting_data["scores"].values() if v is not None)
                        if component_sum > 0:
                            tasting_data["aws_score"] = round(component_sum, 1)
                    if tasting_data["total_score"] is None and tasting_data["aws_score"] is not None:
                        tasting_data["total_score"] = round(50 + (tasting_data["aws_score"] / 20) * 50, 1)

                    # Parse notes from body
                    tasting_data["notes"] = _parse_wine_notes(body_content)
                else:
                    # Whiskey scores
                    tasting_data["scores"] = {
                        "nose": _parse_float(frontmatter.get("Nose")),
                        "palate": _parse_float(frontmatter.get("Palate")),
                        "finish": _parse_float(frontmatter.get("Finish")),
                        "overall": _parse_float(frontmatter.get("Overall"))
                    }
                    tasting_data["total_score"] = _parse_float(frontmatter.get("TotalScore"))
                    tasting_data["days_from_crack"] = _parse_int(frontmatter.get("DaysFromCrack"))
                    tasting_data["fill_level"] = _parse_int(frontmatter.get("FillLevel"))
                    tasting_data["max_score"] = 10

                    # Backstop: calculate TotalScore from components if Obsidian hasn't run
                    if tasting_data["total_score"] is None:
                        component_sum = sum(v for v in tasting_data["scores"].values() if v is not None)
                        if component_sum > 0:
                            tasting_data["total_score"] = round(component_sum, 2)

                    # Parse notes from body
                    tasting_data["notes"] = _parse_whiskey_notes(body_content)

                tastings.append(tasting_data)

            except Exception as e:
                logger.warning(f"Failed to parse tasting file {tasting_file.name}: {e}")
                continue

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


def _parse_float(value: str) -> float | None:
    """Parse a string to float, returning None if invalid."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _parse_int(value: str) -> int | None:
    """Parse a string to int, returning None if invalid."""
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
async def update_bottle_metadata(bottle_index: int, request: Request):
    """
    Apply approved metadata changes to a bottle in the vault.

    Args:
        bottle_index: Index of bottle in the vault bottles list
        request: Request containing the updated bottle data

    Returns:
        dict: Status of the update operation
    """
    from ...app import core_config
    from ....generators.obsidian import ObsidianGenerator
    from pathlib import Path

    try:
        # Get the updated bottle data from request body
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Bottle data not provided")

        # Convert to BottleMetadata
        from ....core.models import BottleMetadata
        bottle = BottleMetadata(**bottle_data)

        # Check vault path is configured
        if not core_config.vault_path or not core_config.vault_path.exists():
            raise HTTPException(status_code=500, detail="Vault path not configured")

        # Initialize Obsidian generator
        template_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(vault_path=core_config.vault_path, template_dir=template_dir)

        # Generate bottle file
        obsidian_file = generator.generate_bottle_file(bottle)

        # Write the updated bottle file
        obsidian_file.file_path.parent.mkdir(parents=True, exist_ok=True)
        obsidian_file.file_path.write_text(obsidian_file.content, encoding="utf-8")

        logger.info(f"Updated bottle {bottle_index}: {bottle.producer} - {bottle.name} at {obsidian_file.file_path}")

        return {
            "status": "success",
            "bottle": bottle.model_dump(mode='json'),
            "path": str(obsidian_file.file_path)
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
        from ....core.models import BottleMetadata

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
        from ....core.models import BottleMetadata

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
async def start_batch_verification(background_tasks: BackgroundTasks):
    """
    Start batch verification of all bottles in the background.

    Returns:
        dict: Batch ID and initial status
    """
    from ... import app as app_module
    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry
    import uuid

    try:
        # Load all bottles (pass registry for ID assignment)
        vault_reader = VaultReader(core_config.vault_path, registry=bottle_registry)
        bottles = vault_reader.read_all_bottles()
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


def find_existing_bottle_file(vault_path: Path, bottle: BottleMetadata) -> Optional[Path]:
    """
    Find the existing bottle file in the vault.

    Args:
        vault_path: Path to vault
        bottle: Bottle metadata with original name/producer

    Returns:
        Path to existing bottle file or None if not found
    """
    import shutil

    # Determine the type directory
    type_dir = vault_path / ("1_Wines" if bottle.type == "wine" else "1_Whiskeys")

    if not type_dir.exists():
        return None

    # Search for bottle directory matching the original bottle name pattern
    for bottle_dir in type_dir.iterdir():
        if not bottle_dir.is_dir():
            continue

        # Look for the bottle file
        bottle_file = bottle_dir / f"{bottle_dir.name}.md"
        if bottle_file.exists():
            # Read the file and check if it matches our bottle
            try:
                content = bottle_file.read_text(encoding="utf-8")

                # Parse frontmatter to get year/vintage
                import re
                frontmatter_match = re.match(r'^---\n(.*?)\n---\n', content, re.DOTALL)
                if frontmatter_match:
                    frontmatter = frontmatter_match.group(1)

                    # Extract year/vintage from frontmatter
                    year_match = re.search(r'^(?:Year|Vintage):\s*(.+?)$', frontmatter, re.MULTILINE)
                    file_year = None
                    if year_match:
                        try:
                            # Remove quotes and whitespace, then parse as int
                            year_str = year_match.group(1).strip().strip('"').strip("'")
                            file_year = int(year_str)
                        except ValueError:
                            pass

                    # Check if producer, name, AND year match
                    # CRITICAL: Only match if years are equal (or both are None)
                    # Don't accept a file if we can't determine its year when bottle has a year
                    producer_match = bottle.producer in content
                    name_match = bottle.name in content
                    year_match = (bottle.year is None and file_year is None) or (bottle.year == file_year)

                    if producer_match and name_match and year_match:
                        logger.info(f"Found existing bottle file: {bottle_file} (year={file_year}, expected={bottle.year})")
                        return bottle_file
                    elif producer_match and name_match and not year_match:
                        logger.debug(f"Skipping {bottle_file}: year mismatch (file={file_year}, expected={bottle.year})")
            except Exception as e:
                logger.warning(f"Error reading {bottle_file}: {e}")
                continue

    return None


@router.post("/api/v1/management/bottles/update-fields")
async def update_bottle_fields(request: Request):
    """
    Update specific fields of a bottle (individual field approval).

    Request body:
        - bottle: Original bottle data (with id field for lookup)
        - updates: Dict of field names to new values

    Returns:
        dict: Status of the update operation
    """
    from ... import app as app_module
    core_config = app_module.core_config
    bottle_registry = app_module.bottle_registry
    from ....generators.obsidian import ObsidianGenerator
    from ....core.models import BottleMetadata
    from pathlib import Path
    import shutil

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

        # Resolve vault_path from bottle ID if not provided directly
        # This is necessary because vault_path is no longer sent from frontend
        bottle_id = cleaned_bottle_data.get("id")
        if not cleaned_bottle_data.get("vault_path") and bottle_id and bottle_registry:
            resolved_path = bottle_registry.get_path(bottle_id)
            if resolved_path:
                cleaned_bottle_data["vault_path"] = resolved_path
                logger.info(f"Resolved vault_path from ID {bottle_id}: {resolved_path}")

        # Convert to BottleMetadata
        original_bottle = BottleMetadata(**cleaned_bottle_data)

        logger.info(f"Original bottle before updates: producer={original_bottle.producer}, name={original_bottle.name}")

        # Apply only the approved updates
        bottle_dict = original_bottle.model_dump()
        for field, value in updates.items():
            if field in bottle_dict:
                old_value = bottle_dict[field]
                bottle_dict[field] = value
                logger.info(f"Applying update: {field}: {old_value} -> {value}")

        # Create updated bottle
        updated_bottle = BottleMetadata(**bottle_dict)

        # Check vault path is configured
        if not core_config.vault_path or not core_config.vault_path.exists():
            raise HTTPException(status_code=500, detail="Vault path not configured")

        # Bottles loaded from vault MUST have vault_path set (resolved from ID if needed)
        # This endpoint is for updating existing bottles, not creating new ones
        if not original_bottle.vault_path:
            logger.error(f"Bottle missing vault_path and ID could not be resolved - this endpoint only works with bottles loaded from vault")
            raise HTTPException(status_code=400, detail="Bottle must have vault_path or valid ID (only bottles loaded from vault can be updated)")

        # Use vault_path directly - no searching needed
        # vault_path is relative, e.g., "1_Whiskeys/Distiller - Name - Year"
        bottle_dir = core_config.vault_path / original_bottle.vault_path
        if not bottle_dir.exists() or not bottle_dir.is_dir():
            logger.error(f"Bottle directory not found: {bottle_dir}")
            raise HTTPException(status_code=404, detail=f"Bottle directory not found: {original_bottle.vault_path}")

        # Look for the bottle file
        existing_file = bottle_dir / f"{bottle_dir.name}.md"
        if not existing_file.exists():
            # Try to find any .md file in the directory (in case filename doesn't match folder)
            md_files = [f for f in bottle_dir.glob("*.md") if not f.name.startswith("Tasting-")]
            if not md_files:
                logger.error(f"No bottle file found in {bottle_dir}")
                raise HTTPException(status_code=404, detail=f"No bottle file found in directory: {original_bottle.vault_path}")
            existing_file = md_files[0]
            logger.info(f"Found bottle file with different name: {existing_file.name}")

        existing_dir = existing_file.parent
        logger.info(f"Found existing bottle at: {existing_file}")

        # Read existing file content
        existing_content = existing_file.read_text(encoding="utf-8")

        # Parse frontmatter and body (allow leading whitespace/newlines for backwards compatibility)
        import re
        frontmatter_match = re.match(r'^\s*---\n(.*?)\n---\n(.*)$', existing_content, re.DOTALL)

        if not frontmatter_match:
            logger.error(f"Could not parse frontmatter from {existing_file}")
            raise HTTPException(status_code=500, detail="Invalid bottle file format")

        frontmatter_text = frontmatter_match.group(1)
        body_content = frontmatter_match.group(2)

        # Map model field names to Obsidian frontmatter field names
        # Different mappings for wine vs whiskey
        if original_bottle.type == "wine":
            field_name_map = {
                "producer": "Winemaker",
                "name": "WineName",
                "year": "Vintage",
                "beverage_type": "Type",
                "variety": "Variety",
                "country": "Country-Region",  # Special handling needed
                "region": "Country-Region",   # Special handling needed
                "vineyard": "Vineyard",
                "abv": "ABV",
                "style": "Style",
                "price": "Price",
                "purchase_source": "PurchaseSource",
                "purchase_link": "PurchaseLink",
                "inventory": "Inventory",
                "buy": "Buy",
                "value_for_money": "ValueForMoney",
                "points": "Points",
                "stars": "Stars",
            }
        else:  # whiskey and other spirits
            field_name_map = {
                "producer": "Distiller",
                "name": "WhiskeyName",
                "year": "Year",
                "beverage_type": "Type",
                "country": "Region-State",    # Whiskey uses Region-State
                "region": "Region-State",      # Whiskey uses Region-State
                "age_statement": "AgeStatement",
                "proof": "Proof",
                "mash_bill": "MashBill",
                "barrel_type": "BarrelType",
                "batch_number": "BatchNumber",
                "bottle_number": "BottleNumber",
                "price": "Price",
                "purchase_source": "PurchaseSource",
                "purchase_link": "PurchaseLink",
                "inventory": "Inventory",
                "buy": "Buy",
                "value_for_money": "ValueForMoney",
                "stars": "Stars",
                "bottle_opened_date": "BottleOpenedDate",
            }

        # Parse frontmatter into dict (preserving order and original keys)
        frontmatter_lines = []
        frontmatter_dict = {}
        for line in frontmatter_text.split('\n'):
            if ':' in line:
                key, value = line.split(':', 1)
                key_clean = key.strip()
                frontmatter_lines.append((key_clean, value.strip()))
                # Store lowercase version for lookup
                frontmatter_dict[key_clean.lower()] = key_clean

        # Track which updates have been applied
        applied_updates = set()

        # Update existing fields
        updated_lines = []
        for key_original, value_original in frontmatter_lines:
            key_lower = key_original.lower()

            # Find if any update field maps to this frontmatter field
            updated = False
            for update_field, update_value in updates.items():
                obsidian_field = field_name_map.get(update_field)

                # Special handling for Country-Region (wine) or Region-State (whiskey)
                region_field = "country-region" if original_bottle.type == "wine" else "region-state"
                if key_lower == region_field and update_field in ["country", "region"]:
                    # We'll handle this after the loop
                    continue

                if obsidian_field and obsidian_field.lower() == key_lower:
                    updated_lines.append((key_original, str(update_value)))
                    applied_updates.add(update_field)
                    logger.info(f"Updated frontmatter field: {key_original}: {value_original} -> {update_value}")
                    updated = True
                    break

            if not updated:
                # No update for this field, keep original
                updated_lines.append((key_original, value_original))

        # Handle Country-Region (wine) or Region-State (whiskey) special case
        if "country" in updates or "region" in updates:
            # Determine which field to look for based on bottle type
            if original_bottle.type == "wine":
                target_field = "country-region"
            else:
                target_field = "region-state"

            # Find the region field line
            for i, (key, val) in enumerate(updated_lines):
                if key.lower() == target_field:
                    country_val = updates.get("country", original_bottle.country)
                    region_val = updates.get("region", original_bottle.region)

                    # Wine uses "Country - Region" format
                    # Whiskey uses just the state/region
                    if original_bottle.type == "wine":
                        if country_val and region_val:
                            new_val = f"{country_val} - {region_val}"
                        elif country_val:
                            new_val = country_val
                        elif region_val:
                            new_val = region_val
                        else:
                            new_val = ""
                    else:
                        # Whiskey: just use region (state)
                        new_val = region_val or country_val or ""

                    updated_lines[i] = (key, new_val)
                    applied_updates.add("country")
                    applied_updates.add("region")
                    logger.info(f"Updated frontmatter field: {key}: -> {new_val}")
                    break

        # Add any new fields that don't exist in the frontmatter yet
        for update_field, update_value in updates.items():
            if update_field not in applied_updates:
                obsidian_field = field_name_map.get(update_field)
                if obsidian_field and obsidian_field.lower() not in frontmatter_dict:
                    # Add new field
                    updated_lines.append((obsidian_field, str(update_value)))
                    logger.info(f"Added new frontmatter field: {obsidian_field}: {update_value}")

        # CRITICAL: Update the composite Name field if any component changed
        # Name field MUST always match the folder/file name: "Producer - Name - Year"
        # For wine: "Winemaker - WineName - Vintage"
        # For whiskey: "Distiller - WhiskeyName - Year"
        if "producer" in updates or "name" in updates or "year" in updates:
            # Get current values from updated_bottle (which has the new values)
            if original_bottle.type == "wine":
                producer_field = "Winemaker"
                name_field = "WineName"
                year_field = "Vintage"
            else:
                producer_field = "Distiller"
                name_field = "WhiskeyName"
                year_field = "Year"

            # Build the composite Name value
            name_parts = []
            if updated_bottle.producer:
                name_parts.append(updated_bottle.producer)
            if updated_bottle.name:
                name_parts.append(updated_bottle.name)
            if updated_bottle.year:
                name_parts.append(str(updated_bottle.year))

            composite_name = " - ".join(name_parts)

            # Update the Name field in frontmatter
            name_updated = False
            for i, (key, val) in enumerate(updated_lines):
                if key == "Name":
                    updated_lines[i] = (key, f'"{composite_name}"')
                    logger.info(f"Updated composite Name field: {val} -> {composite_name}")
                    name_updated = True
                    break

            # If Name field doesn't exist, add it (should always exist but handle edge case)
            if not name_updated:
                updated_lines.insert(0, ("Name", f'"{composite_name}"'))
                logger.info(f"Added composite Name field: {composite_name}")

        # Rebuild frontmatter
        new_frontmatter_lines = []
        for key, value in updated_lines:
            new_frontmatter_lines.append(f"{key}: {value}")

        new_content = "---\n" + "\n".join(new_frontmatter_lines) + "\n---\n" + body_content

        # Determine new file path based on updated metadata
        from ....generators.obsidian import ObsidianGenerator
        template_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(vault_path=core_config.vault_path, template_dir=template_dir)
        obsidian_file = generator.generate_bottle_file(updated_bottle)
        new_path = obsidian_file.file_path
        new_dir = new_path.parent

        # Check if folder needs to move
        # Use samefile() to handle case-insensitive filesystems (WSL/Windows)
        paths_are_same = False
        try:
            # Both paths must exist for samefile to work
            if existing_dir.exists() and new_dir.exists():
                paths_are_same = existing_dir.samefile(new_dir)
            elif existing_dir.resolve() == new_dir.resolve():
                # If new_dir doesn't exist yet, compare resolved paths
                paths_are_same = True
        except (OSError, ValueError):
            # Fall back to string comparison if samefile fails
            paths_are_same = str(existing_dir.resolve()).lower() == str(new_dir.resolve()).lower()

        if not paths_are_same:
            logger.info(f"Bottle path changed - moving from {existing_dir} to {new_dir}")
            logger.info(f"Resolved paths: {existing_dir.resolve()} -> {new_dir.resolve()}")

            # CRITICAL: Check if destination already exists with files
            if new_dir.exists():
                existing_files = list(new_dir.iterdir())
                if existing_files:
                    error_msg = (
                        f"Cannot move bottle: destination folder already exists with {len(existing_files)} files. "
                        f"This would overwrite an existing bottle at '{new_dir}'. "
                        f"If you want to rename this bottle, please ensure the year/name doesn't conflict with another bottle."
                    )
                    logger.error(error_msg)
                    raise HTTPException(status_code=409, detail=error_msg)

            # Create new directory
            new_dir.mkdir(parents=True, exist_ok=True)

            # Move all files from old directory to new directory
            for item in existing_dir.iterdir():
                dest = new_dir / item.name
                logger.info(f"Moving {item} to {dest}")
                shutil.move(str(item), str(dest))

            # Remove old directory
            existing_dir.rmdir()
            logger.info(f"Removed old directory: {existing_dir}")

            # Update reference to existing file (now in new dir)
            existing_file = new_dir / existing_file.name
            bottle_was_moved = True
        else:
            logger.info(f"Bottle path unchanged - updating file in place at {existing_dir}")
            bottle_was_moved = False

        # Check if file needs to be renamed
        if existing_file.name != new_path.name:
            logger.info(f"Renaming bottle file from {existing_file.name} to {new_path.name}")
            final_path = existing_file.parent / new_path.name
            existing_file.rename(final_path)
        else:
            final_path = existing_file

        # Write the updated content
        final_path.write_text(new_content, encoding="utf-8")

        logger.info(
            f"Updated bottle {original_bottle.producer} - {original_bottle.name} "
            f"with {len(updates)} field changes at {final_path}"
        )

        return {
            "status": "success",
            "bottle": updated_bottle.model_dump(mode='json'),
            "path": str(final_path),
            "updated_fields": list(updates.keys()),
            "moved": bottle_was_moved
        }

    except Exception as e:
        logger.error(f"Failed to update bottle fields: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Label Quality Review Routes - Simple grid-based workflow
# ============================================================================

