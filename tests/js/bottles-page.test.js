/**
 * Unit tests for the bottle collection grid page component
 * (src/reserve_automation/web/static/js/bottles/bottles-page.js).
 *
 * The REAL bottle-editor-modal module is imported so composition is tested
 * for real. Alpine itself is not loaded; the factory's return value is used
 * directly, which exercises the live filteredBottles getter the same way
 * Alpine would.
 *
 * Bottle fixtures mirror GET /api/v1/bottles/collection
 * (web/routes/bottles/collection.py): BottleMetadata.model_dump(mode='json')
 * — id, type, producer, name, year, region, country, variety (list),
 * beverage_type, style, barrel_type, inventory.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

const BOTTLES = [
    {
        id: '1', type: 'wine', producer: 'Chateau Margaux', name: 'Grand Vin',
        year: 2015, region: 'Bordeaux', country: 'France',
        variety: ['Cabernet Sauvignon', 'Merlot'], beverage_type: 'Red',
        style: 'Bold', barrel_type: null, inventory: 2,
    },
    {
        id: '2', type: 'wine', producer: 'Cloudy Bay', name: 'Sauvignon Blanc',
        year: 2022, region: null, country: 'New Zealand',
        variety: ['Sauvignon Blanc'], beverage_type: 'White',
        style: 'Crisp', barrel_type: null, inventory: 0,
    },
    {
        id: '3', type: 'whiskey', producer: 'Buffalo Trace', name: 'Weller 12',
        year: null, region: 'Kentucky', country: 'USA',
        variety: [], beverage_type: 'Bourbon',
        style: null, barrel_type: 'New Oak', inventory: 1,
    },
    {
        id: '4', type: 'whiskey', producer: 'Lagavulin', name: '16 Year',
        year: 2020, region: 'Islay', country: 'Scotland',
        variety: [], beverage_type: 'Scotch',
        style: null, barrel_type: 'Sherry Cask', inventory: 3,
    },
];

function appWithBottles() {
    const app = freshApp();
    app.labelBottles = JSON.parse(JSON.stringify(BOTTLES));
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
        expect(app.selectedLabelBottle).toBeNull();
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
        app.labelBottles = JSON.parse(JSON.stringify(BOTTLES));
        expect(app.filteredBottles.length).toBe(4);
    });
});

// ---------------------------------------------------------------------------
// filteredBottles — the central computed of the grid
// ---------------------------------------------------------------------------

describe('filteredBottles', () => {
    it('returns everything with no filters active', () => {
        expect(appWithBottles().filteredBottles.map(b => b.id)).toEqual(['1', '2', '3', '4']);
    });

    it('filters by type tab', () => {
        const app = appWithBottles();
        app.gridFilterType = 'wine';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1', '2']);
        app.gridFilterType = 'whiskey';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3', '4']);
    });

    it('searches across producer, name, year, region, country, variety, beverage_type and style', () => {
        const app = appWithBottles();

        app.gridSearchQuery = 'margaux';            // producer
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1']);

        app.gridSearchQuery = 'weller';             // name
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3']);

        app.gridSearchQuery = '2022';               // year
        expect(app.filteredBottles.map(b => b.id)).toEqual(['2']);

        app.gridSearchQuery = 'islay';              // region
        expect(app.filteredBottles.map(b => b.id)).toEqual(['4']);

        app.gridSearchQuery = 'zealand';            // country
        expect(app.filteredBottles.map(b => b.id)).toEqual(['2']);

        app.gridSearchQuery = 'merlot';             // variety list
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1']);

        app.gridSearchQuery = 'bourbon';            // beverage_type
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3']);

        app.gridSearchQuery = 'crisp';              // style
        expect(app.filteredBottles.map(b => b.id)).toEqual(['2']);

        app.gridSearchQuery = 'nothing-matches';
        expect(app.filteredBottles).toEqual([]);
    });

    it('matches the region filter against region OR country', () => {
        const app = appWithBottles();
        app.gridFilterRegion = 'Kentucky';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['3']);
        app.gridFilterRegion = 'New Zealand';       // bottle 2 has no region, only country
        expect(app.filteredBottles.map(b => b.id)).toEqual(['2']);
    });

    it('filters by beverage type', () => {
        const app = appWithBottles();
        app.gridFilterBeverageType = 'Scotch';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['4']);
    });

    it('filters by variety substring, case-insensitively', () => {
        const app = appWithBottles();
        app.gridFilterVariety = 'sauv';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1', '2']);
        app.gridFilterVariety = 'merlot';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1']);
    });

    it('filters by style and barrel type exactly', () => {
        const app = appWithBottles();
        app.gridFilterStyle = 'Bold';
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1']);

        const app2 = appWithBottles();
        app2.gridFilterBarrelType = 'Sherry Cask';
        expect(app2.filteredBottles.map(b => b.id)).toEqual(['4']);
    });

    it('hides out-of-stock bottles with the in-stock toggle', () => {
        const app = appWithBottles();
        app.gridFilterInStockOnly = true;
        expect(app.filteredBottles.map(b => b.id)).toEqual(['1', '3', '4']);
    });

    it('stacks filters', () => {
        const app = appWithBottles();
        app.gridFilterType = 'whiskey';
        app.gridFilterRegion = 'Islay';
        app.gridFilterInStockOnly = true;
        expect(app.filteredBottles.map(b => b.id)).toEqual(['4']);
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
        ['gridFilterRegion', 'Islay'],
        ['gridFilterBeverageType', 'Red'],
        ['gridFilterVariety', 'Merlot'],
        ['gridFilterStyle', 'Bold'],
        ['gridFilterBarrelType', 'New Oak'],
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
        app.gridFilterRegion = 'Bordeaux';
        app.gridFilterBeverageType = 'Red';
        app.gridFilterVariety = 'Merlot';
        app.gridFilterStyle = 'Bold';
        app.gridFilterBarrelType = 'New Oak';

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
        app.gridSearchQuery = 'weller';
        app.gridFilterBarrelType = 'New Oak';
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
        const app = appWithBottles();
        expect(app.gridAvailableRegions()).toEqual(
            ['Bordeaux', 'Islay', 'Kentucky', 'New Zealand'],
        );
    });

    it('gridAvailableRegions respects the current type tab', () => {
        const app = appWithBottles();
        app.gridFilterType = 'whiskey';
        expect(app.gridAvailableRegions()).toEqual(['Islay', 'Kentucky']);
    });

    it('gridAvailableBeverageTypes respects the current type tab', () => {
        const app = appWithBottles();
        expect(app.gridAvailableBeverageTypes()).toEqual(['Bourbon', 'Red', 'Scotch', 'White']);
        app.gridFilterType = 'wine';
        expect(app.gridAvailableBeverageTypes()).toEqual(['Red', 'White']);
    });

    it('gridAvailableVarieties flattens wine varieties only', () => {
        const app = appWithBottles();
        expect(app.gridAvailableVarieties()).toEqual(
            ['Cabernet Sauvignon', 'Merlot', 'Sauvignon Blanc'],
        );
    });

    it('gridAvailableStyles lists wine styles only', () => {
        const app = appWithBottles();
        expect(app.gridAvailableStyles()).toEqual(['Bold', 'Crisp']);
    });

    it('gridAvailableBarrelTypes lists whiskey barrels only', () => {
        const app = appWithBottles();
        expect(app.gridAvailableBarrelTypes()).toEqual(['New Oak', 'Sherry Cask']);
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
            bottle_name: 'Chateau Margaux - Grand Vin (2015)',
            producer: 'Chateau Margaux',
            thumbnail_url: '/api/v1/labels/thumbnail?id=1&size=400',
            beverage_type: 'wine',
            confidence: 1.0,
        });
        expect(window.location.href).toBe('/manual-tasting');
    });

    it('omits the year suffix when the bottle has no year', () => {
        const app = appWithBottles();
        app.navigateToCreateTasting(app.labelBottles[2]);
        const preselect = JSON.parse(sessionStorage.getItem('preselect_bottle'));
        expect(preselect.bottle_name).toBe('Buffalo Trace - Weller 12');
        expect(preselect.beverage_type).toBe('whiskey');
    });
});

// ---------------------------------------------------------------------------
// init — permissions + initial load
// ---------------------------------------------------------------------------

describe('init', () => {
    it('reads permissions from /api/v1/me and loads the collection', async () => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/me', jsonResponse({
                authenticated: true,
                permissions: { bottles_edit: true, tastings_submit: true },
            })],
            ['/api/v1/bottles/collection', jsonResponse({ bottles: BOTTLES, count: 4 })],
        ]));

        const app = freshApp();
        await app.init();

        expect(app.canEdit).toBe(true);
        expect(app.canCreateTasting).toBe(true);
        expect(app.labelBottles.length).toBe(4);
        expect(app.labelsLoading).toBe(false);
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
            return jsonResponse({ bottles: BOTTLES, count: 4 });
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
    it('fetches the exact collection endpoint and updates the timestamp', async () => {
        vi.spyOn(console, 'log').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/collection', jsonResponse({ bottles: BOTTLES, count: 4 })],
        ]));

        const app = freshApp();
        const before = app.labelGridTimestamp;
        await new Promise(r => setTimeout(r, 2));   // ensure Date.now() can advance
        await app.loadBottles();

        expect(fetch).toHaveBeenCalledWith('/api/v1/bottles/collection');
        expect(app.labelBottles).toEqual(BOTTLES);
        expect(app.labelGridTimestamp).toBeGreaterThanOrEqual(before);
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
