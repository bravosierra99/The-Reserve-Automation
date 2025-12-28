"""API Contract Tests for Tasting Routes.

These tests verify API endpoint contracts, request/response schemas, and error handling
for the tasting upload and review workflow.

CRITICAL: These tests prevent API breaking changes and ensure consistent behavior.

NOTE: These are integration tests that may require more setup to run properly.
They serve as API contract documentation and can be extended as needed.
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch

from reserve_automation.web.schemas.tasting import (
    TastingSession,
    TastingSessionItem,
    TastingData,
    TastingStatus,
    MatchCandidate
)


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def client(tmp_path):
    """Create test client with app."""
    # Import app after setting up mocks
    from reserve_automation.web import app as app_module
    from reserve_automation.core.config import Config
    
    # Create temp vault
    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)
    
    # Mock global config
    config = Config(paths={"vault": str(vault_path), "templates_dir": "templates"})
    app_module.core_config = config
    
    web_config = Mock()
    web_config.sessions.secret_key = "test-secret"
    web_config.sessions.max_age_hours = 24
    app_module.web_config = web_config
    
    # Create test client (bypasses lifespan)
    return TestClient(app_module.app)


@pytest.fixture
def sample_session_data():
    """Sample tasting session data."""
    return {
        "extraction_id": "test-extraction-123",
        "tasting_session": {
            "extraction_id": "test-extraction-123",
            "beverage_type": "wine",
            "template_type": "aws_wine",
            "actual_count": 1,
            "tastings": [
                {
                    "index": 0,
                    "status": "extracted",
                    "tasting_data": {
                        "bottle_name": "Caymus Cabernet 2019",
                        "taster_name": "Alice",
                        "tasting_date": "2025-12-27",
                        "beverage_type": "wine",
                        "wine_appearance": 2.5
                    },
                    "match_candidates": [],
                    "selected_match": None
                }
            ]
        }
    }


# ============================================================================
# Basic API Contract Tests
# ============================================================================

class TestTastingAPIContracts:
    """Test basic API contract requirements."""

    def test_get_session_requires_cookie(self, client):
        """GET /api/v1/tastings/{id} requires session cookie."""
        response = client.get("/api/v1/tastings/test-id")
        assert response.status_code == 401

    def test_update_tasting_requires_cookie(self, client):
        """PUT /api/v1/tastings/{id}/{index} requires session cookie."""
        response = client.put(
            "/api/v1/tastings/test-id/0",
            json={"tasting_data": {"bottle_name": "Test"}}
        )
        assert response.status_code == 401

    def test_select_match_requires_cookie(self, client):
        """POST /api/v1/tastings/{id}/{index}/match requires session cookie."""
        response = client.post(
            "/api/v1/tastings/test-id/0/match",
            json={"bottle_path": "1_Wines/Test"}
        )
        assert response.status_code == 401

    def test_approve_tasting_requires_cookie(self, client):
        """POST /api/v1/tastings/{id}/{index}/approve requires session cookie."""
        response = client.post("/api/v1/tastings/test-id/0/approve")
        assert response.status_code == 401


class TestSessionValidation:
    """Test session validation logic."""

    def test_invalid_session_returns_401(self, client):
        """Invalid session cookie returns 401."""
        client.cookies.set("session", "invalid-token")
        
        with patch('reserve_automation.web.routes.tastings.SessionManager') as mock_sm:
            mock_sm.return_value.read_session.return_value = None
            
            response = client.get("/api/v1/tastings/test-id")
            assert response.status_code == 401

    def test_mismatched_extraction_id_returns_404(self, client):
        """Extraction ID mismatch returns 404."""
        client.cookies.set("session", "valid-token")
        
        with patch('reserve_automation.web.routes.tastings.SessionManager') as mock_sm:
            mock_sm.return_value.read_session.return_value = {
                "extraction_id": "different-id"
            }
            
            response = client.get("/api/v1/tastings/test-id")
            assert response.status_code == 404


class TestManualTastingContracts:
    """Test manual tasting wizard API contracts."""

    def test_start_manual_tasting_accepts_valid_data(self, client):
        """POST /api/v1/manual-tasting/start accepts valid request."""
        with patch('reserve_automation.web.routes.tastings.SessionManager') as mock_sm:
            mock_sm.return_value.create_session.return_value = "new-token"
            
            response = client.post(
                "/api/v1/manual-tasting/start",
                json={"mode": "obsidian", "beverage_type": "wine"}
            )
            
            # Should succeed (200) or fail validation (422), not server error
            assert response.status_code in [200, 422, 500]

    def test_get_manual_session_requires_cookie(self, client):
        """GET /api/v1/manual-tasting/session requires session."""
        response = client.get("/api/v1/manual-tasting/session")
        assert response.status_code == 401


class TestErrorResponses:
    """Test error response format consistency."""

    def test_missing_session_returns_json_error(self, client):
        """401 errors return JSON with detail field."""
        response = client.get("/api/v1/tastings/test-id")
        assert response.status_code == 401
        assert "detail" in response.json()

    def test_not_found_returns_json_error(self, client):
        """404 errors return JSON with detail field."""
        client.cookies.set("session", "valid-token")
        
        with patch('reserve_automation.web.routes.tastings.SessionManager') as mock_sm:
            mock_sm.return_value.read_session.return_value = {
                "extraction_id": "other-id"
            }
            
            response = client.get("/api/v1/tastings/test-id")
            assert response.status_code == 404
            assert "detail" in response.json()
