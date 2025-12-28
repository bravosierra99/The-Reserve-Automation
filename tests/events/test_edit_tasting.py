#!/usr/bin/env python3
"""Test editing an existing tasting in an event."""
import requests
import json
import urllib.parse

BASE_URL = "http://localhost:8000"

print("✏️ Testing Tasting Edit Functionality")
print("=" * 60)

# Create a simple event
print("\n📝 Creating test event...")
response = requests.get(f"{BASE_URL}/api/v1/management/bottles/search?q=Stagg")
bottles = response.json()["bottles"][:2]

event_data = {
    "name": "Test Edit Tasting Event",
    "beverage_type": "whiskey",
    "is_blind": False,
    "host_name": "Test Host",
    "bottle_paths": [b["vault_path"] for b in bottles],
    "blind_numbers": None
}

response = requests.post(f"{BASE_URL}/api/v1/events", json=event_data)
event = response.json()
event_id = event["event_id"]
print(f"✓ Event created: {event_id[:8]}...")

# Join event
print("\n👤 Joining event as 'Taylor'...")
session = requests.Session()
response = session.post(
    f"{BASE_URL}/api/v1/events/{event_id}/join",
    json={"participant_name": "Taylor"}
)
join_data = response.json()
participant_id = join_data['participant_id']
print(f"✓ Joined (participant ID: {participant_id[:8]}...)")

# Add initial tasting
print("\n📝 Adding initial tasting...")
bottle_path = event["bottles"][0]["bottle_path"]

response = session.post(
    f"{BASE_URL}/api/v1/manual-tasting/start",
    json={"mode": "event", "beverage_type": "whiskey", "event_id": event_id}
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "taster_info",
        "data": {"taster_name": "Taylor", "tasting_date": "2025-12-27", "beverage_type": "whiskey"}
    }
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "bottle_selection",
        "data": {"selected_bottle_path": bottle_path}
    }
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "tasting_form",
        "data": {
            "tasting_data": {
                "whiskey_nose": 2.0,
                "whiskey_palate": 2.0,
                "whiskey_finish": 2.0,
                "whiskey_overall": 0.6,
                "nose_notes": ["vanilla", "oak"],
                "palate_notes": ["caramel", "spice"],
                "finish_notes": ["medium", "warm"],
                "overall_notes": "Original tasting - pretty good."
            }
        }
    }
)

response = session.post(f"{BASE_URL}/api/v1/manual-tasting/save")
assert response.ok, "Failed to save initial tasting"
print("✓ Initial tasting saved")

# Verify initial scores
response = requests.get(f"{BASE_URL}/api/v1/events/{event_id}")
event_check = response.json()
tasting = event_check["participants"][participant_id]["tastings"][0]
initial_score = (tasting["tasting_data"]["whiskey_nose"] +
                 tasting["tasting_data"]["whiskey_palate"] +
                 tasting["tasting_data"]["whiskey_finish"] +
                 tasting["tasting_data"]["whiskey_overall"])
print(f"  Initial score: {initial_score:.1f}/10")
assert initial_score == 6.6, "Initial score incorrect"

# Edit the tasting (update scores and notes)
print("\n✏️ Editing tasting with updated scores...")
response = session.post(
    f"{BASE_URL}/api/v1/manual-tasting/start",
    json={"mode": "event", "beverage_type": "whiskey", "event_id": event_id}
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "taster_info",
        "data": {"taster_name": "Taylor", "tasting_date": "2025-12-27", "beverage_type": "whiskey"}
    }
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "bottle_selection",
        "data": {"selected_bottle_path": bottle_path}  # Same bottle
    }
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "tasting_form",
        "data": {
            "tasting_data": {
                "whiskey_nose": 2.8,
                "whiskey_palate": 2.7,
                "whiskey_finish": 2.9,
                "whiskey_overall": 0.9,
                "nose_notes": ["complex caramel", "deep oak", "dried fruit"],
                "palate_notes": ["rich", "layered", "chocolate", "tobacco"],
                "finish_notes": ["very long", "warming", "satisfying"],
                "overall_notes": "EDITED: After more time, this is exceptional!"
            }
        }
    }
)

response = session.post(f"{BASE_URL}/api/v1/manual-tasting/save")
assert response.ok, "Failed to save edited tasting"
print("✓ Edited tasting saved")

# Verify edited scores
response = requests.get(f"{BASE_URL}/api/v1/events/{event_id}")
event_check = response.json()
tastings = event_check["participants"][participant_id]["tastings"]
assert len(tastings) == 1, f"Should have 1 tasting, found {len(tastings)}"

tasting = tastings[0]
edited_score = (tasting["tasting_data"]["whiskey_nose"] +
                tasting["tasting_data"]["whiskey_palate"] +
                tasting["tasting_data"]["whiskey_finish"] +
                tasting["tasting_data"]["whiskey_overall"])
print(f"  Updated score: {edited_score:.1f}/10")
assert edited_score == 9.3, "Edited score incorrect"

# Verify notes were updated
assert "EDITED" in tasting["tasting_data"]["overall_notes"], "Notes weren't updated"
assert "complex caramel" in tasting["tasting_data"]["nose_notes"], "Nose notes weren't updated"

print("\n" + "="*60)
print("✅ EDIT TASTING TEST PASSED!")
print("="*60)
print(f"\n✓ Initial tasting: 6.6/10")
print(f"✓ Edited tasting: 9.3/10")
print(f"✓ Only 1 tasting exists (edit replaced original)")
print(f"✓ Notes and scores updated correctly")
print(f"\n🌐 View event:")
print(f"   {BASE_URL}/events/{event_id}")
print()
