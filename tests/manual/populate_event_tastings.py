#!/usr/bin/env python3
"""Populate an event with tastings from multiple participants."""
import requests
import json
from pathlib import Path

BASE_URL = "http://localhost:8000"

# Read event ID from file
event_id_file = Path("/tmp/event_id.txt")
if not event_id_file.exists():
    print("❌ No event ID found. Run /tmp/create_test_event.py first!")
    exit(1)

EVENT_ID = event_id_file.read_text().strip()
print(f"📋 Using Event ID: {EVENT_ID}")

# Get event details
response = requests.get(f"{BASE_URL}/api/v1/events/{EVENT_ID}")
if not response.ok:
    print(f"❌ Failed to get event: {response.status_code}")
    exit(1)

event_data = response.json()
print(f"✓ Event: {event_data['name']}")
print(f"  Bottles: {len(event_data['bottles'])}")

bottles = event_data['bottles']

# Define participants and their scores
# Whiskey scoring: Nose 0-3, Palate 0-3, Finish 0-3, Overall 0-1 (Total: 10 points)
# Realistic scoring with good variance (typical range: 5.0-8.5)
participants_data = [
    {
        "name": "Alice",
        "scores": [
            {"bottle_idx": 0, "nose": 2.4, "palate": 2.3, "finish": 2.5, "overall": 0.8, "notes": "Absolutely amazing! Rich and complex."},
            {"bottle_idx": 1, "nose": 1.8, "palate": 2.0, "finish": 1.9, "overall": 0.6, "notes": "Pretty good, solid bourbon."},
            {"bottle_idx": 2, "nose": 1.2, "palate": 1.4, "finish": 1.3, "overall": 0.4, "notes": "Not my favorite, too harsh."}
        ]
    },
    {
        "name": "Bob",
        "scores": [
            {"bottle_idx": 0, "nose": 1.3, "palate": 1.2, "finish": 1.4, "overall": 0.4, "notes": "Not impressed, too spicy."},
            {"bottle_idx": 1, "nose": 2.1, "palate": 2.0, "finish": 2.2, "overall": 0.7, "notes": "Very nice, smooth and balanced."},
            {"bottle_idx": 2, "nose": 2.5, "palate": 2.4, "finish": 2.6, "overall": 0.9, "notes": "Fantastic! This is my favorite."}
        ]
    },
    {
        "name": "Charlie",
        "scores": [
            {"bottle_idx": 0, "nose": 1.9, "palate": 1.7, "finish": 1.8, "overall": 0.5, "notes": "Decent, middle of the road."},
            {"bottle_idx": 1, "nose": 2.2, "palate": 2.1, "finish": 2.3, "overall": 0.7, "notes": "Really good! Would buy this."},
            {"bottle_idx": 2, "nose": 1.7, "palate": 1.8, "finish": 1.6, "overall": 0.6, "notes": "Good but not great."}
        ]
    }
]

print("\n" + "="*60)
print("POPULATING EVENT WITH TASTINGS")
print("="*60)

for participant_data in participants_data:
    name = participant_data["name"]
    print(f"\n👤 {name}")

    # Join event
    response = requests.post(
        f"{BASE_URL}/api/v1/events/{EVENT_ID}/join",
        json={"participant_name": name}
    )

    if not response.ok:
        print(f"  ❌ Failed to join: {response.status_code}")
        continue

    join_data = response.json()
    participant_id = join_data['participant_id']
    print(f"  ✓ Joined event (ID: {participant_id[:8]}...)")

    # Create session for this participant
    session = requests.Session()
    # Set participant_session cookie
    import urllib.parse
    participant_cookie = json.dumps({
        "participant_id": participant_id,
        "event_id": EVENT_ID,
        "participant_name": name
    })
    session.cookies.set('participant_session', urllib.parse.quote(participant_cookie))

    # Add tastings for each bottle
    for score_data in participant_data["scores"]:
        bottle_idx = score_data["bottle_idx"]
        bottle = bottles[bottle_idx]

        # Start manual tasting session
        response = session.post(
            f"{BASE_URL}/api/v1/manual-tasting/start",
            json={
                "mode": "event",
                "beverage_type": "whiskey",
                "event_id": EVENT_ID
            }
        )

        if not response.ok:
            print(f"  ❌ Failed to start session for bottle {bottle_idx + 1}")
            continue

        # Update taster info
        session.put(
            f"{BASE_URL}/api/v1/manual-tasting/session/step",
            json={
                "step": "taster_info",
                "data": {
                    "taster_name": name,
                    "tasting_date": "2025-12-26",
                    "beverage_type": "whiskey"
                }
            }
        )

        # Select bottle
        session.put(
            f"{BASE_URL}/api/v1/manual-tasting/session/step",
            json={
                "step": "bottle_selection",
                "data": {
                    "selected_bottle_path": bottle['bottle_path']
                }
            }
        )

        # Fill tasting data
        session.put(
            f"{BASE_URL}/api/v1/manual-tasting/session/step",
            json={
                "step": "tasting_form",
                "data": {
                    "whiskey_nose": score_data["nose"],
                    "whiskey_palate": score_data["palate"],
                    "whiskey_finish": score_data["finish"],
                    "whiskey_overall": score_data["overall"],
                    "notes": score_data["notes"]
                }
            }
        )

        # Save tasting
        response = session.post(f"{BASE_URL}/api/v1/manual-tasting/save")

        if response.ok:
            total_score = score_data["nose"] + score_data["palate"] + score_data["finish"] + score_data["overall"]
            print(f"  ✓ Bottle #{bottle_idx + 1}: {total_score} points")
        else:
            print(f"  ❌ Failed to save tasting for bottle {bottle_idx + 1}")

# Now reveal the event
print(f"\n🎭 Revealing bottles...")
response = requests.put(f"{BASE_URL}/api/v1/events/{EVENT_ID}/reveal")

if response.ok:
    print("✓ Event revealed!")
else:
    print(f"❌ Failed to reveal: {response.status_code}")

print("\n" + "="*60)
print("✅ EVENT POPULATED SUCCESSFULLY!")
print("="*60)
print(f"\n📊 View Results:")
print(f"   {BASE_URL}/events/{EVENT_ID}/results")
print(f"\n🎯 Expected Rankings (based on scores):")

# Calculate expected rankings
bottle_totals = {}
for participant_data in participants_data:
    for score_data in participant_data["scores"]:
        bottle_idx = score_data["bottle_idx"]
        total = score_data["nose"] + score_data["palate"] + score_data["finish"] + score_data["overall"]

        if bottle_idx not in bottle_totals:
            bottle_totals[bottle_idx] = {"scores": [], "total": 0}

        bottle_totals[bottle_idx]["scores"].append(total)
        bottle_totals[bottle_idx]["total"] += total

rankings = []
for bottle_idx, data in bottle_totals.items():
    avg = data["total"] / len(data["scores"])
    rankings.append({
        "idx": bottle_idx,
        "name": f"Bottle #{bottle_idx + 1}",
        "avg": avg
    })

rankings.sort(key=lambda x: x["avg"], reverse=True)

for i, ranking in enumerate(rankings):
    badge = ""
    if i == 0:
        badge = "🥇"
    elif i == len(rankings) - 1:
        badge = "🥉"
    else:
        badge = "🥈"

    print(f"   {badge} #{i+1}: {ranking['name']} - {ranking['avg']:.1f} avg")

print("\n💡 Individual Preferences:")
for participant_data in participants_data:
    participant_rankings = []
    for score_data in participant_data["scores"]:
        total = score_data["nose"] + score_data["palate"] + score_data["finish"] + score_data["overall"]
        participant_rankings.append({
            "idx": score_data["bottle_idx"],
            "total": total
        })

    participant_rankings.sort(key=lambda x: x["total"], reverse=True)

    ranked_str = " > ".join([f"#{r['idx']+1}" for r in participant_rankings])
    print(f"   {participant_data['name']}: {ranked_str}")

print("\n🌐 Open in browser:")
print(f"   {BASE_URL}/events/{EVENT_ID}")
print()
