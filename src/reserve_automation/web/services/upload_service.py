"""Upload file handling service."""

import hashlib
import os
import uuid
from pathlib import Path
from typing import Optional

from fastapi import UploadFile, HTTPException


class UploadService:
    """Handles file uploads and validation."""

    def __init__(
        self,
        temp_dir: str,
        max_file_size_mb: int,
        allowed_extensions: list[str]
    ):
        """
        Initialize upload service.

        Args:
            temp_dir: Directory for temporary file storage
            max_file_size_mb: Maximum file size in megabytes
            allowed_extensions: List of allowed file extensions
        """
        self.temp_dir = Path(temp_dir)
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self.allowed_extensions = [ext.lower() for ext in allowed_extensions]

        # Create temp directory if it doesn't exist
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def validate_file(self, file: UploadFile) -> None:
        """
        Validate uploaded file.

        Args:
            file: Uploaded file

        Raises:
            HTTPException: If file is invalid
        """
        # Check filename
        if not file.filename:
            raise HTTPException(status_code=400, detail="No filename provided")

        # Check extension
        extension = Path(file.filename).suffix.lower().lstrip('.')
        if extension not in self.allowed_extensions:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: {', '.join(self.allowed_extensions)}"
            )

        # Check file size
        if file.size and file.size > self.max_file_size_bytes:
            max_mb = self.max_file_size_bytes / 1024 / 1024
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {max_mb:.0f}MB"
            )

    async def save_upload(self, file: UploadFile, session_id: str) -> Path:
        """
        Save uploaded file to temp directory.

        Args:
            file: Uploaded file
            session_id: Session ID for organizing files

        Returns:
            Path to saved file

        Raises:
            HTTPException: If save fails
        """
        # Validate first
        self.validate_file(file)

        # Create session directory
        session_dir = self.temp_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        # Generate safe filename
        extension = Path(file.filename).suffix
        safe_filename = f"original{extension}"
        file_path = session_dir / safe_filename

        # Save file
        try:
            content = await file.read()

            # Double-check size after reading
            if len(content) > self.max_file_size_bytes:
                raise HTTPException(status_code=413, detail="File too large")

            with open(file_path, "wb") as f:
                f.write(content)

            return file_path

        except Exception as e:
            # Clean up on error
            if file_path.exists():
                file_path.unlink()
            raise HTTPException(status_code=500, detail=f"Failed to save file: {str(e)}")

    def cleanup_session_files(self, session_id: str) -> None:
        """
        Delete all files for a session.

        Args:
            session_id: Session ID
        """
        session_dir = self.temp_dir / session_id
        if session_dir.exists():
            # Remove all files in session directory
            for file_path in session_dir.iterdir():
                if file_path.is_file():
                    file_path.unlink()
            # Remove directory
            session_dir.rmdir()

    def cleanup_old_files(self, max_age_hours: int) -> int:
        """
        Clean up orphaned files older than specified age.

        Args:
            max_age_hours: Delete files older than this many hours

        Returns:
            Number of files deleted
        """
        import time

        max_age_seconds = max_age_hours * 3600
        current_time = time.time()
        deleted_count = 0

        # Iterate through all session directories
        for session_dir in self.temp_dir.iterdir():
            if not session_dir.is_dir():
                continue

            # Check all files in session directory
            session_is_old = True
            for file_path in session_dir.iterdir():
                if not file_path.is_file():
                    continue

                # Check file age
                file_age = current_time - file_path.stat().st_mtime
                if file_age > max_age_seconds:
                    file_path.unlink()
                    deleted_count += 1
                else:
                    # At least one file is recent
                    session_is_old = False

            # Remove empty/old session directories
            if session_is_old and not list(session_dir.iterdir()):
                session_dir.rmdir()

        return deleted_count
