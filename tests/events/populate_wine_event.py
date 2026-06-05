#!/usr/bin/env python3
"""Populate a wine event with tastings from multiple participants."""
import json
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000"

# Read event ID
event_id_file = Path("/tmp/event_id.txt")
if not event_id_file.exists():
    print("❌ No event ID found. Run create_wine_event.py first!")
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

# Wine AWS scoring: Appearance 0-3, Aroma 0-6, Taste 0-6, Aftertaste 0-3, Overall 0-2 (Total: 20)
participants_data = [
    {
        "name": "Sophie",
        "scores": [
            {
                "bottle_idx": 0,
                "appearance": 2.5, "aroma": 5.0, "taste": 5.5, "aftertaste": 2.5, "overall": 1.8,
                "nose_notes": ["blackberry", "cassis", "cedar", "tobacco"],
                "palate_notes": ["dark fruit", "oak", "silky tannins", "balanced"],
                "finish_notes": ["long", "elegant", "refined"],
                "overall_notes": "Exceptional Bordeaux. Complex and beautifully structured."
            },
            {
                "bottle_idx": 1,
                "appearance": 2.0, "aroma": 4.0, "taste": 4.5, "aftertaste": 2.0, "overall": 1.5,
                "nose_notes": ["cherry", "vanilla", "oak"],
                "palate_notes": ["red fruit", "smooth", "medium body"],
                "finish_notes": ["medium", "pleasant"],
                "overall_notes": "Nice wine, approachable and well-made."
            },
            {
                "bottle_idx": 2,
                "appearance": 1.5, "aroma": 3.0, "taste": 3.5, "aftertaste": 1.5, "overall": 1.0,
                "nose_notes": ["faint fruit", "some oak"],
                "palate_notes": ["thin", "acidic", "unbalanced"],
                "finish_notes": ["short", "harsh"],
                "overall_notes": "Disappointing. Lacks complexity and balance."
            }
        ]
    },
    {
        "name": "Marcus",
        "scores": [
            {
                "bottle_idx": 0,
                "appearance": 2.0, "aroma": 4.5, "taste": 4.0, "aftertaste": 2.0, "overall": 1.3,
                "nose_notes": ["plum", "leather", "earth"],
                "palate_notes": ["fruit forward", "structured", "good tannins"],
                "finish_notes": ["long", "satisfying"],
                "overall_notes": "Really good, classic profile. Would age well."
            },
            {
                "bottle_idx": 1,
                "appearance": 2.5, "aroma": 5.5, "taste": 5.0, "aftertaste": 2.5, "overall": 1.7,
                "nose_notes": ["raspberry", "rose", "spice", "minerality"],
                "palate_notes": ["vibrant", "fresh", "complex layers"],
                "finish_notes": ["very long", "beautiful"],
                "overall_notes": "Outstanding! My favorite of the night."
            },
            {
                "bottle_idx": 2,
                "appearance": 2.0, "aroma": 4.0, "taste": 4.0, "aftertaste": 1.8, "overall": 1.4,
                "nose_notes": ["blackcurrant", "oak", "vanilla"],
                "palate_notes": ["solid", "good structure", "balanced"],
                "finish_notes": ["medium", "clean"],
                "overall_notes": "Solid wine, nothing spectacular but well-executed."
            }
        ]
    },
    {
        "name": "Elena",
        "scores": [
            {
                "bottle_idx": 0,
                "appearance": 2.5, "aroma": 4.5, "taste": 5.0, "aftertaste": 2.3, "overall": 1.6,
                "nose_notes": ["black cherry", "graphite", "violet"],
                "palate_notes": ["concentrated", "powerful", "velvety"],
                "finish_notes": ["persistent", "harmonious"],
                "overall_notes": "Excellent wine with great aging potential."
            },
            {
                "bottle_idx": 1,
                "appearance": 2.0, "aroma": 4.2, "taste": 4.3, "aftertaste": 2.0, "overall": 1.5,
                "nose_notes": ["strawberry", "herbs", "subtle oak"],
                "palate_notes": ["fresh", "crisp", "medium weight"],
                "finish_notes": ["clean", "refreshing"],
                "overall_notes": "Very nice, especially for summer drinking."
            },
            {
                "bottle_idx": 2,
                "appearance": 1.8, "aroma": 3.5, "taste": 3.8, "aftertaste": 1.7, "overall": 1.2,
                "nose_notes": ["red fruit", "oak", "slight funk"],
                "palate_notes": ["ok", "decent fruit", "slightly hollow"],
                "finish_notes": ["medium", "acceptable"],
                "overall_notes": "Decent but not memorable. Average quality."
            }
        ]
    }
]

print("\n" + "="*60)
print("POPULATING WINE EVENT WITH TASTINGS")
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
    import urllib.parse
    participant_cookie = json.dumps({
        EVENT_ID: {
            "participant_id": participant_id,
            "participant_name": name
        }
    })
    session.cookies.set('participant_sessions', urllib.parse.quote(participant_cookie))

    # Add tastings for each bottle
    for score_data in participant_data["scores"]:
        bottle_idx = score_data["bottle_idx"]
        bottle = bottles[bottle_idx]

        # Start manual tasting session
        response = session.post(
            f"{BASE_URL}/api/v1/manual-tasting/start",
            json={
                "mode": "event",
                "beverage_type": "wine",
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
                    "tasting_date": "2025-12-27",
                    "beverage_type": "wine"
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

        # Fill tasting data (AWS wine scoring)
        session.put(
            f"{BASE_URL}/api/v1/manual-tasting/session/step",
            json={
                "step": "tasting_form",
                "data": {
                    "tasting_data": {
                        "wine_appearance": score_data["appearance"],
                        "wine_aroma": score_data["aroma"],
                        "wine_taste": score_data["taste"],
                        "wine_aftertaste": score_data["aftertaste"],
                        "wine_overall": score_data["overall"],
                        "nose_notes": score_data.get("nose_notes", []),
                        "palate_notes": score_data.get("palate_notes", []),
                        "finish_notes": score_data.get("finish_notes", []),
                        "overall_notes": score_data.get("overall_notes", "")
                    }
                }
            }
        )

        # Save tasting
        response = session.post(f"{BASE_URL}/api/v1/manual-tasting/save")

        if response.ok:
            total_score = (score_data["appearance"] + score_data["aroma"] +
                          score_data["taste"] + score_data["aftertaste"] + score_data["overall"])
            print(f"  ✓ Bottle #{bottle_idx + 1}: {total_score:.1f}/20 points")
        else:
            print(f"  ❌ Failed to save tasting for bottle {bottle_idx + 1}")

# Reveal the event
print("\n🎭 Revealing bottles...")
response = requests.put(f"{BASE_URL}/api/v1/events/{EVENT_ID}/reveal")

if response.ok:
    print("✓ Event revealed!")
else:
    print(f"❌ Failed to reveal: {response.status_code}")

print("\n" + "="*60)
print("✅ WINE EVENT POPULATED SUCCESSFULLY!")
print("="*60)
print("\n📊 View Results:")
print(f"   {BASE_URL}/events/{EVENT_ID}/results")

# Calculate expected rankings
bottle_totals = {}
for participant_data in participants_data:
    for score_data in participant_data["scores"]:
        bottle_idx = score_data["bottle_idx"]
        total = (score_data["appearance"] + score_data["aroma"] +
                score_data["taste"] + score_data["aftertaste"] + score_data["overall"])

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

print("\n🎯 Expected Rankings (based on AWS scores):")
for i, ranking in enumerate(rankings):
    badge = ""
    if i == 0:
        badge = "🥇"
    elif i == len(rankings) - 1:
        badge = "🥉"
    else:
        badge = "🥈"

    print(f"   {badge} #{i+1}: {ranking['name']} - {ranking['avg']:.1f}/20 avg")

print("\n🌐 Open in browser:")
print(f"   {BASE_URL}/events/{EVENT_ID}")
print()
