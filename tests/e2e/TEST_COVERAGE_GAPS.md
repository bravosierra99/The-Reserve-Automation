# E2E Test Coverage Gaps

## Critical Missing Tests (Would Have Caught Real Bugs)

### 1. ⚠️ MANIFEST UPLOAD WORKFLOW - **COMPLETELY UNTESTED**
This is a major feature with zero E2E coverage!

**What's NOT tested:**
- [ ] Upload manifest (photo of multiple bottles)
- [ ] Verify multiple bottles extracted
- [ ] Next/Previous navigation between bottles
- [ ] Skip bottle functionality
- [ ] Edit each bottle individually
- [ ] Save some bottles, skip others
- [ ] Complete entire manifest workflow
- [ ] Purchase source applied to all bottles in manifest
- [ ] Inventory count applied to all bottles

**Risk:** Entire manifest feature could be broken and we wouldn't know

**Test to create:** `test_manifest_upload_full_workflow`

---

### 2. ⚠️ LABEL SEARCH AND DOWNLOAD - **COMPLETELY UNTESTED**
Modal has "Search Web" button - never tested!

**What's NOT tested:**
- [ ] Click "Search Web" button
- [ ] Verify search results appear
- [ ] Click on search result to download label
- [ ] Verify downloaded label appears
- [ ] Manual crop downloaded label
- [ ] Accept and use downloaded label
- [ ] Cancel downloaded label

**Risk:** 404 errors in label search endpoints, broken UI flow

**Test to create:** `test_label_search_and_download_workflow`

---

### 3. ⚠️ UPLOAD CUSTOM LABEL - **COMPLETELY UNTESTED**
"Upload Custom" button exists - never tested!

**What's NOT tested:**
- [ ] Click "Upload Custom" button
- [ ] Select custom image file
- [ ] Verify custom label replaces current label
- [ ] Manual crop custom label
- [ ] Save bottle with custom label

**Risk:** File upload broken, custom labels not saved

**Test to create:** `test_upload_custom_label_workflow`

---

### 4. ⚠️ METADATA CHANGE APPLICATION - **PARTIALLY TESTED**
We verify buttons exist, but never click them!

**What's NOT tested:**
- [ ] Click "Search for Updates"
- [ ] Verify suggested changes appear
- [ ] Check SOME checkboxes (not all)
- [ ] Click "Apply Selected Changes"
- [ ] Verify ONLY checked fields updated
- [ ] Click "Apply All Changes"
- [ ] Verify ALL fields updated
- [ ] Click "Cancel"
- [ ] Verify changes discarded

**Current test only verifies:**
- ✓ Search completes without error
- ✓ Buttons are visible

**Risk:** Buttons could do nothing, wrong fields could be applied

**Test to create:** `test_metadata_change_application_buttons`

---

### 5. ⚠️ DUPLICATE DETECTION - **COMPLETELY UNTESTED**
Core feature to prevent duplicate bottles - never tested!

**What's NOT tested:**
- [ ] Upload bottle that already exists in vault
- [ ] Verify duplicate dialog appears
- [ ] Choose "Save as New" → verify new bottle created
- [ ] Choose "Replace Existing" → verify old bottle replaced
- [ ] Choose "Skip" → verify no bottle created
- [ ] Multiple duplicates found → verify all shown

**Risk:** Duplicate bottles created, data loss on replace, skip not working

**Test to create:**
- `test_duplicate_detection_save_new`
- `test_duplicate_detection_replace`
- `test_duplicate_detection_skip`

---

### 6. ⚠️ PURCHASE INFO FORM - **COMPLETELY UNTESTED**
Upload page has purchase source and inventory fields - never tested!

**What's NOT tested:**
- [ ] Enter purchase source text
- [ ] Select inventory count (0-6 buttons)
- [ ] Upload bottle
- [ ] Verify purchase source saved to bottle
- [ ] Verify inventory count saved to bottle
- [ ] Manifest upload with purchase info
- [ ] Verify ALL bottles in manifest get same purchase info

**Risk:** Purchase info never saved, inventory count wrong

**Test to create:** `test_purchase_info_saved_to_bottle`

---

### 7. ⚠️ MANAGEMENT PAGE LABEL OPERATIONS - **PARTIALLY TESTED**
Management page has same label buttons, but we don't test them!

**What's NOT tested:**
- [ ] Open bottle from management grid
- [ ] Click Manual Crop (in management mode)
- [ ] Click Auto-Crop (in management mode)
- [ ] Click Search Web (in management mode)
- [ ] Upload Custom Label (in management mode)
- [ ] Verify label operations work in vault context

**Current test only verifies:**
- ✓ Management page loads
- ✓ Click bottle opens modal
- ✓ Save button works

**Risk:** Label operations broken in management mode, vault files corrupted

**Test to create:** `test_management_label_operations`

---

## Medium Priority Gaps

### 8. Error Handling Scenarios

**What's NOT tested:**
- [ ] Network failure during label search
- [ ] Invalid image file upload
- [ ] LLM extraction returns no bottles
- [ ] LLM extraction fails completely
- [ ] Vault write permission denied
- [ ] Temp directory full/not writable

**Test to create:** `test_error_scenarios`

---

### 9. Form Validation

**What's NOT tested:**
- [ ] Required field validation
- [ ] Field length limits (max 200 chars)
- [ ] Numeric field validation (ABV, proof, year)
- [ ] Empty string handling in all fields

**Test to create:** `test_form_validation`

---

### 10. Navigation and Modal State

**What's NOT tested:**
- [ ] Close modal with X button
- [ ] Close modal with ESC key
- [ ] Open modal, close, reopen → verify clean state
- [ ] Multiple bottles in succession without page refresh
- [ ] Browser back button behavior

**Test to create:** `test_modal_navigation_state`

---

## Summary by Feature

| Feature | Current Coverage | Missing Tests | Risk Level |
|---------|-----------------|---------------|------------|
| Single bottle upload | ✅ Good | Label operations | Medium |
| **Manifest upload** | ❌ **None** | **Everything** | **CRITICAL** |
| Manual crop | ✅ Good | Management mode | Medium |
| Auto-crop | ✅ Good | Management mode | Medium |
| Cancel crop | ✅ Good | - | Low |
| Metadata search | ⚠️ Partial | Apply/cancel buttons | High |
| **Label search/download** | ❌ **None** | **Everything** | **High** |
| **Upload custom label** | ❌ **None** | **Everything** | **High** |
| **Duplicate detection** | ❌ **None** | **Everything** | **CRITICAL** |
| **Purchase info form** | ❌ **None** | **Everything** | **High** |
| Save to vault | ✅ Good | - | Low |
| Management grid | ⚠️ Partial | Label operations | High |

---

## Test Count Summary

**Current E2E tests:** 8 browser tests
**Missing critical tests:** ~15-20 tests

**Coverage estimate:**
- Current: ~40% of user-facing functionality
- With missing tests: ~85% of user-facing functionality

---

## Recommended Priority Order

1. **HIGHEST PRIORITY:**
   - Manifest upload workflow (completely broken and we wouldn't know)
   - Duplicate detection (prevents data corruption)

2. **HIGH PRIORITY:**
   - Metadata change application buttons (user-reported they used to work)
   - Label search and download (major feature, untested)
   - Purchase info form (data loss risk)

3. **MEDIUM PRIORITY:**
   - Upload custom label
   - Management label operations
   - Error scenarios

4. **LOW PRIORITY:**
   - Form validation edge cases
   - Modal state management
   - Navigation edge cases
