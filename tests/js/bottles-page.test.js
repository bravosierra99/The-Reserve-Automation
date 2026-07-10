/**
 * Unit tests for the bottle collection grid page component
 * (src/reserve_automation/web/static/js/bottles/bottles-page.js).
 *
 * The REAL bottle-editor-modal module is imported so composition is tested
 * for real. Alpine itself is not loaded; the factory's return value is used
 * directly, which exercises the live filteredBottles getter the same way
 * Alpine would.
 *
 * Bottle fixtures are NOT hand-written: they are contract fixtures — the
 * real GET /api/v1/bottles/collection and /api/v1/me responses captured and
 * snapshot-verified by tests/contract/test_bottles_contract.py (see
 * tests/contract/contract.py). Collection contents (sorted by producer,name):
 *   id 1  Buffalo Trace - Eagle Rare 10 Year   whiskey, Kentucky/USA, Bourbon,
 *         barrel "New Charred Oak", inventory 2, notes set
 *   id 3  Caymus Vineyards - Special Selection Cabernet  wine, Napa Valley,
 *         Red, variety [Cabernet Sauvignon, Merlot], style Bold, inventory 1
 *   id 4  Cloudy Bay - Sauvignon Blanc Reserve  wine, country-only (NZ),
 *         White, style Crisp, inventory 0
 *   id 2  Willett - Pot Still Reserve           whiskey, minimal (all nulls)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
import '../../src/reserve_automation/web/static/js/components/bottle-editor-modal.js';
import '../../src/reserve_automation/web/static/js/bottles/bottles-page.js';

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
    return window.bottlesApp();
}

const COLLECTION = loadContract('bottles_collection');

function appWithBottles() {
    const app = freshApp();
    app.labelBottles = loadContract('bottles_collection').bottles;
    return app;
}

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([]));
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.stubGlobal('location', { href: '', origin: 'http://localhost:3000' });
    sessionStorage.clear();
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Composition and initial state
// ---------------------------------------------------------------------------

describe('composition and initial state', () => {
    it('embeds a real bottle editor instance', () => {
        const app = freshApp();
        expect(app.bottleEditor).toBeTruthy();
        expect(app.bottleEditor.openManagement).toBeTypeOf('function');
    });

    it('soft-guards a missing bottle editor module', () => {
        const original = window.bottleEditorModal;
        try {
            window.bottleEditorModal = undefined;
            const app = freshApp();
            expect(app.bottleEditor).toEqual({});
        } finally {
            window.bottleEditorModal = original;
        }
    });

    it('starts with an empty grid, no filters and no permissions', () => {
        const app = freshApp();
        expect(app.labelsLoading).toBe(false);
        expect(app.labelBottles).toEqual([]);
        expect(app.gridFilterType).toBe('all');
        expect(app.gridSearchQuery).toBe('');
        expect(app.gridFilterRegion).toBe('');
        expect(app.gridFilterBeverageType).toBe('');
        expect(app.gridFilterVariety).toBe('');
        expect(app.gridFilterStyle).toBe('');
        expect(app.gridFilterBarrelType).toBe('');
        expect(app.gridFilterInStockOnly).toBe(false);
        expect(app.canEdit).toBe(false);
        expect(app.canCreateTasting).toBe(false);
        expect(app.toasts).toEqual([]);
        expect(app.toastIdCounter).toBe(0);
    });

    it('keeps the filteredBottles getter live (the reason this factory is never spread)', () => {
        const app = freshApp();
        expect(app.filteredBottles).toEqual([]);
        app.labelBottles = loadContract('bottles_collection').bottles;
        expect(app.filteredBottles.length).toBe(4);
    });
});

// ---------------------------------------------------------------------------
// filteredBottles — the central computed of the grid
// ---------------------------------------------------------------------------

describe('filteredBottles', () => {
    it('returns everything with no filters active', () => {
        expect(appWithBottles().filteredBottles.map(b => b.id)).toEqual(['1', '3', '4', '2']);
    });

    it('filters by type tab', () => {
        const app = appWithBottles();
        app.gridFilterType = 'wine';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3', '4']);
        app.gridFilterType = 'whiskey';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1', '2']);
    });

    it('searches across producer, name, year, region, country, variety, beverage_type and style', () => {
        const app = appWithBottles();

        app.gridSearchQuery = 'caymus';             // producer
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3']);

        app.gridSearchQuery = 'eagle';              // name
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1']);

        app.gridSearchQuery = '2022';               // year
        expect(app.filteredBottles.map(b => b.id)).toEqual(['4']);

        app.gridSearchQuery = 'napa';               // region
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3']);

        app.gridSearchQuery = 'zealand';            // country
        expect(app.filteredBottles.map(b => b.id)).toEqual(['4']);

        app.gridSearchQuery = 'merlot';             // variety list
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3']);

        app.gridSearchQuery = 'bourbon';            // beverage_type
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1']);

        app.gridSearchQuery = 'crisp';              // style
        expect(app.filteredBottles.map(b => b.id)).toEqual(['4']);

        app.gridSearchQuery = 'nothing-matches';
        expect(app.filteredBottles).toEqual([]);
    });

    it('tolerates the minimal bottle whose optional fields are all null (contract data)', () => {
        // Real minimal bottles carry null (not '') for every optional field —
        // the (b.x || '') guards must hold for actual API nulls.
        const app = appWithBottles();
        app.gridSearchQuery = 'pot still';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['2']);
    });

    it('matches the region filter against region OR country', () => {
        const app = appWithBottles();
        app.gridFilterRegion = 'Kentucky';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1']);
        app.gridFilterRegion = 'New Zealand';       // bottle 4 has no region, only country
        expect(app.filteredBottles.map(b => b.id)).toEqual(['4']);
    });

    it('filters by beverage type', () => {
        const app = appWithBottles();
        app.gridFilterBeverageType = 'White';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['4']);
    });

    it('filters by variety substring, case-insensitively', () => {
        const app = appWithBottles();
        app.gridFilterVariety = 'sauv';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3', '4']);
        app.gridFilterVariety = 'merlot';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3']);
    });

    it('filters by style and barrel type exactly', () => {
        const app = appWithBottles();
        app.gridFilterStyle = 'Bold';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3']);

        const app2 = appWithBottles();
        app2.gridFilterBarrelType = 'New Charred Oak';
        expect(app2.filteredBottles.map(b => b.id)).toEqual(['1']);
    });

    it('hides out-of-stock bottles with the in-stock toggle', () => {
        const app = appWithBottles();
        app.gridFilterInStockOnly = true;
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1', '3']);
    });

    it('stacks filters', () => {
        const app = appWithBottles();
        app.gridFilterType = 'whiskey';
        app.gridFilterRegion = 'Kentucky';
        app.gridFilterInStockOnly = true;
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1']);
    });
});

// ---------------------------------------------------------------------------
// Filter state helpers
// ---------------------------------------------------------------------------

describe('gridHasActiveFilters', () => {
    it('is falsy with everything at defaults', () => {
        expect(freshApp().gridHasActiveFilters()).toBeFalsy();
    });

    it.each([
        ['gridFilterType', 'wine'],
        ['gridSearchQuery', 'x'],
        ['gridFilterRegion', 'Kentucky'],
        ['gridFilterBeverageType', 'Red'],
        ['gridFilterVariety', 'Merlot'],
        ['gridFilterStyle', 'Bold'],
        ['gridFilterBarrelType', 'New Charred Oak'],
        ['gridFilterInStockOnly', true],
    ])('is truthy when %s is set', (key, value) => {
        const app = freshApp();
        app[key] = value;
        expect(app.gridHasActiveFilters()).toBeTruthy();
    });
});

describe('reset helpers', () => {
    it('gridResetTypeFilters clears type-specific filters but not the tab/search', () => {
        const app = freshApp();
        app.gridFilterType = 'wine';
        app.gridSearchQuery = 'keep me';
        app.gridFilterRegion = 'Napa Valley';
        app.gridFilterBeverageType = 'Red';
        app.gridFilterVariety = 'Merlot';
        app.gridFilterStyle = 'Bold';
        app.gridFilterBarrelType = 'New Charred Oak';

        app.gridResetTypeFilters();

        expect(app.gridFilterRegion).toBe('');
        expect(app.gridFilterBeverageType).toBe('');
        expect(app.gridFilterVariety).toBe('');
        expect(app.gridFilterStyle).toBe('');
        expect(app.gridFilterBarrelType).toBe('');
        expect(app.gridFilterType).toBe('wine');
        expect(app.gridSearchQuery).toBe('keep me');
    });

    it('gridResetAllFilters restores every filter to defaults', () => {
        const app = freshApp();
        app.gridFilterType = 'whiskey';
        app.gridSearchQuery = 'eagle';
        app.gridFilterBarrelType = 'New Charred Oak';
        app.gridFilterInStockOnly = true;

        app.gridResetAllFilters();

        expect(app.gridFilterType).toBe('all');
        expect(app.gridSearchQuery).toBe('');
        expect(app.gridFilterBarrelType).toBe('');
        expect(app.gridFilterInStockOnly).toBe(false);
        expect(app.gridHasActiveFilters()).toBeFalsy();
    });
});

// ---------------------------------------------------------------------------
// Dropdown option providers
// ---------------------------------------------------------------------------

describe('option providers', () => {
    it('gridAvailableRegions collects region (or country as fallback), sorted', () => {
        // Cloudy Bay contributes its country (no region); the minimal Willett
        // bottle has neither and contributes nothing.
        const app = appWithBottles();
        expect(app.gridAvailableRegions()).toEqual(
            ['Kentucky', 'Napa Valley', 'New Zealand'],
        );
    });

    it('gridAvailableRegions respects the current type tab', () => {
        const app = appWithBottles();
        app.gridFilterType = 'whiskey';
        expect(app.gridAvailableRegions()).toEqual(['Kentucky']);
    });

    it('gridAvailableBeverageTypes respects the current type tab', () => {
        const app = appWithBottles();
        expect(app.gridAvailableBeverageTypes()).toEqual(['Bourbon', 'Red', 'White']);
        app.gridFilterType = 'wine';
        expect(app.gridAvailableBeverageTypes()).toEqual(['Red', 'White']);
    });

    it('gridAvailableStyles lists wine styles only', () => {
        const app = appWithBottles();
        expect(app.gridAvailableStyles()).toEqual(['Bold', 'Crisp']);
    });

    it('gridAvailableBarrelTypes lists whiskey barrels only', () => {
        const app = appWithBottles();
        expect(app.gridAvailableBarrelTypes()).toEqual(['New Charred Oak']);
    });
});

// ---------------------------------------------------------------------------
// navigateToCreateTasting
// ---------------------------------------------------------------------------

describe('navigateToCreateTasting', () => {
    it('stashes the exact preselect payload and navigates to /manual-tasting', () => {
        const app = appWithBottles();
        app.navigateToCreateTasting(app.labelBottles[0]);

        const preselect = JSON.parse(sessionStorage.getItem('preselect_bottle'));
        expect(preselect).toEqual({
            bottle_path: '1',
            bottle_name: 'Buffalo Trace - Eagle Rare 10 Year (2018)',
            producer: 'Buffalo Trace',
            thumbnail_url: '/api/v1/labels/thumbnail?id=1&size=400',
            beverage_type: 'whiskey',
            confidence: 1.0,
        });
        expect(window.location.href).toBe('/manual-tasting');
    });

    it('omits the year suffix when the bottle has no year', () => {
        const app = appWithBottles();
        app.navigateToCreateTasting(app.labelBottles[3]);   // Willett, year null
        const preselect = JSON.parse(sessionStorage.getItem('preselect_bottle'));
        expect(preselect.bottle_name).toBe('Willett - Pot Still Reserve');
        expect(preselect.beverage_type).toBe('whiskey');
    });
});

// ---------------------------------------------------------------------------
// init — permissions + initial load
// ---------------------------------------------------------------------------

describe('init', () => {
    it('reads permissions from /api/v1/me and loads the collection (contract data)', async () => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/me', jsonResponse(loadContract('me'))],
            ['/api/v1/bottles/collection', jsonResponse(loadContract('bottles_collection'))],
        ]));

        const app = freshApp();
        await app.init();

        expect(app.canEdit).toBe(true);
        expect(app.canCreateTasting).toBe(true);
        expect(app.labelBottles.length).toBe(4);
        expect(app.labelsLoading).toBe(false);
    });

    it('turns permissions off for guests (contract data: explicit false flags)', async () => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/me', jsonResponse(loadContract('me_guest'))],
            ['/api/v1/bottles/collection', jsonResponse(loadContract('bottles_collection'))],
        ]));
        const app = freshApp();
        await app.init();
        expect(app.canEdit).toBe(false);
        expect(app.canCreateTasting).toBe(false);
        expect(app.labelBottles.length).toBe(4);
    });

    it('keeps permissions off when /api/v1/me is not ok', async () => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/me', jsonResponse({}, { ok: false, status: 401 })],
            ['/api/v1/bottles/collection', jsonResponse({ bottles: [], count: 0 })],
        ]));
        const app = freshApp();
        await app.init();
        expect(app.canEdit).toBe(false);
        expect(app.canCreateTasting).toBe(false);
    });

    it('keeps permissions off and still loads bottles when /api/v1/me throws', async () => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        vi.stubGlobal('fetch', vi.fn(async (url) => {
            if (String(url).includes('/api/v1/me')) throw new Error('offline');
            return jsonResponse(loadContract('bottles_collection'));
        }));
        const app = freshApp();
        await app.init();
        expect(app.canEdit).toBe(false);
        expect(app.labelBottles.length).toBe(4);
    });

    it('treats missing permission keys as false-y', async () => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/me', jsonResponse({ authenticated: true, permissions: {} })],
            ['/api/v1/bottles/collection', jsonResponse({ bottles: [], count: 0 })],
        ]));
        const app = freshApp();
        await app.init();
        expect(app.canEdit).toBe(false);
        expect(app.canCreateTasting).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// loadBottles
// ---------------------------------------------------------------------------

describe('loadBottles', () => {
    it('fetches the exact collection endpoint and stores the bottles', async () => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/collection', jsonResponse(loadContract('bottles_collection'))],
        ]));

        const app = freshApp();
        await app.loadBottles();

        expect(fetch).toHaveBeenCalledWith('/api/v1/bottles/collection');
        expect(app.labelBottles).toEqual(COLLECTION.bottles);
        expect(app.labelsLoading).toBe(false);
    });

    it('shows an error toast and stops loading on failure', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom'); }));

        const app = freshApp();
        await app.loadBottles();

        expect(app.labelsLoading).toBe(false);
        expect(app.toasts).toEqual([
            { id: 1, message: 'Failed to load bottles: boom', type: 'error' },
        ]);
    });
});

// ---------------------------------------------------------------------------
// showToast
// ---------------------------------------------------------------------------

describe('showToast', () => {
    it('pushes a toast with an incrementing id and default success type', () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.showToast('first');
        app.showToast('second', 'warning');
        expect(app.toasts).toEqual([
            { id: 1, message: 'first', type: 'success' },
            { id: 2, message: 'second', type: 'warning' },
        ]);
    });

    it('auto-dismisses each toast after 3 seconds', () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.showToast('gone soon');
        vi.advanceTimersByTime(1500);
        app.showToast('later');
        vi.advanceTimersByTime(1500);
        expect(app.toasts.map(t => t.message)).toEqual(['later']);
        vi.advanceTimersByTime(1500);
        expect(app.toasts).toEqual([]);
    });
});
