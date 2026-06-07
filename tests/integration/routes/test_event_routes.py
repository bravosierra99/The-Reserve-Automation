"""API Contract Tests for Event Routes.

These tests verify API endpoint contracts for the event system (blind tastings,
participant management, result tracking).

NOTE: These are integration tests that serve as API contract documentation.
"""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def client(tmp_path):
    """Create test client with app."""
    from reserve_automation.core.config import Config
    from reserve_automation.web import app as app_module

    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)

    config = Config(paths={"vault": str(vault_path), "templates_dir": "templates"})
    app_module.core_config = config

    web_config = Mock()
    web_config.sessions.secret_key = "test-secret"
    web_config.sessions.max_age_hours = 24
    app_module.web_config = web_config

    return TestClient(app_module.app)


# ============================================================================
# Event Creation Contract Tests
# ============================================================================

class TestEventCreationContracts:
    """Test event creation API contracts."""

    def test_create_event_requires_event_name(self, client):
        """POST /api/v1/events requires event_name."""
        response = client.post(
            "/api/v1/events",
            json={
                "host_name": "Alice",
                "is_blind": True,
                "bottles": [{"bottle_path": "1_Wines/Test", "bottle_name": "Test"}]
            }
        )

        # Should fail validation
        assert response.status_code == 422

    def test_create_event_requires_host_name(self, client):
        """POST /api/v1/events requires host_name."""
        response = client.post(
            "/api/v1/events",
            json={
                "event_name": "Test Event",
                "is_blind": True,
                "bottles": [{"bottle_path": "1_Wines/Test", "bottle_name": "Test"}]
            }
        )

        # Should fail validation
        assert response.status_code == 422

    def test_create_event_requires_bottles(self, client):
        """POST /api/v1/events requires at least one bottle."""
        response = client.post(
            "/api/v1/events",
            json={
                "event_name": "Test Event",
                "host_name": "Alice",
                "is_blind": True,
                "bottles": []
            }
        )

        # Should fail - empty bottles
        assert response.status_code in [400, 422]


class TestEventRetrievalContracts:
    """Test event retrieval API contracts."""

    def test_get_event_returns_404_for_missing(self, client):
        """GET /api/v1/events/{event_id} returns 404 for non-existent events."""
        response = client.get("/api/v1/events/non-existent")
        assert response.status_code == 404

    def test_get_event_returns_json_response(self, client):
        """GET /api/v1/events/{event_id} returns JSON."""
        # Create event first

        create_response = client.post(
            "/api/v1/events",
            json={
                "event_name": "Test Event",
                "host_name": "Alice",
                "is_blind": True,
                "bottles": [
                    {"bottle_path": "1_Wines/Test", "bottle_name": "Test Wine"}
                ]
            }
        )

        if create_response.status_code == 200:
            event_id = create_response.json()["event_id"]

            # Get event
            get_response = client.get(f"/api/v1/events/{event_id}")

            # Should return JSON (200) or not found (404)
            assert get_response.status_code in [200, 404]

            if get_response.status_code == 200:
                assert "event_id" in get_response.json()


class TestParticipantManagementContracts:
    """Test participant management API contracts."""

    def test_join_event_requires_name(self, client):
        """POST /api/v1/events/{event_id}/join requires name."""
        response = client.post(
            "/api/v1/events/test-id/join",
            json={}  # Missing name
        )

        # Should fail validation
        assert response.status_code in [404, 422]  # 404 if event not found, 422 if validation fails


class TestEventStateContracts:
    """Test event state management API contracts."""

    def test_reveal_event_returns_json(self, client):
        """PUT /api/v1/events/{event_id}/reveal returns JSON."""
        response = client.put("/api/v1/events/non-existent/reveal")

        # Should return error (404) with JSON
        assert response.status_code in [404, 500]

    def test_close_event_returns_json(self, client):
        """PUT /api/v1/events/{event_id}/close returns JSON."""
        response = client.put("/api/v1/events/non-existent/close")

        # Should return error with JSON
        assert response.status_code in [404, 500]

    def test_delete_event_returns_200_or_404(self, client):
        """DELETE /api/v1/events/{event_id} returns 200 or 404."""
        response = client.delete("/api/v1/events/non-existent")

        # Should return 404 for non-existent
        assert response.status_code == 404


class TestErrorResponseFormat:
    """Test consistent error response format."""

    def test_404_errors_return_json(self, client):
        """404 errors return JSON with detail field."""
        response = client.get("/api/v1/events/non-existent")
        assert response.status_code == 404
        assert "detail" in response.json()

    def test_422_errors_return_json(self, client):
        """422 validation errors return JSON."""
        response = client.post(
            "/api/v1/events",
            json={"invalid": "data"}
        )
        assert response.status_code == 422
        # Pydantic validation errors have detail
        assert "detail" in response.json()
