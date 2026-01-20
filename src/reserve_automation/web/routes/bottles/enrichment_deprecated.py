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
    from ...app import core_config, web_config

    if not core_config or not web_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get current bottle data from request body (user's edited version)
        body = await request.json() if request.headers.get("content-type") == "application/json" else {}
        current_bottle_data = body.get("bottle")

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

        # Use current bottle data from frontend if provided, otherwise use session data
        if current_bottle_data:
            logger.info(f"Using current (edited) bottle data for enrichment")
            bottle_dict = current_bottle_data
        else:
            logger.info(f"Using session bottle data for enrichment")
            bottle_dict = bottle_data["bottle"]

        # Always re-run enrichment (even if already enriched)
        # This allows users to re-run if they think more data is available
        logger.info(f"Enriching bottle {bottle_index} (stage: {bottle_data.get('stage')})")

        # Enrich the bottle
        extraction_service = ExtractionService(core_config)
        bottle = extraction_service.bottle_from_dict(bottle_dict)

        enriched_bottle, enrichment_meta = await extraction_service.enrich_bottle(bottle)

        logger.info(f"Bottle {bottle_index} enrichment search complete")

        # DON'T update session yet - just return suggestions
        # The frontend will show the user what changed and let them apply it

        # Calculate what fields changed
        original_dict = bottle_dict
        enriched_dict = extraction_service.bottle_to_dict(enriched_bottle)

        suggestions = {}
        for field, new_value in enriched_dict.items():
            original_value = original_dict.get(field)
            if new_value != original_value and new_value is not None:
                # Don't suggest changes to metadata fields
                if field not in ["confidence", "source", "extracted_at", "enriched", "label_image_url"]:
                    suggestions[field] = {
                        "current": original_value,
                        "suggested": new_value
                    }

        logger.info(f"Found {len(suggestions)} suggested changes")

        return {
            "status": "suggestions_ready",
            "suggestions": suggestions,
            "enrichment_meta": enrichment_meta
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
    from ...app import core_config, web_config
    from ...services.label_service import LabelService

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

        # If user uploaded a bottle image (not manifest), add it as the first candidate
        upload_type = session_data.get("upload_type")
        temp_file_path = session_data.get("temp_file_path")

        if upload_type == "bottle_image" and temp_file_path:
            uploaded_image_path = Path(temp_file_path)
            if uploaded_image_path.exists():
                # Generate a URL to serve the temp uploaded image
                temp_image_url = f"/api/v1/temp-images/{extraction_id}/{uploaded_image_path.name}"

                # Create a candidate for the uploaded image
                uploaded_candidate = {
                    "url": temp_image_url,
                    "source": "uploaded_image",
                    "description": f"Your uploaded image: {session_data.get('upload_filename', 'bottle image')}",
                    "confidence": 1.0  # Highest confidence since it's the actual uploaded image
                }

                # Insert uploaded image as FIRST candidate
                label_candidates.insert(0, uploaded_candidate)
                logger.info(f"Added uploaded image as first label candidate for bottle {bottle_index}")

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
            secure=False,  # Allow over HTTP for local network access
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


@router.post("/api/v1/bottles/search-labels")
async def search_labels_for_bottle(request: Request):
    """
    Search for label images for a bottle (used by management interface).

    Uses the EXACT same label finding logic as the upload flow.

    Request body: BottleMetadata dict

    Returns:
        List of label image candidates
    """
    from ...app import core_config
    from ...services.label_service import LabelService
    from reserve_automation.core.models import BottleMetadata

    if not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    try:
        # Get bottle data from request body
        bottle_data = await request.json()

        logger.info(f"=== LABEL SEARCH REQUEST ===")
        logger.info(f"Producer: {bottle_data.get('producer')}")
        logger.info(f"Name: {bottle_data.get('name')}")
        logger.info(f"Year: {bottle_data.get('year')}")
        logger.info(f"Variety: {bottle_data.get('variety')}")
        logger.info(f"Region: {bottle_data.get('region')}")
        logger.info(f"Vineyard: {bottle_data.get('vineyard')}")
        logger.info(f"Type: {bottle_data.get('type')}")

        # Convert to BottleMetadata
        bottle = BottleMetadata(**bottle_data)

        # Find labels using LLM web search (SAME code as upload flow)
        extraction_service = ExtractionService(core_config)
        label_service = LabelService(extraction_service.llm_gateway)
        label_candidates = await label_service.find_labels(bottle)

        logger.info(f"Found {len(label_candidates)} label candidates")
        for i, candidate in enumerate(label_candidates[:3]):
            logger.info(f"  [{i+1}] {candidate.get('url')} from {candidate.get('source')}")

        return {"images": label_candidates}

    except Exception as e:
        logger.error(f"Failed to search labels: {e}", exc_info=True)
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
    from ...app import core_config, upload_service, web_config
    from ...services.label_service import LabelService
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
            secure=False,  # Allow over HTTP for local network access
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

        # Check if this is an uploaded image (starts with /api/v1/temp-images/)
        import shutil
        if label_url.startswith('/api/v1/temp-images/'):
            # This is the user's uploaded image - copy directly instead of downloading
            temp_file_path = session_data.get("temp_file_path")
            if temp_file_path and Path(temp_file_path).exists():
                shutil.copy2(temp_file_path, original_path)
                logger.info(f"Copied uploaded image from {temp_file_path} to {original_path}")
            else:
                raise HTTPException(status_code=404, detail="Uploaded image not found")
        else:
            # External URL - download it
            await label_service.download_and_crop_label(
                image_url=label_url,
                output_path=original_path,
                crop=False  # Don't crop the original
            )

        # Copy to cropped path and try to crop it
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
            secure=False,  # Allow over HTTP for local network access
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


