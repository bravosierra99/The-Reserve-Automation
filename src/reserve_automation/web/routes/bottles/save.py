"""Bottle save endpoint - unified save with duplicate detection."""

import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from loguru import logger

from ....core.models import BottleMetadata
from ....generators.obsidian import ObsidianGenerator
from ....utils.vault_reader import VaultReader
from ...services.duplicate_service import DuplicateDetectionService


router = APIRouter()


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


class SaveBottleRequest(BaseModel):
    """Request to save a bottle to the vault."""
    bottle: dict  # BottleMetadata as dict
    upload_id: Optional[str] = None  # For accessing temp files
    temp_label_index: Optional[int] = None  # Which temp label to use (for manifest uploads)
    force_save: bool = False  # Skip duplicate check
    replace_vault_path: Optional[str] = None  # Replace existing bottle at this path


@router.post("/api/v1/bottles/save")
async def save_bottle(request: SaveBottleRequest):
    """
    Save bottle to vault with duplicate detection.

    Workflow:
    1. Parse bottle metadata
    2. Check for duplicates (unless force_save=True)
    3. If duplicates found, return them for user decision
    4. If no duplicates OR force_save OR replace_vault_path provided:
       - Generate Obsidian markdown file
       - Create bottle folder structure
       - Copy temp label to vault (if available)
       - Delete old bottle if replacing

    Returns:
        {
            "status": "success" | "duplicate_found",
            "vault_path": str (if success),
            "duplicates": [...] (if duplicate_found)
        }
    """
    from ...app import core_config

    if not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(request.bottle)

        # Parse bottle metadata
        bottle = BottleMetadata(**cleaned_bottle_data)

        logger.info(f"Save bottle request: {bottle.producer} - {bottle.name} ({bottle.year})")
        logger.info(f"  upload_id: {request.upload_id}")
        logger.info(f"  force_save: {request.force_save}")
        logger.info(f"  replace_vault_path: {request.replace_vault_path}")

        # Check for duplicates (unless force_save or replacing)
        if not request.force_save and not request.replace_vault_path:
            duplicate_service = DuplicateDetectionService(core_config.vault_path)
            duplicates = duplicate_service.find_potential_duplicates(bottle, threshold=0.7)

            if duplicates:
                logger.info(f"Found {len(duplicates)} potential duplicates")
                # Enhance duplicates with additional info
                vault_reader = VaultReader(core_config.vault_path)
                enhanced_duplicates = []

                for dup in duplicates:
                    # Read bottle file to get full metadata
                    bottle_path = core_config.vault_path / dup["file_path"]
                    try:
                        existing_bottle = vault_reader.read_bottle(bottle_path)
                        enhanced_duplicates.append({
                            **dup,
                            "vault_path": existing_bottle.vault_path,
                            "producer": existing_bottle.producer,
                            "name": existing_bottle.name,
                            "year": existing_bottle.year,
                            "region": existing_bottle.region,
                        })
                    except Exception as e:
                        logger.warning(f"Failed to read duplicate bottle: {e}")
                        # Include basic info even if read fails
                        enhanced_duplicates.append({
                            **dup,
                            "vault_path": str(Path(dup["file_path"]).parent),
                        })

                return {
                    "status": "duplicate_found",
                    "duplicates": enhanced_duplicates
                }

        # No duplicates (or force save) - proceed with save

        # Generate Obsidian file
        template_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(core_config.vault_path, template_dir)
        obsidian_file = generator.generate_bottle_file(bottle)

        # If force_save (Save as New), check if file exists and add unique suffix
        if request.force_save and not request.replace_vault_path:
            original_path = obsidian_file.file_path
            counter = 2
            while obsidian_file.file_path.parent.exists():
                # Folder exists - add suffix to bottle name
                suffix = f" ({counter})"
                new_filename = original_path.parent.name + suffix
                new_folder = original_path.parent.parent / new_filename
                new_file = new_folder / f"{new_filename}.md"

                obsidian_file.file_path = new_file
                obsidian_file.content = obsidian_file.content.replace(
                    f"Name: {original_path.parent.name}\n",
                    f"Name: {new_filename}\n",
                    1  # Only replace first occurrence in frontmatter
                )
                counter += 1

                if counter > 100:  # Safety limit
                    raise HTTPException(status_code=500, detail="Too many duplicate bottles")

            logger.info(f"Force save with unique name: {obsidian_file.file_path.parent.name}")

        # If replacing existing bottle, move/rename directory and preserve tastings
        if request.replace_vault_path:
            old_bottle_folder = core_config.vault_path / request.replace_vault_path
            new_bottle_folder = obsidian_file.file_path.parent

            if old_bottle_folder.exists():
                logger.info(f"Replacing bottle - preserving tastings")
                logger.info(f"  Old path: {old_bottle_folder}")
                logger.info(f"  New path: {new_bottle_folder}")

                # Check if paths are different (name/year changed)
                paths_are_same = False
                try:
                    paths_are_same = old_bottle_folder.samefile(new_bottle_folder)
                except (OSError, ValueError):
                    paths_are_same = str(old_bottle_folder.resolve()).lower() == str(new_bottle_folder.resolve()).lower()

                if not paths_are_same:
                    # Name changed - need to move directory
                    logger.info(f"Bottle name/year changed - moving directory")

                    # Check if destination already exists
                    if new_bottle_folder.exists():
                        existing_files = list(new_bottle_folder.iterdir())
                        if existing_files:
                            raise HTTPException(
                                status_code=409,
                                detail=f"Cannot replace: destination folder already exists with {len(existing_files)} files"
                            )

                    # Create new directory
                    new_bottle_folder.mkdir(parents=True, exist_ok=True)
                    labels_folder = new_bottle_folder / "labels"
                    labels_folder.mkdir(exist_ok=True)

                    # Move all files from old directory to new directory (preserves tastings!)
                    for item in old_bottle_folder.iterdir():
                        if item.name != "labels":  # Skip labels folder, we'll handle separately
                            dest = new_bottle_folder / item.name
                            logger.info(f"  Moving {item.name} to new directory")
                            shutil.move(str(item), str(dest))

                    # Move labels
                    old_labels = old_bottle_folder / "labels"
                    if old_labels.exists():
                        for label_file in old_labels.iterdir():
                            dest = labels_folder / label_file.name
                            logger.info(f"  Moving label {label_file.name}")
                            shutil.move(str(label_file), str(dest))
                        old_labels.rmdir()

                    # Remove old directory
                    old_bottle_folder.rmdir()
                    logger.info(f"  Removed old directory: {old_bottle_folder}")
                else:
                    # Same path - just updating metadata in place
                    logger.info(f"Updating bottle metadata in place at {old_bottle_folder}")
                    labels_folder = old_bottle_folder / "labels"
                    labels_folder.mkdir(exist_ok=True)

                # Write updated markdown file (may have new name if producer/name/year changed)
                logger.info(f"Writing updated markdown file: {obsidian_file.file_path}")
                obsidian_file.file_path.write_text(obsidian_file.content, encoding="utf-8")

                # Delete old .md file if name changed
                if not paths_are_same or old_bottle_folder != new_bottle_folder:
                    old_md_files = list(new_bottle_folder.glob("*.md"))
                    for old_md in old_md_files:
                        if old_md != obsidian_file.file_path:
                            logger.info(f"  Removing old markdown file: {old_md.name}")
                            old_md.unlink()
            else:
                # Old bottle doesn't exist - treat as new
                logger.warning(f"Replace requested but old bottle not found: {old_bottle_folder}")
                bottle_folder = obsidian_file.file_path.parent
                labels_folder = bottle_folder / "labels"
                bottle_folder.mkdir(parents=True, exist_ok=True)
                labels_folder.mkdir(exist_ok=True)
                obsidian_file.file_path.write_text(obsidian_file.content, encoding="utf-8")
        else:
            # New bottle - create everything
            bottle_folder = obsidian_file.file_path.parent
            labels_folder = bottle_folder / "labels"

            logger.info(f"Creating bottle folder: {bottle_folder}")
            bottle_folder.mkdir(parents=True, exist_ok=True)
            labels_folder.mkdir(exist_ok=True)

            # Write markdown file
            logger.info(f"Writing markdown file: {obsidian_file.file_path}")
            obsidian_file.file_path.write_text(obsidian_file.content, encoding="utf-8")

        # Ensure bottle_folder is set for label copying
        if request.replace_vault_path:
            bottle_folder = obsidian_file.file_path.parent

        # Copy label from temp directory (if available)
        if request.upload_id:
            # Use the same temp directory structure as upload service: /tmp/reserve_uploads/{upload_id}/
            temp_upload_dir = Path("/tmp/reserve_uploads") / request.upload_id
            temp_labels_dir = temp_upload_dir / "labels"

            # Determine which temp label to use
            if request.temp_label_index is not None:
                # Manifest upload - specific bottle index
                temp_label = temp_labels_dir / f"{request.temp_label_index}.jpg"
            else:
                # Single bottle upload - use label.jpg
                temp_label = temp_labels_dir / "label.jpg"

            if temp_label.exists():
                dest_label = labels_folder / "label.jpg"
                logger.info(f"Copying label: {temp_label} -> {dest_label}")
                shutil.copy2(temp_label, dest_label)
            else:
                logger.warning(f"Temp label not found: {temp_label}")
                logger.warning(f"  Checked: {temp_label}")
                logger.warning(f"  Upload dir contents: {list(temp_upload_dir.iterdir()) if temp_upload_dir.exists() else 'directory does not exist'}")

        # Calculate vault_path (relative to vault root)
        vault_path = str(bottle_folder.relative_to(core_config.vault_path))

        logger.info(f"Bottle saved successfully: {vault_path}")

        return {
            "status": "success",
            "vault_path": vault_path,
            "message": f"Bottle saved: {bottle.producer} - {bottle.name}"
        }

    except Exception as e:
        logger.error(f"Save bottle failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/check-duplicates")
async def check_duplicates_manual(bottle_data: dict):
    """
    Manually check for duplicate bottles in the vault.

    Used by the bottle editor modal to allow users to manually trigger
    duplicate detection at any time (not just on save).

    Args:
        bottle_data: Bottle metadata as dict

    Returns:
        {
            "status": "checked",
            "duplicates": [...],
            "count": int
        }
    """
    from ...app import core_config
    from ...services.duplicate_service import DuplicateDetectionService
    from ....utils.vault_reader import VaultReader

    if not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Clean empty strings before validation
        cleaned_bottle_data = clean_bottle_data(bottle_data)

        # Parse bottle metadata
        bottle = BottleMetadata(**cleaned_bottle_data)

        logger.info(f"Manual duplicate check: {bottle.producer} - {bottle.name} ({bottle.year})")
        logger.info(f"  Bottle type: {bottle.type}")

        # Check for duplicates with very low threshold to show all potential matches
        # User wants to see ALL possible matches above threshold, not just close ones
        duplicate_service = DuplicateDetectionService(core_config.vault_path)
        duplicates = duplicate_service.find_potential_duplicates(bottle, threshold=0.3)

        logger.info(f"Found {len(duplicates)} potential duplicates")

        # Enhance duplicates with additional info
        vault_reader = VaultReader(core_config.vault_path)
        enhanced_duplicates = []

        for dup in duplicates:
            # Read bottle file to get full metadata
            bottle_path = core_config.vault_path / dup["file_path"]
            try:
                existing_bottle = vault_reader.read_bottle(bottle_path)
                enhanced_duplicates.append({
                    **dup,
                    "vault_path": existing_bottle.vault_path,
                    "producer": existing_bottle.producer,
                    "name": existing_bottle.name,
                    "year": existing_bottle.year,
                    "region": existing_bottle.region,
                })
            except Exception as e:
                logger.warning(f"Failed to read duplicate bottle: {e}")
                # Include basic info even if read fails
                enhanced_duplicates.append({
                    **dup,
                    "vault_path": str(Path(dup["file_path"]).parent),
                })

        return {
            "status": "checked",
            "duplicates": enhanced_duplicates,
            "count": len(enhanced_duplicates)
        }

    except Exception as e:
        logger.error(f"Manual duplicate check failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
