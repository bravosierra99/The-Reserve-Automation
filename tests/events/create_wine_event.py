#!/usr/bin/env python3
"""Create a test wine blind tasting event."""
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000"

print("🍷 Creating Test Wine Blind Tasting Event")
print("=" * 60)

# Search for wine bottles
print("\n🔍 Searching for wine bottles...")
response = requests.get(f"{BASE_URL}/api/v1/management/bottles/search?q=Bordeaux")
if not response.ok:
    print(f"❌ Failed to search: {response.status_code}")
    exit(1)

results = response.json()
bottles = results.get("bottles", [])

if len(bottles) < 3:
    print(f"⚠️ Not enough wine bottles found (need 3, found {len(bottles)})")
    print("   Skipping wine test - add wines to vault to enable")
    print("   Try: Bordeaux, Burgundy, Champagne, etc.")
    exit(0)  # Exit with success to not fail the test suite

# Take first 3 wines
selected_bottles = bottles[:3]
print(f"\n✓ Found {len(selected_bottles)} wine bottles:")
for i, bottle in enumerate(selected_bottles):
    print(f"  #{i+1}: {bottle.get('producer', '')} - {bottle.get('name', '')}")

# Create blind event
print("\n📅 Creating blind wine tasting event...")
event_data = {
    "name": "Test Wine Blind Tasting",
    "beverage_type": "wine",
    "is_blind": True,
    "host_name": "Test Host",
    "bottle_ids": [str(b["id"]) for b in selected_bottles],
    "blind_numbers": [1, 2, 3]  # Will be randomized by backend
}

response = requests.post(f"{BASE_URL}/api/v1/events", json=event_data)
if not response.ok:
    print(f"❌ Failed to create event: {response.status_code}")
    print(response.text)
    exit(1)

event = response.json()
event_id = event["event_id"]

print("\n✅ Event created successfully!")
print(f"   Event ID: {event_id}")
print(f"   Event URL: {BASE_URL}/events/{event_id}")
print("\n   Bottles are hidden (blind mode)")
print("   Participants will see: Bottle #1, Bottle #2, Bottle #3")

# Save event ID
Path("/tmp/event_id.txt").write_text(event_id)
print("\n💾 Saving event ID to /tmp/event_id.txt")

print(f"\n🎉 Ready to test! Go to {BASE_URL}/events")
