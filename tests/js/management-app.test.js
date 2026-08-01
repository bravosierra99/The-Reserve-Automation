/**
 * Unit tests for the management page root component
 * (src/reserve_automation/web/static/js/management/management-app.js).
 *
 * The REAL dependency modules (tasting-review, event-create,
 * bottle-editor-modal) are imported so composition is tested for real —
 * managementApp() must merge their state and methods exactly like the page
 * does. Alpine itself is not loaded; the factory's return value is used
 * directly, which exercises the live getters (filteredTastings,
 * trComputedAvg, dcFilteredValues) the same way Alpine would.
 *
 * API fixtures are NOT hand-written: they are contract fixtures — real
 * responses captured and snapshot-verified by
 * tests/contract/test_management_contract.py (management_*) and
 * tests/contract/test_events_contract.py (events_list, me). Per-test variants
 * are explicit mutations of a fresh contract clone. The only hand-written
 * response shapes left are ones the contract flow cannot produce: FastAPI
 * error envelopes, the LLM-dependent bulk-search response, and LLM-produced
 * batch-verification result entries — each is labelled where it appears.
 *
 * Contract tasting rows (management_tastings, date desc): cocktail:1 (Ben,
 * 2026-07-05, 8/10 = 80%), bottle:2 wine (Sarah, 2026-07-03, 92.5/100),
 * bottle:1 whiskey (Ben, 2026-07-01, 8.5/10 = 85%).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
import '../../src/reserve_automation/web/static/js/components/bottle-editor-modal.js';
import '../../src/reserve_automation/web/static/js/management/tasting-review.js';
import '../../src/reserve_automation/web/static/js/management/event-create.js';
import '../../src/reserve_automation/web/static/js/management/management-app.js';

function jsonResponse(data, { ok = true, status = 200 } = {}) {
    return {
        ok,
        status,
        json: async () => data,
        text: async () => JSON.stringify(data),
    };
}

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

function freshApp() {
    return window.managementApp();
}

// Kind-qualified row identity — the contract data really does contain a
// bottle tasting and a cocktail tasting that share numeric id 1.
function keys(tastings) {
    return tastings.map(t => `${t.tasting_kind}:${t.id}`);
}

// Contract rows + one synthetic hidden variant (the API produces hidden rows,
// but the contract flow doesn't save one — explicit mutation of the whiskey).
function makeTastings() {
    const rows = loadContract('management_tastings').tastings;
    const whiskey = rows.find(t => t.type === 'whiskey');
    const hidden = {
        ...whiskey,
        id: 4, bottle_name: 'Hidden Dram', date: '2026-05-01',
        total_score: 5, hidden: true,
    };
    return [...rows, hidden];
}

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([]));
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('confirm', vi.fn(() => true));
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Composition — the page's whole reason to load four modules
// ---------------------------------------------------------------------------

describe('module composition', () => {
    it('merges tasting-review state and methods', () => {
        const app = freshApp();
        expect(app.trAllTastings).toEqual([]);
        expect(app.trSortColumn).toBe('date');
        expect(app.trStartEdit).toBeTypeOf('function');
        expect(app.loadTastings).toBeTypeOf('function');
    });

    it('merges event-create state and methods', () => {
        const app = freshApp();
        expect(app.eventName).toBe('');
        expect(app.eventBeverageType).toBe('wine');
        expect(app.eventSelectedBottles).toEqual([]);
    });

    it('embeds a bottle editor instance', () => {
        const app = freshApp();
        expect(app.bottleEditor).toBeTruthy();
        expect(app.bottleEditor.openManagement).toBeTypeOf('function');
    });

    it('keeps getters live (the reason this factory is never spread)', () => {
        const app = freshApp();
        expect(app.filteredTastings).toEqual([]);
        app.trAllTastings = makeTastings();
        expect(app.filteredTastings.length).toBeGreaterThan(0);
    });
});

// ---------------------------------------------------------------------------
// filteredTastings — the central computed of tasting review
// ---------------------------------------------------------------------------

describe('filteredTastings', () => {
    function appWithTastings() {
        const app = freshApp();
        app.trAllTastings = makeTastings();
        return app;
    }

    it('hides hidden tastings by default and shows them with the toggle', () => {
        const app = appWithTastings();
        expect(keys(app.filteredTastings)).not.toContain('bottle:4');
        app.trShowHidden = true;
        expect(keys(app.filteredTastings)).toContain('bottle:4');
    });

    it('filters by type', () => {
        const app = appWithTastings();
        app.trFilterType = 'wine';
        expect(keys(app.filteredTastings)).toEqual(['bottle:2']);
    });

    it('filters by taster', () => {
        const app = appWithTastings();
        app.trFilterTaster = 'Sarah';
        expect(keys(app.filteredTastings)).toEqual(['bottle:2']);
    });

    it('searches bottle names case-insensitively', () => {
        const app = appWithTastings();
        app.trFilterSearch = 'cabernet';
        expect(keys(app.filteredTastings)).toEqual(['bottle:2']);
    });

    it('searches cocktail component bottles too', () => {
        // 'special reserve' only appears in the cocktail's bottles_used
        // (actual_product 'Weller Special Reserve'), not in any bottle name.
        const app = appWithTastings();
        app.trFilterSearch = 'special reserve';
        expect(keys(app.filteredTastings)).toEqual(['cocktail:1']);
    });

    it('applies exact type-specific dropdown filters', () => {
        const app = appWithTastings();
        app.trTypeFilters = { variety: 'Cabernet Sauvignon' };
        expect(keys(app.filteredTastings)).toEqual(['bottle:2']);
        app.trTypeFilters = { variety: 'Pinot Noir' };
        expect(app.filteredTastings).toEqual([]);
    });

    it('applies partial type-specific search filters', () => {
        const app = appWithTastings();
        app.trTypeFilterSearch = { variety: 'cabern' };
        expect(keys(app.filteredTastings)).toEqual(['bottle:2']);
    });

    it('filters by normalized min/max score and drops unscored rows', () => {
        const app = appWithTastings();
        // Unscored variant: cocktail tastings CAN carry a null score — the
        // contract one is scored, so null it explicitly.
        app.trAllTastings.find(t => t.type === 'cocktail').total_score = null;

        app.trFilterMinScore = '90';
        // whiskey 85% (out), wine 92.5% (in), cocktail null (out)
        expect(keys(app.filteredTastings)).toEqual(['bottle:2']);

        app.trFilterMinScore = '0';
        // everything scored passes; the null cocktail is still dropped
        expect(keys(app.filteredTastings)).toEqual(['bottle:2', 'bottle:1']);

        app.trFilterMinScore = '';
        app.trFilterMaxScore = '90';
        expect(keys(app.filteredTastings)).toEqual(['bottle:1']);
    });

    it('filters by date range', () => {
        const app = appWithTastings();
        app.trFilterDateFrom = '2026-07-02';
        app.trFilterDateTo = '2026-07-04';
        expect(keys(app.filteredTastings)).toEqual(['bottle:2']);
    });

    it('sorts by date descending by default', () => {
        const app = appWithTastings();
        expect(keys(app.filteredTastings)).toEqual(['cocktail:1', 'bottle:2', 'bottle:1']);
    });

    it('sorts normalized scores with nulls sinking to the bottom in either direction', () => {
        const app = appWithTastings();
        app.trAllTastings.find(t => t.type === 'cocktail').total_score = null;
        app.trSortColumn = 'total_score';
        app.trSortDir = 'desc';
        // wine 92.5% > whiskey 85% > cocktail null (sinks)
        expect(keys(app.filteredTastings)).toEqual(['bottle:2', 'bottle:1', 'cocktail:1']);

        app.trSortDir = 'asc';
        expect(keys(app.filteredTastings)).toEqual(['bottle:1', 'bottle:2', 'cocktail:1']);
    });

    it('sorts strings case-insensitively', () => {
        const app = appWithTastings();
        app.trSortColumn = 'bottle_name';
        app.trSortDir = 'asc';
        expect(app.filteredTastings.map(t => t.bottle_name)).toEqual([
            'Buffalo Trace - Weller 12 Year',
            'Caymus Vineyards - Cabernet Sauvignon',
            'Contract Old Fashioned',
        ]);
    });
});

describe('trComputedAvg', () => {
    it('averages normalized scores of the filtered set', () => {
        const app = freshApp();
        app.trAllTastings = makeTastings();
        // cocktail 80 + wine 92.5 + whiskey 85 → 85.8 (hidden row excluded)
        expect(app.trComputedAvg).toBe('85.8');
    });

    it('is null when nothing has a score', () => {
        const app = freshApp();
        const cocktail = makeTastings().find(t => t.type === 'cocktail');
        app.trAllTastings = [{ ...cocktail, total_score: null }];
        expect(app.trComputedAvg).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// init + mode selection
// ---------------------------------------------------------------------------

describe('init', () => {
    it('pre-fills the event host name from the auth identity and warms autocomplete', async () => {
        const app = freshApp();
        app.bottleEditor.loadAutocomplete = vi.fn();
        global.fetch = routeFetch([
            ['/api/v1/me', jsonResponse(loadContract('me'))],
        ]);

        await app.init();

        expect(app.eventHostName).toBe('Admin');   // me.display_name
        expect(app.bottleEditor.loadAutocomplete).toHaveBeenCalled();
    });

    it('survives an unauthenticated /me', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/me', jsonResponse({}, { ok: false, status: 401 })],
        ]);
        await app.init();
        expect(app.eventHostName).toBe('');
    });
});

describe('selectMode', () => {
    it.each([
        ['manage-events', 'loadManagedEvents'],
        ['bulk-import', 'loadBulkIngredientNames'],
        ['tasting-review', 'loadTastings'],
        ['data-cleanup', 'loadCleanupValues'],
    ])('%s triggers %s', (mode, loader) => {
        const app = freshApp();
        app[loader] = vi.fn();
        app.selectMode(mode);
        expect(app.mode).toBe(mode);
        expect(app[loader]).toHaveBeenCalled();
    });

    it('other modes just set the mode', () => {
        const app = freshApp();
        app.selectMode('single');
        expect(app.mode).toBe('single');
    });
});

// ---------------------------------------------------------------------------
// Data cleanup (bulk rename)
// ---------------------------------------------------------------------------

describe('data cleanup', () => {
    it('loadCleanupValues decorates rows with rename state (contract data)', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/management/field-values', jsonResponse(loadContract('management_field_values'))],
        ]);

        await app.loadCleanupValues();

        expect(app.dcValues).toEqual([
            { value: 'Ben', count: 1, renameInput: '', saving: false },
            { value: 'Sarah', count: 1, renameInput: '', saving: false },
        ]);
        expect(app.dcLoading).toBe(false);
        expect(global.fetch).toHaveBeenCalledWith(
            '/api/v1/management/field-values?scope=tastings&field=taster_name'
        );
    });

    it('dcFilteredValues searches and sorts by count or value', () => {
        const app = freshApp();
        app.dcValues = [
            { value: 'Bourbon', count: 3 },
            { value: 'Rye', count: 9 },
            { value: 'Brandy', count: 1 },
        ];

        // default count-desc
        expect(app.dcFilteredValues.map(v => v.value)).toEqual(['Rye', 'Bourbon', 'Brandy']);

        app.dcSort = 'value-asc';
        expect(app.dcFilteredValues.map(v => v.value)).toEqual(['Bourbon', 'Brandy', 'Rye']);

        app.dcSearch = 'br';
        expect(app.dcFilteredValues.map(v => v.value)).toEqual(['Brandy']);
    });

    it('dcSelectField switches scope+field and reloads', () => {
        const app = freshApp();
        app.loadCleanupValues = vi.fn();
        app.dcSelectField('bottles', 'producer');
        expect(app.dcTab).toBe('bottles');
        expect(app.dcField).toBe('producer');
        expect(app.loadCleanupValues).toHaveBeenCalled();
    });

    it('dcApplyRename posts the rename, toasts, and reloads values (contract data)', async () => {
        const app = freshApp();
        app.loadCleanupValues = vi.fn();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/management/bulk-rename', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                // Real response: {"updated": 1} — the contract flow renamed
                // the single Sarah tasting.
                return jsonResponse(loadContract('management_bulk_rename_response'));
            }],
        ]);
        const item = { value: 'Sarah', count: 1, renameInput: 'Sarah B', saving: false };

        await app.dcApplyRename(item);

        expect(sentBody).toEqual({
            scope: 'tastings', field: 'taster_name', old_value: 'Sarah', new_value: 'Sarah B',
        });
        expect(app.toasts[0].message).toBe('Renamed 1 record: "Sarah" → "Sarah B"');
        expect(app.loadCleanupValues).toHaveBeenCalled();
        expect(item.saving).toBe(false);
    });

    it('dcApplyRename is a no-op for empty or unchanged input', async () => {
        const app = freshApp();
        await app.dcApplyRename({ value: 'Ben', renameInput: '  ' });
        await app.dcApplyRename({ value: 'Ben', renameInput: 'Ben' });
        expect(global.fetch).not.toHaveBeenCalled();
    });

    it('dcApplyRename surfaces backend errors as a toast', async () => {
        const app = freshApp();
        // Hand-written: FastAPI {detail} error envelope (contract flow only
        // captures success responses).
        global.fetch = routeFetch([
            ['/api/v1/management/bulk-rename', jsonResponse({ detail: 'name collision' }, { ok: false, status: 409 })],
        ]);
        const item = { value: 'ben', renameInput: 'Ben' };

        await app.dcApplyRename(item);

        expect(app.toasts[0].message).toBe('name collision');
        expect(app.toasts[0].type).toBe('error');
        expect(item.saving).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// Bulk ingredient import
// ---------------------------------------------------------------------------

describe('bulk ingredient import', () => {
    it('loadBulkIngredientNames extracts names for autocomplete', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/ingredients?flat=true', jsonResponse([{ name: 'Gin' }, { name: 'Rye' }])],
        ]);
        await app.loadBulkIngredientNames();
        expect(app.bulkIngredientNames).toEqual(['Gin', 'Rye']);
    });

    it('doBulkSearch ignores blank queries', async () => {
        const app = freshApp();
        app.bulkQuery = '   ';
        await app.doBulkSearch();
        expect(global.fetch).not.toHaveBeenCalled();
    });

    // NOTE: bulk-search responses below are hand-written by necessity —
    // POST /api/v1/ingredients/bulk-search performs a live web search plus an
    // LLM completion (routes/ingredients.py), so no deterministic contract
    // fixture can be captured for it. Shape mirrors BulkSearchResult.
    it('doBulkSearch posts query+parent and stores results', async () => {
        const app = freshApp();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/ingredients/bulk-search', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse({
                    results: [{
                        name: 'Angostura Aromatic Bitters', cost: 12.99,
                        volume_ml: 200, abv: 44.7,
                        notes: 'Classic aromatic bitters', selected: true,
                    }],
                    query: 'bitters', parent: null,
                });
            }],
        ]);
        app.bulkQuery = 'bitters';
        app.bulkParent = '';

        await app.doBulkSearch();

        expect(sentBody).toEqual({ query: 'bitters', parent: null });
        expect(app.bulkResults).toHaveLength(1);
        expect(app.bulkError).toBe('');
        expect(app.bulkSearching).toBe(false);
    });

    it('doBulkSearch reports empty results as a friendly error', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/ingredients/bulk-search', jsonResponse({ results: [], query: 'unobtainium' })],
        ]);
        app.bulkQuery = 'unobtainium';
        await app.doBulkSearch();
        expect(app.bulkError).toContain('No results found');
    });

    it('doBulkSearch surfaces the backend detail on failure', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/ingredients/bulk-search', jsonResponse({ detail: 'LLM offline' }, { ok: false, status: 503 })],
        ]);
        app.bulkQuery = 'bitters';
        await app.doBulkSearch();
        expect(app.bulkError).toBe('LLM offline');
        expect(app.bulkSearching).toBe(false);
    });

    it('doBulkSave requires a selection', async () => {
        const app = freshApp();
        app.bulkResults = [{ name: 'Gin', selected: false }];
        await app.doBulkSave();
        expect(app.bulkError).toBe('No items selected');
        expect(global.fetch).not.toHaveBeenCalled();
    });

    it('doBulkSave reports saved+skipped and refreshes autocomplete names (contract data)', async () => {
        const app = freshApp();
        // Real response: saved = 2 full ingredient objects, skipped = 1
        // {name, reason} entry (the unselected row).
        global.fetch = routeFetch([
            ['/api/v1/ingredients/bulk-save', jsonResponse(loadContract('management_bulk_save_response'))],
            ['/api/v1/ingredients?flat=true', jsonResponse([{ name: 'Gin' }, { name: 'Rye' }])],
        ]);
        app.bulkResults = [
            { name: 'Angostura Aromatic Bitters', selected: true },
            { name: "Peychaud's Bitters", selected: true },
            { name: "Regans' Orange Bitters", selected: false },
        ];

        await app.doBulkSave();

        expect(app.bulkSuccess).toBe('Saved 2 ingredients, skipped 1');
        expect(app.bulkResults).toEqual([]);
        expect(app.bulkIngredientNames).toEqual(['Gin', 'Rye']);
        expect(app.bulkSaving).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// Toasts
// ---------------------------------------------------------------------------

describe('showToast', () => {
    it('adds a toast and auto-dismisses it after its duration', () => {
        vi.useFakeTimers();
        const app = freshApp();

        app.showToast('Saved', 'success', 1000);
        app.showToast('Oops', 'error', 5000);
        expect(app.toasts).toHaveLength(2);

        vi.advanceTimersByTime(1000);
        expect(app.toasts).toHaveLength(1);
        expect(app.toasts[0].message).toBe('Oops');

        vi.advanceTimersByTime(4000);
        expect(app.toasts).toHaveLength(0);
    });
});

// ---------------------------------------------------------------------------
// Batch verification
//
// The contract fixtures (management_batch_verify_response,
// management_batch_status) are captured against an empty bottle table: with
// bottles present the batch's background tasks call the LLM, so only the
// batch envelope (batch_id + status counters + results[]) is contract-backed.
// Result ENTRIES with changes are hand-written below, labelled as such.
// ---------------------------------------------------------------------------

describe('batch verification', () => {
    const BATCH_ID = '00000000-0000-4000-8000-000000000001'; // normalized snapshot UUID

    it('initBatchResult checks all change boxes and initializes card states once', () => {
        const app = freshApp();
        const result = { bottle_index: 3, changes: { region: {}, abv: {} } };

        app.initBatchResult(result);
        expect(app.batchApprovedFields).toEqual({ '3_region': true, '3_abv': true });
        expect(app.batchCollapsedStates[3]).toBe(false);
        expect(app.batchAppliedStates[3]).toBe(false);

        // User unchecks one, then Alpine re-runs x-init — must NOT re-check it
        app.batchApprovedFields['3_region'] = false;
        app.initBatchResult(result);
        expect(app.batchApprovedFields['3_region']).toBe(false);
    });

    it('getMetadataFields includes wine fields for wine and cask fields otherwise', () => {
        const app = freshApp();
        const wineKeys = app.getMetadataFields({ type: 'wine' }).map(f => f.key);
        expect(wineKeys).toContain('variety');
        expect(wineKeys).toContain('vineyard');
        expect(wineKeys).not.toContain('proof');

        const whiskeyKeys = app.getMetadataFields({ type: 'whiskey' }).map(f => f.key);
        expect(whiskeyKeys).toContain('mash_bill');
        expect(whiskeyKeys).toContain('barrel_type');
        expect(whiskeyKeys).not.toContain('vineyard');
    });

    it('applyBatchUpdate sends only the approved fields', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/update-fields', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse({ status: 'ok' });
            }],
        ]);
        const result = {
            bottle_index: 1,
            original: { producer: 'X', name: 'Y' },
            changes: { region: { new: 'Kentucky' }, abv: { new: '45' } },
        };
        app.batchApprovedFields = { '1_region': true, '1_abv': false };

        await app.applyBatchUpdate(result, 0);

        expect(sentBody.updates).toEqual({ region: 'Kentucky' });
        expect(app.batchAppliedStates[1]).toBe(true);

        // Auto-collapses the card after the success beat
        expect(app.batchCollapsedStates[1]).toBeUndefined();
        vi.advanceTimersByTime(800);
        expect(app.batchCollapsedStates[1]).toBe(true);
    });

    it('applyBatchUpdate refuses to apply nothing', async () => {
        const app = freshApp();
        const result = { bottle_index: 1, original: {}, changes: { region: { new: 'X' } } };
        app.batchApprovedFields = { '1_region': false };

        await app.applyBatchUpdate(result, 0);

        expect(alert).toHaveBeenCalledWith('No changes selected to apply');
        expect(global.fetch).not.toHaveBeenCalled();
    });

    it('applyBatchUpdate alerts and resets on backend failure', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/update-fields', jsonResponse({ detail: 'locked' }, { ok: false, status: 423 })],
        ]);
        const result = { bottle_index: 1, original: {}, changes: { region: { new: 'X' } } };
        app.batchApprovedFields = { '1_region': true };

        await app.applyBatchUpdate(result, 0);

        expect(alert).toHaveBeenCalledWith(expect.stringContaining('locked'));
        expect(app.applying).toBe(false);
        expect(app.batchAppliedStates[1]).toBeUndefined();
    });

    it('startBatchVerification stores the batch id and begins polling (contract data)', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/batch-verify',
                jsonResponse(loadContract('management_batch_verify_response'))],
        ]);
        app.pollBatchStatus = vi.fn();

        await app.startBatchVerification();

        expect(app.batchId).toBe(BATCH_ID);
        expect(app.batchStatus.total).toBe(0);
        expect(app.batchStatus.status).toBe('processing');
        expect(app.batchStarting).toBe(false);

        vi.advanceTimersByTime(2000);
        expect(app.pollBatchStatus).toHaveBeenCalledTimes(1);
    });

    it('pollBatchStatus surfaces pending reviews and seeds the first verification result', async () => {
        const app = freshApp();
        app.batchId = BATCH_ID;
        // Base envelope from the contract; the result entries are hand-written
        // — real ones are produced by the LLM enrichment task and cannot be
        // captured deterministically.
        const running = loadContract('management_batch_status');
        running.status = { ...running.status, status: 'running', total: 3, completed: 2, with_changes: 1 };
        running.results = [
            { bottle_index: 0, status: 'completed', has_changes: false },
            {
                bottle_index: 1, status: 'completed', has_changes: true,
                original: { name: 'A' }, updated: { name: 'B' },
                changes: { name: { new: 'B' } }, metadata: {},
            },
            { bottle_index: 2, status: 'processing' },
        ];
        global.fetch = routeFetch([
            [`/api/v1/management/batch/${BATCH_ID}/status`, jsonResponse(running)],
        ]);

        await app.pollBatchStatus();

        expect(app.pendingReviews).toHaveLength(1);
        expect(app.verificationResult.changes.name.new).toBe('B');
        expect(app.approvedFields).toEqual({ name: true });
    });

    it('pollBatchStatus stops polling when the batch completes (contract data)', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.batchId = BATCH_ID;
        app.pollInterval = setInterval(() => {}, 2000);
        const clearSpy = vi.spyOn(globalThis, 'clearInterval');
        // The contract batch-status fixture IS a completed batch.
        global.fetch = routeFetch([
            ['/status', jsonResponse(loadContract('management_batch_status'))],
        ]);

        await app.pollBatchStatus();
        expect(clearSpy).toHaveBeenCalledWith(app.pollInterval);
        clearSpy.mockRestore();
    });

    it('pollBatchStatus without a batch id is a no-op', async () => {
        const app = freshApp();
        await app.pollBatchStatus();
        expect(global.fetch).not.toHaveBeenCalled();
    });

    it('exitBatch clears polling and resets batch state', () => {
        const app = freshApp();
        app.batchId = BATCH_ID;
        app.batchResults = [{}];
        app.pendingReviews = [{}];
        app.verificationResult = {};
        app.mode = 'batch';
        app.pollInterval = setInterval(() => {}, 100000);

        app.exitBatch();

        expect(app.batchId).toBeNull();
        expect(app.batchResults).toEqual([]);
        expect(app.pendingReviews).toEqual([]);
        expect(app.verificationResult).toBeNull();
        expect(app.mode).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// Manage events
// ---------------------------------------------------------------------------

describe('manage events', () => {
    it('loadManagedEvents fills the list (contract data)', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/events', jsonResponse(loadContract('events_list'))],
        ]);
        await app.loadManagedEvents();
        expect(app.managedEvents).toHaveLength(2);
        // Newest first (created_at desc): wine event is created after whiskey.
        expect(app.managedEvents[0].name).toBe('Contract Wine Night');
        expect(app.manageEventsLoading).toBe(false);
    });

    it('loadManagedEvents alerts on failure', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/events', jsonResponse({}, { ok: false, status: 500 })],
        ]);
        await app.loadManagedEvents();
        expect(alert).toHaveBeenCalledWith(expect.stringContaining('Failed to load events'));
    });

    it.each([
        // Responders are the real PUT /reveal and /close responses (contract
        // fixtures); DELETE's body isn't read by the component.
        ['revealEventBottles', '/api/v1/events/e1/reveal', 'PUT',
            () => jsonResponse(loadContract('management_event_reveal_response'))],
        ['closeEventFromManagement', '/api/v1/events/e1/close', 'PUT',
            () => jsonResponse(loadContract('management_event_close_response'))],
        ['deleteEventFromManagement', '/api/v1/events/e1', 'DELETE',
            () => jsonResponse({})],
    ])('%s is confirm-gated and hits %s', async (method, url, verb, responder) => {
        const app = freshApp();
        app.loadManagedEvents = vi.fn();
        global.fetch = routeFetch([[url, responder()]]);

        // User cancels — nothing happens
        confirm.mockReturnValueOnce(false);
        await app[method]('e1');
        expect(global.fetch).not.toHaveBeenCalled();

        // User confirms — the endpoint is hit and the list refreshes
        await app[method]('e1');
        expect(global.fetch).toHaveBeenCalledWith(url, { method: verb });
        expect(app.loadManagedEvents).toHaveBeenCalled();
        expect(app.toasts).toHaveLength(1);
    });
});
