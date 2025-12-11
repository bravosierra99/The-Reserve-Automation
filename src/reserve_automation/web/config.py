"""Web application configuration."""

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

from reserve_automation.core.config import Config as CoreConfig


class UploadConfig(BaseModel):
    """Upload settings."""
    max_file_size_mb: int = Field(default=20, description="Maximum file size in MB")
    allowed_extensions: list[str] = Field(
        default=["jpg", "jpeg", "png", "pdf"],
        description="Allowed file extensions"
    )
    temp_dir: str = Field(
        default="/tmp/reserve_uploads",
        description="Temporary directory for uploads"
    )
    cleanup_age_hours: int = Field(
        default=24,
        description="Delete orphaned files older than this many hours"
    )


class SessionConfig(BaseModel):
    """Session management settings."""
    secret_key: str = Field(
        ...,
        description="Secret key for session encryption (32+ char random string)"
    )
    max_age_hours: int = Field(
        default=24,
        description="Session expires after this many hours"
    )


class FeaturesConfig(BaseModel):
    """Feature flags for future functionality."""
    multi_user_sessions: bool = Field(default=False, description="Enable multi-user tasting sessions")
    authentication: bool = Field(default=False, description="Enable user authentication")
    real_time_updates: bool = Field(default=False, description="Enable WebSocket real-time updates")


class WebConfig(BaseModel):
    """Web application configuration."""
    host: str = Field(default="0.0.0.0", description="Bind host")
    port: int = Field(default=8000, description="Bind port")
    uploads: UploadConfig = Field(default_factory=UploadConfig)
    sessions: SessionConfig
    features: FeaturesConfig = Field(default_factory=FeaturesConfig)


def load_web_config() -> tuple[CoreConfig, WebConfig]:
    """
    Load both core and web configurations.

    Returns:
        Tuple of (core_config, web_config)
    """
    # Load core config
    core_config = CoreConfig.load()

    # Load web config from environment variables
    secret_key = os.getenv("WEB_SECRET_KEY")
    if not secret_key:
        raise ValueError(
            "WEB_SECRET_KEY environment variable is required. "
            "Generate one with: openssl rand -hex 32"
        )

    web_config = WebConfig(
        host=os.getenv("WEB_HOST", "0.0.0.0"),
        port=int(os.getenv("WEB_PORT", "8000")),
        uploads=UploadConfig(
            temp_dir=os.getenv("WEB_TEMP_DIR", "/tmp/reserve_uploads"),
            max_file_size_mb=int(os.getenv("WEB_MAX_FILE_SIZE_MB", "20")),
        ),
        sessions=SessionConfig(
            secret_key=secret_key,
            max_age_hours=int(os.getenv("WEB_SESSION_MAX_AGE_HOURS", "24"))
        )
    )

    return core_config, web_config
