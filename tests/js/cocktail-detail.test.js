/**
 * Unit tests for the cocktail detail page component
 * (src/reserve_automation/web/static/js/cocktails/cocktail-detail.js).
 *
 * The real base-page module is imported so window.formatApiError is the
 * production implementation. Alpine itself is not loaded; the factory's
 * return value is used directly, the same way Alpine would.
 *
 * Fixtures mirror the API response shapes in web/routes/cocktails.py
 * (_cocktail_to_dict / _tasting_to_dict) and web/routes/ingredients.py
 * (_ingredient_to_dict).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/base-page.js';
import '../../src/reserve_automation/web/static/js/cocktails/cocktail-detail.js';

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

function freshApp(id = '7') {
    return window.cocktailDetailApp(id);
}

// Shape: routes/cocktails.py::_cocktail_to_dict
const COCKTAIL = {
    id: 7,
    name: 'Old Fashioned',
    description: 'A classic',
    ingredients: [
        { ingredient: 'bourbon', amount: 2, unit: 'oz', notes: null, optional: false },
        { ingredient: 'sugar', amount: 1, unit: 'barspoon', notes: 'demerara', optional: true },
    ],
    instructions: ['Stir with ice', 'Strain over a big cube'],
    garnish: 'orange peel',
    glassware: 'rocks',
    method: 'stirred',
    style: 'classic',
    serving_size: 1,
    stars: null,
    photo: null,
    avg_score: 8.5,
};

// Shape: routes/cocktails.py::_tasting_to_dict
const TASTINGS = [
    {
        id: 11, recipe_name: 'Old Fashioned', taster_name: 'Ben',
        tasting_date: '2026-06-01', score: 8, notes: 'good', bartender: 'Ben',
        bottles_used: [{ recipe_ingredient: 'bourbon', actual_product: 'Weller SR' }],
    },
    {
        id: 12, recipe_name: 'Old Fashioned', taster_name: 'Sarah',
        tasting_date: '2026-06-10', score: 6, notes: '', bartender: null,
        bottles_used: [],
    },
    {
        id: 13, recipe_name: 'Old Fashioned', taster_name: 'Guest',
        tasting_date: '2026-06-20', score: null, notes: 'no score', bartender: null,
        bottles_used: [],
    },
];

// Shape: routes/ingredients.py::_ingredient_to_dict
const ING_BOURBON = {
    id: 3, name: 'Bourbon', cost: null, abv: null,
    is_product: false, ancestors: ['Whiskey'],
};
const ING_WELLER = {
    id: 9, name: 'Weller Special Reserve', cost: 30, abv: 45,
    is_product: true, ancestors: ['Whiskey', 'Bourbon'],
};

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([]));
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('confirm', vi.fn(() => true));
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

describe('initial state', () => {
    it('captures the cocktailId passed from the template x-data', () => {
        expect(freshApp('42').cocktailId).toBe('42');
    });

    it('starts loading with empty tasting wizard state', () => {
        const app = freshApp();
        expect(app.cocktail).toBeNull();
        expect(app.loading).toBe(true);
        expect(app.tastings).toEqual([]);
        expect(app.avgScore).toBeNull();
        expect(app.showTastingForm).toBe(false);
        expect(app.tastingStep).toBe(1);
        expect(app.tastingData).toEqual({
            taster_name: '', score: 7, notes: '', bartender: '', bottles_used: [],
        });
        expect(app.bottleSearchQueries).toEqual({});
        expect(app.bottleResults).toEqual({});
        expect(app.showEditForm).toBe(false);
        expect(app.showEditTastingForm).toBe(false);
        expect(app.editData.ingredients).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// loadCocktail / loadTastings
// ---------------------------------------------------------------------------

describe('loadCocktail', () => {
    it('loads the cocktail, its tastings, and sibling names for parent selection', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/7/tastings', jsonResponse(TASTINGS)],
            ['/api/v1/cocktails/7', jsonResponse(COCKTAIL)],
            ['/api/v1/cocktails', jsonResponse([
                { ...COCKTAIL }, { ...COCKTAIL, id: 8, name: 'Moscow Mule' },
            ])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        await app.loadCocktail();

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/cocktails/7');
        expect(app.cocktail).toEqual(COCKTAIL);
        expect(app.tastings).toEqual(TASTINGS);
        // own name filtered out of the parent-cocktail datalist
        expect(app.cocktailNames).toEqual(['Moscow Mule']);
        expect(app.loading).toBe(false);
    });

    it('leaves cocktail null on a 404 but still clears loading', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/7', jsonResponse({ detail: 'Cocktail not found' }, { ok: false, status: 404 })],
        ]));
        const app = freshApp('7');
        await app.loadCocktail();
        expect(app.cocktail).toBeNull();
        expect(app.loading).toBe(false);
    });

    it('swallows network errors and clears loading', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom'); }));
        const app = freshApp('7');
        await app.loadCocktail();
        expect(app.cocktail).toBeNull();
        expect(app.loading).toBe(false);
        expect(console.error).toHaveBeenCalled();
    });
});

describe('loadTastings', () => {
    it('averages only the scored tastings', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/7/tastings', jsonResponse(TASTINGS)],
        ]));
        const app = freshApp('7');
        await app.loadTastings();
        expect(app.tastings).toEqual(TASTINGS);
        expect(app.avgScore).toBe(7); // (8 + 6) / 2, null score excluded
    });

    it('sets avgScore null when nothing is scored', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/tastings', jsonResponse([{ ...TASTINGS[2] }])],
        ]));
        const app = freshApp('7');
        app.avgScore = 5;
        await app.loadTastings();
        expect(app.avgScore).toBeNull();
    });

    it('keeps existing tastings on a failed response', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/tastings', jsonResponse({ detail: 'nope' }, { ok: false, status: 500 })],
        ]));
        const app = freshApp('7');
        app.tastings = TASTINGS;
        await app.loadTastings();
        expect(app.tastings).toEqual(TASTINGS);
    });
});

// ---------------------------------------------------------------------------
// Bottle search + selection (Rate This wizard, step 1)
// ---------------------------------------------------------------------------

describe('searchBottles', () => {
    it('searches by the typed query and sorts products first', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([ING_BOURBON, ING_WELLER])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        app.bottleSearchQueries[0] = 'weller';
        await app.searchBottles(0, 'bourbon');

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/search?q=weller');
        // is_product entries bubble to the top
        expect(app.bottleResults[0].map(r => r.name))
            .toEqual(['Weller Special Reserve', 'Bourbon']);
        // no query in the box -> did NOT fall back to the descendants flow
        expect(fetchMock).not.toHaveBeenCalledWith('/api/v1/ingredients?flat=true');
    });

    it('with no query, defaults to the recipe ingredient node plus its descendants', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([])],
            ['/api/v1/ingredients?flat=true', jsonResponse([ING_BOURBON, ING_WELLER])],
            ['/api/v1/ingredients/3/descendants', jsonResponse([ING_WELLER])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        await app.searchBottles(0, 'bourbon'); // matches "Bourbon" case-insensitively

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/search?q=bourbon');
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/3/descendants');
        expect(app.bottleResults[0].map(r => r.name))
            .toEqual(['Weller Special Reserve', 'Bourbon']);
    });

    it('with no query and no matching node, keeps the plain search results', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([ING_WELLER])],
            ['/api/v1/ingredients?flat=true', jsonResponse([])],
        ]));
        const app = freshApp('7');
        await app.searchBottles(1, 'rye');
        expect(app.bottleResults[1]).toEqual([ING_WELLER]);
    });

    it('swallows fetch failures', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp('7');
        await app.searchBottles(0, 'bourbon');
        expect(app.bottleResults[0]).toBeUndefined();
        expect(console.error).toHaveBeenCalled();
    });
});

describe('selectBottle', () => {
    it('records the selection, mirrors it into the query box, and closes the dropdown', () => {
        const app = freshApp('7');
        app.bottleResults[0] = [ING_WELLER];
        app.selectBottle(0, ING_WELLER, 'bourbon');
        expect(app.tastingData.bottles_used[0]).toEqual({
            recipe_ingredient: 'bourbon',
            actual_product: 'Weller Special Reserve',
        });
        expect(app.bottleSearchQueries[0]).toBe('Weller Special Reserve');
        expect(app.bottleResults[0]).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// createAndSelectIngredient (create-on-the-fly)
// ---------------------------------------------------------------------------

describe('createAndSelectIngredient', () => {
    it('does nothing when the query box is blank', async () => {
        const app = freshApp('7');
        app.bottleSearchQueries[0] = '   ';
        await app.createAndSelectIngredient(0, 'bourbon');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs the new ingredient parented under the recipe ingredient and selects it', async () => {
        const created = { ...ING_WELLER, name: 'New Rye' };
        const fetchMock = routeFetch([
            ['/api/v1/ingredients', jsonResponse(created)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        app.bottleSearchQueries[0] = '  New Rye ';
        await app.createAndSelectIngredient(0, 'bourbon');

        const [url, opts] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/v1/ingredients');
        expect(opts.method).toBe('POST');
        expect(JSON.parse(opts.body)).toEqual({ name: 'New Rye', parent: 'bourbon' });
        expect(app.tastingData.bottles_used[0]).toEqual({
            recipe_ingredient: 'bourbon', actual_product: 'New Rye',
        });
        expect(app.tastingError).toBe('');
    });

    it('retries at the root when the recipe-ingredient parent is rejected (400)', async () => {
        const created = { ...ING_WELLER, name: 'Fresh Mint' };
        let calls = 0;
        const fetchMock = routeFetch([
            ['/api/v1/ingredients', () => {
                calls += 1;
                return calls === 1
                    ? jsonResponse({ detail: 'bad parent' }, { ok: false, status: 400 })
                    : jsonResponse(created);
            }],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        app.bottleSearchQueries[0] = 'Fresh Mint';
        await app.createAndSelectIngredient(0, 'mint');

        expect(JSON.parse(fetchMock.mock.calls[0][1].body).parent).toBe('mint');
        expect(JSON.parse(fetchMock.mock.calls[1][1].body).parent).toBeNull();
        expect(app.tastingData.bottles_used[0].actual_product).toBe('Fresh Mint');
    });

    it('uses the typed name as-is when it already exists (409)', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients', jsonResponse({ detail: 'exists' }, { ok: false, status: 409 })],
        ]));
        const app = freshApp('7');
        app.bottleSearchQueries[0] = 'Angostura';
        await app.createAndSelectIngredient(0, 'bitters');
        expect(app.tastingData.bottles_used[0]).toEqual({
            recipe_ingredient: 'bitters', actual_product: 'Angostura',
        });
        expect(app.tastingError).toBe('');
    });

    it('surfaces API validation errors through formatApiError', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients', jsonResponse(
                { detail: [{ loc: ['body', 'name'], msg: 'too long' }] },
                { ok: false, status: 422 },
            )],
        ]));
        const app = freshApp('7');
        app.bottleSearchQueries[0] = 'X';
        await app.createAndSelectIngredient(0, 'bourbon');
        expect(app.tastingError).toBe('name: too long');
        expect(app.tastingData.bottles_used[0]).toBeUndefined();
    });

    it('reports thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('net down'); }));
        const app = freshApp('7');
        app.bottleSearchQueries[0] = 'X';
        await app.createAndSelectIngredient(0, 'bourbon');
        expect(app.tastingError).toBe('net down');
    });
});

// ---------------------------------------------------------------------------
// Tasting form save/close
// ---------------------------------------------------------------------------

describe('closeTastingForm', () => {
    it('resets the wizard to step 1 with fresh data', () => {
        const app = freshApp('7');
        app.showTastingForm = true;
        app.tastingStep = 2;
        app.tastingData.taster_name = 'Ben';
        app.bottleSearchQueries[0] = 'weller';
        app.bottleResults[0] = [ING_WELLER];

        app.closeTastingForm();

        expect(app.showTastingForm).toBe(false);
        expect(app.tastingStep).toBe(1);
        expect(app.tastingData).toEqual({
            taster_name: '', score: 7, notes: '', bartender: '', bottles_used: [],
        });
        expect(app.bottleSearchQueries).toEqual({});
        expect(app.bottleResults).toEqual({});
    });
});

describe('saveTasting', () => {
    it('requires a taster name before hitting the API', async () => {
        const app = freshApp('7');
        app.tastingData.taster_name = '  ';
        await app.saveTasting();
        expect(app.tastingError).toBe('Name is required');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs the tasting with sparse/empty bottles_used entries dropped', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/7/tastings', (url, opts) =>
                opts && opts.method === 'POST'
                    ? jsonResponse(TASTINGS[0])
                    : jsonResponse(TASTINGS)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        app.showTastingForm = true;
        app.tastingData.taster_name = 'Ben';
        app.tastingData.score = 8.5;
        app.tastingData.notes = 'zesty';
        app.tastingData.bartender = 'Sarah';
        // Sparse: slot 0 empty product, slot 1 unset (hole), slot 2 selected
        app.tastingData.bottles_used[0] = { recipe_ingredient: 'bourbon', actual_product: '  ' };
        app.tastingData.bottles_used[2] = { recipe_ingredient: 'sugar', actual_product: 'Demerara' };

        await app.saveTasting();

        const postCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'POST');
        expect(postCall[0]).toBe('/api/v1/cocktails/7/tastings');
        expect(JSON.parse(postCall[1].body)).toEqual({
            taster_name: 'Ben',
            score: 8.5,
            notes: 'zesty',
            bartender: 'Sarah',
            bottles_used: [{ recipe_ingredient: 'sugar', actual_product: 'Demerara' }],
        });
        // closed + tastings reloaded
        expect(app.showTastingForm).toBe(false);
        expect(app.tastings).toEqual(TASTINGS);
        expect(app.tastingSaving).toBe(false);
    });

    it('shows the API error detail and keeps the form open', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/tastings', jsonResponse({ detail: 'Cocktail not found' }, { ok: false, status: 404 })],
        ]));
        const app = freshApp('7');
        app.showTastingForm = true;
        app.tastingData.taster_name = 'Ben';
        await app.saveTasting();
        expect(app.tastingError).toBe('Cocktail not found');
        expect(app.showTastingForm).toBe(true);
        expect(app.tastingSaving).toBe(false);
    });

    it('reports thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('nope'); }));
        const app = freshApp('7');
        app.tastingData.taster_name = 'Ben';
        await app.saveTasting();
        expect(app.tastingError).toBe('nope');
        expect(app.tastingSaving).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// Recipe edit modal
// ---------------------------------------------------------------------------

describe('openEditForm', () => {
    it('deep-copies the cocktail into editData and lazily loads ingredient names', () => {
        const fetchMock = routeFetch([
            ['/api/v1/ingredients?flat=true', jsonResponse([ING_BOURBON])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        app.cocktail = JSON.parse(JSON.stringify(COCKTAIL));
        app.openEditForm();

        expect(app.showEditForm).toBe(true);
        expect(app.editData.name).toBe('Old Fashioned');
        expect(app.editData.description).toBe('A classic');
        // API responses never include parent_cocktail -> defaults to ''
        expect(app.editData.parent_cocktail).toBe('');
        expect(app.editData.ingredients).toEqual(COCKTAIL.ingredients);
        // deep copy: mutating editData must not touch the displayed cocktail
        app.editData.ingredients[0].ingredient = 'rye';
        expect(app.cocktail.ingredients[0].ingredient).toBe('bourbon');
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients?flat=true');
    });

    it('seeds one empty ingredient and instruction row for bare recipes', () => {
        const app = freshApp('7');
        app.ingredientNames = ['Bourbon']; // already loaded -> no fetch
        app.cocktail = { ...COCKTAIL, ingredients: [], instructions: [], description: null,
                         method: null, style: null, glassware: null, garnish: null };
        app.openEditForm();
        expect(fetch).not.toHaveBeenCalled();
        expect(app.editData.ingredients).toEqual([
            { ingredient: '', amount: null, unit: 'oz', notes: '', optional: false },
        ]);
        expect(app.editData.instructions).toEqual(['']);
        expect(app.editData.method).toBe('');
        expect(app.editData.garnish).toBe('');
    });
});

describe('saveEdit', () => {
    it('requires a name', async () => {
        const app = freshApp('7');
        app.editData.name = ' ';
        await app.saveEdit();
        expect(app.editError).toBe('Name is required');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('PUTs the recipe with blank rows filtered and empty strings nulled', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/7/tastings', jsonResponse([])],
            ['/api/v1/cocktails/7', (url, opts) =>
                opts && opts.method === 'PUT' ? jsonResponse(COCKTAIL) : jsonResponse(COCKTAIL)],
            ['/api/v1/cocktails', jsonResponse([COCKTAIL])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        app.showEditForm = true;
        app.editData = {
            name: 'Old Fashioned', description: '', parent_cocktail: '',
            method: 'stirred', style: '', glassware: 'rocks', garnish: '',
            ingredients: [
                { ingredient: 'bourbon', amount: 2, unit: 'oz', notes: '', optional: false },
                { ingredient: '  ', amount: null, unit: 'oz', notes: '', optional: false },
            ],
            instructions: ['Stir', '  ', ''],
        };
        await app.saveEdit();

        const putCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'PUT');
        expect(putCall[0]).toBe('/api/v1/cocktails/7');
        expect(JSON.parse(putCall[1].body)).toEqual({
            name: 'Old Fashioned',
            description: null,
            parent_cocktail: null,
            method: 'stirred',
            style: null,
            glassware: 'rocks',
            garnish: null,
            ingredients: [{ ingredient: 'bourbon', amount: 2, unit: 'oz', notes: '', optional: false }],
            instructions: ['Stir'],
        });
        expect(app.showEditForm).toBe(false);
        // reloaded the cocktail afterwards
        expect(app.cocktail).toEqual(COCKTAIL);
        expect(app.editSaving).toBe(false);
    });

    it('shows the API error and keeps the modal open', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/7', jsonResponse({ detail: 'name taken' }, { ok: false, status: 400 })],
        ]));
        const app = freshApp('7');
        app.showEditForm = true;
        app.editData.name = 'Old Fashioned';
        await app.saveEdit();
        expect(app.editError).toBe('name taken');
        expect(app.showEditForm).toBe(true);
        expect(app.editSaving).toBe(false);
    });

    it('reports thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down'); }));
        const app = freshApp('7');
        app.editData.name = 'Old Fashioned';
        await app.saveEdit();
        expect(app.editError).toBe('down');
    });
});

// ---------------------------------------------------------------------------
// Deletes
// ---------------------------------------------------------------------------

describe('deleteCocktail', () => {
    it('is confirm-gated', async () => {
        vi.stubGlobal('confirm', vi.fn(() => false));
        const app = freshApp('7');
        await app.deleteCocktail();
        expect(fetch).not.toHaveBeenCalled();
    });

    it('DELETEs and navigates back to the list', async () => {
        vi.stubGlobal('location', { href: '' });
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/7', jsonResponse({ message: 'deleted' })],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        await app.deleteCocktail();

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/cocktails/7', { method: 'DELETE' });
        expect(window.location.href).toBe('/cocktails');
    });

    it('alerts on network failure', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp('7');
        await app.deleteCocktail();
        expect(alert).toHaveBeenCalledWith('Failed to delete: offline');
    });
});

describe('deleteTasting', () => {
    it('is confirm-gated', async () => {
        vi.stubGlobal('confirm', vi.fn(() => false));
        const app = freshApp('7');
        await app.deleteTasting(11);
        expect(fetch).not.toHaveBeenCalled();
    });

    it('DELETEs the tasting and reloads the history', async () => {
        const remaining = [TASTINGS[1]];
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/7/tastings/11', jsonResponse({ message: 'deleted' })],
            ['/api/v1/cocktails/7/tastings', jsonResponse(remaining)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        await app.deleteTasting(11);

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/v1/cocktails/7/tastings/11', { method: 'DELETE' });
        expect(app.tastings).toEqual(remaining);
    });

    it('alerts when the API refuses', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/tastings/11', jsonResponse({ detail: 'nope' }, { ok: false, status: 403 })],
        ]));
        const app = freshApp('7');
        await app.deleteTasting(11);
        expect(alert).toHaveBeenCalledWith('Failed to delete tasting');
    });

    it('alerts on network failure', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp('7');
        await app.deleteTasting(11);
        expect(alert).toHaveBeenCalledWith('Failed to delete: offline');
    });
});

// ---------------------------------------------------------------------------
// Edit-tasting modal
// ---------------------------------------------------------------------------

describe('openEditTastingModal', () => {
    it('indexes bottles_used by the recipe ingredient positions', () => {
        const app = freshApp('7');
        app.cocktail = COCKTAIL;
        app.openEditTastingModal(TASTINGS[0]);

        expect(app.editingTastingId).toBe(11);
        expect(app.showEditTastingForm).toBe(true);
        expect(app.editTastingError).toBe('');
        expect(app.editTastingData.taster_name).toBe('Ben');
        expect(app.editTastingData.tasting_date).toBe('2026-06-01');
        expect(app.editTastingData.score).toBe(8);
        expect(app.editTastingData.bottles_used).toEqual([
            { recipe_ingredient: 'bourbon', actual_product: 'Weller SR' },
            { recipe_ingredient: 'sugar', actual_product: '' },
        ]);
        expect(app.editBottleQueries).toEqual({ 0: 'Weller SR', 1: '' });
    });

    it('defaults a null score to 7 and missing fields to empty strings', () => {
        const app = freshApp('7');
        app.cocktail = COCKTAIL;
        app.openEditTastingModal(TASTINGS[2]);
        expect(app.editTastingData.score).toBe(7);
        expect(app.editTastingData.bartender).toBe('');
        expect(app.editTastingData.notes).toBe('no score');
    });

    it('copes with the cocktail not being loaded yet', () => {
        const app = freshApp('7');
        app.cocktail = null;
        app.openEditTastingModal(TASTINGS[1]);
        expect(app.editTastingData.bottles_used).toEqual([]);
    });
});

// Edit mode reuses the SAME searchBottles implementation (ONE PATH) — the
// 'edit' mode argument only redirects which query/result buckets are used.
describe('searchBottles (edit mode)', () => {
    it('searches by the typed query, reading/writing the edit buckets', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([ING_BOURBON, ING_WELLER])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        app.editBottleQueries[0] = 'weller';
        await app.searchBottles(0, 'bourbon', 'edit');

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/search?q=weller');
        expect(app.editBottleResults[0].map(r => r.name))
            .toEqual(['Weller Special Reserve', 'Bourbon']);
        // add-mode buckets untouched
        expect(app.bottleResults).toEqual({});
    });

    it('with no query, defaults to the recipe node plus descendants', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([])],
            ['/api/v1/ingredients?flat=true', jsonResponse([ING_BOURBON])],
            ['/api/v1/ingredients/3/descendants', jsonResponse([ING_WELLER])],
        ]));
        const app = freshApp('7');
        await app.searchBottles(0, 'Bourbon', 'edit');
        expect(app.editBottleResults[0].map(r => r.name))
            .toEqual(['Weller Special Reserve', 'Bourbon']);
    });

    it('ignores the add-mode query for the same slot', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([ING_WELLER])],
            ['/api/v1/ingredients?flat=true', jsonResponse([])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('7');
        app.bottleSearchQueries[0] = 'weller'; // add-mode bucket must not leak in
        await app.searchBottles(0, 'rye', 'edit');
        // empty edit query -> falls back to the recipe ingredient
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/search?q=rye');
        expect(app.editBottleResults[0]).toEqual([ING_WELLER]);
    });

    it('bails silently on a failed search', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp('7');
        await app.searchBottles(0, 'bourbon', 'edit');
        expect(app.editBottleResults[0]).toBeUndefined();
    });

    it('swallows thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp('7');
        await expect(app.searchBottles(0, 'bourbon', 'edit')).resolves.toBeUndefined();
        expect(console.error).toHaveBeenCalled();
    });
});

describe('selectEditBottle', () => {
    it('records the selection into editTastingData and closes the dropdown', () => {
        const app = freshApp('7');
        app.editTastingData = { bottles_used: [] };
        app.editBottleResults[1] = [ING_WELLER];
        app.selectEditBottle(1, ING_WELLER, 'bourbon');
        expect(app.editTastingData.bottles_used[1]).toEqual({
            recipe_ingredient: 'bourbon', actual_product: 'Weller Special Reserve',
        });
        expect(app.editBottleQueries[1]).toBe('Weller Special Reserve');
        expect(app.editBottleResults[1]).toEqual([]);
    });
});

describe('saveEditTasting', () => {
    function seededApp() {
        const app = freshApp('7');
        app.editingTastingId = 11;
        app.showEditTastingForm = true;
        app.editTastingData = {
            taster_name: 'Ben',
            tasting_date: '2026-06-01',
            score: '8.5',
            notes: 'better',
            bartender: 'Sarah',
            bottles_used: [
                { recipe_ingredient: 'bourbon', actual_product: 'Weller SR' },
                { recipe_ingredient: 'sugar', actual_product: '' },
            ],
        };
        return app;
    }

    it('PATCHes the tasting with parsed score and empty bottle rows dropped', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/7/tastings/11', jsonResponse(TASTINGS[0])],
            ['/api/v1/cocktails/7/tastings', jsonResponse(TASTINGS)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = seededApp();
        await app.saveEditTasting();

        const patchCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'PATCH');
        expect(patchCall[0]).toBe('/api/v1/cocktails/7/tastings/11');
        expect(JSON.parse(patchCall[1].body)).toEqual({
            taster_name: 'Ben',
            tasting_date: '2026-06-01',
            score: 8.5,
            notes: 'better',
            bartender: 'Sarah',
            bottles_used: [{ recipe_ingredient: 'bourbon', actual_product: 'Weller SR' }],
        });
        expect(app.showEditTastingForm).toBe(false);
        expect(app.tastings).toEqual(TASTINGS);
    });

    it('sends a null score when the slider value is empty', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/7/tastings/11', jsonResponse(TASTINGS[0])],
            ['/api/v1/cocktails/7/tastings', jsonResponse(TASTINGS)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = seededApp();
        app.editTastingData.score = '';
        await app.saveEditTasting();

        const patchCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'PATCH');
        expect(JSON.parse(patchCall[1].body).score).toBeNull();
    });

    it('surfaces server errors without closing the modal', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/7/tastings/11', jsonResponse({ detail: 'Tasting not found' }, { ok: false, status: 404 })],
        ]));
        const app = seededApp();
        await app.saveEditTasting();
        expect(app.editTastingError).toBe('Failed to save: Tasting not found');
        expect(app.showEditTastingForm).toBe(true);
    });

    it('falls back to the status code when the error body is not JSON', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/7/tastings/11', {
                ok: false, status: 500,
                json: async () => { throw new Error('not json'); },
            }],
        ]));
        const app = seededApp();
        await app.saveEditTasting();
        expect(app.editTastingError).toBe('Failed to save: Server error 500');
    });
});

// ---------------------------------------------------------------------------
// Navigation + autocomplete helpers
// ---------------------------------------------------------------------------

describe('viewIngredient', () => {
    it('navigates to the ingredients page with an auto-search hash', async () => {
        vi.stubGlobal('location', { href: '' });
        const app = freshApp('7');
        await app.viewIngredient('Angostura & Co');
        expect(window.location.href)
            .toBe(`/ingredients#search=${encodeURIComponent('Angostura & Co')}`);
    });
});

describe('handleAutocomplete', () => {
    function keyEvent(key, value) {
        const target = document.createElement('input');
        target.value = value;
        return {
            key,
            target,
            preventDefault: vi.fn(),
        };
    }

    it('ignores keys other than Tab/Enter', () => {
        const app = freshApp('7');
        const event = keyEvent('a', 'bo');
        app.handleAutocomplete(event, ['Bourbon']);
        expect(event.preventDefault).not.toHaveBeenCalled();
        expect(event.target.value).toBe('bo');
    });

    it('ignores empty input', () => {
        const app = freshApp('7');
        const event = keyEvent('Tab', '   ');
        app.handleAutocomplete(event, ['Bourbon']);
        expect(event.preventDefault).not.toHaveBeenCalled();
    });

    it('prefers a starts-with match and fires an input event for x-model', () => {
        const app = freshApp('7');
        const event = keyEvent('Tab', 'bo');
        const inputSpy = vi.fn();
        event.target.addEventListener('input', inputSpy);
        app.handleAutocomplete(event, ['Absinthe', 'Bourbon', 'Old Bourbon Blend']);
        expect(event.target.value).toBe('Bourbon');
        expect(event.preventDefault).toHaveBeenCalled();
        expect(inputSpy).toHaveBeenCalled();
    });

    it('falls back to a contains match on Enter', () => {
        const app = freshApp('7');
        const event = keyEvent('Enter', 'fashion');
        app.handleAutocomplete(event, ['Old Fashioned', 'Martini']);
        expect(event.target.value).toBe('Old Fashioned');
        expect(event.preventDefault).toHaveBeenCalled();
    });

    it('does nothing when nothing matches', () => {
        const app = freshApp('7');
        const event = keyEvent('Tab', 'zzz');
        app.handleAutocomplete(event, ['Bourbon']);
        expect(event.target.value).toBe('zzz');
        expect(event.preventDefault).not.toHaveBeenCalled();
    });
});
