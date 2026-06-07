#!/usr/bin/env python3
"""Test multi-event participation - one user joins and participates in multiple events."""
import pytest

pytest.skip("Manual integration test script requiring web server on localhost:8000", allow_module_level=True)

import json
import urllib.parse

import requests

BASE_URL = "http://localhost:8000"

print("🎭 Testing Multi-Event Participation")
print("=" * 60)

# Create Event 1: Whiskey
print("\n📝 Creating Event 1: Whiskey Blind Tasting...")
response = requests.get(f"{BASE_URL}/api/v1/management/bottles/search?q=Stagg")
whiskey_bottles = response.json()["bottles"][:2]

event1_data = {
    "name": "Test Multi-Event Whiskey",
    "beverage_type": "whiskey",
    "is_blind": True,
    "host_name": "Test Host",
    "bottle_ids": [str(b["id"]) for b in whiskey_bottles],
    "blind_numbers": [1, 2]
}

response = requests.post(f"{BASE_URL}/api/v1/events", json=event1_data)
event1 = response.json()
event1_id = event1["event_id"]
print(f"✓ Event 1 created: {event1_id[:8]}...")

# Create Event 2: Another Whiskey (non-blind)
print("\n📝 Creating Event 2: Non-Blind Whiskey Tasting...")
response = requests.get(f"{BASE_URL}/api/v1/management/bottles/search?q=Buffalo")
whiskey_bottles2 = response.json()["bottles"][:2]

if len(whiskey_bottles2) < 2:
    print("⚠️  Not enough bottles for Event 2, using same bottles as Event 1")
    whiskey_bottles2 = whiskey_bottles

event2_data = {
    "name": "Test Multi-Event Whiskey 2",
    "beverage_type": "whiskey",
    "is_blind": False,  # Non-blind
    "host_name": "Test Host",
    "bottle_ids": [str(b["id"]) for b in whiskey_bottles2],
    "blind_numbers": None
}

response = requests.post(f"{BASE_URL}/api/v1/events", json=event2_data)
event2 = response.json()
event2_id = event2["event_id"]
print(f"✓ Event 2 created: {event2_id[:8]}...")

# User joins both events
print("\n👤 User 'Alex' joining both events...")
session = requests.Session()

# Join Event 1
response = session.post(
    f"{BASE_URL}/api/v1/events/{event1_id}/join",
    json={"participant_name": "Alex"}
)
join1_data = response.json()
participant1_id = join1_data['participant_id']
print(f"✓ Joined Event 1 (participant ID: {participant1_id[:8]}...)")

# Cookie should now have Event 1 session
cookies = session.cookies.get_dict()
if 'participant_sessions' in cookies:
    sessions = json.loads(urllib.parse.unquote(cookies['participant_sessions']))
    print(f"  Cookie contains {len(sessions)} event session(s)")
    assert event1_id in sessions, "Event 1 session not in cookie!"

# Join Event 2
response = session.post(
    f"{BASE_URL}/api/v1/events/{event2_id}/join",
    json={"participant_name": "Alex"}
)
join2_data = response.json()
participant2_id = join2_data['participant_id']
print(f"✓ Joined Event 2 (participant ID: {participant2_id[:8]}...)")

# Cookie should now have BOTH events
cookies = session.cookies.get_dict()
if 'participant_sessions' in cookies:
    sessions = json.loads(urllib.parse.unquote(cookies['participant_sessions']))
    print(f"  Cookie now contains {len(sessions)} event session(s)")
    print(f"  Event IDs in cookie: {list(sessions.keys())}")
    print(f"  Looking for Event 1: {event1_id}")
    print(f"  Looking for Event 2: {event2_id}")
    assert event1_id in sessions, f"Event 1 session missing from cookie! Cookie has: {list(sessions.keys())}"
    assert event2_id in sessions, "Event 2 session missing from cookie!"
    assert sessions[event1_id]['participant_id'] == participant1_id
    assert sessions[event2_id]['participant_id'] == participant2_id
    print("  ✓ Cookie correctly stores both events")

# Add tasting to Event 1
print("\n🥃 Adding whiskey tasting to Event 1...")
response = session.post(
    f"{BASE_URL}/api/v1/manual-tasting/start",
    json={"mode": "event", "beverage_type": "whiskey", "event_id": event1_id}
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "taster_info",
        "data": {"taster_name": "Alex", "tasting_date": "2025-12-27", "beverage_type": "whiskey"}
    }
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "bottle_selection",
        "data": {"selected_bottle_path": event1["bottles"][0]["bottle_path"]}
    }
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "tasting_form",
        "data": {
            "tasting_data": {
                "whiskey_nose": 2.5,
                "whiskey_palate": 2.4,
                "whiskey_finish": 2.6,
                "whiskey_overall": 0.9,
                "overall_notes": "Event 1 whiskey - excellent!"
            }
        }
    }
)

response = session.post(f"{BASE_URL}/api/v1/manual-tasting/save")
if response.ok:
    print("✓ Whiskey tasting saved to Event 1")
else:
    print(f"❌ Failed to save: {response.text}")

# Add tasting to Event 2
print("\n🥃 Adding whiskey tasting to Event 2...")
response = session.post(
    f"{BASE_URL}/api/v1/manual-tasting/start",
    json={"mode": "event", "beverage_type": "whiskey", "event_id": event2_id}
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "taster_info",
        "data": {"taster_name": "Alex", "tasting_date": "2025-12-27", "beverage_type": "whiskey"}
    }
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "bottle_selection",
        "data": {"selected_bottle_path": event2["bottles"][0]["bottle_path"]}
    }
)

session.put(
    f"{BASE_URL}/api/v1/manual-tasting/session/step",
    json={
        "step": "tasting_form",
        "data": {
            "tasting_data": {
                "whiskey_nose": 2.3,
                "whiskey_palate": 2.2,
                "whiskey_finish": 2.4,
                "whiskey_overall": 0.8,
                "overall_notes": "Event 2 whiskey - very good!"
            }
        }
    }
)

response = session.post(f"{BASE_URL}/api/v1/manual-tasting/save")
if response.ok:
    print("✓ Whiskey tasting saved to Event 2")
else:
    print(f"❌ Failed to save: {response.text}")

# Verify tastings were saved to correct events
print("\n🔍 Verifying tastings in each event...")

response = requests.get(f"{BASE_URL}/api/v1/events/{event1_id}")
event1_check = response.json()
alex_tastings_e1 = event1_check["participants"][participant1_id]["tastings"]
print(f"✓ Event 1: Alex has {len(alex_tastings_e1)} tasting(s)")
assert len(alex_tastings_e1) == 1, "Should have 1 tasting in Event 1"

response = requests.get(f"{BASE_URL}/api/v1/events/{event2_id}")
event2_check = response.json()
alex_tastings_e2 = event2_check["participants"][participant2_id]["tastings"]
print(f"✓ Event 2: Alex has {len(alex_tastings_e2)} tasting(s)")
assert len(alex_tastings_e2) == 1, "Should have 1 tasting in Event 2"

print("\n" + "="*60)
print("✅ MULTI-EVENT TEST PASSED!")
print("="*60)
print("\n✓ User successfully joined 2 events")
print("✓ Cookie correctly stored both sessions")
print("✓ Tastings saved to correct events")
print("\n🌐 View events:")
print(f"   Event 1: {BASE_URL}/events/{event1_id}")
print(f"   Event 2: {BASE_URL}/events/{event2_id}")
print()
