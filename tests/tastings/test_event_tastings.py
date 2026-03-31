#!/usr/bin/env python3
"""
Test Suite 1: Event-Based Tasting Tests

Tests the manual tasting wizard in event mode.
SAFE: No vault writes - all data stored in SQLite database.

CRITICAL: These tests use an in-memory SQLite database via conftest.py fixtures.
"""

import json
import pytest

# test_client and weller_bottle fixtures come from conftest.py
# which sets up an isolated test vault


def test_manual_event_tasting(test_client, weller_bottle):
    """Test adding a tasting via manual wizard in event mode."""
    print("\n🥃 Test: Manual Event Tasting")
    print("=" * 60)

    # Use fixture bottle (from isolated test vault)
    test_bottle = weller_bottle
    print(f"\n1️⃣ Using test fixture bottle: {test_bottle['name']}")

    # Step 2: Create test event
    print("\n2️⃣ Creating test event...")
    event_data = {
        "name": "Test Manual Tasting Event",
        "host_name": "TestHost",
        "date": "2025-12-27",
        "is_blind": False,
        "beverage_type": "whiskey",
        "bottle_ids": [test_bottle["id"]]  # Use opaque ID instead of vault_path
    }
    response = test_client.post("/api/v1/events", json=event_data)
    assert response.status_code == 200, f"Event creation failed: {response.status_code} - {response.text}"
    event = response.json()
    event_id = event["event_id"]
    print(f"   ✓ Event created: {event_id[:8]}...")

    # Step 3: Join event as participant
    print("\n3️⃣ Joining event as 'TestUser'...")
    response = test_client.post(
        f"/api/v1/events/{event_id}/join",
        json={"participant_name": "TestUser"}
    )
    assert response.status_code == 200, f"Join failed: {response.status_code}"
    join_data = response.json()
    participant_id = join_data["participant_id"]
    cookies = response.cookies
    print(f"   ✓ Joined (participant ID: {participant_id[:8]}...)")

    # Step 4: Save tasting directly (sessionless - single POST with all data)
    print("\n4️⃣ Saving tasting (sessionless API)...")
    tasting_data = {
        "whiskey_nose": 2.5,
        "whiskey_palate": 2.8,
        "whiskey_finish": 2.3,
        "whiskey_overall": 0.9,
        "nose_notes": ["caramel", "vanilla", "oak"],
        "palate_notes": ["spice", "leather", "cherry"],
        "finish_notes": ["long", "warm", "smooth"],
        "overall_notes": "Excellent bourbon with great complexity."
    }

    save_request = {
        "mode": "event",
        "beverage_type": "whiskey",
        "taster_name": "TestUser",
        "tasting_date": "2025-12-27",
        "selected_bottle_id": test_bottle["id"],
        "event_id": event_id,
        "participant_id": participant_id,
        "tasting_data": tasting_data
    }

    response = test_client.post("/api/v1/manual-tasting/save", json=save_request, cookies=cookies)
    assert response.status_code == 200, f"Save failed: {response.status_code} - {response.text}"
    print(f"   ✓ Tasting saved to event store")

    # Step 5: Verify tasting exists in event
    print("\n5️⃣ Verifying tasting in event...")
    response = test_client.get(f"/api/v1/events/{event_id}")
    assert response.status_code == 200, f"Event fetch failed: {response.status_code}"
    event_data = response.json()

    participant = event_data["participants"][participant_id]
    assert len(participant["tastings"]) == 1, f"Expected 1 tasting, found {len(participant['tastings'])}"

    tasting = participant["tastings"][0]
    assert "whiskey_nose" in tasting["tasting_data"], "Tasting data missing nose score"
    assert tasting["tasting_data"]["whiskey_nose"] == 2.5, "Nose score mismatch"
    print(f"   ✓ Tasting verified in event store")
    print(f"   ✓ Score: {tasting['tasting_data']['whiskey_nose'] + tasting['tasting_data']['whiskey_palate'] + tasting['tasting_data']['whiskey_finish'] + tasting['tasting_data']['whiskey_overall']:.1f}/10")

    # Cleanup
    print("\n6️⃣ Cleaning up test event...")
    response = test_client.delete(f"/api/v1/events/{event_id}")
    assert response.status_code == 200, f"Cleanup failed: {response.status_code}"
    print("   ✓ Test event deleted")

    print("\n" + "=" * 60)
    print("✅ TEST PASSED: Manual Event Tasting")
    print("=" * 60)


def test_edit_event_tasting(test_client, weller_bottle):
    """Test editing an existing tasting in an event."""
    print("\n✏️ Test: Edit Event Tasting")
    print("=" * 60)

    # Setup: Create event, join, add initial tasting
    print("\n📝 Setup: Creating event with initial tasting...")

    # Use fixture bottle (from isolated test vault)
    test_bottle = weller_bottle

    # Create event
    event_data = {
        "name": "Test Edit Tasting Event",
        "host_name": "TestHost",
        "date": "2025-12-27",
        "is_blind": False,
        "beverage_type": "whiskey",
        "bottle_ids": [test_bottle["id"]]
    }
    response = test_client.post("/api/v1/events", json=event_data)
    assert response.status_code == 200, f"Event creation failed: {response.status_code} - {response.text}"
    event = response.json()
    event_id = event["event_id"]

    # Join event
    response = test_client.post(
        f"/api/v1/events/{event_id}/join",
        json={"participant_name": "TestEditor"}
    )
    participant_id = response.json()["participant_id"]
    cookies = response.cookies

    # Add initial tasting (sessionless - single POST)
    print("   ✓ Adding initial tasting (score: 6.0/10)...")
    response = test_client.post("/api/v1/manual-tasting/save", json={
        "mode": "event",
        "beverage_type": "whiskey",
        "taster_name": "TestEditor",
        "tasting_date": "2025-12-27",
        "selected_bottle_id": test_bottle["id"],
        "event_id": event_id,
        "participant_id": participant_id,
        "tasting_data": {
            "whiskey_nose": 1.5,
            "whiskey_palate": 2.0,
            "whiskey_finish": 1.5,
            "whiskey_overall": 1.0,
            "overall_notes": "Initial tasting"
        }
    }, cookies=cookies)
    assert response.status_code == 200, f"Initial save failed: {response.text}"
    print("   ✓ Initial tasting saved")

    # Test: Edit the tasting (same bottle path = update, not add)
    print("\n✏️ Editing tasting with new scores (9.0/10)...")
    response = test_client.post("/api/v1/manual-tasting/save", json={
        "mode": "event",
        "beverage_type": "whiskey",
        "taster_name": "TestEditor",
        "tasting_date": "2025-12-27",
        "selected_bottle_id": test_bottle["id"],
        "event_id": event_id,
        "participant_id": participant_id,
        "tasting_data": {
            "whiskey_nose": 3.0,
            "whiskey_palate": 3.0,
            "whiskey_finish": 2.0,
            "whiskey_overall": 1.0,
            "overall_notes": "Edited tasting - much better!"
        }
    }, cookies=cookies)
    assert response.status_code == 200, f"Edit save failed: {response.text}"
    print("   ✓ Edited tasting saved")

    # Verify: Only 1 tasting exists with updated scores
    print("\n🔍 Verifying edit replaced original...")
    response = test_client.get(f"/api/v1/events/{event_id}")
    event_data = response.json()
    participant = event_data["participants"][participant_id]

    assert len(participant["tastings"]) == 1, f"Expected 1 tasting, found {len(participant['tastings'])} (edit should replace)"

    tasting = participant["tastings"][0]
    score = (tasting["tasting_data"]["whiskey_nose"] +
             tasting["tasting_data"]["whiskey_palate"] +
             tasting["tasting_data"]["whiskey_finish"] +
             tasting["tasting_data"]["whiskey_overall"])

    assert score == 9.0, f"Expected score 9.0, got {score}"
    assert "much better" in tasting["tasting_data"]["overall_notes"], "Notes not updated"
    print(f"   ✓ Only 1 tasting exists")
    print(f"   ✓ Score updated: 9.0/10")
    print(f"   ✓ Notes updated: '{tasting['tasting_data']['overall_notes']}'")

    # Cleanup
    test_client.delete(f"/api/v1/events/{event_id}")

    print("\n" + "=" * 60)
    print("✅ TEST PASSED: Edit Event Tasting")
    print("=" * 60)
