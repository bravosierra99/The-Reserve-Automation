"""
Automated test suite for the Event API.

Tests cover:
- Event CRUD operations (create, list, get, delete)
- Participant management (join, cookie handling)
- Event status transitions (reveal, close)
- Tasting submission
- Response format validation (bottle_path, blind numbers)

CRITICAL: All tests use an isolated test vault in /tmp, never the real vault.
"""

import json
from urllib.parse import unquote

import pytest


class TestEventCRUD:
    """Test basic event CRUD operations."""

    def test_create_event_whiskey(self, test_client, weller_bottle, blantons_bottle):
        """Test creating a whiskey tasting event."""
        response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Bourbon Night",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"], blantons_bottle["id"]],
                "blind_numbers": None
            }
        )
        assert response.status_code == 200
        event = response.json()

        assert event["name"] == "Bourbon Night"
        assert event["beverage_type"] == "whiskey"
        assert event["is_blind"] is False
        assert event["status"] == "open"
        assert event["host_name"] == "Test Host"
        assert len(event["bottles"]) == 2
        assert "event_id" in event

    def test_create_event_wine_blind(self, test_client, caymus_bottle, opus_bottle):
        """Test creating a blind wine tasting event."""
        response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Napa Cab Blind Tasting",
                "beverage_type": "wine",
                "is_blind": True,
                "host_name": "Wine Host",
                "bottle_ids": [caymus_bottle["id"], opus_bottle["id"]],
                "blind_numbers": [1, 2]
            }
        )
        assert response.status_code == 200
        event = response.json()

        assert event["is_blind"] is True
        assert len(event["bottles"]) == 2
        # Verify blind numbers are assigned
        blind_nums = {b["blind_number"] for b in event["bottles"]}
        assert blind_nums == {1, 2}

    def test_create_event_missing_blind_numbers(self, test_client, weller_bottle):
        """Test that blind events require blind numbers."""
        response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Invalid Blind Event",
                "beverage_type": "whiskey",
                "is_blind": True,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None  # Missing!
            }
        )
        assert response.status_code == 400
        assert "blind numbers required" in response.json()["detail"].lower()

    def test_create_event_invalid_bottle_id(self, test_client):
        """Test that invalid bottle IDs are rejected."""
        response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Invalid Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": ["99999"],
                "blind_numbers": None
            }
        )
        assert response.status_code == 404
        assert "bottle not found" in response.json()["detail"].lower()

    def test_list_events(self, test_client, weller_bottle):
        """Test listing all events."""
        # Create an event first
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "List Test Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        assert create_response.status_code == 200

        # List events
        response = test_client.get("/api/v1/events")
        assert response.status_code == 200
        events = response.json()
        assert isinstance(events, list)
        assert len(events) >= 1

    def test_get_event(self, test_client, weller_bottle):
        """Test getting a specific event."""
        # Create event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Get Test Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        event_id = create_response.json()["event_id"]

        # Get event
        response = test_client.get(f"/api/v1/events/{event_id}")
        assert response.status_code == 200
        event = response.json()
        assert event["event_id"] == event_id
        assert event["name"] == "Get Test Event"

    def test_get_event_not_found(self, test_client):
        """Test getting a non-existent event."""
        response = test_client.get("/api/v1/events/nonexistent-id")
        assert response.status_code == 404

    def test_delete_event(self, test_client, weller_bottle):
        """Test deleting an event."""
        # Create event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Delete Test Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        event_id = create_response.json()["event_id"]

        # Delete event
        response = test_client.delete(f"/api/v1/events/{event_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"

        # Verify it's gone
        get_response = test_client.get(f"/api/v1/events/{event_id}")
        assert get_response.status_code == 404


class TestEventParticipation:
    """Test participant joining and session management."""

    def test_join_event(self, test_client, weller_bottle):
        """Test joining an event as a participant."""
        # Create event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Join Test Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        event_id = create_response.json()["event_id"]

        # Join event
        response = test_client.post(
            f"/api/v1/events/{event_id}/join",
            json={"participant_name": "Alice"}
        )
        assert response.status_code == 200
        join_data = response.json()
        assert join_data["participant_name"] == "Alice"
        assert "participant_id" in join_data
        assert join_data["event_id"] == event_id

    def test_join_event_sets_cookie(self, test_client, weller_bottle):
        """Test that joining sets the participant session cookie."""
        # Create event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Cookie Test Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        event_id = create_response.json()["event_id"]

        # Join event
        response = test_client.post(
            f"/api/v1/events/{event_id}/join",
            json={"participant_name": "Bob"}
        )
        assert response.status_code == 200

        # Check cookie was set
        assert "participant_sessions" in response.cookies
        cookie_value = unquote(response.cookies["participant_sessions"])
        sessions = json.loads(cookie_value)
        assert event_id in sessions
        assert sessions[event_id]["participant_name"] == "Bob"

    def test_join_closed_event_rejected(self, test_client, weller_bottle):
        """Test that joining a closed event is rejected."""
        # Create and close event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Closed Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        event_id = create_response.json()["event_id"]

        # Close event
        test_client.put(f"/api/v1/events/{event_id}/close")

        # Try to join
        response = test_client.post(
            f"/api/v1/events/{event_id}/join",
            json={"participant_name": "Late Joiner"}
        )
        assert response.status_code == 400
        assert "closed" in response.json()["detail"].lower()


class TestEventStatusTransitions:
    """Test event status state machine."""

    def test_reveal_blind_event(self, test_client, caymus_bottle):
        """Test revealing a blind event."""
        # Create blind event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Reveal Test Event",
                "beverage_type": "wine",
                "is_blind": True,
                "host_name": "Test Host",
                "bottle_ids": [caymus_bottle["id"]],
                "blind_numbers": [1]
            }
        )
        event_id = create_response.json()["event_id"]

        # Reveal
        response = test_client.put(f"/api/v1/events/{event_id}/reveal")
        assert response.status_code == 200
        assert response.json()["event"]["status"] == "revealed"

    def test_reveal_non_blind_event_rejected(self, test_client, weller_bottle):
        """Test that revealing a non-blind event is rejected."""
        # Create non-blind event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Non-Blind Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        event_id = create_response.json()["event_id"]

        # Try to reveal
        response = test_client.put(f"/api/v1/events/{event_id}/reveal")
        assert response.status_code == 400
        assert "not a blind" in response.json()["detail"].lower()

    def test_close_event(self, test_client, weller_bottle):
        """Test closing an event."""
        # Create event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Close Test Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        event_id = create_response.json()["event_id"]

        # Close
        response = test_client.put(f"/api/v1/events/{event_id}/close")
        assert response.status_code == 200
        assert response.json()["event"]["status"] == "closed"

    def test_close_already_closed_event(self, test_client, weller_bottle):
        """Test closing an already closed event is idempotent."""
        # Create and close event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Double Close Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        event_id = create_response.json()["event_id"]
        test_client.put(f"/api/v1/events/{event_id}/close")

        # Close again
        response = test_client.put(f"/api/v1/events/{event_id}/close")
        assert response.status_code == 200
        assert "already closed" in response.json()["message"].lower()

    def test_reveal_closed_event_rejected(self, test_client, caymus_bottle):
        """Test that revealing a closed event is rejected."""
        # Create blind event and close it
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Closed Blind Event",
                "beverage_type": "wine",
                "is_blind": True,
                "host_name": "Test Host",
                "bottle_ids": [caymus_bottle["id"]],
                "blind_numbers": [1]
            }
        )
        event_id = create_response.json()["event_id"]
        test_client.put(f"/api/v1/events/{event_id}/close")

        # Try to reveal
        response = test_client.put(f"/api/v1/events/{event_id}/reveal")
        assert response.status_code == 400
        assert "closed" in response.json()["detail"].lower()


class TestEventBottleDisplay:
    """Test bottle information in API responses."""

    def test_bottle_path_included_in_response(self, test_client, weller_bottle):
        """Test that bottle_path is included in event response."""
        # Create event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Bottle Path Test Event",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        assert create_response.status_code == 200
        event = create_response.json()

        # Verify bottle_path is present
        assert len(event["bottles"]) == 1
        bottle = event["bottles"][0]
        assert "bottle_path" in bottle
        assert bottle["bottle_path"] == weller_bottle["id"]

    def test_bottle_path_in_get_response(self, test_client, caymus_bottle):
        """Test that bottle_path is included when getting an event."""
        # Create event
        create_response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Get Bottle Path Test",
                "beverage_type": "wine",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [caymus_bottle["id"]],
                "blind_numbers": None
            }
        )
        event_id = create_response.json()["event_id"]

        # Get event
        response = test_client.get(f"/api/v1/events/{event_id}")
        assert response.status_code == 200
        event = response.json()

        # Verify bottle_path is present
        bottle = event["bottles"][0]
        assert "bottle_path" in bottle
        assert bottle["bottle_path"] == caymus_bottle["id"]

    def test_blind_numbers_assigned(self, test_client, weller_bottle, blantons_bottle):
        """Test that blind numbers are correctly assigned."""
        # Create blind event
        response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Blind Numbers Test",
                "beverage_type": "whiskey",
                "is_blind": True,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"], blantons_bottle["id"]],
                "blind_numbers": [7, 13]  # Custom numbers
            }
        )
        assert response.status_code == 200
        event = response.json()

        # Verify blind numbers
        blind_numbers = [b["blind_number"] for b in event["bottles"]]
        assert set(blind_numbers) == {7, 13}

    def test_bottle_name_from_folder(self, test_client, weller_bottle):
        """Test that bottle_name is extracted from folder name."""
        response = test_client.post(
            "/api/v1/events",
            json={
                "name": "Bottle Name Test",
                "beverage_type": "whiskey",
                "is_blind": False,
                "host_name": "Test Host",
                "bottle_ids": [weller_bottle["id"]],
                "blind_numbers": None
            }
        )
        assert response.status_code == 200
        event = response.json()

        # Bottle name should be folder name (last part of path)
        bottle = event["bottles"][0]
        assert bottle["bottle_name"] == "Buffalo Trace - Weller Special Reserve"
