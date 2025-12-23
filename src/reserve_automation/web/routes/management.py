"""Management routes for bottle metadata updates and admin functions."""

#CLAUDE_REQ: When adding/modifying field_name_map, verify coherence with:
#CLAUDE_REQ: - BottleMetadata model (core/models.py) - model field names on left
#CLAUDE_REQ: - Obsidian FileClass (the-reserve/Cellar/8_FileClass/*.md) - Obsidian field names on right
#CLAUDE_REQ: - Wine: Winemaker/WineName/Vintage/Country-Region/ABV/Variety/Vineyard
#CLAUDE_REQ: - Whiskey: Distiller/WhiskeyName/Year/Region-State/Proof/AgeStatement/MashBill/BarrelType
#CLAUDE_REQ: - Composite Name field updates when producer/name/year change (see line ~597)

import asyncio
import re
from typing import Dict, Optional
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from loguru import logger

from ...utils.vault_reader import VaultReader
from ..services.extraction_service import ExtractionService

router = APIRouter()

# In-memory storage for verification results
# In production, this should be Redis or a database
verification_results: Dict[str, dict] = {}
batch_status: Dict[str, dict] = {}


@router.get("/management", response_class=HTMLResponse)
async def management_page(request: Request):
    """
    Render the management page.

    This page provides administrative functions including:
    - Update all bottle metadata from vault
    """
    from ..app import templates, web_config

    return templates.TemplateResponse(
        "management.html",
        {"request": request}
    )


@router.get("/api/v1/management/bottles")
async def get_all_vault_bottles():
    """
    Get all bottles from the vault for metadata update.

    Returns:
        dict: Contains list of bottles with their current metadata
    """
    from ..app import core_config

    try:
        vault_reader = VaultReader(core_config.vault_path)
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
        dict: List of matching bottles
    """
    from ..app import core_config

    try:
        vault_reader = VaultReader(core_config.vault_path)
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


@router.post("/api/v1/management/bottles/{bottle_index}/verify")
async def verify_bottle_metadata(bottle_index: int, request: Request):
    """
    Verify and get updated metadata for a specific bottle.

    Args:
        bottle_index: Index of bottle in the vault bottles list
        request: Request containing the bottle data

    Returns:
        dict: Contains original bottle, updated bottle, and changes made
    """
    from ..app import core_config

    try:
        # Get the bottle data from request body
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Bottle data not provided")

        # Convert to BottleMetadata
        from ...core.models import BottleMetadata
        bottle = BottleMetadata(**bottle_data)

        # Initialize extraction service
        extraction_service = ExtractionService(core_config)

        # Verify the bottle metadata (this will check and correct all fields)
        updated_bottle, metadata = await extraction_service.enrich_bottle(bottle)

        changes = metadata.get("changes", {})

        logger.info(
            f"Verified bottle {bottle_index}: {bottle.producer} - {bottle.name}, "
            f"{len(changes)} changes found"
        )

        return {
            "original": bottle.model_dump(mode='json'),
            "updated": updated_bottle.model_dump(mode='json'),
            "changes": changes,
            "metadata": metadata
        }

    except Exception as e:
        logger.error(f"Failed to verify bottle {bottle_index}: {e}", exc_info=True)
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
    from ..app import core_config
    from ...generators.obsidian import ObsidianGenerator
    from pathlib import Path

    try:
        # Get the updated bottle data from request body
        body = await request.json()
        bottle_data = body.get("bottle")

        if not bottle_data:
            raise HTTPException(status_code=400, detail="Bottle data not provided")

        # Convert to BottleMetadata
        from ...core.models import BottleMetadata
        bottle = BottleMetadata(**bottle_data)

        # Check vault path is configured
        if not core_config.vault_path or not core_config.vault_path.exists():
            raise HTTPException(status_code=500, detail="Vault path not configured")

        # Initialize Obsidian generator
        template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"
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
        from ...core.models import BottleMetadata

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


@router.post("/api/v1/management/bottles/batch-verify")
async def start_batch_verification(background_tasks: BackgroundTasks):
    """
    Start batch verification of all bottles in the background.

    Returns:
        dict: Batch ID and initial status
    """
    from ..app import core_config
    import uuid

    try:
        # Load all bottles
        vault_reader = VaultReader(core_config.vault_path)
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
                # Simple check: if producer and name appear in the file, it's probably the right one
                if bottle.producer in content and bottle.name in content:
                    logger.info(f"Found existing bottle file: {bottle_file}")
                    return bottle_file
            except Exception as e:
                logger.warning(f"Error reading {bottle_file}: {e}")
                continue

    return None


@router.post("/api/v1/management/bottles/update-fields")
async def update_bottle_fields(request: Request):
    """
    Update specific fields of a bottle (individual field approval).

    Request body:
        - bottle: Original bottle data
        - updates: Dict of field names to new values

    Returns:
        dict: Status of the update operation
    """
    from ..app import core_config
    from ...generators.obsidian import ObsidianGenerator
    from ...core.models import BottleMetadata
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

        # Convert to BottleMetadata
        original_bottle = BottleMetadata(**bottle_data)

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

        # Find existing bottle file
        existing_file = find_existing_bottle_file(core_config.vault_path, original_bottle)

        if not existing_file:
            logger.error(f"Could not find existing bottle file for {original_bottle.producer} - {original_bottle.name}")
            raise HTTPException(status_code=404, detail="Existing bottle file not found in vault")

        existing_dir = existing_file.parent
        logger.info(f"Found existing bottle at: {existing_file}")

        # Read existing file content
        existing_content = existing_file.read_text(encoding="utf-8")

        # Parse frontmatter and body
        import re
        frontmatter_match = re.match(r'^---\n(.*?)\n---\n(.*)$', existing_content, re.DOTALL)

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
                "price": "Price",
                "purchase_source": "PurchaseSource",
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
                "price": "Price",
                "purchase_source": "PurchaseSource",
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
        from ...generators.obsidian import ObsidianGenerator
        template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(vault_path=core_config.vault_path, template_dir=template_dir)
        obsidian_file = generator.generate_bottle_file(updated_bottle)
        new_path = obsidian_file.file_path
        new_dir = new_path.parent

        # Check if folder needs to move
        if existing_dir != new_dir:
            logger.info(f"Bottle path changed - moving from {existing_dir} to {new_dir}")

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
            "moved": existing_dir != new_dir if existing_dir != new_dir else False
        }

    except Exception as e:
        logger.error(f"Failed to update bottle fields: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
