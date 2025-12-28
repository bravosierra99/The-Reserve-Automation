#!/usr/bin/env python3
"""
Test Suite 1: Event-Based Tasting Tests

Tests the manual tasting wizard in event mode.
SAFE: No vault writes - all data stored in-memory event store.
"""

import json
import requests
import urllib.parse

BASE_URL = "http://localhost:8000"

def test_manual_event_tasting():
    """Test adding a tasting via manual wizard in event mode."""
    print("\n🥃 Test: Manual Event Tasting")
    print("=" * 60)

    # Step 1: Search for test bottles
    print("\n1️⃣ Searching for Stagg bottles...")
    response = requests.get(f"{BASE_URL}/api/v1/management/bottles/search?q=Stagg")
    assert response.status_code == 200, f"Bottle search failed: {response.status_code}"
    bottles = response.json()["bottles"]
    assert len(bottles) >= 1, "Need at least 1 Stagg bottle for test"
    test_bottle = bottles[0]
    print(f"   ✓ Found: {test_bottle['name']}")

    # Step 2: Create test event
    print("\n2️⃣ Creating test event...")
    event_data = {
        "event_name": "Test Manual Tasting Event",
        "event_date": "2025-12-27",
        "is_blind": False,
        "beverage_type": "whiskey",
        "bottle_paths": [test_bottle["vault_path"]]
    }
    response = requests.post(f"{BASE_URL}/api/v1/events", json=event_data)
    assert response.status_code == 200, f"Event creation failed: {response.status_code}"
    event = response.json()
    event_id = event["event_id"]
    print(f"   ✓ Event created: {event_id[:8]}...")

    # Step 3: Join event as participant
    print("\n3️⃣ Joining event as 'TestUser'...")
    session = requests.Session()
    response = session.post(
        f"{BASE_URL}/api/v1/events/{event_id}/join",
        json={"participant_name": "TestUser"}
    )
    assert response.status_code == 200, f"Join failed: {response.status_code}"
    join_data = response.json()
    participant_id = join_data["participant_id"]
    print(f"   ✓ Joined (participant ID: {participant_id[:8]}...)")

    # Step 4: Start manual tasting wizard in event mode
    print("\n4️⃣ Starting manual tasting wizard (event mode)...")
    wizard_data = {
        "mode": "event",
        "event_id": event_id,
        "participant_id": participant_id,
        "taster_name": "TestUser",
        "tasting_date": "2025-12-27"
    }
    response = session.post(f"{BASE_URL}/api/v1/manual-tasting/start", json=wizard_data)
    assert response.status_code == 200, f"Wizard start failed: {response.status_code}"
    print("   ✓ Wizard started")

    # Step 5: Advance to bottle selection
    print("\n5️⃣ Selecting bottle...")
    response = session.put(
        f"{BASE_URL}/api/v1/manual-tasting/session/step",
        json={
            "step": "bottle_selection",
            "data": {"bottle_path": test_bottle["vault_path"]}
        }
    )
    assert response.status_code == 200, f"Bottle selection failed: {response.status_code}"
    print(f"   ✓ Selected: {test_bottle['name']}")

    # Step 6: Submit tasting scores
    print("\n6️⃣ Submitting tasting scores...")
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
    response = session.put(
        f"{BASE_URL}/api/v1/manual-tasting/session/step",
        json={
            "step": "tasting_form",
            "data": {"tasting_data": tasting_data}
        }
    )
    assert response.status_code == 200, f"Tasting data submission failed: {response.status_code}"
    print("   ✓ Scores submitted")

    # Step 7: Save tasting to event
    print("\n7️⃣ Saving tasting to event...")
    response = session.post(f"{BASE_URL}/api/v1/manual-tasting/save")
    assert response.status_code == 200, f"Save failed: {response.status_code}"
    print("   ✓ Tasting saved to event store")

    # Step 8: Verify tasting exists in event
    print("\n8️⃣ Verifying tasting in event...")
    response = requests.get(f"{BASE_URL}/api/v1/events/{event_id}")
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
    print("\n9️⃣ Cleaning up test event...")
    response = requests.delete(f"{BASE_URL}/api/v1/events/{event_id}")
    assert response.status_code == 200, f"Cleanup failed: {response.status_code}"
    print("   ✓ Test event deleted")

    print("\n" + "=" * 60)
    print("✅ TEST PASSED: Manual Event Tasting")
    print("=" * 60)
    return True


def test_edit_event_tasting():
    """Test editing an existing tasting in an event."""
    print("\n✏️ Test: Edit Event Tasting")
    print("=" * 60)

    # Setup: Create event, join, add initial tasting
    print("\n📝 Setup: Creating event with initial tasting...")

    # Search for bottle
    response = requests.get(f"{BASE_URL}/api/v1/management/bottles/search?q=Stagg")
    bottles = response.json()["bottles"]
    test_bottle = bottles[0]

    # Create event
    event_data = {
        "event_name": "Test Edit Tasting Event",
        "event_date": "2025-12-27",
        "is_blind": False,
        "beverage_type": "whiskey",
        "bottle_paths": [test_bottle["vault_path"]]
    }
    response = requests.post(f"{BASE_URL}/api/v1/events", json=event_data)
    event = response.json()
    event_id = event["event_id"]

    # Join event
    session = requests.Session()
    response = session.post(
        f"{BASE_URL}/api/v1/events/{event_id}/join",
        json={"participant_name": "TestEditor"}
    )
    participant_id = response.json()["participant_id"]

    # Add initial tasting
    print("   ✓ Adding initial tasting (score: 6.0/10)...")
    session.post(f"{BASE_URL}/api/v1/manual-tasting/start", json={
        "mode": "event",
        "event_id": event_id,
        "participant_id": participant_id,
        "taster_name": "TestEditor",
        "tasting_date": "2025-12-27"
    })
    session.put(f"{BASE_URL}/api/v1/manual-tasting/session/step", json={
        "step": "bottle_selection",
        "data": {"bottle_path": test_bottle["vault_path"]}
    })
    session.put(f"{BASE_URL}/api/v1/manual-tasting/session/step", json={
        "step": "tasting_form",
        "data": {"tasting_data": {
            "whiskey_nose": 1.5,
            "whiskey_palate": 2.0,
            "whiskey_finish": 1.5,
            "whiskey_overall": 1.0,
            "overall_notes": "Initial tasting"
        }}
    })
    session.post(f"{BASE_URL}/api/v1/manual-tasting/save")
    print("   ✓ Initial tasting saved")

    # Test: Edit the tasting
    print("\n✏️ Editing tasting with new scores (9.0/10)...")
    session.post(f"{BASE_URL}/api/v1/manual-tasting/start", json={
        "mode": "event",
        "event_id": event_id,
        "participant_id": participant_id,
        "taster_name": "TestEditor",
        "tasting_date": "2025-12-27"
    })
    session.put(f"{BASE_URL}/api/v1/manual-tasting/session/step", json={
        "step": "bottle_selection",
        "data": {"bottle_path": test_bottle["vault_path"]}
    })
    session.put(f"{BASE_URL}/api/v1/manual-tasting/session/step", json={
        "step": "tasting_form",
        "data": {"tasting_data": {
            "whiskey_nose": 3.0,
            "whiskey_palate": 3.0,
            "whiskey_finish": 2.0,
            "whiskey_overall": 1.0,
            "overall_notes": "Edited tasting - much better!"
        }}
    })
    session.post(f"{BASE_URL}/api/v1/manual-tasting/save")
    print("   ✓ Edited tasting saved")

    # Verify: Only 1 tasting exists with updated scores
    print("\n🔍 Verifying edit replaced original...")
    response = requests.get(f"{BASE_URL}/api/v1/events/{event_id}")
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
    requests.delete(f"{BASE_URL}/api/v1/events/{event_id}")

    print("\n" + "=" * 60)
    print("✅ TEST PASSED: Edit Event Tasting")
    print("=" * 60)
    return True


if __name__ == "__main__":
    try:
        print("\n" + "=" * 60)
        print("TEST SUITE 1: EVENT-BASED TASTINGS (SAFE)")
        print("=" * 60)
        print("These tests use in-memory event store - NO VAULT WRITES")
        print("=" * 60)

        # Run tests
        test_manual_event_tasting()
        print("\n")
        test_edit_event_tasting()

        print("\n" + "=" * 60)
        print("🎉 ALL SUITE 1 TESTS PASSED!")
        print("=" * 60)
        print("\n✓ Manual event tastings work correctly")
        print("✓ Editing event tastings works (replaces original)")
        print("✓ No files written to vault")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
