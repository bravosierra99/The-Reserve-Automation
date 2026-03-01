"""Health check and identity endpoints."""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request
from loguru import logger

router = APIRouter()


def _get_git_info() -> dict:
    """Get git version information.

    Tries to load from version.json file first (for Docker builds),
    then falls back to git commands if available.
    """
    # First try to load from version.json (generated at Docker build time)
    version_file = Path(__file__).parent.parent.parent / "version.json"
    if version_file.exists():
        try:
            with open(version_file) as f:
                version_data = json.load(f)
                return {
                    "version": version_data.get("version", "dev"),
                    "commit": version_data.get("commit", "unknown"),
                    "commit_short": version_data.get("commit_short", "unknown"),
                    "branch": version_data.get("branch", "unknown"),
                    "clean": version_data.get("clean"),
                    "commit_message": version_data.get("commit_message", "Unknown"),
                    "commit_date": version_data.get("commit_date"),
                    "build_date": version_data.get("build_date"),
                }
        except (json.JSONDecodeError, IOError):
            pass  # Fall through to git commands

    # Fall back to git commands (for local development)
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

        # Get version from git tag
        try:
            version = subprocess.check_output(
                ["git", "describe", "--tags", "--abbrev=0"],
                stderr=subprocess.DEVNULL,
                text=True,
            ).strip()
            # Remove 'v' prefix if present (v1.2.3 -> 1.2.3)
            if version.startswith("v"):
                version = version[1:]
        except subprocess.CalledProcessError:
            version = "dev"  # No tags found

        return {
            "version": version,
            "commit": commit,
            "commit_short": commit_short,
            "branch": branch,
            "clean": is_clean,
            "commit_message": commit_message,
            "commit_date": commit_date,
            "build_date": None,  # Not available from git
        }
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {
            "version": "unknown",
            "commit": "unknown",
            "commit_short": "unknown",
            "branch": "unknown",
            "clean": None,
            "commit_message": "Git not available",
            "commit_date": None,
            "build_date": None,
        }


@router.get("/health")
async def health_check():
    """
    Health check endpoint with version and deployment information.

    Returns:
        Status information including git commit, Python version, etc.
    """
    git_info = _get_git_info()

    response = {
        "status": "healthy",
        "service": "The Reserve Automation",
        "version": git_info["version"],  # From git tag
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

    # Add build date if available (from Docker build)
    if git_info.get("build_date"):
        response["git"]["build_date"] = git_info["build_date"]

    # Log health check with version info for visibility
    logger.info(
        f"Health check: v{response['version']} "
        f"[{git_info['commit_short']}@{git_info['branch']}] "
        f"clean={git_info['clean']}"
    )

    return response


@router.get("/me")
async def get_current_user_info(request: Request):
    """Return the current authenticated user's identity and permissions.

    Used by the frontend to display identity and filter UI elements.
    """
    user = getattr(request.state, "user", None)
    if user is None:
        return {
            "authenticated": False,
            "email": None,
            "role": None,
            "display_name": None,
            "permissions": {},
            "dev_mode": False,
        }

    auth_config = getattr(request.app.state, "auth_config", None)
    permissions = {}
    # Only report dev_mode if this request actually used dev mode
    # (not when accessing through Cloudflare, even if dev.enabled is true in config)
    dev_mode = getattr(request.state, "used_dev_mode", False)
    if auth_config:
        permissions = auth_config.get_permissions_dict(user.role)

    return {
        "authenticated": True,
        "email": user.email,
        "role": user.role,
        "display_name": user.display_name,
        "permissions": permissions,
        "dev_mode": dev_mode,
    }
