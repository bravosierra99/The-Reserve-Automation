#!/usr/bin/env python3
"""Create a test event for whiskey tasting with Stagg bottles."""


import requests

# Configuration
API_BASE = "http://localhost:8000"

def main():
    print("🔍 Searching for Stagg bottles...")

    # Search for bottles with "stagg" in the name
    search_response = requests.get(
        f"{API_BASE}/api/v1/management/bottles/search",
        params={"q": "stagg"}
    )

    if not search_response.ok:
        print(f"❌ Failed to search for bottles: {search_response.status_code}")
        return

    bottles_data = search_response.json()
    bottles = bottles_data.get("bottles", [])

    if len(bottles) < 3:
        print(f"⚠️  Only found {len(bottles)} Stagg bottles, need at least 3")
        print("Available bottles:")
        for b in bottles:
            print(f"  - {b.get('producer')} - {b.get('name')}")
        return

    # Take first 3 bottles
    selected_bottles = bottles[:3]
    bottle_paths = [b["vault_path"] for b in selected_bottles]

    print(f"\n✓ Found {len(selected_bottles)} Stagg bottles:")
    for i, b in enumerate(selected_bottles, 1):
        print(f"  #{i}: {b.get('producer')} - {b.get('name')}")

    # Create the event
    print("\n📅 Creating blind whiskey tasting event...")

    event_data = {
        "name": "Test Stagg Blind Tasting",
        "beverage_type": "whiskey",
        "is_blind": True,
        "host_name": "Test Host",
        "bottle_paths": bottle_paths,
        "blind_numbers": [1, 2, 3]
    }

    create_response = requests.post(
        f"{API_BASE}/api/v1/events",
        headers={"Content-Type": "application/json"},
        json=event_data
    )

    if not create_response.ok:
        print(f"❌ Failed to create event: {create_response.status_code}")
        print(create_response.text)
        return

    event = create_response.json()
    event_id = event["event_id"]

    print("\n✅ Event created successfully!")
    print(f"   Event ID: {event_id}")
    print(f"   Event URL: http://localhost:8000/events/{event_id}")
    print("\n   Bottles are hidden (blind mode)")
    print("   Participants will see: Bottle #1, Bottle #2, Bottle #3")
    print("\n💾 Saving event ID to /tmp/event_id.txt")

    # Save event ID for convenience
    with open("/tmp/event_id.txt", "w") as f:
        f.write(event_id)

    print("\n🎉 Ready to test! Go to http://localhost:8000/events")

if __name__ == "__main__":
    main()
