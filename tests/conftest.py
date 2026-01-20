"""Pytest configuration and fixtures for all tests."""

import os
import pytest


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Set up test environment variables before any tests run."""
    # Set WEB_SECRET_KEY for web tests
    # Use a fixed test key (not secure, but that's fine for tests)
    os.environ.setdefault("WEB_SECRET_KEY", "test_secret_key_for_testing_only_not_secure_32_chars_min")

    # Set LM Studio URL (use localhost default if not already set)
    os.environ.setdefault("RESERVE_LM_STUDIO_URL", "http://localhost:1234/v1")

    # Set vault path for tests
    os.environ.setdefault("RESERVE_VAULT_PATH", "/tmp/test-vault")

    yield

    # Cleanup after all tests (optional)
    pass
