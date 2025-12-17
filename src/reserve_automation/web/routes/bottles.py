"""Bottle upload and review endpoints."""

import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, Response, Cookie, HTTPException, Request
from fastapi.templating import Jinja2Templates
from loguru import logger

from ..sessions import SessionManager
from ..services.upload_service import UploadService
from ..services.extraction_service import ExtractionService

router = APIRouter()

# Templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


@router.post("/api/v1/bottles/upload")
async def upload_bottle(
    response: Response,
    file: UploadFile = File(...),
    upload_type: str = Form("bottle_image"),  # bottle_image or manifest
    beverage_type: str = Form("auto"),  # wine, whiskey, auto
    expected_count: Optional[int] = Form(None),  # Expected bottle count (optional)
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """
    Upload and extract bottle data from image or manifest.

    Args:
        response: FastAPI response for setting cookies
        file: Uploaded file
        upload_type: Type of upload (bottle_image or manifest)
        beverage_type: Type of beverage (wine, whiskey, auto)
        expected_count: Expected number of bottles (helps improve extraction accuracy)
        session_token: Existing session token (if any)

    Returns:
        Upload result with extraction_id and bottles data
    """
    from ..app import upload_service, core_config, web_config

    if not upload_service or not core_config or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    logger.info(f"Processing bottle upload: {file.filename} (type: {upload_type}, beverage: {beverage_type}, expected_count: {expected_count})")

    try:
        # Generate session ID
        session_id = str(uuid.uuid4())

        # Save uploaded file
        file_path = await upload_service.save_upload(file, session_id)
        logger.info(f"Saved upload to: {file_path}")

        # Extract data based on upload type
        extraction_service = ExtractionService(core_config)

        if upload_type == "bottle_image":
            # Extract from single bottle label image
            bottle, extraction_meta = await extraction_service.extract_bottle_from_image(
                image_path=file_path,
                beverage_type=beverage_type
            )

            bottles_data = [{
                "bottle": extraction_service.bottle_to_dict(bottle),
                "extraction_meta": extraction_meta,
                "enrichment_meta": None,  # Not enriched yet
                "stage": "extracted"  # Stage 1: extraction complete
            }]

        elif upload_type == "manifest":
            # Extract multiple bottles from manifest
            bottles = await extraction_service.extract_bottles_from_manifest(
                file_path=file_path,
                beverage_type=beverage_type,
                expected_count=expected_count
            )

            bottles_data = [{
                "bottle": extraction_service.bottle_to_dict(bottle),
                "extraction_meta": {"confidence": bottle.confidence},
                "enrichment_meta": None,
                "stage": "extracted"
            } for bottle in bottles]

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported upload_type: {upload_type}"
            )

        # Create session with extraction data
        session_manager = SessionManager(
            secret_key=web_config.sessions.secret_key,
            max_age_hours=web_config.sessions.max_age_hours
        )

        session_data = {
            "extraction_id": session_id,
            "upload_filename": file.filename,
            "upload_type": upload_type,
            "beverage_type": beverage_type,
            "temp_file_path": str(file_path),
            "bottles": bottles_data,
            "current_bottle_index": 0  # Start with first bottle
        }

        session_token = session_manager.create_session(session_data)

        # Set session cookie
        response.set_cookie(
            key="session",
            value=session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            samesite="lax"
        )

        logger.info(f"Extraction complete: {session_id}, {len(bottles_data)} bottle(s)")

        return {
            "status": "completed",
            "extraction_id": session_id,
            "bottles_count": len(bottles_data),
            "upload_type": upload_type
        }

    except Exception as e:
        logger.error(f"Bottle upload processing failed: {e}", exc_info=True)
        # Clean up on error
        if 'session_id' in locals():
            upload_service.cleanup_session_files(session_id)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/bottles/search")
async def search_bottles(
    q: str,
    beverage_type: Optional[str] = None,
    limit: int = 10,
    session_token: Optional[str] = Cookie(None, alias="session")
):
    """Search for bottles in the vault."""
    from ..app import core_config, web_config
    from ..services.tasting_service import TastingService

    if not core_config or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    if not session_token:
        raise HTTPException(status_code=401, detail="No active session")

    session_manager = SessionManager(
        secret_key=web_config.sessions.secret_key,
        max_age_hours=web_config.sessions.max_age_hours
    )

    session_data = session_manager.read_session(session_token)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    tasting_service = TastingService(core_config)
    results = tasting_service.search_bottles(
        query=q,
        beverage_type=beverage_type,
        limit=limit
    )

    return {
        "query": q,
        "results": [r.model_dump() for r in results]
    }


@router.get("/api/v1/bottles/{extraction_id}")
async def get_bottle_extraction(
    extraction_id: str,
    request: Request
):
    """
    Get bottle extraction data from session.

    Args:
        extraction_id: Extraction ID
        request: FastAPI request

    Returns:
        Extraction data for review
    """
    from ..app import web_config

    if not web_config:
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

        return {
            "extraction_id": extraction_id,
            "upload_type": session_data.get("upload_type"),
            "beverage_type": session_data.get("beverage_type"),
            "bottles": session_data.get("bottles", []),
            "current_bottle_index": session_data.get("current_bottle_index", 0)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to load extraction: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/{extraction_id}/enrich/{bottle_index}")
async def enrich_bottle(
    extraction_id: str,
    bottle_index: int,
    request: Request,
    response: Response
):
    """
    Enrich a specific bottle with web search data (Stage 2).

    Args:
        extraction_id: Extraction ID
        bottle_index: Index of bottle to enrich
        request: FastAPI request
        response: FastAPI response

    Returns:
        Enriched bottle data and changes
    """
    from ..app import core_config, web_config

    if not core_config or not web_config:
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

        # Check if already enriched
        if bottle_data.get("stage") == "enriched":
            return {
                "status": "already_enriched",
                "bottle": bottle_data["bottle"],
                "enrichment_meta": bottle_data["enrichment_meta"]
            }

        # Enrich the bottle
        extraction_service = ExtractionService(core_config)
        bottle = extraction_service.bottle_from_dict(bottle_data["bottle"])

        enriched_bottle, enrichment_meta = await extraction_service.enrich_bottle(bottle)

        # Update session with enriched data
        bottles[bottle_index] = {
            "bottle": extraction_service.bottle_to_dict(enriched_bottle),
            "extraction_meta": bottle_data["extraction_meta"],
            "enrichment_meta": enrichment_meta,
            "stage": "enriched"  # Stage 2: enrichment complete
        }

        session_data["bottles"] = bottles

        # Update session cookie
        new_session_token = session_manager.create_session(session_data)
        response.set_cookie(
            key="session",
            value=new_session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            samesite="lax"
        )

        logger.info(f"Bottle {bottle_index} enriched successfully")

        # Automatically check for duplicates after enrichment
        from ..services.duplicate_service import DuplicateDetectionService
        duplicate_service = DuplicateDetectionService(core_config.vault_path)
        duplicates = duplicate_service.find_potential_duplicates(enriched_bottle, threshold=0.5)

        # Store duplicates in bottle data
        bottles[bottle_index]["potential_duplicates"] = duplicates

        logger.info(f"Auto-duplicate check found {len(duplicates)} potential duplicates")

        return {
            "status": "enriched",
            "bottle": extraction_service.bottle_to_dict(enriched_bottle),
            "enrichment_meta": enrichment_meta,
            "potential_duplicates": duplicates
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to enrich bottle: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/{extraction_id}/find-labels/{bottle_index}")
async def find_labels(
    extraction_id: str,
    bottle_index: int,
    request: Request,
    response: Response
):
    """
    Find label images for a bottle using LLM web search (Stage 2.5).

    Args:
        extraction_id: Extraction ID
        bottle_index: Index of bottle to find labels for
        request: FastAPI request
        response: FastAPI response

    Returns:
        List of label image candidates
    """
    from ..app import core_config, web_config
    from ..services.label_service import LabelService

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

        # Find labels using LLM web search
        label_service = LabelService(extraction_service.llm_gateway)
        label_candidates = await label_service.find_labels(bottle)

        # Store candidates in session
        bottles[bottle_index]["label_candidates"] = label_candidates
        session_data["bottles"] = bottles

        # Update session
        new_session_token = session_manager.create_session(session_data)
        response.set_cookie(
            key="session",
            value=new_session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            samesite="lax"
        )

        logger.info(f"Found {len(label_candidates)} label candidates for bottle {bottle_index}")

        return {
            "status": "found",
            "label_candidates": label_candidates,
            "count": len(label_candidates)
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to find labels: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/{extraction_id}/select-label/{bottle_index}")
async def select_label(
    extraction_id: str,
    bottle_index: int,
    request: Request,
    response: Response
):
    """
    Select and download a label image, with crop approval (Stage 2.75).

    Request body:
        {
            "label_url": "https://...",  // URL to download, or null for no label
            "use_crop": true  // Whether to use cropped version (if applicable)
        }

    Args:
        extraction_id: Extraction ID
        bottle_index: Index of bottle to set label for
        request: FastAPI request
        response: FastAPI response

    Returns:
        Label selection result with preview URLs
    """
    from ..app import core_config, upload_service, web_config
    from ..services.label_service import LabelService
    import uuid

    if not core_config or not upload_service or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get session and body
        session_token = request.cookies.get("session")
        if not session_token:
            raise HTTPException(status_code=404, detail="No session found")

        body = await request.json()
        label_url = body.get("label_url")
        use_crop = body.get("use_crop", True)

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

        # If no label URL, user wants to add their own later
        if not label_url:
            bottles[bottle_index]["selected_label"] = None
            bottles[bottle_index]["label_choice"] = "none"
            session_data["bottles"] = bottles

            new_session_token = session_manager.create_session(session_data)
            response.set_cookie(
                key="session",
                value=new_session_token,
                max_age=web_config.sessions.max_age_hours * 3600,
                httponly=True,
                samesite="lax"
            )

            return {
                "status": "no_label",
                "message": "Label placeholder will be added - you can add your own later"
            }

        # Download and crop label
        label_service = LabelService(ExtractionService(core_config).llm_gateway)

        # Save to temp location first
        temp_label_dir = upload_service.temp_dir / extraction_id / "labels"
        temp_label_dir.mkdir(parents=True, exist_ok=True)

        original_path = temp_label_dir / f"original_{uuid.uuid4().hex[:8]}.jpg"
        cropped_path = temp_label_dir / f"cropped_{uuid.uuid4().hex[:8]}.jpg"

        # Download to original path (no crop)
        await label_service.download_and_crop_label(
            image_url=label_url,
            output_path=original_path,
            crop=False  # Don't crop the original
        )

        # Copy to cropped path and try to crop it
        import shutil
        shutil.copy2(original_path, cropped_path)

        # Try to crop the cropped version
        crop_succeeded = False
        try:
            # First detect bounds using computer vision
            with open(cropped_path, 'rb') as f:
                image_bytes = f.read()

            bounds = label_service.label_processor.detect_label_bounds_cv(image_bytes)

            if bounds:
                # Crop using detected bounds
                result = label_service.label_processor.crop_to_label(cropped_path, bounds)
                crop_succeeded = result is not None
                if crop_succeeded:
                    logger.info("Label cropped successfully")
                else:
                    logger.info("Crop operation failed despite bounds detection")
                    cropped_path.unlink(missing_ok=True)
            else:
                logger.info("Could not detect label boundaries - no crop available")
                # Remove the cropped file if crop failed
                cropped_path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning(f"Label cropping failed: {e}")
            cropped_path.unlink(missing_ok=True)

        has_crop = crop_succeeded and cropped_path.exists()

        # Store selection in session
        bottles[bottle_index]["selected_label"] = {
            "url": label_url,
            "original_path": str(original_path),
            "cropped_path": str(cropped_path) if has_crop else None,
            "use_crop": use_crop and has_crop
        }
        bottles[bottle_index]["label_choice"] = "cropped" if (use_crop and has_crop) else "original"
        session_data["bottles"] = bottles

        new_session_token = session_manager.create_session(session_data)
        response.set_cookie(
            key="session",
            value=new_session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            samesite="lax"
        )

        logger.info(f"Label selected for bottle {bottle_index}: {label_url}")

        return {
            "status": "selected",
            "has_crop": has_crop,
            "using": "cropped" if (use_crop and has_crop) else "original",
            "original_filename": original_path.name,
            "cropped_filename": cropped_path.name if has_crop else None
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to select label: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
    from ..app import web_config

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get session token and request body
        session_token = request.cookies.get("session")
        if not session_token:
            raise HTTPException(status_code=404, detail="No session found")

        body = await request.json()
        updated_bottle_data = body.get("bottle")

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
        session_data["bottles"] = bottles

        # Update session cookie
        new_session_token = session_manager.create_session(session_data)
        response.set_cookie(
            key="session",
            value=new_session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
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
    from ..app import core_config, upload_service, web_config

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

        template_dir = Path(__file__).parent.parent.parent.parent.parent / "templates"
        generator = ObsidianGenerator(vault_path=vault_path, template_dir=template_dir)

        # Generate bottle file
        obsidian_file = generator.generate_bottle_file(bottle)

        # Check if bottle already exists (log warning but allow override)
        if obsidian_file.file_path.exists():
            logger.warning(f"Bottle file already exists, will be overwritten: {obsidian_file.file_path}")

        # Create bottle directory and file
        obsidian_file.file_path.parent.mkdir(parents=True, exist_ok=True)
        obsidian_file.file_path.write_text(obsidian_file.content, encoding="utf-8")

        # Handle label image based on selection workflow
        label_path = None
        labels_dir = obsidian_file.file_path.parent / "labels"
        labels_dir.mkdir(exist_ok=True)

        # Check if user selected a label via the find-labels workflow
        selected_label = bottle_data.get("selected_label")
        label_choice = bottle_data.get("label_choice")

        if selected_label and label_choice != "none":
            # User went through label selection workflow
            label_path = labels_dir / "label.jpg"

            # Determine which version to use (cropped or original)
            use_crop = selected_label.get("use_crop", False)
            source_path = None

            if use_crop and selected_label.get("cropped_path"):
                source_path = Path(selected_label["cropped_path"])
                logger.info("Using cropped label version")
            elif selected_label.get("original_path"):
                source_path = Path(selected_label["original_path"])
                logger.info("Using original label version")

            # Copy the selected label to final location
            if source_path and source_path.exists():
                import shutil
                shutil.copy2(source_path, label_path)
                logger.info(f"Copied selected label to {label_path}")
            else:
                logger.warning(f"Selected label file not found: {source_path}")
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
    from ..app import upload_service, web_config

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
    from ..app import core_config, web_config
    from ..services.duplicate_service import DuplicateDetectionService

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
            # Extract bottle type (wines or whiskeys) from path
            bottle_type = "wines" if "1_Wines" in str(file_path) else "whiskeys"

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
    from ..app import upload_service, web_config

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
    from ..app import core_config, upload_service, web_config
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


@router.get("/api/v1/temp-images/{extraction_id}/{filename}")
async def serve_temp_image(extraction_id: str, filename: str):
    """
    Serve temporary label images for preview.

    Args:
        extraction_id: Extraction session ID
        filename: Name of the temporary image file

    Returns:
        Image file response
    """
    from ..app import web_config
    from fastapi.responses import FileResponse

    if not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Construct path to temp label directory
        temp_label_dir = Path(web_config.uploads.temp_dir) / extraction_id / "labels"
        image_path = temp_label_dir / filename

        # Security: Ensure filename doesn't contain path traversal
        if not image_path.resolve().is_relative_to(temp_label_dir.resolve()):
            raise HTTPException(status_code=403, detail="Invalid filename")

        # Check if file exists
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        # Serve the image
        return FileResponse(
            path=image_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-cache"}
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve temp image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/v1/vault-images/{bottle_type}/{filename}")
async def serve_vault_image(bottle_type: str, filename: str):
    """
    Serve label images from the vault Labels directory.

    Args:
        bottle_type: Type of bottle ('wines' or 'whiskeys')
        filename: Name of the label image file

    Returns:
        Image file response
    """
    from ..app import core_config
    from fastapi.responses import FileResponse

    if not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Validate bottle_type
        if bottle_type not in ["wines", "whiskeys"]:
            raise HTTPException(status_code=400, detail="Invalid bottle type")

        # Construct path to vault label directory
        vault_label_dir = core_config.vault_path / "Labels" / bottle_type
        image_path = vault_label_dir / filename

        # Security: Ensure filename doesn't contain path traversal
        if not image_path.resolve().is_relative_to(vault_label_dir.resolve()):
            raise HTTPException(status_code=403, detail="Invalid filename")

        # Check if file exists
        if not image_path.exists():
            raise HTTPException(status_code=404, detail="Image not found")

        # Serve the image
        return FileResponse(
            path=image_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"}  # Cache for 1 hour
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to serve vault image: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/{extraction_id}/re-extract")
async def re_extract(
    extraction_id: str,
    request: Request,
    response: Response
):
    """
    Re-run extraction on the same uploaded file.

    Useful when the LLM didn't extract all bottles the first time.

    Args:
        extraction_id: Extraction ID
        request: FastAPI request
        response: FastAPI response

    Returns:
        Status of re-extraction
    """
    from ..app import core_config, web_config
    from ..services.extraction import ExtractionService

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

        # Get original upload info
        upload_info = session_data.get("upload_info")
        if not upload_info:
            raise HTTPException(status_code=400, detail="No upload info found - cannot re-extract")

        file_path = Path(upload_info["file_path"])
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Original file no longer exists")

        logger.info(f"Re-extracting from file: {file_path}")

        # Run extraction again
        extraction_service = ExtractionService(core_config)
        bottles = await extraction_service.extract_bottles(
            file_path=file_path,
            expected_count=upload_info.get("expected_count"),
            beverage_type=upload_info.get("beverage_type", "auto")
        )

        logger.info(f"Re-extraction complete: extracted {len(bottles)} bottles")

        # Update session with new extraction
        session_data["bottles"] = [
            {
                "bottle": extraction_service.bottle_to_dict(bottle),
                "stage": "extracted"
            }
            for bottle in bottles
        ]

        # Update session
        new_session_token = session_manager.create_session(session_data)
        response.set_cookie(
            key="session",
            value=new_session_token,
            max_age=web_config.sessions.max_age_hours * 3600,
            httponly=True,
            samesite="lax"
        )

        return {
            "status": "re-extracted",
            "bottle_count": len(bottles),
            "message": f"Successfully re-extracted {len(bottles)} bottles"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Re-extraction failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
