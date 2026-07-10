"""Fixtures for contract tests.

Each contract test module gets a database wiped clean at module setup (so
SQLite integer PKs restart at 1 and snapshots are deterministic no matter
which other suites ran first in the session) and a TestClient wired the same
way as the other API suites.
"""

import pytest

from .contract import wipe_database


@pytest.fixture(scope="module")
def contract_db():
    """A DB session against a fully wiped database."""
    from reserve_automation.db.engine import get_db

    db = next(get_db())
    wipe_database(db)
    yield db
    wipe_database(db)


@pytest.fixture(scope="module")
def contract_client(contract_db):
    """TestClient over the wiped DB (dev-mode auth from root conftest)."""
    from fastapi.testclient import TestClient

    from reserve_automation.web import app as web_app
    from reserve_automation.web.app import app
    from reserve_automation.web.config import load_web_config
    from reserve_automation.web.services.upload_service import UploadService

    core_config, web_config = load_web_config()
    web_app.core_config = core_config
    web_app.web_config = web_config
    web_app.upload_service = UploadService(
        temp_dir=web_config.uploads.temp_dir,
        max_file_size_mb=web_config.uploads.max_file_size_mb,
        allowed_extensions=web_config.uploads.allowed_extensions,
    )

    with TestClient(app, follow_redirects=False) as client:
        yield client
