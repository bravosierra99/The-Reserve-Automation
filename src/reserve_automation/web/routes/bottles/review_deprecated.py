"""Bottle upload and review endpoints."""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Response, Cookie, HTTPException, Request
from fastapi.templating import Jinja2Templates
from loguru import logger

from ...sessions import SessionManager
from ...services.upload_service import UploadService
from ...services.extraction_service import ExtractionService

router = APIRouter()

# Templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)

@router.put("/api/v1/bottles/{extraction_id}/update/{bottle_index}")
async def update_bottle(
    extraction_id: str,
    bottle_index: int,
    request: Request,
    response: Response
):
    """
    Update bottle data in session (user edits).

    Args:
        extraction_id: Extraction ID
        bottle_index: Index of bottle to update
        request: FastAPI request
        response: FastAPI response

    Returns:
        Updated status
    """
    from ...app import web_config

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get session token and request body
        session_token = request.cookies.get("session")
        if not session_token:
            raise HTTPException(status_code=404, detail="No session found")

        body = await request.json()
        updated_bottle_data = body.get("bottle")
        updated_label = body.get("selected_label")
        updated_label_choice = body.get("label_choice")

        if not updated_bottle_data:
            raise HTTPException(status_code=400, detail="No bottle data provided")

        # Load session
        session_manager = SessionManager(
            secret_key=web_config.sessions.secret_key,
            max_age_hours=web_config.sessions.max_age_hours
        )

        session_data = session_manager.read_session(session_token)
        if not session_data or session_data.get("extraction_id") != extraction_id:
            raise HTTPException(status_code=404, detail="Extraction not found")

        bottles = session_data.get("bottles", [])
        if bottle_index >= len(bottles):
            raise HTTPException(status_code=404, detail="Bottle index out of range")

        # Update bottle data
        bottles[bottle_index]["bottle"] = updated_bottle_data

        # Update label selection if provided
        if updated_label is not None:
            bottles[bottle_index]["selected_label"] = updated_label
            logger.info(f"Updated selected_label for bottle {bottle_index}: use_crop={updated_label.get('use_crop')}")

        if updated_label_choice is not None:
            bottles[bottle_index]["label_choice"] = updated_label_choice
            logger.info(f"Updated label_choice for bottle {bottle_index}: {updated_label_choice}")

        session_data["bottles"] = bottles

        # Update session cookie
        new_session_token = session_manager.create_session(session_data)
        response.set_cookie(
            key="session",
            value=new_session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            secure=False,  # Allow over HTTP for local network access
            samesite="lax"
        )

        logger.info(f"Bottle {bottle_index} updated successfully")

        return {"status": "updated"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update bottle: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/{extraction_id}/approve/{bottle_index}")
async def approve_bottle(
    extraction_id: str,
    bottle_index: int,
    request: Request,
    response: Response
):
    """
    Approve and save a bottle to Obsidian vault (Stage 3).

    Args:
        extraction_id: Extraction ID
        bottle_index: Index of bottle to approve
        request: FastAPI request
        response: FastAPI response

    Returns:
        Approval result with files created
    """
    from ...app import core_config, upload_service, web_config

    if not core_config or not upload_service or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get session token from cookie
        session_token = request.cookies.get("session")
        if not session_token:
            raise HTTPException(status_code=404, detail="No session found")

        # Load session
        session_manager = SessionManager(
            secret_key=web_config.sessions.secret_key,
            max_age_hours=web_config.sessions.max_age_hours
        )

        session_data = session_manager.read_session(session_token)
        if not session_data or session_data.get("extraction_id") != extraction_id:
            raise HTTPException(status_code=404, detail="Extraction not found")

        bottles = session_data.get("bottles", [])
        if bottle_index >= len(bottles):
            raise HTTPException(status_code=404, detail="Bottle index out of range")

        bottle_data = bottles[bottle_index]

        # Generate Obsidian file
        from reserve_automation.generators.obsidian import ObsidianGenerator
        from reserve_automation.utils.label_processor import LabelImageProcessor

        extraction_service = ExtractionService(core_config)
        bottle = extraction_service.bottle_from_dict(bottle_data["bottle"])

        # Initialize generator
        vault_path = core_config.vault_path
        if not vault_path or not vault_path.exists():
            raise HTTPException(status_code=500, detail="Vault path not configured")

        template_dir = Path(__file__).parent.parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(vault_path=vault_path, template_dir=template_dir)

        # Generate bottle file
        obsidian_file = generator.generate_bottle_file(bottle)

        # Check if bottle already exists (log warning but allow override)
        if obsidian_file.file_path.exists():
            logger.warning(f"Bottle file already exists, will be overwritten: {obsidian_file.file_path}")

        # Create bottle directory and file
        obsidian_file.file_path.parent.mkdir(parents=True, exist_ok=True)
        obsidian_file.file_path.write_text(obsidian_file.content, encoding="utf-8")

        # Invalidate bottle cache so new bottle appears in tasting matching immediately
        from ...services.tasting_service import TastingService
        tasting_service = TastingService(core_config)
        beverage_type = bottle.beverage_type  # "wine" or "whiskey"
        tasting_service.invalidate_bottle_cache(beverage_type)
        logger.info(f"Invalidated bottle cache for {beverage_type} after saving new bottle")

        # Handle label image based on selection workflow
        label_path = None
        labels_dir = obsidian_file.file_path.parent / "labels"
        labels_dir.mkdir(exist_ok=True)

        # Check if user selected a label via the find-labels workflow
        selected_label = bottle_data.get("selected_label")
        label_choice = bottle_data.get("label_choice")

        logger.info(f"Approval label info: label_choice={label_choice}, use_crop={selected_label.get('use_crop') if selected_label else None}")

        if selected_label and label_choice != "none":
            # User went through label selection workflow
            label_path = labels_dir / "label.jpg"

            # Determine which version to use (cropped or original)
            use_crop = selected_label.get("use_crop", False)
            source_path = None

            logger.info(f"Label selection workflow: use_crop={use_crop}, has_cropped={selected_label.get('cropped_path') is not None}, has_original={selected_label.get('original_path') is not None}")

            if use_crop and selected_label.get("cropped_path"):
                source_path = Path(selected_label["cropped_path"])
                logger.info(f"Using CROPPED label version from {source_path}")
            elif selected_label.get("original_path"):
                source_path = Path(selected_label["original_path"])
                logger.info(f"Using ORIGINAL label version from {source_path}")

            # Copy the selected label to final location
            if source_path:
                if source_path.exists():
                    import shutil
                    shutil.copy2(source_path, label_path)
                    logger.info(f"✓ Copied selected label to {label_path}")
                else:
                    logger.error(f"✗ Selected label file NOT FOUND: {source_path}")
                    logger.error(f"  - File exists check failed")
                    logger.error(f"  - Directory exists: {source_path.parent.exists()}")
                    if source_path.parent.exists():
                        logger.error(f"  - Files in directory: {list(source_path.parent.iterdir())}")
                    label_path = None
            else:
                logger.error(f"✗ No source_path determined! selected_label={selected_label}")
                label_path = None

        elif label_choice == "none":
            # User chose "none" - just create empty labels directory
            # They can add their own label.jpg later
            logger.info("No label selected - user will add their own")
            label_path = None

        elif session_data.get("upload_type") == "bottle_image":
            # Fallback: Single bottle upload without label workflow
            temp_file_path = Path(session_data.get("temp_file_path", ""))
            if temp_file_path.exists():
                label_path = labels_dir / "label.jpg"
                import shutil
                shutil.copy2(temp_file_path, label_path)
                logger.info("Copied uploaded bottle image as label (no selection workflow)")

        # Mark bottle as approved in session
        bottles[bottle_index]["stage"] = "approved"
        session_data["bottles"] = bottles

        # Check if all bottles are approved
        all_approved = all(b.get("stage") == "approved" for b in bottles)

        if all_approved:
            # Clean up temp files if all bottles are approved
            upload_service.cleanup_session_files(extraction_id)
            # Clear session
            response.delete_cookie(key="session")
        else:
            # Update session for remaining bottles
            new_session_token = session_manager.create_session(session_data)
            response.set_cookie(
                key="session",
                value=new_session_token,
                max_age=web_config.sessions.max_age_hours * 3600,
                httponly=True,
            secure=False,  # Allow over HTTP for local network access
                samesite="lax"
            )

        logger.info(f"Bottle {bottle_index} approved and saved to {obsidian_file.file_path}")

        return {
            "status": "approved",
            "file_created": str(obsidian_file.file_path.relative_to(vault_path)),
            "label_saved": label_path is not None,
            "all_approved": all_approved,
            "remaining_bottles": len([b for b in bottles if b.get("stage") != "approved"])
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve bottle: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/{extraction_id}/reject")
async def reject_bottles(
    extraction_id: str,
    request: Request,
    response: Response
):
    """
    Reject all bottles and clean up.

    Args:
        extraction_id: Extraction ID
        request: FastAPI request
        response: FastAPI response

    Returns:
        Rejection status
    """
    from ...app import upload_service, web_config

    if not upload_service or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Clean up temp files
        upload_service.cleanup_session_files(extraction_id)

        # Clear session cookie
        response.delete_cookie(key="session")

        logger.info(f"Bottles rejected and cleaned up: {extraction_id}")

        return {"status": "rejected"}

    except Exception as e:
        logger.error(f"Failed to reject bottles: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/{extraction_id}/check-duplicates/{bottle_index}")
async def check_duplicates(
    extraction_id: str,
    bottle_index: int,
    request: Request,
    response: Response
):
    """
    Check for potential duplicate bottles in the vault.

    Args:
        extraction_id: Extraction ID
        bottle_index: Index of bottle to check
        request: FastAPI request
        response: FastAPI response

    Returns:
        List of potential duplicates
    """
    from ...app import core_config, web_config
    from ...services.duplicate_service import DuplicateDetectionService

    if not core_config or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get session
        session_token = request.cookies.get("session")
        if not session_token:
            raise HTTPException(status_code=404, detail="No session found")

        session_manager = SessionManager(
            secret_key=web_config.sessions.secret_key,
            max_age_hours=web_config.sessions.max_age_hours
        )

        session_data = session_manager.read_session(session_token)
        if not session_data or session_data.get("extraction_id") != extraction_id:
            raise HTTPException(status_code=404, detail="Extraction not found")

        bottles = session_data.get("bottles", [])
        if bottle_index >= len(bottles):
            raise HTTPException(status_code=404, detail="Bottle index out of range")

        bottle_data = bottles[bottle_index]

        # Convert to BottleMetadata
        extraction_service = ExtractionService(core_config)
        bottle = extraction_service.bottle_from_dict(bottle_data["bottle"])

        # Check for duplicates (using lower threshold for manual checks)
        duplicate_service = DuplicateDetectionService(core_config.vault_path)
        duplicates = duplicate_service.find_potential_duplicates(bottle, threshold=0.5)

        # Add label image URLs to each duplicate
        for dup in duplicates:
            # file_path is relative to vault, e.g., "1_Wines/Napa Valley/Producer - Name (Year).md"
            # We need to find the label image in the Labels directory
            file_path = Path(dup["file_path"])
            # Extract bottle type (wines, whiskeys, or spirits) from path
            if "1_Wines" in str(file_path):
                bottle_type = "wines"
            elif "1_Whiskeys" in str(file_path):
                bottle_type = "whiskeys"
            elif "1_Spirits" in str(file_path):
                bottle_type = "spirits"
            else:
                bottle_type = "spirits"  # Default to spirits for unknown types

            # Construct label image path: Labels/wines/Producer - Name (Year).jpg
            label_filename = file_path.stem + ".jpg"  # .stem removes .md extension
            label_path = core_config.vault_path / "Labels" / bottle_type / label_filename

            # Check if label exists and add URL
            if label_path.exists():
                dup["label_url"] = f"/api/v1/vault-images/{bottle_type}/{label_filename}"
            else:
                dup["label_url"] = None

        # Store duplicates in session
        bottles[bottle_index]["potential_duplicates"] = duplicates
        session_data["bottles"] = bottles

        new_session_token = session_manager.create_session(session_data)
        response.set_cookie(
            key="session",
            value=new_session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            secure=False,  # Allow over HTTP for local network access
            samesite="lax"
        )

        logger.info(f"Found {len(duplicates)} potential duplicates for bottle {bottle_index}")

        return {
            "status": "checked",
            "duplicates": duplicates,
            "count": len(duplicates)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to check duplicates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/{extraction_id}/skip/{bottle_index}")
async def skip_bottle(
    extraction_id: str,
    bottle_index: int,
    request: Request,
    response: Response
):
    """
    Skip a bottle (mark as skipped, won't be saved).

    Args:
        extraction_id: Extraction ID
        bottle_index: Index of bottle to skip
        request: FastAPI request
        response: FastAPI response

    Returns:
        Skip confirmation
    """
    from ...app import upload_service, web_config

    if not upload_service or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get session
        session_token = request.cookies.get("session")
        if not session_token:
            raise HTTPException(status_code=404, detail="No session found")

        session_manager = SessionManager(
            secret_key=web_config.sessions.secret_key,
            max_age_hours=web_config.sessions.max_age_hours
        )

        session_data = session_manager.read_session(session_token)
        if not session_data or session_data.get("extraction_id") != extraction_id:
            raise HTTPException(status_code=404, detail="Extraction not found")

        bottles = session_data.get("bottles", [])
        if bottle_index >= len(bottles):
            raise HTTPException(status_code=404, detail="Bottle index out of range")

        # Mark as skipped
        bottles[bottle_index]["stage"] = "skipped"
        session_data["bottles"] = bottles

        # Check if all bottles are done (approved or skipped)
        all_done = all(b.get("stage") in ["approved", "skipped"] for b in bottles)

        if all_done:
            # Clean up temp files if all bottles are done
            upload_service.cleanup_session_files(extraction_id)
            # Clear session
            response.delete_cookie(key="session")
        else:
            # Update session for remaining bottles
            new_session_token = session_manager.create_session(session_data)
            response.set_cookie(
                key="session",
                value=new_session_token,
                max_age=web_config.sessions.max_age_hours * 3600,
                httponly=True,
            secure=False,  # Allow over HTTP for local network access
                samesite="lax"
            )

        logger.info(f"Bottle {bottle_index} skipped")

        return {
            "status": "skipped",
            "all_done": all_done,
            "remaining_bottles": len([b for b in bottles if b.get("stage") not in ["approved", "skipped"]])
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to skip bottle: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/{extraction_id}/upload-label/{bottle_index}")
async def upload_manual_label(
    extraction_id: str,
    bottle_index: int,
    file: UploadFile,
    try_crop: bool = Form(True),
    request: Request = None,
    response: Response = None
):
    """
    Upload a manual label image for a bottle.

    Args:
        extraction_id: Extraction ID
        bottle_index: Index of bottle
        file: Uploaded image file
        try_crop: Whether to attempt cropping
        request: FastAPI request
        response: FastAPI response

    Returns:
        Upload result with file paths
    """
    from ...app import core_config, upload_service, web_config
    from fastapi import UploadFile, Form

    if not core_config or not upload_service or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get session
        session_token = request.cookies.get("session")
        if not session_token:
            raise HTTPException(status_code=404, detail="No session found")

        session_manager = SessionManager(
            secret_key=web_config.sessions.secret_key,
            max_age_hours=web_config.sessions.max_age_hours
        )

        session_data = session_manager.read_session(session_token)
        if not session_data or session_data.get("extraction_id") != extraction_id:
            raise HTTPException(status_code=404, detail="Extraction not found")

        bottles = session_data.get("bottles", [])
        if bottle_index >= len(bottles):
            raise HTTPException(status_code=404, detail="Bottle index out of range")

        # Save uploaded file to temp location
        temp_label_dir = upload_service.temp_dir / extraction_id / "labels"
        temp_label_dir.mkdir(parents=True, exist_ok=True)

        original_path = temp_label_dir / f"manual_{uuid.uuid4().hex[:8]}.jpg"

        # Save uploaded file
        content = await file.read()
        original_path.write_bytes(content)

        logger.info(f"Manual label uploaded: {original_path}")

        # Optionally crop
        has_crop = False
        cropped_path = temp_label_dir / f"cropped_{uuid.uuid4().hex[:8]}.jpg"

        if try_crop:
            # Copy to cropped path and try to crop it
            import shutil
            from ...services.label_service import LabelService
            shutil.copy2(original_path, cropped_path)

            # Try to crop
            label_service = LabelService(ExtractionService(core_config).llm_gateway)
            try:
                result = await label_service.label_processor.crop_to_label(cropped_path)
                has_crop = result is not None
                if has_crop:
                    logger.info("Manual label cropped successfully")
                else:
                    logger.info("Could not detect label boundaries in manual upload")
                    cropped_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"Manual label cropping failed: {e}")
                cropped_path.unlink(missing_ok=True)

        # Store in session
        bottles[bottle_index]["selected_label"] = {
            "url": "manual_upload",
            "original_path": str(original_path),
            "cropped_path": str(cropped_path) if has_crop else None,
            "use_crop": try_crop and has_crop
        }
        bottles[bottle_index]["label_choice"] = "cropped" if (try_crop and has_crop) else "original"
        session_data["bottles"] = bottles

        new_session_token = session_manager.create_session(session_data)
        response.set_cookie(
            key="session",
            value=new_session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            secure=False,  # Allow over HTTP for local network access
            samesite="lax"
        )

        logger.info(f"Manual label uploaded for bottle {bottle_index}")

        return {
            "status": "uploaded",
            "has_crop": has_crop,
            "using": "cropped" if (try_crop and has_crop) else "original",
            "original_filename": original_path.name,
            "cropped_filename": cropped_path.name if has_crop else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to upload manual label: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


