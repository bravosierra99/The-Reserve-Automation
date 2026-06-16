"""Bottle upload and extraction endpoints - STATELESS (no sessions)."""

import asyncio
import json
import shutil
import uuid
from pathlib import Path
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

from ...auth.dependencies import require
from ...services.extraction_service import ExtractionService


def _sse(data: dict) -> str:
    """Format a server-sent event."""
    return f"data: {json.dumps(data)}\n\n"


def _format_extraction_error(e: Exception) -> str:
    """Convert exceptions into user-friendly error messages."""
    err_str = str(e)
    err_lower = err_str.lower()

    if isinstance(e, httpx.TimeoutException) or "timed out" in err_lower or "timeout" in err_lower:
        return (
            "Request timed out. The model may be loading — this can take 2–5 minutes "
            "for large models. Please wait a moment and try again."
        )
    if isinstance(e, httpx.ConnectError) or "connection refused" in err_lower or "connect" in err_lower:
        return (
            "Cannot connect to LM Studio. Please make sure LM Studio is running "
            "and a model is loaded."
        )
    if "model" in err_lower and ("not loaded" in err_lower or "load" in err_lower):
        return (
            "The model is not loaded in LM Studio. Please open LM Studio, "
            "load a vision model, and try again."
        )
    if "failed to extract" in err_lower or "none" in err_lower:
        return (
            "Could not extract bottle data from the image. "
            "Make sure the label is clearly visible and try again."
        )
    if "file too large" in err_lower:
        return "File is too large. Please use a smaller image."
    if "invalid file type" in err_lower:
        return "Invalid file type. Please upload a JPEG, PNG, or PDF."
    # Fall back to the raw message, stripped of internal details
    return f"Extraction failed: {err_str}"


# Seconds between heartbeat events while an extraction runs. Must stay well under
# the tightest plausible upstream proxy idle-timeout (nginx proxy_read_timeout
# defaults to 60s). Module-level so tests can shrink it.
_HEARTBEAT_INTERVAL_SECONDS = 15


async def _await_with_heartbeat(coro, on_status, status, message_fn, interval=None):
    """Await `coro` while emitting a heartbeat status event every `interval`
    seconds.

    The extraction LLM call can run for ~100s+ with no output. An SSE response
    that goes silent that long trips an upstream proxy idle-timeout before the
    'complete' event ever lands (nginx proxy_read_timeout defaults to 60s;
    Cloudflare's 524 fires ~100s) — so the browser sees a failure even though
    the backend finishes fine. Periodic heartbeats keep the stream alive.

    Returns the coroutine's result; re-raises its exception.
    """
    import time

    if interval is None:
        interval = _HEARTBEAT_INTERVAL_SECONDS

    task = asyncio.ensure_future(coro)
    start = time.monotonic()
    while True:
        done, _ = await asyncio.wait({task}, timeout=interval)
        if done:
            return task.result()  # re-raises if the extraction failed
        elapsed = int(time.monotonic() - start)
        await on_status(status, message_fn(elapsed))


router = APIRouter()

# Templates
templates_dir = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_dir)


@router.post("/api/v1/bottles/upload", dependencies=[Depends(require("bottles.create"))])
async def upload_bottle(
    file: UploadFile = File(...),
    upload_type: str = Form("bottle_image"),  # bottle_image or manifest
    beverage_type: str = Form("auto"),  # wine, whiskey, auto
    expected_count: Optional[int] = Form(None),  # Expected bottle count (optional)
    purchase_source: Optional[str] = Form(None),  # Where bottle was purchased
    inventory: int = Form(0),  # Number of bottles in inventory
):
    """
    Upload and extract bottle data from image or manifest.

    NO SESSIONS - Returns JSON with bottle data directly.
    Frontend stores in client-side state (Alpine.js).

    Args:
        file: Uploaded file
        upload_type: Type of upload (bottle_image or manifest)
        beverage_type: Type of beverage (wine, whiskey, auto)
        expected_count: Expected number of bottles (helps improve extraction accuracy)
        purchase_source: Where the bottle was purchased
        inventory: Number of bottles in inventory (default 0)

    Returns:
        {
            "upload_id": str,  # For temp file management
            "bottles": [...]    # Array of BottleMetadata objects as JSON
            "is_manifest": bool
        }
    """
    from ...app import core_config, upload_service

    if not upload_service or not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    logger.info(f"Processing bottle upload: {file.filename} (type: {upload_type}, beverage: {beverage_type}, expected_count: {expected_count})")

    try:
        # Generate upload ID for temp file management
        upload_id = str(uuid.uuid4())

        # Save uploaded file to /tmp/upload_{upload_id}/
        file_path = await upload_service.save_upload(file, upload_id)
        logger.info(f"Saved upload to: {file_path}")

        # Copy uploaded image to labels/label.jpg for display in modal
        import shutil
        from pathlib import Path
        upload_dir = Path(file_path).parent
        labels_dir = upload_dir / "labels"
        labels_dir.mkdir(exist_ok=True)

        # Copy the uploaded file as label.jpg
        label_path = labels_dir / "label.jpg"
        shutil.copy(file_path, label_path)
        logger.info(f"Copied label to: {label_path}")

        # Extract data based on upload type
        extraction_service = ExtractionService(core_config)

        if upload_type == "bottle_image":
            # Extract from single bottle label image
            bottle, extraction_meta = await extraction_service.extract_bottle_from_image(
                image_path=file_path,
                beverage_type=beverage_type
            )

            # Apply purchase info
            if purchase_source:
                bottle.purchase_source = purchase_source
            bottle.inventory = inventory

            bottles = [extraction_service.bottle_to_dict(bottle)]

        elif upload_type == "manifest":
            # Extract multiple bottles from manifest
            extracted_bottles = await extraction_service.extract_bottles_from_manifest(
                file_path=file_path,
                beverage_type=beverage_type,
                expected_count=expected_count
            )

            # Apply purchase info to all bottles
            for bottle in extracted_bottles:
                if purchase_source:
                    bottle.purchase_source = purchase_source
                bottle.inventory = inventory

            bottles = [extraction_service.bottle_to_dict(bottle) for bottle in extracted_bottles]

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported upload_type: {upload_type}"
            )

        logger.info(f"Extraction complete: {upload_id}, {len(bottles)} bottle(s)")

        # Return JSON directly - NO sessions!
        return {
            "upload_id": upload_id,
            "bottles": bottles,
            "is_manifest": upload_type == "manifest"
        }

    except Exception as e:
        logger.error(f"Bottle upload processing failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/v1/bottles/upload/stream", dependencies=[Depends(require("bottles.create"))])
async def upload_bottle_stream(
    file: UploadFile = File(...),
    upload_type: str = Form("bottle_image"),
    beverage_type: str = Form("auto"),
    expected_count: Optional[int] = Form(None),
    purchase_source: Optional[str] = Form(None),
    inventory: int = Form(0),
):
    """
    Upload and extract bottle data with real-time status updates via SSE.

    Returns a text/event-stream where each event is a JSON object:
      { "status": "uploading"|"checking_model"|"extracting"|"complete"|"error",
        "message": "...",
        ... extra fields on "complete" }

    On "complete":
      { "status": "complete", "upload_id": str, "bottles": [...], "is_manifest": bool }
    On "error":
      { "status": "error", "message": "..." }
    """
    from ...app import core_config, upload_service

    if not upload_service or not core_config:
        raise HTTPException(status_code=500, detail="Service not initialized")

    # Read the file content NOW (before the generator starts — UploadFile is not re-readable)
    file_content = await file.read()
    file_name = file.filename or "upload"
    upload_id = str(uuid.uuid4())

    # Determine which LM Studio model/URL will be used for status messages
    routing = core_config.llm.get("routing", {})
    providers_cfg = core_config.llm.get("providers", {})
    ocr_provider_name = routing.get("ocr", "lm_studio_vision")
    ocr_cfg = providers_cfg.get(ocr_provider_name, {})
    model_name = ocr_cfg.get("model", "vision model")
    lm_base_url = ocr_cfg.get("base_url", "http://localhost:1234/v1")

    async def run_pipeline(on_status):
        """Run the full upload → extract pipeline, calling on_status at each stage."""
        try:
            # ── Stage 1: Save upload ──────────────────────────────────────────
            await on_status("uploading", "Saving image...")

            ext = Path(file_name).suffix or ".jpg"
            session_dir = upload_service.temp_dir / upload_id
            session_dir.mkdir(parents=True, exist_ok=True)
            file_path = session_dir / f"original{ext}"
            with open(file_path, "wb") as f:
                f.write(file_content)

            # Copy to labels subdirectory (used by the review modal)
            labels_dir = session_dir / "labels"
            labels_dir.mkdir(exist_ok=True)
            shutil.copy(file_path, labels_dir / "label.jpg")

            # ── Stage 2: Check / wait for model ──────────────────────────────
            await on_status(
                "checking_model",
                f"Connecting to LM Studio ({model_name})..."
            )
            model_ready = await _poll_for_model(lm_base_url, model_name, on_status)
            if not model_ready:
                await on_status(
                    "error",
                    f"Model '{model_name}' did not become available. "
                    "Please open LM Studio, load the model, and try again."
                )
                return

            # ── Stage 3: Extract ──────────────────────────────────────────────
            if upload_type == "bottle_image":
                await on_status("extracting", "Analyzing bottle label...")
            elif upload_type == "manifest":
                await on_status("extracting", "Processing manifest — this may take several minutes...")
            else:
                await on_status("error", f"Unsupported upload type: {upload_type}")
                return

            extraction_service = ExtractionService(core_config)

            if upload_type == "bottle_image":
                bottle, _ = await _await_with_heartbeat(
                    extraction_service.extract_bottle_from_image(
                        image_path=file_path,
                        beverage_type=beverage_type
                    ),
                    on_status,
                    "extracting",
                    lambda s: f"Analyzing bottle label... ({s}s elapsed)",
                )
                if purchase_source:
                    bottle.purchase_source = purchase_source
                bottle.inventory = inventory
                bottles = [extraction_service.bottle_to_dict(bottle)]

            else:  # manifest
                extracted = await _await_with_heartbeat(
                    extraction_service.extract_bottles_from_manifest(
                        file_path=file_path,
                        beverage_type=beverage_type,
                        expected_count=expected_count
                    ),
                    on_status,
                    "extracting",
                    lambda s: f"Processing manifest... ({s}s elapsed)",
                )
                for b in extracted:
                    if purchase_source:
                        b.purchase_source = purchase_source
                    b.inventory = inventory
                bottles = [extraction_service.bottle_to_dict(b) for b in extracted]

            logger.info(f"Stream extraction complete: {upload_id}, {len(bottles)} bottle(s)")

            # ── Stage 4: Done ─────────────────────────────────────────────────
            await on_status(
                "complete",
                f"Done! Found {len(bottles)} bottle(s).",
                upload_id=upload_id,
                bottles=bottles,
                is_manifest=upload_type == "manifest",
            )

        except Exception as e:
            logger.error(f"Stream pipeline failed: {e}", exc_info=True)
            await on_status("error", _format_extraction_error(e))

    async def event_stream():
        queue: asyncio.Queue = asyncio.Queue()

        async def on_status(status: str, message: str, **extra):
            await queue.put({"status": status, "message": message, **extra})

        task = asyncio.create_task(run_pipeline(on_status))

        try:
            while True:
                item = await queue.get()
                yield _sse(item)
                if item.get("status") in ("complete", "error"):
                    break
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _poll_for_model(
    base_url: str,
    model_name: str,
    on_status,
    max_wait_seconds: int = 300,
    poll_interval: int = 8,
) -> bool:
    """
    Check whether the model is available in LM Studio.

    If not immediately available, stream "model_loading" status events and poll
    every poll_interval seconds until the model appears or max_wait_seconds elapses.

    Returns True if model became available, False on timeout.
    """
    import time

    async def _is_loaded() -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{base_url}/models")
                if resp.status_code == 200:
                    loaded = resp.json().get("data", [])
                    for m in loaded:
                        mid = m.get("id", "")
                        if model_name in mid or mid in model_name:
                            return True
        except Exception:
            pass
        return False

    # Fast path — model already loaded
    if await _is_loaded():
        return True

    # Model not yet available — stream waiting messages
    start = time.monotonic()
    while True:
        elapsed = int(time.monotonic() - start)
        if elapsed >= max_wait_seconds:
            return False

        remaining = max_wait_seconds - elapsed
        await on_status(
            "model_loading",
            f"Waiting for model to load... ({elapsed}s elapsed, "
            f"up to {remaining}s remaining). "
            "Large models can take 2–5 minutes to load into memory."
        )

        await asyncio.sleep(poll_interval)

        if await _is_loaded():
            await on_status("model_ready", "Model is ready!")
            return True


@router.get("/api/v1/bottles/search", dependencies=[Depends(require("bottles.view"))])
async def search_bottles(
    q: str,
    beverage_type: Optional[str] = None,
    limit: int = 10,
    event_id: Optional[str] = None
):
    """
    Search for bottles in the vault.

    This is a read-only endpoint that searches the user's local vault.
    No authentication required - the vault is already accessible to anyone
    using the web interface (it's their own data).

    Args:
        q: Search query string
        beverage_type: Optional filter (whiskey, wine, spirit)
        limit: Maximum results to return
        event_id: Optional event ID (restricts to event bottles only)
    """
    from ....db.engine import get_db
    from ....db.repositories.bottle_repo import SQLiteBottleRepository
    from ....db.repositories.tasting_repo import SQLiteTastingRepository
    from ...services.tasting_service import TastingService

    db = next(get_db())
    tasting_service = TastingService(SQLiteBottleRepository(db), SQLiteTastingRepository(db))
    results = tasting_service.search_bottles(
        query=q,
        beverage_type=beverage_type,
        limit=limit,
        event_id=event_id
    )

    return {
        "query": q,
        "results": [r.model_dump() for r in results]
    }


# Removed deprecated session-based endpoint /api/v1/bottles/{extraction_id}
# The new stateless bottle upload returns data directly as JSON
# Frontend stores in Alpine.js client-side state (no session lookup needed)


