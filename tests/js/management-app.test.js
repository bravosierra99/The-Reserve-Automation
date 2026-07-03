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
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

const TASTINGS = [
    {
        id: 1, tasting_kind: 'bottle', type: 'whiskey', taster: 'Ben',
        bottle_name: 'Weller 12', date: '2026-06-01',
        total_score: 8, max_score: 10, hidden: false,
    },
    {
        id: 2, tasting_kind: 'bottle', type: 'wine', taster: 'Sarah',
        bottle_name: 'Grand Cru', date: '2026-06-10',
        total_score: 90, max_score: 100, hidden: false, variety: 'Merlot',
    },
    {
        id: 3, tasting_kind: 'cocktail', type: 'cocktail', taster: 'Ben',
        bottle_name: 'Old Fashioned', date: '2026-06-20',
        total_score: null, max_score: 10, hidden: false,
        bottles_used: [
            { recipe_ingredient: 'bourbon', actual_product: 'Weller Special Reserve' },
        ],
    },
    {
        id: 4, tasting_kind: 'bottle', type: 'whiskey', taster: 'Ben',
        bottle_name: 'Hidden Dram', date: '2026-05-01',
        total_score: 5, max_score: 10, hidden: true,
    },
];

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
        app.trAllTastings = TASTINGS;
        expect(app.filteredTastings.length).toBeGreaterThan(0);
    });
});

// ---------------------------------------------------------------------------
// filteredTastings — the central computed of tasting review
// ---------------------------------------------------------------------------

describe('filteredTastings', () => {
    function appWithTastings() {
        const app = freshApp();
        app.trAllTastings = JSON.parse(JSON.stringify(TASTINGS));
        return app;
    }

    it('hides hidden tastings by default and shows them with the toggle', () => {
        const app = appWithTastings();
        expect(app.filteredTastings.map(t => t.id)).not.toContain(4);
        app.trShowHidden = true;
        expect(app.filteredTastings.map(t => t.id)).toContain(4);
    });

    it('filters by type', () => {
        const app = appWithTastings();
        app.trFilterType = 'wine';
        expect(app.filteredTastings.map(t => t.id)).toEqual([2]);
    });

    it('filters by taster', () => {
        const app = appWithTastings();
        app.trFilterTaster = 'Sarah';
        expect(app.filteredTastings.map(t => t.id)).toEqual([2]);
    });

    it('searches bottle names case-insensitively', () => {
        const app = appWithTastings();
        app.trFilterSearch = 'grand';
        expect(app.filteredTastings.map(t => t.id)).toEqual([2]);
    });

    it('searches cocktail component bottles too', () => {
        const app = appWithTastings();
        app.trFilterSearch = 'special reserve';
        expect(app.filteredTastings.map(t => t.id)).toEqual([3]);
    });

    it('applies exact type-specific dropdown filters', () => {
        const app = appWithTastings();
        app.trTypeFilters = { variety: 'Merlot' };
        expect(app.filteredTastings.map(t => t.id)).toEqual([2]);
        app.trTypeFilters = { variety: 'Pinot' };
        expect(app.filteredTastings).toEqual([]);
    });

    it('applies partial type-specific search filters', () => {
        const app = appWithTastings();
        app.trTypeFilterSearch = { variety: 'merl' };
        expect(app.filteredTastings.map(t => t.id)).toEqual([2]);
    });

    it('filters by normalized min/max score and drops unscored rows', () => {
        const app = appWithTastings();
        app.trFilterMinScore = '85';
        // whiskey 8/10 = 80 (out), wine 90/100 = 90 (in), cocktail null (out)
        expect(app.filteredTastings.map(t => t.id)).toEqual([2]);

        app.trFilterMinScore = '';
        app.trFilterMaxScore = '85';
        expect(app.filteredTastings.map(t => t.id)).toEqual([1]);
    });

    it('filters by date range', () => {
        const app = appWithTastings();
        app.trFilterDateFrom = '2026-06-05';
        app.trFilterDateTo = '2026-06-15';
        expect(app.filteredTastings.map(t => t.id)).toEqual([2]);
    });

    it('sorts by date descending by default', () => {
        const app = appWithTastings();
        expect(app.filteredTastings.map(t => t.id)).toEqual([3, 2, 1]);
    });

    it('sorts normalized scores with nulls sinking to the bottom in either direction', () => {
        const app = appWithTastings();
        app.trSortColumn = 'total_score';
        app.trSortDir = 'desc';
        // wine 90% > whiskey 80% > cocktail null (sinks)
        expect(app.filteredTastings.map(t => t.id)).toEqual([2, 1, 3]);

        app.trSortDir = 'asc';
        expect(app.filteredTastings.map(t => t.id)).toEqual([1, 2, 3]);
    });

    it('sorts strings case-insensitively', () => {
        const app = appWithTastings();
        app.trSortColumn = 'bottle_name';
        app.trSortDir = 'asc';
        expect(app.filteredTastings.map(t => t.bottle_name)).toEqual(
            ['Grand Cru', 'Old Fashioned', 'Weller 12']
        );
    });
});

describe('trComputedAvg', () => {
    it('averages normalized scores of the filtered set', () => {
        const app = freshApp();
        app.trAllTastings = JSON.parse(JSON.stringify(TASTINGS));
        // whiskey 80 + wine 90 → 85.0 (null cocktail excluded)
        expect(app.trComputedAvg).toBe('85.0');
    });

    it('is null when nothing has a score', () => {
        const app = freshApp();
        app.trAllTastings = [{ ...TASTINGS[2] }];
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
            ['/api/v1/me', jsonResponse({ display_name: 'Ben' })],
        ]);

        await app.init();

        expect(app.eventHostName).toBe('Ben');
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
    it('loadCleanupValues decorates rows with rename state', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/management/field-values', jsonResponse([
                { value: 'Ben', count: 10 },
                { value: 'ben', count: 2 },
            ])],
        ]);

        await app.loadCleanupValues();

        expect(app.dcValues).toEqual([
            { value: 'Ben', count: 10, renameInput: '', saving: false },
            { value: 'ben', count: 2, renameInput: '', saving: false },
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

    it('dcApplyRename posts the rename, toasts, and reloads values', async () => {
        const app = freshApp();
        app.loadCleanupValues = vi.fn();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/management/bulk-rename', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse({ updated: 12 });
            }],
        ]);
        const item = { value: 'ben', count: 2, renameInput: 'Ben', saving: false };

        await app.dcApplyRename(item);

        expect(sentBody).toEqual({
            scope: 'tastings', field: 'taster_name', old_value: 'ben', new_value: 'Ben',
        });
        expect(app.toasts[0].message).toContain('Renamed 12 records');
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

    it('doBulkSearch posts query+parent and stores results', async () => {
        const app = freshApp();
        let sentBody = null;
        global.fetch = routeFetch([
            ['/api/v1/ingredients/bulk-search', (url, opts) => {
                sentBody = JSON.parse(opts.body);
                return jsonResponse({ results: [{ name: 'Angostura' }] });
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
            ['/api/v1/ingredients/bulk-search', jsonResponse({ results: [] })],
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

    it('doBulkSave reports saved+skipped and refreshes autocomplete names', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/ingredients/bulk-save', jsonResponse({ saved: ['Gin', 'Rye'], skipped: ['Vodka'] })],
            ['/api/v1/ingredients?flat=true', jsonResponse([{ name: 'Gin' }, { name: 'Rye' }])],
        ]);
        app.bulkResults = [{ name: 'Gin', selected: true }, { name: 'Vodka', selected: true }];

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
// ---------------------------------------------------------------------------

describe('batch verification', () => {
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

    it('startBatchVerification stores the batch id and begins polling', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/management/bottles/batch-verify', jsonResponse({
                batch_id: 'batch-9',
                status: { total: 5, completed: 0, with_changes: 0, errors: 0 },
            })],
        ]);
        app.pollBatchStatus = vi.fn();

        await app.startBatchVerification();

        expect(app.batchId).toBe('batch-9');
        expect(app.batchStatus.total).toBe(5);
        expect(app.batchStarting).toBe(false);

        vi.advanceTimersByTime(2000);
        expect(app.pollBatchStatus).toHaveBeenCalledTimes(1);
    });

    it('pollBatchStatus surfaces pending reviews and seeds the first verification result', async () => {
        const app = freshApp();
        app.batchId = 'batch-9';
        global.fetch = routeFetch([
            ['/api/v1/management/batch/batch-9/status', jsonResponse({
                status: { status: 'running', total: 3, completed: 2, with_changes: 1, errors: 0 },
                results: [
                    { bottle_index: 0, status: 'completed', has_changes: false },
                    {
                        bottle_index: 1, status: 'completed', has_changes: true,
                        original: { name: 'A' }, updated: { name: 'B' },
                        changes: { name: { new: 'B' } }, metadata: {},
                    },
                    { bottle_index: 2, status: 'processing' },
                ],
            })],
        ]);

        await app.pollBatchStatus();

        expect(app.pendingReviews).toHaveLength(1);
        expect(app.verificationResult.changes.name.new).toBe('B');
        expect(app.approvedFields).toEqual({ name: true });
    });

    it('pollBatchStatus stops polling when the batch completes', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.batchId = 'batch-9';
        app.pollInterval = setInterval(() => {}, 2000);
        const clearSpy = vi.spyOn(globalThis, 'clearInterval');
        global.fetch = routeFetch([
            ['/status', jsonResponse({
                status: { status: 'complete', total: 3, completed: 3, with_changes: 0, errors: 0 },
                results: [],
            })],
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
        app.batchId = 'batch-9';
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
    it('loadManagedEvents fills the list', async () => {
        const app = freshApp();
        global.fetch = routeFetch([
            ['/api/v1/events', jsonResponse([{ id: 'e1' }, { id: 'e2' }])],
        ]);
        await app.loadManagedEvents();
        expect(app.managedEvents).toHaveLength(2);
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
        ['revealEventBottles', '/api/v1/events/e1/reveal', 'PUT'],
        ['closeEventFromManagement', '/api/v1/events/e1/close', 'PUT'],
        ['deleteEventFromManagement', '/api/v1/events/e1', 'DELETE'],
    ])('%s is confirm-gated and hits %s', async (method, url, verb) => {
        const app = freshApp();
        app.loadManagedEvents = vi.fn();

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
