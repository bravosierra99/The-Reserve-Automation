# Manual Testing Scripts

This directory contains scripts for manual testing and populating the web application with test data.

## Prerequisites

1. Start the web server:
   ```bash
   WEB_SECRET_KEY=test uv run uvicorn reserve_automation.web.app:app --host 0.0.0.0 --port 8000
   ```

2. Make sure you have bottles in your vault with "Stagg" in the name (or modify the scripts to use different bottles)

## Scripts

### `create_test_event.py`

Creates a blind whiskey tasting event with 3 Stagg bottles.

**Usage:**
```bash
python3 tests/manual/create_test_event.py
```

**What it does:**
- Searches for bottles with "Stagg" in the name
- Creates a blind tasting event with 3 bottles
- Saves the event ID to `/tmp/event_id.txt`
- Prints the event URL

**Output:**
```
✅ Event created successfully!
   Event ID: abc123...
   Event URL: http://localhost:8000/events/abc123...
```

---

### `populate_event_tastings.py`

Populates an existing event with tastings from 3 simulated participants.

**Usage:**
```bash
# First create an event
python3 tests/manual/create_test_event.py

# Then populate it
python3 tests/manual/populate_event_tastings.py
```

**What it does:**
- Reads event ID from `/tmp/event_id.txt`
- Creates 3 participants: Alice, Bob, Charlie
- Each participant tastes all bottles with different scores
- Automatically reveals the event
- Shows expected rankings and individual preferences

**Participant Scores (designed to show varied preferences):**
- **Alice**: Loves Bottle #1 (95 pts), hates Bottle #3 (62 pts)
- **Bob**: Hates Bottle #1 (62 pts), loves Bottle #3 (98 pts)
- **Charlie**: Consistently rates Bottle #2 highest (90 pts)

**Output:**
```
✅ EVENT POPULATED SUCCESSFULLY!

📊 View Results:
   http://localhost:8000/events/abc123.../results

🎯 Expected Rankings:
   🥇 #1: Bottle #2 - 86.3 avg (Most liked)
   🥈 #2: Bottle #3 - 79.3 avg
   🥉 #3: Bottle #1 - 78.7 avg (Least liked)

💡 Individual Preferences:
   Alice: #1 > #2 > #3
   Bob: #3 > #2 > #1
   Charlie: #2 > #1 > #3
```

---

### `create-and-populate-event.sh` ⭐ **Recommended**

One-command script that creates an event AND populates it with test data.

**Usage:**
```bash
./tests/manual/create-and-populate-event.sh
```

**What it does:**
- Runs `create_test_event.py`
- Runs `populate_event_tastings.py`
- Gives you a fully populated event ready for visual testing

**Perfect for:**
- Quick visual testing of the UI
- Testing the results/rankings page
- Demonstrating the app to others
- Testing workflows end-to-end

---

## Testing Workflows

### Complete Event Workflow Test

```bash
# 1. Start server
WEB_SECRET_KEY=test uv run uvicorn reserve_automation.web.app:app --host 0.0.0.0 --port 8000

# 2. Create and populate event
./tests/manual/create-and-populate-event.sh

# 3. Open the event URL in browser
# (URL printed by script)

# 4. Test features:
#    - View event detail page
#    - Click "Show QR Code" to display QR code for sharing
#    - Join as a new participant
#    - Add tastings (manual entry or upload)
#    - View results page (already revealed by script)
#    - Check rankings and statistics
#    - Click scores in table to view detailed tasting notes
```

### Test Edit Functionality

```bash
# 1. Create and populate event
./tests/manual/create-and-populate-event.sh

# 2. Join event as yourself
# (Go to event URL, enter your name)

# 3. Add a tasting via manual entry

# 4. Go back to Step 2 (bottle selection)
# - Verify the bottle shows as "✓ Tasted" with green border
# - Click "📝 Edit Tasting"
# - Verify your previous data is loaded
# - Make changes and save
# - Verify the tasting was updated (not duplicated)
```

### Test Results Page

```bash
# 1. Create and populate event
./tests/manual/create-and-populate-event.sh

# 2. Open results URL
# (Printed at end of script output)

# 3. Verify:
#    - Overall rankings show correct order
#    - Highest rated bottle has gold badge
#    - Individual rankings show per-participant preferences
#    - Scores are calculated correctly
#    - Detailed notes table shows all bottles vs participants
#    - Click any score to open modal with full tasting details
#    - Modal shows nose/palate/finish/overall scores and notes
```

## Modifying Test Data

To customize the test participants and scores, edit `populate_event_tastings.py`:

```python
participants_data = [
    {
        "name": "Your Name",
        "scores": [
            {"bottle_idx": 0, "nose": 24, "palate": 23, "finish": 24, "overall": 24, "notes": "Your notes"},
            # ... more bottles
        ]
    },
    # ... more participants
]
```

## Tips

- **Clear event data**: Restart the server to clear in-memory event store
- **Different bottles**: Modify the search term in `create_test_event.py`
- **More participants**: Add to `participants_data` in `populate_event_tastings.py`
- **Different scores**: Adjust the scores to test edge cases (all same, all different, etc.)

## Troubleshooting

**"Event not found" error:**
- Make sure the server is running
- Check that `/tmp/event_id.txt` has the correct event ID
- Server restart clears all events (need to create new one)

**"No bottles found" error:**
- Ensure you have bottles with "Stagg" in the name in your vault
- Or modify the search term in `create_test_event.py`

**Cookie issues:**
- Clear browser cookies for localhost:8000
- Check that `participant_session` cookie is being set correctly
