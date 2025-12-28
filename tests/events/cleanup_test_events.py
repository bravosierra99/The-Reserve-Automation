#!/usr/bin/env python3
"""Clean up all test events (events with 'Test' in the name)."""
import requests

BASE_URL = "http://localhost:8000"

print("🧹 Cleaning up test events...")

# Get all events
response = requests.get(f"{BASE_URL}/api/v1/events")
if not response.ok:
    print(f"❌ Failed to get events: {response.status_code}")
    exit(1)

events = response.json()
test_events = [e for e in events if "Test" in e.get("name", "")]

if not test_events:
    print("✓ No test events to clean up")
    exit(0)

print(f"Found {len(test_events)} test event(s) to delete:")
for event in test_events:
    print(f"  - {event['name']} ({event['event_id'][:8]}...)")

deleted = 0
for event in test_events:
    response = requests.delete(f"{BASE_URL}/api/v1/events/{event['event_id']}")
    if response.ok:
        deleted += 1
        print(f"  ✓ Deleted: {event['name']}")
    else:
        print(f"  ❌ Failed to delete: {event['name']}")

print(f"\n✅ Cleaned up {deleted}/{len(test_events)} test events")
