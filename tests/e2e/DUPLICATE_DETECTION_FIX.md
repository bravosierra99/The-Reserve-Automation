# Duplicate Detection Fix - 2026-01-14

## Problem
Duplicate detection tests were failing because the duplicate dialog never appeared, even though backend was detecting duplicates correctly.

## Root Cause
The `duplicateAction` field in `bottle-editor-modal.js` was initialized to `'save_new'` instead of `null`, causing:
1. First save attempt set `force_save=true` in the request
2. Backend skipped duplicate detection when `force_save=true`
3. Bottle was saved without showing duplicate dialog

## Fixes Applied

### 1. Frontend - bottle-editor-modal.js

**Line 50** - Initialization:
```javascript
// BEFORE:
duplicateAction: 'save_new',  // Wrong - causes force_save on first attempt

// AFTER:
duplicateAction: null,  // Correct - allows duplicate detection on first save
```

**Line 179** - Reset method:
```javascript
// BEFORE:
this.duplicateAction = 'save_new';

// AFTER:
this.duplicateAction = null;  // Reset to null so first save attempt checks for duplicates
```

### 2. Backend - save.py

**Lines 142-164** - Added unique suffix for "Save as New":
```python
# If force_save (Save as New), check if file exists and add unique suffix
if request.force_save and not request.replace_vault_path:
    original_path = obsidian_file.file_path
    counter = 2
    while obsidian_file.file_path.parent.exists():
        # Folder exists - add suffix to bottle name
        suffix = f" ({counter})"
        new_filename = original_path.parent.name + suffix
        new_folder = original_path.parent.parent / new_filename
        new_file = new_folder / f"{new_filename}.md"

        obsidian_file.file_path = new_file
        obsidian_file.content = obsidian_file.content.replace(
            f"Name: {original_path.parent.name}\n",
            f"Name: {new_filename}\n",
            1  # Only replace first occurrence in frontmatter
        )
        counter += 1

        if counter > 100:  # Safety limit
            raise HTTPException(status_code=500, detail="Too many duplicate bottles")

    logger.info(f"Force save with unique name: {obsidian_file.file_path.parent.name}")
```

**Result**: Bottles saved as new get " (2)", " (3)", etc. suffixes instead of overwriting existing bottles.

### 3. Test Fixture - conftest.py

**Lines 28-64** - Created matching fixture bottle:
```python
# Create a Weller bottle for duplicate detection testing
# This bottle should match bourbon_001.jpg extraction (Weller - THE ORIGINAL WHEATED BOURBON)
weller_bottle_dir = test_vault_path / "1_Whiskeys" / "Weller - THE ORIGINAL WHEATED BOURBON"
weller_bottle_dir.mkdir()

weller_md = weller_bottle_dir / "Weller - THE ORIGINAL WHEATED BOURBON.md"
weller_md.write_text("""---
fileClass: Whiskey
Name: Weller - THE ORIGINAL WHEATED BOURBON
Distiller: Weller
WhiskeyName: THE ORIGINAL WHEATED BOURBON
...
""")
```

**Result**: Tests now have a bottle that actually matches the extraction, triggering duplicate detection.

## Test Results

All 4 duplicate detection tests now passing:

```
test_duplicate_skip PASSED                                [✅]
test_duplicate_save_as_new PASSED                         [✅]
test_duplicate_replace_existing PASSED                    [✅]
test_duplicate_detection_triggers_correctly PASSED        [✅]

4 passed in 337.92s (0:05:37)
```

## How Duplicate Detection Works Now

### First Save Attempt
1. User uploads bourbon_001.jpg → extracts as "Weller - THE ORIGINAL WHEATED BOURBON"
2. User clicks "Save"
3. `duplicateAction` is `null` → `force_save=false`
4. Backend checks for duplicates → finds existing "Weller - THE ORIGINAL WHEATED BOURBON"
5. Backend returns `{"status": "duplicate_found", "duplicates": [...]}`
6. Frontend sets `showDuplicateDialog = true` → dialog appears

### User Chooses Action

**Skip:**
- `handleDuplicateResolution('skip')`
- Dialog closes, no save

**Save as New:**
- `handleDuplicateResolution('new')`
- Sets `force_save=true`
- Backend adds " (2)" suffix if folder exists
- Creates "Weller - THE ORIGINAL WHEATED BOURBON (2)"

**Replace:**
- `handleDuplicateResolution('replace', vault_path)`
- Sets `replace_vault_path`
- Backend moves old folder contents to new location
- Preserves existing tasting notes

## Alpine.js Testing Pattern Used

Access Alpine component directly via `_x_dataStack`:
```javascript
const uploadForm = document.querySelector('[x-data="uploadForm()"]');
const editor = uploadForm._x_dataStack[0].bottleEditor;

// Call methods directly
editor.handleDuplicateResolution('skip');

// Check state
if (editor.showDuplicateDialog === true) {
    // Dialog is visible
}
```

This pattern avoids Playwright button click issues with Alpine.js `@click` handlers.

## Files Modified

1. `src/reserve_automation/web/static/js/components/bottle-editor-modal.js`
2. `src/reserve_automation/web/routes/bottles/save.py`
3. `tests/e2e/conftest.py`
4. `tests/e2e/test_duplicate_detection.py`
5. `tests/e2e/TEST_STATUS_REPORT.md`
