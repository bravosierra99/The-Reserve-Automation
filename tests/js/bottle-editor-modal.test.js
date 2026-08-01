/**
 * Unit tests for the unified bottle editor modal
 * (src/reserve_automation/web/static/js/components/bottle-editor-modal.js).
 *
 * The component is a whole-factory window attachment
 * (window.bottleEditorModal()) used by BOTH the management page and the
 * upload page — the ONE-PATH mandate lives here, so mode-dependent behavior
 * (endpoints, payloads, navigation) is what these tests pin down.
 *
 * API fixtures are NOT hand-written: they are contract fixtures — real
 * responses captured and snapshot-verified by
 * tests/contract/test_bottles_contract.py (see tests/contract/contract.py).
 * Bottles handed to openManagement come from the real
 * GET /api/v1/bottles/collection payload (that is exactly what the grid
 * passes in), so real nulls, list-typed variety and numeric age_statement
 * flow through the component. Hand-written fixtures remain ONLY for:
 *   - extraction-shaped upload bottles (extraction requires LM Studio),
 *   - enrichment/verify + task-status responses (background LLM tasks),
 *   - label search/crop responses (LLM web search + image ops),
 *   - error responses.
 *
 * window.cropperManager is mocked wholesale: Cropper.js lifecycle is
 * unit-tested in tests/js/cropper-manager.test.js; here we only assert the
 * modal drives it with the right endpoints and payloads.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
// base-page.js provides window.modalScrollLock (shared body-scroll lock)
import '../../src/reserve_automation/web/static/js/components/base-page.js';
import '../../src/reserve_automation/web/static/js/components/bottle-editor-modal.js';

// Fresh clones of real collection bottles (management mode receives exactly
// these objects from the grid).
function collectionBottle(id) {
    return loadContract('bottles_collection').bottles.find(b => b.id === id);
}
const whiskeyBottle = () => collectionBottle('1'); // Buffalo Trace - Eagle Rare 10 Year (has notes)
const wineBottle = () => collectionBottle('3');    // Caymus - Special Selection Cabernet

const WHISKEY_NOTES = 'Great in an Old Fashioned; decant 10 min';

// HAND-WRITTEN (labeled): what the upload page hands the modal — extraction
// output, which cannot be contract-captured without LM Studio. Field set
// mirrors tests/contract/test_bottles_contract.py NEAR_DUPLICATE_BOTTLE,
// which is also the payload that produced the duplicate fixtures below.
const UPLOAD_BOTTLE = {
    type: 'whiskey',
    producer: 'Buffalo Trace',
    name: 'Eagle Rare 10',
    year: 2018,
    beverage_type: 'Bourbon',
    region: 'Kentucky',
    proof: null,
    price: null,
    source: 'image',
    confidence: 0.85,
};

/** Build a fetch Response-like object. */
function jsonResponse(data, { ok = true, status = 200, contentType = 'application/json' } = {}) {
    return {
        ok,
        status,
        statusText: `HTTP ${status}`,
        json: async () => data,
        text: async () => JSON.stringify(data),
        headers: { get: (name) => (name.toLowerCase() === 'content-type' ? contentType : null) },
    };
}

/** Fresh modal instance with fetch defaulting to benign empty responses. */
function freshModal() {
    return window.bottleEditorModal();
}

/** Route fetch calls by URL substring; unmatched URLs get an empty 200. */
function routeFetch(routes) {
    return vi.fn(async (url, opts) => {
        for (const [needle, responder] of routes) {
            if (String(url).includes(needle)) {
                return typeof responder === 'function' ? responder(url, opts) : responder;
            }
        }
        return jsonResponse({});
    });
}

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([]));
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('location', { href: '', reload: vi.fn() });
    window.cropperManager = {
        initializeCropper: vi.fn(async () => ({ mock: 'cropper' })),
        completeCrop: vi.fn(async () => ({})),
        destroyCropper: vi.fn(),
        getCropData: vi.fn(() => ({ x: 0, y: 0, width: 10, height: 10 })),
    };
    sessionStorage.clear();
    document.body.innerHTML = '';
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
    document.body.style.overflow = '';
});

// ---------------------------------------------------------------------------
// Opening the modal
// ---------------------------------------------------------------------------

describe('openManagement', () => {
    it('enters management mode with a copy of the bottle and loads the tasting summary (contract data)', async () => {
        const m = freshModal();
        const bottle = whiskeyBottle();
        global.fetch = routeFetch([
            ['/api/v1/bottles/tastings-summary', jsonResponse(loadContract('bottles_tastings_summary'))],
        ]);

        await m.openManagement(bottle);

        expect(m.mode).toBe('management');
        expect(m.readOnly).toBe(false);
        expect(m.isOpen).toBe(true);
        expect(m.bottleId).toBe('1');
        expect(m.uploadId).toBeNull();
        expect(m.manifestContext).toBeNull();
        expect(m.tastingSummary).toEqual({
            tasting_count: 2,
            avg_score: 7.5,
            latest_date: '2026-07-04',
            tasters: ['Ben', 'Sarah'],
            max_score: 10,
        });
        // Copy, not a reference — edits must not mutate the grid's object
        expect(m.bottle).not.toBe(bottle);
        expect(m.bottle).toEqual(bottle);
    });

    it('honors readOnly for non-admin users', async () => {
        const m = freshModal();
        await m.openManagement(wineBottle(), true);
        expect(m.readOnly).toBe(true);
    });
});

describe('openUpload', () => {
    it('enters upload mode and auto-checks duplicates without blocking open', async () => {
        const m = freshModal();
        const noDupes = loadContract('bottles_check_duplicates_response');
        noDupes.duplicates = [];
        noDupes.count = 0;
        global.fetch = routeFetch([
            ['/api/v1/bottles/check-duplicates', jsonResponse(noDupes)],
        ]);

        await m.openUpload(UPLOAD_BOTTLE, 'up-123');
        // Let the fire-and-forget duplicate check settle
        await vi.waitFor(() => expect(m.saving).toBe(false));

        expect(m.mode).toBe('upload');
        expect(m.uploadId).toBe('up-123');
        expect(m.bottleId).toBeNull();
        expect(m.isOpen).toBe(true);
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/v1/bottles/check-duplicates',
            expect.objectContaining({ method: 'POST' })
        );
    });

    it('pre-loads an enrichment result when the manifest panel provides one', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/api/v1/bottles/check-duplicates', jsonResponse({ duplicates: [] })],
        ]);
        // HAND-WRITTEN (labeled): enrichment results come from the LLM
        // verify task, which cannot run without LM Studio.
        const enrich = { changes: { region: { old: '', new: 'Kentucky' } } };

        await m.openUpload(UPLOAD_BOTTLE, 'up-123', null, enrich);
        await vi.waitFor(() => expect(m.saving).toBe(false));

        expect(m.searchResult).toBe(enrich);
        expect(m.hasChanges).toBe(true);
    });

    it('pre-selects save_new when the auto duplicate check finds matches (contract data)', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/api/v1/bottles/check-duplicates',
                jsonResponse(loadContract('bottles_check_duplicates_response'))],
        ]);

        await m.openUpload(UPLOAD_BOTTLE, 'up-123');
        await vi.waitFor(() => expect(m.duplicates.length).toBe(1));

        expect(m.duplicateAction).toBe('save_new');
        // The duplicate card renders these fields (id, confidence, reason)
        expect(m.duplicates[0].id).toBe('1');
        expect(m.duplicates[0].confidence).toBe(0.93);
        expect(m.duplicates[0].reason).toContain('Same producer');
    });
});

describe('initializeEditableBottle', () => {
    it('exposes wine-specific fields for wine bottles (contract data)', () => {
        const m = freshModal();
        m.bottle = wineBottle();
        m.initializeEditableBottle();

        expect(m.editableBottle.country).toBe('USA');
        // The real API sends variety as a LIST — it flows into the editable
        // form state unchanged (the text input renders it comma-joined).
        expect(m.editableBottle.variety).toEqual(['Cabernet Sauvignon', 'Merlot']);
        expect(m.editableBottle).not.toHaveProperty('proof');
        expect(m.editableBottle).not.toHaveProperty('mash_bill');
    });

    it('exposes whiskey-specific fields for non-wine bottles (contract data)', () => {
        const m = freshModal();
        m.bottle = whiskeyBottle();
        m.initializeEditableBottle();

        expect(m.editableBottle.proof).toBe(90.0);
        // age_statement is numeric in the real API (years), not a string
        expect(m.editableBottle.age_statement).toBe(10);
        expect(m.editableBottle.barrel_type).toBe('New Charred Oak');
        expect(m.editableBottle).not.toHaveProperty('country');
        expect(m.editableBottle).not.toHaveProperty('vineyard');
    });

    it('maps real API nulls to empty strings so inputs bind cleanly (contract minimal bottle)', () => {
        const m = freshModal();
        m.bottle = collectionBottle('2'); // Willett — every optional field null
        m.initializeEditableBottle();

        expect(m.editableBottle.year).toBe('');
        expect(m.editableBottle.price).toBe('');
        expect(m.editableBottle.proof).toBe('');
        expect(m.editableBottle.region).toBe('');
    });

    it('defaults missing fields to empty strings so inputs bind cleanly', () => {
        // Synthetic edge case: a bottle object with no fields at all.
        const m = freshModal();
        m.bottle = { type: 'whiskey' };
        m.initializeEditableBottle();

        expect(m.editableBottle.producer).toBe('');
        expect(m.editableBottle.price).toBe('');
        expect(m.editableBottle.proof).toBe('');
    });
});

describe('close', () => {
    it('closes immediately and clears bottle state after the animation delay', async () => {
        vi.useFakeTimers();
        const m = freshModal();
        m.bottle = wineBottle();
        m.bottleId = '3';
        m.isOpen = true;
        m.mode = 'management';

        m.close();
        expect(m.isOpen).toBe(false);
        expect(m.bottle).not.toBeNull(); // still set during animation

        vi.advanceTimersByTime(300);
        expect(m.bottle).toBeNull();
        expect(m.bottleId).toBeNull();
        expect(m.mode).toBeNull();
        expect(m.editableBottle).toEqual({});
    });

    it('destroys any live cropper instances on close', () => {
        const m = freshModal();
        m.cropperInstance = { mock: 'cropper' };
        m.close();
        expect(window.cropperManager.destroyCropper).toHaveBeenCalledWith({ mock: 'cropper' });
        expect(m.cropperInstance).toBeNull();
        expect(m.manualCropActive).toBe(false);
    });
});

describe('body scroll lock', () => {
    // Without the lock, iOS Safari chains modal touch-scrolls to the page body:
    // the modal rebounds and the page behind scrolls, hiding the Save footer.
    it('locks page scroll on openManagement and releases it on close', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/api/v1/bottles/tastings-summary', jsonResponse(loadContract('bottles_tastings_summary'))],
        ]);

        await m.openManagement(wineBottle());
        expect(document.body.style.overflow).toBe('hidden');

        m.close();
        expect(document.body.style.overflow).toBe('');
    });

    it('locks page scroll on openUpload and releases it on close', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/api/v1/bottles/check-duplicates', jsonResponse({ duplicates: [] })],
        ]);

        await m.openUpload(UPLOAD_BOTTLE, 'up-123');
        expect(document.body.style.overflow).toBe('hidden');

        m.close();
        expect(document.body.style.overflow).toBe('');
    });
});

describe('startTasting', () => {
    it('stashes a preselect payload and navigates to the manual tasting page', () => {
        const m = freshModal();
        m.bottle = wineBottle();
        m.savedBottleId = loadContract('bottles_save_response').id;

        m.startTasting();

        const preselect = JSON.parse(sessionStorage.getItem('preselect_bottle'));
        expect(preselect.bottle_path).toBe('5');
        expect(preselect.bottle_name).toBe('Caymus Vineyards - Special Selection Cabernet');
        expect(preselect.beverage_type).toBe('wine');
        expect(location.href).toBe('/manual-tasting');
    });

    it('does nothing without a saved bottle id', () => {
        const m = freshModal();
        m.bottle = wineBottle();
        m.savedBottleId = null;
        m.startTasting();
        expect(sessionStorage.getItem('preselect_bottle')).toBeNull();
        expect(location.href).toBe('');
    });
});

// ---------------------------------------------------------------------------
// Saving — management mode
// ---------------------------------------------------------------------------

describe('saveManagement', () => {
    it('POSTs edited fields in `updates` — the only key the route persists', async () => {
        // Regression: the modal used to send edits only inside `bottle` (plus a
        // `changes` key the route never read), so every management-mode edit
        // was silently discarded while the UI showed a success toast.
        const m = freshModal();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/update-fields', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse(loadContract('bottles_update_fields_response'));
            }],
        ]);
        m.mode = 'management';
        m.bottle = whiskeyBottle();
        m.initializeEditableBottle();
        m.editableBottle.price = '';
        m.editableBottle.year = '';
        m.editableBottle.barrel_type = 'Toasted Oak';

        await m.save(); // dispatches to saveManagement

        expect(sentBody.updates.barrel_type).toBe('Toasted Oak');
        expect(sentBody.updates.price).toBe('');   // server-side clean_bottle_data nulls these
        expect(sentBody.bottle.id).toBe('1');      // identity for the lookup
        expect(sentBody.bottle.price).toBeNull();
        expect(sentBody.bottle.year).toBeNull();
        // Notes are owned by saveNotes(), never by the field editor —
        // the contract bottle HAS notes, and they must not appear in updates
        expect(sentBody.bottle.notes).toBe(WHISKEY_NOTES);
        expect(sentBody.updates.notes).toBeUndefined();
        expect(m.saveSuccess).toBe(true);
        expect(m.saving).toBe(false);
    });

    it('reloads the page after the success delay so the grid refreshes', async () => {
        vi.useFakeTimers();
        const m = freshModal();
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/update-fields',
                jsonResponse(loadContract('bottles_update_fields_response'))],
        ]);
        m.mode = 'management';
        m.bottle = whiskeyBottle();
        m.initializeEditableBottle();

        await m.saveManagement();
        await vi.advanceTimersByTimeAsync(800);

        expect(m.isOpen).toBe(false);
        expect(location.reload).toHaveBeenCalled();
    });

    it('keeps the modal open and reports the error on failure', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/update-fields', jsonResponse({}, { ok: false, status: 500 })],
        ]);
        m.mode = 'management';
        m.bottle = whiskeyBottle();
        m.isOpen = true;
        m.initializeEditableBottle();

        await m.saveManagement();

        expect(m.saveSuccess).toBe(false);
        expect(m.saving).toBe(false);
        expect(m.isOpen).toBe(true);
        expect(location.reload).not.toHaveBeenCalled();
        // Error surfaced as a toast, not swallowed
        expect(document.body.textContent).toContain('Save failed');
    });
});

// ---------------------------------------------------------------------------
// Shared bottle notes
// ---------------------------------------------------------------------------

describe('bottle notes', () => {
    it('initializes the draft from the bottle on openManagement and loads notes permission (contract data)', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/api/v1/me', jsonResponse(loadContract('me'))],
        ]);

        // The contract whiskey bottle carries real shared notes
        await m.openManagement(whiskeyBottle(), true);
        await vi.waitFor(() => expect(m.canEditNotes).toBe(true));

        expect(m.notesDraft).toBe(WHISKEY_NOTES);
    });

    it('initializes an empty draft when the bottle has no notes (contract null)', async () => {
        const m = freshModal();
        await m.openManagement(wineBottle());
        expect(m.notesDraft).toBe('');
    });

    it('saveNotes PUTs to the notes endpoint and syncs modal + grid copies (contract data)', async () => {
        const m = freshModal();
        const gridBottle = whiskeyBottle();
        gridBottle.notes = null; // grid copy is stale — no notes yet
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/bottles/1/notes', (url, opts) => {
                expect(opts.method).toBe('PUT');
                sentBody = JSON.parse(opts.body);
                return jsonResponse(loadContract('bottles_notes_response'));
            }],
        ]);
        await m.openManagement(gridBottle);
        m.notesDraft = WHISKEY_NOTES;

        await m.saveNotes();

        expect(sentBody).toEqual({ notes: WHISKEY_NOTES });
        expect(m.bottle.notes).toBe(WHISKEY_NOTES);
        // Grid's object updated in place so reopening shows fresh notes
        expect(gridBottle.notes).toBe(WHISKEY_NOTES);
        expect(m.notesSaving).toBe(false);
        expect(document.body.textContent).toContain('Notes saved');
    });

    it('saveNotes surfaces failures as a toast and keeps the draft', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/notes', jsonResponse({}, { ok: false, status: 500 })],
        ]);
        await m.openManagement(whiskeyBottle());
        m.notesDraft = 'unsaved text';

        await m.saveNotes();

        expect(m.notesDraft).toBe('unsaved text');
        expect(m.notesSaving).toBe(false);
        expect(document.body.textContent).toContain('Notes save failed');
    });

    it('saveNotes is a no-op without a bottleId (upload mode)', async () => {
        const m = freshModal();
        m.bottleId = null;
        await m.saveNotes();
        expect(global.fetch).not.toHaveBeenCalled();
    });

    it('close() clears the draft and grid reference', async () => {
        vi.useFakeTimers();
        const m = freshModal();
        m.notesDraft = 'stale';
        m._sourceBottle = { id: 'x' };
        m.close();
        await vi.advanceTimersByTimeAsync(300);
        expect(m.notesDraft).toBe('');
        expect(m._sourceBottle).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// Saving — upload mode + duplicate detection
// ---------------------------------------------------------------------------

describe('saveUpload', () => {
    function uploadModal(bottle = UPLOAD_BOTTLE) {
        const m = freshModal();
        m.mode = 'upload';
        m.bottle = { ...bottle };
        m.uploadId = 'up-1';
        m.initializeEditableBottle();
        return m;
    }

    it('saves and exposes post-save actions for a single-bottle upload (contract response)', async () => {
        const m = uploadModal();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse(loadContract('bottles_save_response'));
            }],
        ]);

        await m.saveUpload();

        expect(sentBody.upload_id).toBe('up-1');
        expect(sentBody.force_save).toBe(false);
        expect(sentBody.replace_bottle_id).toBeNull();
        // Real API returns status "success" and a stringified integer id
        expect(m.savedBottleId).toBe('5');
        expect(m.saving).toBe(false);
    });

    it('folds the notes draft into the create payload (trimmed, empty → null)', async () => {
        const m = uploadModal();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse(loadContract('bottles_save_response'));
            }],
        ]);
        m.notesDraft = '  drink on hot days  ';

        await m.saveUpload();
        expect(sentBody.bottle.notes).toBe('drink on hot days');

        m.notesDraft = '   ';
        await m.saveUpload();
        expect(sentBody.bottle.notes).toBeNull();
    });

    it('shows the duplicate dialog with save_new pre-selected when the backend flags duplicates (contract response)', async () => {
        const m = uploadModal();
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', jsonResponse(loadContract('bottles_save_duplicate_response'))],
        ]);

        await m.saveUpload();

        expect(m.showDuplicateDialog).toBe(true);
        expect(m.duplicates).toHaveLength(1);
        expect(m.duplicates[0]).toMatchObject({
            id: '1', producer: 'Buffalo Trace', confidence: 0.93,
        });
        expect(m.duplicateAction).toBe('save_new');
        expect(m.saving).toBe(false);
        expect(m.savedBottleId).toBeNull();
    });

    it('sends force_save when the user chose "save as new"', async () => {
        const m = uploadModal();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse(loadContract('bottles_save_response'));
            }],
        ]);
        m.duplicates = loadContract('bottles_save_duplicate_response').duplicates;
        m.duplicateAction = 'save_new';

        await m.saveUpload();
        expect(sentBody.force_save).toBe(true);
        expect(sentBody.replace_bottle_id).toBeNull();
    });

    it('sends replace_bottle_id when the user chose "replace"', async () => {
        const m = uploadModal();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse({ ...loadContract('bottles_save_response'), id: '1' });
            }],
        ]);
        m.duplicates = loadContract('bottles_save_duplicate_response').duplicates;
        m.duplicateAction = 'replace';
        m.selectedDuplicate = '1';

        await m.saveUpload();
        expect(sentBody.force_save).toBe(false);
        expect(sentBody.replace_bottle_id).toBe('1');
    });

    it('skip with duplicates closes without saving and fires the skip callback', async () => {
        const m = uploadModal();
        const onSkip = vi.fn();
        m.duplicates = loadContract('bottles_save_duplicate_response').duplicates;
        m.duplicateAction = 'skip';
        m._onSkipCallback = onSkip;
        m.isOpen = true;

        await m.saveUpload();

        expect(onSkip).toHaveBeenCalled();
        expect(m.isOpen).toBe(false);
        expect(global.fetch).not.toHaveBeenCalledWith('/api/v1/bottles/save', expect.anything());
    });

    it('refuses to save a bottle without a type field', async () => {
        const m = uploadModal({ ...UPLOAD_BOTTLE, type: undefined });
        await m.saveUpload();
        expect(document.body.textContent).toContain('Missing bottle type');
        expect(m.saving).toBe(false);
    });

    it('fires the save callback instead of showing post-save actions (manifest panel)', async () => {
        const m = uploadModal();
        const onSave = vi.fn();
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', jsonResponse(loadContract('bottles_save_response'))],
        ]);
        m._onSaveCallback = onSave;

        await m.saveUpload();

        expect(onSave).toHaveBeenCalledWith(m.bottle);
        expect(m._onSaveCallback).toBeNull();
        expect(m.savedBottleId).toBeNull();
    });

    it('advances to the next manifest bottle after saving in manifest mode', async () => {
        const m = uploadModal();
        const noDupes = loadContract('bottles_check_duplicates_response');
        noDupes.duplicates = [];
        noDupes.count = 0;
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', jsonResponse(loadContract('bottles_save_response'))],
            ['/api/v1/bottles/check-duplicates', jsonResponse(noDupes)],
        ]);
        const second = { ...UPLOAD_BOTTLE, name: 'Second' };
        m.manifestContext = { bottles: [{ ...UPLOAD_BOTTLE }, second], currentIndex: 0 };

        await m.saveUpload();

        expect(m.manifestContext.currentIndex).toBe(1);
        expect(m.bottle.name).toBe('Second');
    });

    it('surfaces the backend error message on save failure', async () => {
        const m = uploadModal();
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', jsonResponse({ error: 'vault exploded' }, { ok: false, status: 500 })],
        ]);

        await m.saveUpload();

        expect(document.body.textContent).toContain('vault exploded');
        expect(m.saving).toBe(false);
    });
});

describe('handleDuplicateResolution', () => {
    function dialogModal() {
        const m = freshModal();
        m.mode = 'upload';
        m.bottle = { ...UPLOAD_BOTTLE };
        m.uploadId = 'up-1';
        m.initializeEditableBottle();
        m.duplicates = loadContract('bottles_save_duplicate_response').duplicates;
        m.showDuplicateDialog = true;
        m.isOpen = true;
        return m;
    }

    it('skip closes the dialog and the modal without saving', async () => {
        const m = dialogModal();
        await m.handleDuplicateResolution('skip');
        expect(m.showDuplicateDialog).toBe(false);
        expect(m.isOpen).toBe(false);
        expect(global.fetch).not.toHaveBeenCalled();
    });

    it('"new" saves with force_save and closes', async () => {
        const m = dialogModal();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse(loadContract('bottles_save_response'));
            }],
        ]);

        await m.handleDuplicateResolution('new');

        expect(sentBody.force_save).toBe(true);
        expect(sentBody.replace_bottle_id).toBeNull();
        expect(m.showDuplicateDialog).toBe(false);
        expect(m.isOpen).toBe(false);
    });

    it('"replace" saves with the chosen duplicate id', async () => {
        const m = dialogModal();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse({ ...loadContract('bottles_save_response'), id: '1' });
            }],
        ]);

        await m.handleDuplicateResolution('replace', '1');

        expect(sentBody.force_save).toBe(false);
        expect(sentBody.replace_bottle_id).toBe('1');
    });

    it('keeps the dialog open and alerts on save failure', async () => {
        const m = dialogModal();
        global.fetch = routeFetch([
            ['/api/v1/bottles/save', jsonResponse({ error: 'nope' }, { ok: false, status: 500 })],
        ]);

        await m.handleDuplicateResolution('new');

        expect(alert).toHaveBeenCalledWith(expect.stringContaining('nope'));
        expect(m.saving).toBe(false);
    });
});

describe('manualCheckDuplicates', () => {
    it('stores duplicates inline and pre-selects the safe default (contract data)', async () => {
        const m = freshModal();
        m.bottle = { ...UPLOAD_BOTTLE };
        m.initializeEditableBottle();
        global.fetch = routeFetch([
            ['/api/v1/bottles/check-duplicates',
                jsonResponse(loadContract('bottles_check_duplicates_response'))],
        ]);

        await m.manualCheckDuplicates();

        expect(m.duplicates).toEqual(loadContract('bottles_check_duplicates_response').duplicates);
        expect(m.duplicateAction).toBe('save_new');
        expect(m.showDuplicateDialog).toBe(false); // inline panel, not dialog
    });

    it('clears duplicates when the check fails rather than showing stale results', async () => {
        const m = freshModal();
        m.bottle = { ...UPLOAD_BOTTLE };
        m.initializeEditableBottle();
        m.duplicates = loadContract('bottles_check_duplicates_response').duplicates;
        global.fetch = routeFetch([
            ['/api/v1/bottles/check-duplicates', jsonResponse({}, { ok: false, status: 500 })],
        ]);

        await m.manualCheckDuplicates();
        expect(m.duplicates).toEqual([]);
    });
});

describe('manualMatchSearch', () => {
    it('searches the whole collection and surfaces same-type bottles first (contract data)', async () => {
        const m = freshModal();
        m.bottle = { ...UPLOAD_BOTTLE };   // whiskey
        global.fetch = routeFetch([
            // Real response order is by producer: Cloudy Bay (wine) first,
            // Willett (whiskey) second — the modal must re-sort by type.
            ['/api/v1/management/bottles/search',
                jsonResponse(loadContract('bottles_management_search'))],
        ]);
        m.manualMatchQuery = 'reserve';

        await m.manualMatchSearch();

        expect(m.manualMatchResults[0].type).toBe('whiskey');
        expect(m.manualMatchResults[0].producer).toBe('Willett');
        expect(m.manualMatchResults).toHaveLength(2); // keeps all — explicit override
        expect(m.manualMatchSearching).toBe(false);
    });

    it('clears results for a blank query without hitting the API', async () => {
        const m = freshModal();
        m.manualMatchQuery = '   ';
        m.manualMatchResults = [{ id: 'stale' }];

        await m.manualMatchSearch();

        expect(m.manualMatchResults).toEqual([]);
        expect(global.fetch).not.toHaveBeenCalled();
    });

    it('URL-encodes the query', async () => {
        const m = freshModal();
        m.bottle = { ...UPLOAD_BOTTLE };
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/search', jsonResponse({ bottles: [] })],
        ]);
        m.manualMatchQuery = 'pappy & co';

        await m.manualMatchSearch();

        expect(global.fetch).toHaveBeenCalledWith(
            '/api/v1/management/bottles/search?q=pappy%20%26%20co'
        );
    });

    it('empties results on search failure', async () => {
        const m = freshModal();
        m.bottle = { ...UPLOAD_BOTTLE };
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/search', jsonResponse({}, { ok: false, status: 500 })],
        ]);
        m.manualMatchQuery = 'x';
        m.manualMatchResults = [{ id: 'stale' }];

        await m.manualMatchSearch();
        expect(m.manualMatchResults).toEqual([]);
        expect(m.manualMatchSearching).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// Manifest navigation
// ---------------------------------------------------------------------------

describe('manifest navigation', () => {
    function manifestModal() {
        const m = freshModal();
        m.mode = 'upload';
        m.uploadId = 'up-1';
        m.bottle = { ...UPLOAD_BOTTLE };
        m.manifestContext = {
            bottles: [
                { ...UPLOAD_BOTTLE, name: 'First' },
                { ...UPLOAD_BOTTLE, type: 'wine', name: 'Second' },
            ],
            currentIndex: 0,
        };
        global.fetch = routeFetch([
            ['/api/v1/bottles/check-duplicates', jsonResponse({ duplicates: [] })],
        ]);
        return m;
    }

    it('nextBottle opens the following manifest bottle', async () => {
        const m = manifestModal();
        await m.nextBottle();
        expect(m.manifestContext.currentIndex).toBe(1);
        expect(m.bottle.name).toBe('Second');
        expect(m.mode).toBe('upload');
    });

    it('nextBottle on the last bottle closes the modal', async () => {
        const m = manifestModal();
        m.manifestContext.currentIndex = 1;
        m.isOpen = true;
        await m.nextBottle();
        expect(m.isOpen).toBe(false);
    });

    it('previousBottle steps back and stops at the first bottle', async () => {
        const m = manifestModal();
        m.manifestContext.currentIndex = 1;
        await m.previousBottle();
        expect(m.manifestContext.currentIndex).toBe(0);
        expect(m.bottle.name).toBe('First');

        await m.previousBottle(); // already at 0 — no-op
        expect(m.manifestContext.currentIndex).toBe(0);
    });

    it('skipBottle without a manifest just closes', async () => {
        const m = freshModal();
        m.manifestContext = null;
        m.isOpen = true;
        await m.skipBottle();
        expect(m.isOpen).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// Enrichment / verification
//
// HAND-WRITTEN fixtures (labeled): /api/v1/management/bottles/verify runs a
// background LLM web-search task and /api/v1/management/tasks/{id}/status
// reports it — neither can be exercised without LM Studio, so these shapes
// cannot be contract-captured (see tests/contract/test_bottles_contract.py).
// ---------------------------------------------------------------------------

describe('enrichMetadata', () => {
    it('starts the async task, polls, and exposes changes', async () => {
        const m = freshModal();
        m.bottle = wineBottle();
        m.initializeEditableBottle();
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/verify', jsonResponse({ task_id: 't-1', status: 'queued' })],
        ]);
        m.pollTaskStatus = vi.fn(async () => ({
            status: 'complete',
            changes: { region: { old: 'Napa Valley', new: 'Rutherford' } },
            metadata: { verified: true },
        }));

        await m.enrichMetadata();

        expect(m.pollTaskStatus).toHaveBeenCalledWith('t-1');
        expect(m.hasChanges).toBe(true);
        expect(m.searchResult.changes.region.new).toBe('Rutherford');
        expect(m.verifying).toBe(false);
        expect(m.verifyingTaskId).toBeNull();
    });

    it('treats verified:false results as failures', async () => {
        const m = freshModal();
        m.bottle = wineBottle();
        m.initializeEditableBottle();
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/verify', jsonResponse({ task_id: 't-1', status: 'queued' })],
        ]);
        m.pollTaskStatus = vi.fn(async () => ({
            status: 'complete',
            metadata: { verified: false, error: 'no results found' },
        }));

        await m.enrichMetadata();

        expect(m.searchResult).toBeNull();
        expect(m.hasChanges).toBe(false);
        expect(document.body.textContent).toContain('no results found');
    });

    it('reports a failure to start verification', async () => {
        const m = freshModal();
        m.bottle = wineBottle();
        m.initializeEditableBottle();
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/verify', jsonResponse({ error: 'LLM offline' }, { ok: false, status: 503 })],
        ]);

        await m.enrichMetadata();

        expect(document.body.textContent).toContain('LLM offline');
        expect(m.verifying).toBe(false);
    });
});

describe('pollTaskStatus', () => {
    it('resolves as soon as the task completes', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/status', jsonResponse({ status: 'complete', changes: {} })],
        ]);
        const result = await m.pollTaskStatus('t-1');
        expect(result.status).toBe('complete');
    });

    it('polls through processing to completion, updating progress', async () => {
        vi.useFakeTimers();
        const m = freshModal();
        const statuses = [{ status: 'processing' }, { status: 'complete', changes: {} }];
        global.fetch = vi.fn(async () => jsonResponse(statuses.shift()));

        const promise = m.pollTaskStatus('t-1');
        await vi.advanceTimersByTimeAsync(2000);
        const result = await promise;

        expect(result.status).toBe('complete');
        expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    it('rejects when the task reports failure', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/status', jsonResponse({ status: 'failed', error: 'search blew up' })],
        ]);
        // 'failed' throws, then the retry logic retries up to 3 times before
        // propagating — drain those retries with fake timers.
        vi.useFakeTimers();
        const promise = m.pollTaskStatus('t-1');
        promise.catch(() => {}); // avoid unhandled rejection while timers advance
        await vi.advanceTimersByTimeAsync(3 * 2000);
        await expect(promise).rejects.toThrow('search blew up');
    });

    it('surfaces 404 as task-not-found after retries', async () => {
        vi.useFakeTimers();
        const m = freshModal();
        global.fetch = routeFetch([
            ['/status', jsonResponse({}, { ok: false, status: 404 })],
        ]);
        const promise = m.pollTaskStatus('t-missing');
        promise.catch(() => {});
        await vi.advanceTimersByTimeAsync(3 * 2000);
        await expect(promise).rejects.toThrow('Task not found');
    });

    it('recovers from transient network errors', async () => {
        vi.useFakeTimers();
        const m = freshModal();
        let calls = 0;
        global.fetch = vi.fn(async () => {
            calls++;
            if (calls === 1) throw new Error('network down');
            return jsonResponse({ status: 'complete', changes: {} });
        });

        const promise = m.pollTaskStatus('t-1');
        await vi.advanceTimersByTimeAsync(2000);
        const result = await promise;
        expect(result.status).toBe('complete');
        expect(calls).toBe(2);
    });
});

describe('applying enrichment changes', () => {
    // HAND-WRITTEN searchResult (labeled): shape produced by the LLM verify
    // task — not contract-capturable without LM Studio.
    function enrichedModal() {
        const m = freshModal();
        m.bottle = wineBottle();
        m.initializeEditableBottle();
        m.searchResult = {
            changes: {
                region: { old: 'Napa Valley', new: 'Rutherford' },
                abv: { old: '', new: '13.5' },
            },
        };
        m.hasChanges = true;
        return m;
    }

    it('applySelectedChanges applies only approved fields', () => {
        const m = enrichedModal();
        m.approvedChanges = { region: true, abv: false };

        m.applySelectedChanges();

        expect(m.editableBottle.region).toBe('Rutherford');
        expect(m.editableBottle.abv).toBe(14.8); // not approved — keeps contract value
        expect(m.searchResult).toBeNull();
    });

    it('applyAllChanges applies every suggested field', () => {
        const m = enrichedModal();
        m.applyAllChanges();
        expect(m.editableBottle.region).toBe('Rutherford');
        expect(m.editableBottle.abv).toBe('13.5');
        expect(m.searchResult).toBeNull();
    });

    it('cancelChanges discards suggestions without touching the form', () => {
        const m = enrichedModal();
        m.cancelChanges();
        expect(m.editableBottle.region).toBe('Napa Valley');
        expect(m.searchResult).toBeNull();
        expect(m.hasChanges).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// Tastings panel (management mode)
// ---------------------------------------------------------------------------

describe('tastings panel', () => {
    it('loadTastingsList populates the list (contract data, newest first)', async () => {
        const m = freshModal();
        m.bottleId = '1';
        m.bottle = whiskeyBottle();
        global.fetch = routeFetch([
            ['/api/v1/bottles/tastings-list', jsonResponse(loadContract('bottles_tastings_list'))],
        ]);

        await m.loadTastingsList();

        expect(m.tastingsList).toHaveLength(2);
        // Sorted by date descending — the panel renders these exact fields
        expect(m.tastingsList[0]).toMatchObject({
            date: '2026-07-04', taster: 'Sarah', total_score: 6.5, max_score: 10,
        });
        expect(m.tastingsList[1]).toMatchObject({
            date: '2026-07-01', taster: 'Ben', total_score: 8.5,
        });
        expect(m.tastingsList[1].scores).toEqual({
            nose: 2.5, palate: 3.0, finish: 2.0, overall: 1.0,
        });
        expect(m.loadingTastings).toBe(false);
    });

    it('toggleTastingsList lazily loads tastings only when there are some to show', async () => {
        const m = freshModal();
        m.bottleId = '1';
        m.bottle = whiskeyBottle();
        m.tastingSummary = loadContract('bottles_tastings_summary'); // tasting_count 2
        global.fetch = routeFetch([
            ['/api/v1/bottles/tastings-list', jsonResponse(loadContract('bottles_tastings_list'))],
        ]);

        await m.toggleTastingsList();
        expect(m.showTastingsList).toBe(true);
        expect(m.tastingsList).toHaveLength(2);

        // Collapsing clears the detail selection
        m.selectedTasting = m.tastingsList[0];
        await m.toggleTastingsList();
        expect(m.showTastingsList).toBe(false);
        expect(m.selectedTasting).toBeNull();
    });

    it('toggleTastingsList skips the fetch when the bottle has no tastings', async () => {
        const m = freshModal();
        m.bottleId = '3';
        const summary = loadContract('bottles_tastings_summary');
        summary.tasting_count = 0;
        m.tastingSummary = summary;

        await m.toggleTastingsList();

        expect(m.showTastingsList).toBe(true);
        expect(global.fetch).not.toHaveBeenCalled();
    });

    it('selectTasting / closeTastingDetail manage the detail view', () => {
        const m = freshModal();
        const tasting = loadContract('bottles_tastings_list').tastings[0];
        m.selectTasting(tasting);
        expect(m.selectedTasting).toEqual(tasting);
        m.closeTastingDetail();
        expect(m.selectedTasting).toBeNull();
    });

    it('formatNotesAsHashtags formats real contract note arrays and tolerates junk', () => {
        const m = freshModal();
        const ben = loadContract('bottles_tastings_list').tastings[1];
        expect(m.formatNotesAsHashtags(ben.notes.palate)).toBe('#oak #brown_sugar');
        expect(m.formatNotesAsHashtags([])).toBe('');
        expect(m.formatNotesAsHashtags(null)).toBe('');
        expect(m.formatNotesAsHashtags('not-an-array')).toBe('');
    });
});

// ---------------------------------------------------------------------------
// Label operations
//
// HAND-WRITTEN response fixtures (labeled): search-labels runs an LLM web
// image search, and the crop/download/upload endpoints operate on real label
// image files — none can be contract-captured (see
// tests/contract/test_bottles_contract.py).
// ---------------------------------------------------------------------------

describe('label operations', () => {
    it('startManualCrop uses the label API in management mode and initializes the cropper', async () => {
        vi.useFakeTimers();
        const m = freshModal();
        m.mode = 'management';
        m.bottleId = '1';
        document.body.innerHTML = '<img id="manualCropImage" src="x.jpg">';

        m.startManualCrop();
        expect(m.manualCropActive).toBe(true);
        expect(m.manualCropImageSrc).toContain('/api/v1/labels/view?id=1');

        await vi.advanceTimersByTimeAsync(200);
        expect(window.cropperManager.initializeCropper).toHaveBeenCalled();
        expect(m.cropperInstance).toEqual({ mock: 'cropper' });
    });

    it('startManualCrop uses the temp-image path in upload mode', () => {
        const m = freshModal();
        m.mode = 'upload';
        m.uploadId = 'up-1';
        m.startManualCrop();
        expect(m.manualCropImageSrc).toContain('/api/v1/temp-images/up-1/label.jpg');
    });

    it('acceptManualCrop drives cropperManager with the mode-specific endpoint', async () => {
        const m = freshModal();
        m.mode = 'management';
        m.bottleId = '1';
        m.bottle = whiskeyBottle();
        m.cropperInstance = { mock: 'cropper' };

        await m.acceptManualCrop();

        expect(window.cropperManager.completeCrop).toHaveBeenCalledWith(
            { mock: 'cropper' },
            '/api/v1/management/labels/manual-crop',
            { bottle_id: '1' },
            expect.any(Function),
            expect.any(Function)
        );
        expect(m.labelActionInProgress).toBe(false);
    });

    it('acceptManualCrop targets the temp endpoint in upload mode', async () => {
        const m = freshModal();
        m.mode = 'upload';
        m.uploadId = 'up-1';
        m.bottle = { ...UPLOAD_BOTTLE };
        m.cropperInstance = { mock: 'cropper' };

        await m.acceptManualCrop();

        expect(window.cropperManager.completeCrop).toHaveBeenCalledWith(
            { mock: 'cropper' },
            '/api/v1/bottles/manual-crop-temp',
            { upload_id: 'up-1' },
            expect.any(Function),
            expect.any(Function)
        );
    });

    it('acceptManualCrop is a no-op without an active cropper', async () => {
        const m = freshModal();
        await m.acceptManualCrop();
        expect(window.cropperManager.completeCrop).not.toHaveBeenCalled();
    });

    it('cropExistingLabel in management mode exposes a preview for review', async () => {
        const m = freshModal();
        m.mode = 'management';
        m.bottleId = '1';
        global.fetch = routeFetch([
            ['/api/v1/management/labels/crop-current', jsonResponse({ status: 'ok' })],
        ]);

        await m.cropExistingLabel();

        expect(m.labelCropPreview).toContain('file=label_preview.jpg');
        expect(m.labelActionInProgress).toBe(false);
    });

    it('cropExistingLabel in upload mode exposes a preview for review (does NOT apply)', async () => {
        const m = freshModal();
        m.mode = 'upload';
        m.uploadId = 'up-1';
        const before = m.currentLabelTimestamp;
        let calledUrl = null;
        global.fetch = routeFetch([
            ['/api/v1/bottles/auto-crop-temp', (url, opts) => {
                calledUrl = url;
                expect(JSON.parse(opts.body)).toEqual({ upload_id: 'up-1' });
                return jsonResponse({ status: 'success', preview_filename: 'label_crop_preview.jpg' });
            }],
        ]);

        await m.cropExistingLabel();

        expect(calledUrl).toBe('/api/v1/bottles/auto-crop-temp');
        expect(m.labelCropPreview).toContain('/api/v1/temp-images/up-1/label_crop_preview.jpg');
        // The temp label itself must be untouched until acceptCropPreview.
        expect(m.currentLabelTimestamp).toBe(before);
    });

    it('acceptCropPreview in management mode commits the preview and clears it', async () => {
        const m = freshModal();
        m.mode = 'management';
        m.bottleId = '1';
        m.labelCropPreview = '/some/preview.jpg';
        let body = null;
        global.fetch = routeFetch([
            ['/api/v1/management/labels/accept-crop', (url, opts) => {
                body = JSON.parse(opts.body);
                return jsonResponse({ status: 'ok' });
            }],
        ]);

        await m.acceptCropPreview();

        expect(body).toEqual({ bottle_id: '1' });
        expect(m.labelCropPreview).toBeNull();
        expect(m.labelActionInProgress).toBe(false);
    });

    it('acceptCropPreview in upload mode commits the temp preview and refreshes the label', async () => {
        const m = freshModal();
        m.mode = 'upload';
        m.uploadId = 'up-1';
        m.labelCropPreview = '/api/v1/temp-images/up-1/label_crop_preview.jpg';
        let body = null;
        global.fetch = routeFetch([
            ['/api/v1/bottles/accept-crop-temp', (url, opts) => {
                body = JSON.parse(opts.body);
                return jsonResponse({ status: 'success' });
            }],
        ]);

        await m.acceptCropPreview();

        expect(body).toEqual({ upload_id: 'up-1' });
        expect(m.labelCropPreview).toBeNull();
        expect(m.labelActionInProgress).toBe(false);
    });

    it('cancelCropPreview just discards the preview', () => {
        const m = freshModal();
        m.labelCropPreview = '/some/preview.jpg';
        m.cancelCropPreview();
        expect(m.labelCropPreview).toBeNull();
    });

    it('searchForLabelReplacement stores candidate images', async () => {
        const m = freshModal();
        m.bottle = whiskeyBottle();
        global.fetch = routeFetch([
            // HAND-WRITTEN (labeled): LLM web image search response
            ['/api/v1/bottles/search-labels', jsonResponse({ images: [{ url: 'a.jpg' }, { url: 'b.jpg' }] })],
        ]);

        await m.searchForLabelReplacement();

        expect(m.labelSearchResults).toHaveLength(2);
        expect(m.labelActionInProgress).toBe(false);
    });

    it('searchForLabelReplacement alerts with the backend detail on failure', async () => {
        const m = freshModal();
        m.bottle = whiskeyBottle();
        global.fetch = routeFetch([
            ['/api/v1/bottles/search-labels', jsonResponse({ detail: 'search quota hit' }, { ok: false, status: 429 })],
        ]);

        await m.searchForLabelReplacement();

        expect(alert).toHaveBeenCalledWith(expect.stringContaining('search quota hit'));
        expect(m.labelSearchResults).toEqual([]);
    });

    it('uploadCustomLabel posts the file to the mode-specific endpoint and clears the input', async () => {
        const m = freshModal();
        m.mode = 'upload';
        m.uploadId = 'up-1';
        m.bottle = { ...UPLOAD_BOTTLE };
        let sentUrl = null;
        let sentForm = null;
        global.fetch = routeFetch([
            ['upload-custom-label', (url, opts) => {
                sentUrl = url;
                sentForm = opts.body;
                return jsonResponse({ status: 'ok' });
            }],
        ]);
        const file = new File(['fake'], 'label.jpg', { type: 'image/jpeg' });
        const event = { target: { files: [file], value: 'label.jpg' } };

        await m.uploadCustomLabel(event);

        expect(sentUrl).toBe('/api/v1/bottles/upload-custom-label');
        expect(sentForm.get('upload_id')).toBe('up-1');
        expect(sentForm.get('file')).toBe(file);
        expect(event.target.value).toBe('');
    });

    it('uploadCustomLabel does nothing when no file is chosen', async () => {
        const m = freshModal();
        await m.uploadCustomLabel({ target: { files: [] } });
        expect(global.fetch).not.toHaveBeenCalled();
    });

    it('useSelectedSearchImage downloads the image and clears search results', async () => {
        const m = freshModal();
        m.bottleId = '1';
        m.labelSearchResults = [{ url: 'a.jpg' }];
        global.fetch = routeFetch([
            ['/api/v1/management/labels/download-image', jsonResponse({ status: 'ok' })],
        ]);

        await m.useSelectedSearchImage('http://example.com/a.jpg');

        expect(m.labelDownloadedOriginal).toContain('file=label_download.jpg');
        expect(m.labelSearchResults).toEqual([]);
    });

    it('useDownloadedLabel commits and clears the downloaded state', async () => {
        const m = freshModal();
        m.bottleId = '1';
        m.labelDownloadedOriginal = '/x.jpg';
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/management/labels/use-downloaded', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse({ status: 'ok' });
            }],
        ]);

        await m.useDownloadedLabel(true);

        expect(sentBody).toEqual({ bottle_id: '1', use_cropped: true });
        expect(m.labelDownloadedOriginal).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// Autocomplete + misc helpers
// ---------------------------------------------------------------------------

describe('loadAutocomplete', () => {
    it('loads every field once and caches (contract data)', async () => {
        const m = freshModal();
        global.fetch = routeFetch([
            ['/api/v1/autocomplete/bottles/producer',
                jsonResponse(loadContract('autocomplete_bottles_producer'))],
            ['/api/v1/autocomplete/bottles/variety',
                // The API rejects `variety` (stored as a JSON list) — real 400
                jsonResponse(loadContract('autocomplete_bottles_variety_error'),
                    { ok: false, status: 400 })],
            ['/api/v1/autocomplete/bottles/', jsonResponse([])],
        ]);

        await m.loadAutocomplete();

        expect(m._acLoaded).toBe(true);
        expect(m.acData.producer).toEqual([
            'Buffalo Trace', 'Caymus Vineyards', 'Cloudy Bay', 'Heaven Hill', 'Willett',
        ]);
        const callCount = global.fetch.mock.calls.length;
        expect(callCount).toBe(Object.keys(m.acData).length);

        await m.loadAutocomplete(); // cached — no extra fetches
        expect(global.fetch.mock.calls.length).toBe(callCount);
    });

    it('degrades the API-rejected variety field to an empty list (contract 400)', async () => {
        // The modal requests /autocomplete/bottles/variety but the endpoint
        // supports only scalar columns — the real API answers 400 and the
        // modal's r.ok guard turns it into []. (Also note: the modal never
        // requests barrel_type, which the API DOES support.)
        const m = freshModal();
        global.fetch = routeFetch([
            ['/api/v1/autocomplete/bottles/variety',
                jsonResponse(loadContract('autocomplete_bottles_variety_error'),
                    { ok: false, status: 400 })],
            ['/api/v1/autocomplete/bottles/', jsonResponse([])],
        ]);

        await m.loadAutocomplete();

        expect(m.acData.variety).toEqual([]);
        expect(m._acLoaded).toBe(true);
    });

    it('degrades quietly when the autocomplete API fails', async () => {
        const m = freshModal();
        global.fetch = vi.fn(async () => { throw new Error('offline'); });
        await m.loadAutocomplete();
        expect(m._acLoaded).toBe(false);
        expect(m.acData.producer).toEqual([]);
    });
});

describe('getFieldLabel', () => {
    it('maps known fields to display labels and passes unknown ones through', () => {
        const m = freshModal();
        expect(m.getFieldLabel('producer')).toBe('Producer/Distiller');
        expect(m.getFieldLabel('mash_bill')).toBe('Mash Bill');
        expect(m.getFieldLabel('mystery_field')).toBe('mystery_field');
    });
});

describe('showToast', () => {
    it('appends a toast, then removes it after the display window', () => {
        vi.useFakeTimers();
        const m = freshModal();

        m.showToast('Saved!', 'success');
        const toast = document.body.querySelector('div');
        expect(toast.textContent).toBe('Saved!');
        expect(toast.className).toContain('bg-green-600');

        vi.advanceTimersByTime(3000 + 300 + 50);
        expect(document.body.querySelector('div')).toBeNull();
    });

    it('styles error toasts red', () => {
        const m = freshModal();
        m.showToast('Boom', 'error');
        expect(document.body.querySelector('div').className).toContain('bg-red-600');
    });
});
