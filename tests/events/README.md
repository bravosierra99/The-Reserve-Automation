# Event System Test Suite

Comprehensive automated tests for the multi-user tasting event system.

## Quick Start

```bash
# Run all event tests
./tests/events/run_all_tests.sh

# Clean up test events
python3 tests/events/cleanup_test_events.py
```

## Test Coverage

### 1. Blind Whiskey Event ✅
**Files:** `create_test_event.py` + `populate_event_tastings.py`

**Tests:**
- Creating blind whiskey event with 3 bottles
- Randomized blind numbers (host can't predict mapping)
- 3 participants joining and tasting
- Full tasting notes (nose/palate/finish arrays + overall)
- Whiskey 10-point scoring system
- Revealing bottles
- Rankings calculation

**Data:**
- Participants: Alice, Bob, Charlie
- Bottles: 3 Stagg variants
- Scores: Realistic range 4.3-8.4 points
- Notes: Detailed flavor profiles per category

### 2. Blind Wine Event ✅ (Skipped if no wines)
**Files:** `create_wine_event.py` + `populate_wine_event.py`

**Tests:**
- Creating blind wine event
- AWS wine scoring (Appearance/Aroma/Taste/Aftertaste/Overall - max 20)
- Wine-specific tasting notes
- Rankings with different scoring system

**Data:**
- Participants: Sophie, Marcus, Elena
- Bottles: 3 Bordeaux wines
- Scores: AWS 20-point scale (10.5-17.3 range)

### 3. Multi-Event Participation ✅
**File:** `test_multi_event.py`

**Tests:**
- User joining 2+ events simultaneously
- Multi-event cookie structure
- Event-specific participant IDs
- Tastings saved to correct events

**Status:** Passing - users can join multiple events and tastings are correctly saved to each event

### 4. Edit Existing Tasting ✅
**File:** `test_edit_tasting.py`

**Tests:**
- Creating initial tasting
- Editing same bottle (updates, doesn't duplicate)
- Score changes reflected
- Notes updated correctly

**Assertions:**
- Only 1 tasting exists after edit
- Scores match edited values
- Notes contain updated content

## Test Scripts

### Core Event Tests
- `create_test_event.py` - Create blind whiskey event
- `populate_event_tastings.py` - Populate with 3 participants
- `create_wine_event.py` - Create blind wine event
- `populate_wine_event.py` - Populate wine event

### Feature Tests
- `test_multi_event.py` - Multi-event participation
- `test_edit_tasting.py` - Edit existing tasting

### Utilities
- `cleanup_test_events.py` - Delete all "Test*" events
- `run_all_tests.sh` - Master test runner

## Running Tests

### Run All Tests
```bash
cd /mnt/d/users/ben/Documents/spirits/automation
./tests/events/run_all_tests.sh
```

### Run Individual Tests
```bash
# Whiskey blind tasting
python3 tests/events/create_test_event.py
python3 tests/events/populate_event_tastings.py

# Wine blind tasting (if you have wines)
python3 tests/events/create_wine_event.py
python3 tests/events/populate_wine_event.py

# Multi-event
python3 tests/events/test_multi_event.py

# Edit tasting
python3 tests/events/test_edit_tasting.py
```

### Clean Up After Tests
```bash
python3 tests/events/cleanup_test_events.py
```

## When to Run Tests

### ✅ ALWAYS run event tests after:
- Changes to `/src/reserve_automation/web/routes/events.py`
- Changes to `/src/reserve_automation/web/routes/tastings.py`
- Changes to `/src/reserve_automation/web/templates/event_*.html`
- Changes to `/src/reserve_automation/web/templates/manual_tasting.html`
- Changes to event-related schemas
- Cookie/session handling changes

### Recommended workflow:
1. Make changes to event system
2. Run `./tests/events/run_all_tests.sh`
3. Verify all tests pass (3/4 currently)
4. Manually view test events at http://localhost:8000/events
5. Run `python3 tests/events/cleanup_test_events.py`

## Test Data Format

### Whiskey Tasting Data
```python
{
    "whiskey_nose": 2.5,
    "whiskey_palate": 2.4,
    "whiskey_finish": 2.6,
    "whiskey_overall": 0.9,
    "nose_notes": ["caramel", "vanilla", "oak", "brown sugar"],
    "palate_notes": ["cherry", "dark chocolate", "leather"],
    "finish_notes": ["long", "warm", "spicy"],
    "overall_notes": "Exceptional bourbon with great complexity."
}
```

### Wine Tasting Data
```python
{
    "wine_appearance": 2.5,
    "wine_aroma": 5.0,
    "wine_taste": 5.5,
    "wine_aftertaste": 2.5,
    "wine_overall": 1.8,
    "nose_notes": ["blackberry", "cassis", "cedar"],
    "palate_notes": ["dark fruit", "oak", "silky tannins"],
    "finish_notes": ["long", "elegant"],
    "overall_notes": "Exceptional Bordeaux."
}
```

## Expected Test Output

```
╔════════════════════════════════════════════════════════════╗
║     THE RESERVE AUTOMATION - COMPREHENSIVE TEST SUITE     ║
╔════════════════════════════════════════════════════════════╗

🧹 Cleaning up previous test events...
✅ Cleaned up X test events

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TEST 1: Blind Whiskey Event
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ PASSED: Blind Whiskey Event

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TEST 2: Blind Wine Event
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ PASSED: Blind Wine Event (skipped - no wines)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TEST 3: Multi-Event Participation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ PASSED: Multi-Event Participation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TEST 4: Edit Existing Tasting
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ PASSED: Edit Existing Tasting

╔════════════════════════════════════════════════════════════╗
║                      TEST SUMMARY                          ║
╚════════════════════════════════════════════════════════════╝

  Total Tests:   4
  Passed:        4
  Failed:        0

🎉 ALL TESTS PASSED!
```

## Bugs Fixed by These Tests

### ✅ Multi-Event Cookie Bug (FIXED 2025-12-27)
- **Issue:** When joining Event 2, Event 1 session disappeared from cookie
- **Root Cause:** Missing `unquote` import in `events.py`
- **Fixed in:** `events.py:8` - added `unquote` to urllib.parse imports, added `path="/"` to cookie
- **Test:** `test_multi_event.py` verifies both events remain in cookie

### ✅ Double-Nesting Bug
- **Issue:** `{tasting_data: {tasting_data: {...}}}`
- **Fixed in:** `tastings.py`, `event_results.html`, `manual_tasting.html`
- **Test:** All tests verify flat structure

### ✅ Tasting Notes Not Displaying
- **Issue:** Only overall notes showed, not category notes
- **Fixed in:** `event_results.html` - added nose/palate/finish display
- **Test:** Whiskey and wine tests verify all notes appear

### ✅ Bottle Order Not Sorted
- **Issue:** Bottles shown in random order to participants
- **Fixed in:** `manual_tasting.html:736-739` - sorts by blind_number
- **Test:** Whiskey blind test verifies sorted display

## Viewing Test Results

After running tests, events remain active for manual inspection:

```bash
# Open in browser
http://localhost:8000/events

# View specific event results
http://localhost:8000/events/{event_id}/results
```

Test events all have "Test" in the name for easy identification.

## Adding New Tests

1. Create test script in `tests/events/test_*.py`
2. Add to `run_all_tests.sh`:
   ```bash
   run_test "Test Name" "python3 tests/events/test_*.py" || true
   ```
3. Document in this README
4. Update test count in summary section

## Future Test Ideas

- Event lifecycle (create → reveal → close → delete)
- Partial participation (not all users taste all bottles)
- Large events (10+ participants, 5+ bottles)
- Upload extraction workflow
- Obsidian manual entry (non-event mode)
- Concurrent access (multiple users simultaneously)
