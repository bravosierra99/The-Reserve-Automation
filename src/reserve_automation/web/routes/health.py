"""Health check endpoints."""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

router = APIRouter()


def _get_git_info() -> dict:
    """Get git version information."""
    try:
        # Get git commit hash
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

        # Get short hash
        commit_short = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

        # Get branch name
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

        # Check if working directory is clean
        status = subprocess.check_output(
            ["git", "status", "--porcelain"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        is_clean = len(status) == 0

        # Get last commit message
        commit_message = subprocess.check_output(
            ["git", "log", "-1", "--pretty=%B"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

        # Get commit date
        commit_date = subprocess.check_output(
            ["git", "log", "-1", "--format=%ai"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()

        return {
            "commit": commit,
            "commit_short": commit_short,
            "branch": branch,
            "clean": is_clean,
            "commit_message": commit_message,
            "commit_date": commit_date,
        }
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {
            "commit": "unknown",
            "commit_short": "unknown",
            "branch": "unknown",
            "clean": None,
            "commit_message": "Git not available",
            "commit_date": None,
        }


@router.get("/health")
async def health_check():
    """
    Health check endpoint with version and deployment information.

    Returns:
        Status information including git commit, Python version, etc.
    """
    git_info = _get_git_info()

    return {
        "status": "healthy",
        "service": "The Reserve Automation",
        "version": "0.1.0",
        "git": {
            "commit": git_info["commit_short"],  # Short hash for readability
            "commit_full": git_info["commit"],
            "branch": git_info["branch"],
            "clean": git_info["clean"],
            "message": git_info["commit_message"],
            "date": git_info["commit_date"],
        },
        "runtime": {
            "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "platform": sys.platform,
        },
        "timestamp": datetime.now().isoformat(),
    }
