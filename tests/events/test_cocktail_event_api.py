"""Tests for cocktail event API endpoints.

CRITICAL: These tests use an isolated test vault at /tmp/test-vault-events-*.
"""

import json
from urllib.parse import quote

import pytest


class TestCreateCocktailEvent:
    """Test POST /api/v1/events/cocktail."""

    def test_create_flight_event(self, test_client):
        """Create a flight mode cocktail event (no cocktails required upfront)."""
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Friday Night Cocktails",
            "host_name": "Ben",
            "event_mode": "flight",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Friday Night Cocktails"
        assert data["event_type"] == "cocktail"
        assert data["event_mode"] == "flight"
        assert data["is_blind"] is False
        assert data["status"] == "open"
        assert data["host_name"] == "Ben"
        assert data["cocktails"] == []
        assert data["bottles"] == []

    def test_create_blind_event_with_cocktails(self, test_client):
        """Create a blind mode cocktail event with fixed cocktails."""
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Blind Cocktail Night",
            "host_name": "Alice",
            "event_mode": "blind",
            "cocktails": [
                {"cocktail_name": "Moscow Mule", "bartender": "Alice"},
                {"cocktail_name": "Old Fashioned", "bartender": "Alice"},
            ],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "cocktail"
        assert data["event_mode"] == "blind"
        assert data["is_blind"] is True
        assert len(data["cocktails"]) == 2
        assert data["cocktails"][0]["cocktail_name"] == "Moscow Mule"
        # Blind numbers auto-assigned
        assert data["cocktails"][0]["blind_number"] == 1
        assert data["cocktails"][1]["blind_number"] == 2

    def test_create_blind_event_requires_cocktails(self, test_client):
        """Blind mode without cocktails should fail."""
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Empty Blind",
            "host_name": "Test",
            "event_mode": "blind",
            "cocktails": [],
        })
        assert response.status_code == 400

    def test_create_flight_with_initial_cocktails(self, test_client):
        """Flight events can optionally start with cocktails."""
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Pre-loaded Flight",
            "host_name": "Ben",
            "event_mode": "flight",
            "cocktails": [
                {"cocktail_name": "Margarita"},
            ],
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["cocktails"]) == 1


class TestAddEventCocktail:
    """Test POST /api/v1/events/{event_id}/cocktails."""

    def test_add_cocktail_to_flight(self, test_client):
        """Add cocktails dynamically to a flight event."""
        # Create flight event
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Add Cocktails Test",
            "host_name": "Ben",
            "event_mode": "flight",
        })
        event_id = response.json()["event_id"]

        # Add a cocktail
        response = test_client.post(f"/api/v1/events/{event_id}/cocktails", json={
            "cocktail_name": "Daiquiri",
            "bartender": "Ben",
        })
        assert response.status_code == 200
        assert response.json()["cocktail"]["cocktail_name"] == "Daiquiri"

        # Add another
        response = test_client.post(f"/api/v1/events/{event_id}/cocktails", json={
            "cocktail_name": "Whiskey Sour",
        })
        assert response.status_code == 200

        # Verify event has both cocktails
        response = test_client.get(f"/api/v1/events/{event_id}")
        event = response.json()
        assert len(event["cocktails"]) == 2

    def test_cannot_add_to_blind_event(self, test_client):
        """Cannot add cocktails to blind mode events."""
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Blind No Add",
            "host_name": "Test",
            "event_mode": "blind",
            "cocktails": [{"cocktail_name": "Negroni"}],
        })
        event_id = response.json()["event_id"]

        response = test_client.post(f"/api/v1/events/{event_id}/cocktails", json={
            "cocktail_name": "Extra Cocktail",
        })
        assert response.status_code == 400

    def test_cannot_add_to_closed_event(self, test_client):
        """Cannot add cocktails to closed events."""
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Closed Flight",
            "host_name": "Test",
            "event_mode": "flight",
        })
        event_id = response.json()["event_id"]

        # Close the event
        test_client.put(f"/api/v1/events/{event_id}/close")

        response = test_client.post(f"/api/v1/events/{event_id}/cocktails", json={
            "cocktail_name": "Late Addition",
        })
        assert response.status_code == 400

    def test_cannot_add_to_bottle_event(self, test_client, weller_bottle, blantons_bottle):
        """Cannot add cocktails to a regular bottle event."""
        response = test_client.post("/api/v1/events", json={
            "name": "Bottle Event",
            "beverage_type": "whiskey",
            "host_name": "Test",
            "bottle_ids": [weller_bottle["id"], blantons_bottle["id"]],
        })
        event_id = response.json()["event_id"]

        response = test_client.post(f"/api/v1/events/{event_id}/cocktails", json={
            "cocktail_name": "Negroni",
        })
        assert response.status_code == 400


class TestCocktailEventRatings:
    """Test POST /api/v1/events/{event_id}/cocktail-ratings."""

    def test_submit_rating(self, test_client):
        """Submit a cocktail rating in a flight event."""
        # Create flight event with a cocktail
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Rating Test Event",
            "host_name": "Ben",
            "event_mode": "flight",
            "cocktails": [{"cocktail_name": "Mojito"}],
        })
        event_id = response.json()["event_id"]

        # Join the event
        response = test_client.post(f"/api/v1/events/{event_id}/join", json={
            "participant_name": "TestRater",
        })
        assert response.status_code == 200
        participant_id = response.json()["participant_id"]

        # Build the session cookie
        sessions = {event_id: {"participant_id": participant_id, "participant_name": "TestRater"}}
        cookie_value = quote(json.dumps(sessions))

        # Submit rating
        response = test_client.post(
            f"/api/v1/events/{event_id}/cocktail-ratings",
            json={
                "cocktail_name": "Mojito",
                "score": 8.5,
                "notes": "Very refreshing",
            },
            cookies={"participant_sessions": cookie_value},
        )
        assert response.status_code == 200
        assert response.json()["rating"]["score"] == 8.5

        # Verify rating is stored on participant
        response = test_client.get(f"/api/v1/events/{event_id}")
        event = response.json()
        participant = event["participants"][participant_id]
        assert len(participant["cocktail_ratings"]) == 1
        assert participant["cocktail_ratings"][0]["score"] == 8.5

    def test_update_existing_rating(self, test_client):
        """Re-submitting a rating for the same cocktail updates it."""
        # Create event
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Update Rating Test",
            "host_name": "Ben",
            "event_mode": "flight",
            "cocktails": [{"cocktail_name": "Mai Tai"}],
        })
        event_id = response.json()["event_id"]

        # Join
        response = test_client.post(f"/api/v1/events/{event_id}/join", json={
            "participant_name": "Updater",
        })
        pid = response.json()["participant_id"]
        sessions = {event_id: {"participant_id": pid, "participant_name": "Updater"}}
        cookie = quote(json.dumps(sessions))

        # First rating
        test_client.post(
            f"/api/v1/events/{event_id}/cocktail-ratings",
            json={"cocktail_name": "Mai Tai", "score": 6.0},
            cookies={"participant_sessions": cookie},
        )

        # Update rating
        test_client.post(
            f"/api/v1/events/{event_id}/cocktail-ratings",
            json={"cocktail_name": "Mai Tai", "score": 9.0, "notes": "Changed my mind"},
            cookies={"participant_sessions": cookie},
        )

        # Verify only one rating, with updated score
        response = test_client.get(f"/api/v1/events/{event_id}")
        participant = response.json()["participants"][pid]
        assert len(participant["cocktail_ratings"]) == 1
        assert participant["cocktail_ratings"][0]["score"] == 9.0
        assert participant["cocktail_ratings"][0]["notes"] == "Changed my mind"

    def test_rating_requires_joining(self, test_client):
        """Cannot rate without joining the event."""
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "No Join Rating",
            "host_name": "Ben",
            "event_mode": "flight",
            "cocktails": [{"cocktail_name": "Gimlet"}],
        })
        event_id = response.json()["event_id"]

        response = test_client.post(
            f"/api/v1/events/{event_id}/cocktail-ratings",
            json={"cocktail_name": "Gimlet", "score": 7.0},
        )
        assert response.status_code == 403

    def test_rating_nonexistent_cocktail(self, test_client):
        """Cannot rate a cocktail not in the event."""
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Wrong Cocktail",
            "host_name": "Ben",
            "event_mode": "flight",
            "cocktails": [{"cocktail_name": "Cosmopolitan"}],
        })
        event_id = response.json()["event_id"]

        # Join
        response = test_client.post(f"/api/v1/events/{event_id}/join", json={
            "participant_name": "Tester",
        })
        pid = response.json()["participant_id"]
        sessions = {event_id: {"participant_id": pid, "participant_name": "Tester"}}
        cookie = quote(json.dumps(sessions))

        response = test_client.post(
            f"/api/v1/events/{event_id}/cocktail-ratings",
            json={"cocktail_name": "Not In Event", "score": 5.0},
            cookies={"participant_sessions": cookie},
        )
        assert response.status_code == 404


class TestCocktailEventLifecycle:
    """Test full lifecycle of cocktail events."""

    def test_flight_lifecycle(self, test_client):
        """Full flight event: create -> add cocktails -> join -> rate -> close."""
        # Create
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Full Flight Test",
            "host_name": "Ben",
            "event_mode": "flight",
        })
        event_id = response.json()["event_id"]

        # Add cocktails
        test_client.post(f"/api/v1/events/{event_id}/cocktails", json={
            "cocktail_name": "Negroni",
            "bartender": "Ben",
        })
        test_client.post(f"/api/v1/events/{event_id}/cocktails", json={
            "cocktail_name": "Manhattan",
            "bartender": "Alice",
        })

        # Join
        response = test_client.post(f"/api/v1/events/{event_id}/join", json={
            "participant_name": "Charlie",
        })
        pid = response.json()["participant_id"]
        sessions = {event_id: {"participant_id": pid, "participant_name": "Charlie"}}
        cookie = quote(json.dumps(sessions))

        # Rate cocktails
        test_client.post(
            f"/api/v1/events/{event_id}/cocktail-ratings",
            json={"cocktail_name": "Negroni", "score": 8.0, "notes": "Bitter and perfect"},
            cookies={"participant_sessions": cookie},
        )
        test_client.post(
            f"/api/v1/events/{event_id}/cocktail-ratings",
            json={"cocktail_name": "Manhattan", "score": 9.0},
            cookies={"participant_sessions": cookie},
        )

        # Close
        response = test_client.put(f"/api/v1/events/{event_id}/close")
        assert response.status_code == 200

        # Verify final state
        response = test_client.get(f"/api/v1/events/{event_id}")
        event = response.json()
        assert event["status"] == "closed"
        assert len(event["cocktails"]) == 2
        assert len(event["participants"]) == 1
        participant = event["participants"][pid]
        assert len(participant["cocktail_ratings"]) == 2

    def test_blind_lifecycle(self, test_client):
        """Full blind cocktail event: create -> join -> rate -> reveal -> close."""
        # Create with fixed cocktails
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Blind Cocktail Test",
            "host_name": "Ben",
            "event_mode": "blind",
            "cocktails": [
                {"cocktail_name": "Cocktail A", "bartender": "Ben"},
                {"cocktail_name": "Cocktail B", "bartender": "Ben"},
            ],
        })
        event_id = response.json()["event_id"]

        # Join
        response = test_client.post(f"/api/v1/events/{event_id}/join", json={
            "participant_name": "Taster",
        })
        pid = response.json()["participant_id"]
        sessions = {event_id: {"participant_id": pid, "participant_name": "Taster"}}
        cookie = quote(json.dumps(sessions))

        # Rate
        test_client.post(
            f"/api/v1/events/{event_id}/cocktail-ratings",
            json={"cocktail_name": "Cocktail A", "score": 7.0},
            cookies={"participant_sessions": cookie},
        )

        # Reveal
        response = test_client.put(f"/api/v1/events/{event_id}/reveal")
        assert response.status_code == 200
        assert response.json()["event"]["status"] == "revealed"

        # Close
        response = test_client.put(f"/api/v1/events/{event_id}/close")
        assert response.status_code == 200

    def test_cocktail_event_appears_in_list(self, test_client):
        """Cocktail events show up in the general events list."""
        response = test_client.post("/api/v1/events/cocktail", json={
            "name": "Listed Cocktail Event",
            "host_name": "Ben",
            "event_mode": "flight",
        })
        event_id = response.json()["event_id"]

        response = test_client.get("/api/v1/events")
        events = response.json()
        cocktail_events = [e for e in events if e.get("event_type") == "cocktail"]
        assert any(e["event_id"] == event_id for e in cocktail_events)


class TestBackwardCompatibility:
    """Verify existing bottle events still work with new schema fields."""

    def test_bottle_event_has_default_fields(self, test_client, weller_bottle, blantons_bottle):
        """Regular bottle events get default event_type and event_mode."""
        response = test_client.post("/api/v1/events", json={
            "name": "Regular Bottle Event",
            "beverage_type": "whiskey",
            "host_name": "Ben",
            "bottle_ids": [weller_bottle["id"], blantons_bottle["id"]],
        })
        assert response.status_code == 200
        data = response.json()
        assert data["event_type"] == "bottle"
        assert data["event_mode"] == "standard"
        assert data["cocktails"] == []

    def test_bottle_event_delete_still_works(self, test_client, weller_bottle, blantons_bottle):
        """Deleting bottle events still works."""
        response = test_client.post("/api/v1/events", json={
            "name": "Delete Test",
            "beverage_type": "whiskey",
            "host_name": "Ben",
            "bottle_ids": [weller_bottle["id"]],
        })
        event_id = response.json()["event_id"]

        response = test_client.delete(f"/api/v1/events/{event_id}")
        assert response.status_code == 200
        assert response.json()["status"] == "deleted"
