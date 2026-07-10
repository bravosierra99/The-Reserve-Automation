/**
 * Unit tests for the cocktail detail page component
 * (src/reserve_automation/web/static/js/cocktails/cocktail-detail.js).
 *
 * The real base-page module is imported so window.formatApiError is the
 * production implementation. Alpine itself is not loaded; the factory's
 * return value is used directly, the same way Alpine would.
 *
 * API-response fixtures are NOT hand-written: they are contract fixtures —
 * real responses captured and snapshot-verified by
 * tests/contract/test_cocktails_contract.py and
 * tests/contract/test_ingredients_contract.py (see tests/contract/contract.py
 * for the rationale). Per-test variants mutate a fresh clone of the loaded
 * contract object.
 *
 * Contract flow data: the detail cocktail is the Wisconsin Old Fashioned
 * (id "2", parent_cocktail "Old Fashioned" — the field whose omission caused
 * the July 2026 edit-wipe bug) with ingredients [Brandy, Angostura Bitters,
 * Sugar, Lemon-Lime Soda]. Tastings: Ben 9 (2026-07-07, Korbel Brandy +
 * Angostura selected), Sarah 8 (2026-07-06) -> avg 8.5. NOTE: the real API
 * returns ids as STRINGS, recipe-row notes as '' (not null), and
 * bottles_used in ITS OWN order, not submission order — the modal maps them
 * by recipe_ingredient name, so order must not matter.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
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

// The contract detail cocktail has id "2"
function freshApp(id = '2') {
    return window.cocktailDetailApp(id);
}

const cocktailDetail = () => loadContract('cocktail_detail');
const cocktailTastings = () => loadContract('cocktail_tastings');
const cocktailsList = () => loadContract('cocktails_list');
const ingredientsSearch = () => loadContract('ingredients_search'); // q=bo: Bourbon + Buffalo Trace Bourbon
const ingredientsFlat = () => loadContract('ingredients_flat');
const whiskeyDescendants = () => loadContract('ingredient_descendants'); // of Whiskey (id "1")
const createdIngredient = () => loadContract('ingredient_create_response'); // Angostura Bitters

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
        const cocktail = cocktailDetail();
        const tastings = cocktailTastings();
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/2/tastings', jsonResponse(tastings)],
            ['/api/v1/cocktails/2', jsonResponse(cocktail)],
            ['/api/v1/cocktails', jsonResponse(cocktailsList())],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        await app.loadCocktail();

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/cocktails/2');
        expect(app.cocktail).toEqual(cocktail);
        expect(app.tastings).toEqual(tastings);
        // own name filtered out of the parent-cocktail datalist
        expect(app.cocktailNames).toEqual(['Manhattan', 'Old Fashioned']);
        expect(app.loading).toBe(false);
    });

    it('leaves cocktail null on a 404 but still clears loading', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/2', jsonResponse({ detail: 'Cocktail not found' }, { ok: false, status: 404 })],
        ]));
        const app = freshApp('2');
        await app.loadCocktail();
        expect(app.cocktail).toBeNull();
        expect(app.loading).toBe(false);
    });

    it('swallows network errors and clears loading', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom'); }));
        const app = freshApp('2');
        await app.loadCocktail();
        expect(app.cocktail).toBeNull();
        expect(app.loading).toBe(false);
        expect(console.error).toHaveBeenCalled();
    });
});

describe('loadTastings', () => {
    it('averages the scored tastings (contract data: Ben 9, Sarah 8)', async () => {
        const tastings = cocktailTastings();
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/2/tastings', jsonResponse(tastings)],
        ]));
        const app = freshApp('2');
        await app.loadTastings();
        expect(app.tastings).toEqual(tastings);
        expect(app.avgScore).toBe(8.5);
    });

    it('excludes unscored tastings from the average', async () => {
        // Variant: a third tasting without a score must not drag the average
        const tastings = cocktailTastings();
        tastings.push({ ...tastings[1], id: '3', taster_name: 'Guest', score: null });
        vi.stubGlobal('fetch', routeFetch([['/tastings', jsonResponse(tastings)]]));
        const app = freshApp('2');
        await app.loadTastings();
        expect(app.avgScore).toBe(8.5);
    });

    it('sets avgScore null when nothing is scored', async () => {
        const unscored = { ...cocktailTastings()[1], score: null };
        vi.stubGlobal('fetch', routeFetch([
            ['/tastings', jsonResponse([unscored])],
        ]));
        const app = freshApp('2');
        app.avgScore = 5;
        await app.loadTastings();
        expect(app.avgScore).toBeNull();
    });

    it('keeps existing tastings on a failed response', async () => {
        const tastings = cocktailTastings();
        vi.stubGlobal('fetch', routeFetch([
            ['/tastings', jsonResponse({ detail: 'nope' }, { ok: false, status: 500 })],
        ]));
        const app = freshApp('2');
        app.tastings = tastings;
        await app.loadTastings();
        expect(app.tastings).toEqual(tastings);
    });
});

// ---------------------------------------------------------------------------
// Bottle search + selection (Rate This wizard, step 1)
// ---------------------------------------------------------------------------

describe('searchBottles', () => {
    it('searches by the typed query and sorts products first', async () => {
        // Contract order is [Bourbon (category), Buffalo Trace Bourbon
        // (product)] — the component must flip the product to the top.
        const fetchMock = routeFetch([
            ['/api/v1/ingredients/search', jsonResponse(ingredientsSearch())],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        app.bottleSearchQueries[0] = 'bo';
        await app.searchBottles(0, 'Brandy');

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/search?q=bo');
        expect(app.bottleResults[0].map(r => r.name))
            .toEqual(['Buffalo Trace Bourbon', 'Bourbon']);
        // typed query -> did NOT fall back to the descendants flow
        expect(fetchMock).not.toHaveBeenCalledWith('/api/v1/ingredients?flat=true');
    });

    it('with no query, defaults to the recipe ingredient node plus its descendants', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([])],
            ['/api/v1/ingredients?flat=true', jsonResponse(ingredientsFlat())],
            ['/api/v1/ingredients/1/descendants', jsonResponse(whiskeyDescendants())],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        await app.searchBottles(0, 'whiskey'); // matches "Whiskey" case-insensitively

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/search?q=whiskey');
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/1/descendants');
        // [Whiskey, Bourbon, Buffalo Trace, Eagle Rare] products-first sorted
        expect(app.bottleResults[0].map(r => r.name)).toEqual([
            'Buffalo Trace Bourbon', 'Eagle Rare 10 Year', 'Whiskey', 'Bourbon',
        ]);
    });

    it('with no query and no matching node, keeps the plain search results', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse(ingredientsSearch())],
            ['/api/v1/ingredients?flat=true', jsonResponse([])],
        ]));
        const app = freshApp('2');
        await app.searchBottles(1, 'Rye');
        expect(app.bottleResults[1].map(r => r.name))
            .toEqual(['Buffalo Trace Bourbon', 'Bourbon']);
    });

    it('swallows fetch failures', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp('2');
        await app.searchBottles(0, 'Brandy');
        expect(app.bottleResults[0]).toBeUndefined();
        expect(console.error).toHaveBeenCalled();
    });
});

describe('selectBottle', () => {
    it('records the selection, mirrors it into the query box, and closes the dropdown', () => {
        const product = ingredientsSearch()[1]; // Buffalo Trace Bourbon
        const app = freshApp('2');
        app.bottleResults[0] = [product];
        app.selectBottle(0, product, 'Bourbon');
        expect(app.tastingData.bottles_used[0]).toEqual({
            recipe_ingredient: 'Bourbon',
            actual_product: 'Buffalo Trace Bourbon',
        });
        expect(app.bottleSearchQueries[0]).toBe('Buffalo Trace Bourbon');
        expect(app.bottleResults[0]).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// createAndSelectIngredient (create-on-the-fly) — the success response is the
// contract fixture for POST /api/v1/ingredients.
// ---------------------------------------------------------------------------

describe('createAndSelectIngredient', () => {
    it('does nothing when the query box is blank', async () => {
        const app = freshApp('2');
        app.bottleSearchQueries[0] = '   ';
        await app.createAndSelectIngredient(0, 'Brandy');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs the new ingredient parented under the recipe ingredient and selects it', async () => {
        const created = createdIngredient(); // Angostura Bitters
        const fetchMock = routeFetch([
            ['/api/v1/ingredients', jsonResponse(created)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        app.bottleSearchQueries[0] = '  Angostura Bitters ';
        await app.createAndSelectIngredient(0, 'Bitters');

        const [url, opts] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/v1/ingredients');
        expect(opts.method).toBe('POST');
        expect(JSON.parse(opts.body)).toEqual({ name: 'Angostura Bitters', parent: 'Bitters' });
        expect(app.tastingData.bottles_used[0]).toEqual({
            recipe_ingredient: 'Bitters', actual_product: 'Angostura Bitters',
        });
        expect(app.tastingError).toBe('');
    });

    it('retries at the root when the recipe-ingredient parent is rejected (400)', async () => {
        const created = { ...createdIngredient(), name: 'Fresh Mint', parent: null };
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

        const app = freshApp('2');
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
        const app = freshApp('2');
        app.bottleSearchQueries[0] = 'Angostura';
        await app.createAndSelectIngredient(0, 'Bitters');
        expect(app.tastingData.bottles_used[0]).toEqual({
            recipe_ingredient: 'Bitters', actual_product: 'Angostura',
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
        const app = freshApp('2');
        app.bottleSearchQueries[0] = 'X';
        await app.createAndSelectIngredient(0, 'Brandy');
        expect(app.tastingError).toBe('name: too long');
        expect(app.tastingData.bottles_used[0]).toBeUndefined();
    });

    it('reports thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('net down'); }));
        const app = freshApp('2');
        app.bottleSearchQueries[0] = 'X';
        await app.createAndSelectIngredient(0, 'Brandy');
        expect(app.tastingError).toBe('net down');
    });
});

// ---------------------------------------------------------------------------
// Tasting form save/close — the POST body assertions mirror what the wizard
// builds; the contract producer (test_cocktails_contract.py) sends these
// exact payloads to the real API.
// ---------------------------------------------------------------------------

describe('closeTastingForm', () => {
    it('resets the wizard to step 1 with fresh data', () => {
        const app = freshApp('2');
        app.showTastingForm = true;
        app.tastingStep = 2;
        app.tastingData.taster_name = 'Ben';
        app.bottleSearchQueries[0] = 'korbel';
        app.bottleResults[0] = ingredientsSearch();

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
        const app = freshApp('2');
        app.tastingData.taster_name = '  ';
        await app.saveTasting();
        expect(app.tastingError).toBe('Name is required');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs the tasting with sparse/empty bottles_used entries dropped', async () => {
        const tastings = cocktailTastings();
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/2/tastings', (url, opts) =>
                opts && opts.method === 'POST'
                    ? jsonResponse(tastings[0])
                    : jsonResponse(tastings)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        app.showTastingForm = true;
        app.tastingData.taster_name = 'Ben';
        app.tastingData.score = 9;
        app.tastingData.notes = 'Nailed the supper club vibe';
        app.tastingData.bartender = 'Sarah';
        // Sparse: slot 0 empty product, slot 1 unset (hole), slot 2 selected
        app.tastingData.bottles_used[0] = { recipe_ingredient: 'Brandy', actual_product: '  ' };
        app.tastingData.bottles_used[2] = { recipe_ingredient: 'Sugar', actual_product: 'Demerara Cube' };

        await app.saveTasting();

        const postCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'POST');
        expect(postCall[0]).toBe('/api/v1/cocktails/2/tastings');
        expect(JSON.parse(postCall[1].body)).toEqual({
            taster_name: 'Ben',
            score: 9,
            notes: 'Nailed the supper club vibe',
            bartender: 'Sarah',
            bottles_used: [{ recipe_ingredient: 'Sugar', actual_product: 'Demerara Cube' }],
        });
        // closed + tastings reloaded
        expect(app.showTastingForm).toBe(false);
        expect(app.tastings).toEqual(tastings);
        expect(app.tastingSaving).toBe(false);
    });

    it('shows the API error detail and keeps the form open', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/tastings', jsonResponse({ detail: 'Cocktail not found' }, { ok: false, status: 404 })],
        ]));
        const app = freshApp('2');
        app.showTastingForm = true;
        app.tastingData.taster_name = 'Ben';
        await app.saveTasting();
        expect(app.tastingError).toBe('Cocktail not found');
        expect(app.showTastingForm).toBe(true);
        expect(app.tastingSaving).toBe(false);
    });

    it('reports thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('nope'); }));
        const app = freshApp('2');
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
    it('deep-copies the cocktail into editData, including parent_cocktail', () => {
        const fetchMock = routeFetch([
            ['/api/v1/ingredients?flat=true', jsonResponse(ingredientsFlat())],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const cocktail = cocktailDetail();
        const app = freshApp('2');
        app.cocktail = cocktail;
        app.openEditForm();

        expect(app.showEditForm).toBe(true);
        expect(app.editData.name).toBe('Wisconsin Old Fashioned');
        expect(app.editData.description).toBe('Brandy old fashioned sweet, the supper club standard');
        // The contract response DOES carry parent_cocktail — the edit form
        // must seed it or every save wipes the stored parent (July 2026 bug;
        // the old hand-written fixture omitted the field and masked this).
        expect(app.editData.parent_cocktail).toBe('Old Fashioned');
        expect(app.editData.ingredients).toEqual(cocktail.ingredients);
        // deep copy: mutating editData must not touch the displayed cocktail
        app.editData.ingredients[0].ingredient = 'Rye';
        expect(app.cocktail.ingredients[0].ingredient).toBe('Brandy');
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients?flat=true');
    });

    it('seeds one empty ingredient and instruction row for bare recipes', () => {
        const app = freshApp('2');
        app.ingredientNames = ['Brandy']; // already loaded -> no fetch
        app.cocktail = {
            ...cocktailDetail(), ingredients: [], instructions: [], description: null,
            parent_cocktail: null, method: null, style: null, glassware: null, garnish: null,
        };
        app.openEditForm();
        expect(fetch).not.toHaveBeenCalled();
        expect(app.editData.ingredients).toEqual([
            { ingredient: '', amount: null, unit: 'oz', notes: '', optional: false },
        ]);
        expect(app.editData.instructions).toEqual(['']);
        expect(app.editData.method).toBe('');
        expect(app.editData.garnish).toBe('');
        expect(app.editData.parent_cocktail).toBe('');
    });
});

describe('saveEdit', () => {
    it('requires a name', async () => {
        const app = freshApp('2');
        app.editData.name = ' ';
        await app.saveEdit();
        expect(app.editError).toBe('Name is required');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('PUTs the recipe with blank rows filtered and empty strings nulled', async () => {
        const cocktail = cocktailDetail();
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/2/tastings', jsonResponse(cocktailTastings())],
            ['/api/v1/cocktails/2', jsonResponse(cocktail)],
            ['/api/v1/cocktails', jsonResponse(cocktailsList())],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        app.showEditForm = true;
        app.editData = {
            name: 'Wisconsin Old Fashioned', description: '', parent_cocktail: 'Old Fashioned',
            method: 'built', style: '', glassware: 'rocks', garnish: '',
            ingredients: [
                { ingredient: 'Brandy', amount: 2, unit: 'oz', notes: '', optional: false },
                { ingredient: '  ', amount: null, unit: 'oz', notes: '', optional: false },
            ],
            instructions: ['Build over ice', '  ', ''],
        };
        await app.saveEdit();

        const putCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'PUT');
        expect(putCall[0]).toBe('/api/v1/cocktails/2');
        expect(JSON.parse(putCall[1].body)).toEqual({
            name: 'Wisconsin Old Fashioned',
            description: null,
            parent_cocktail: 'Old Fashioned',
            method: 'built',
            style: null,
            glassware: 'rocks',
            garnish: null,
            ingredients: [{ ingredient: 'Brandy', amount: 2, unit: 'oz', notes: '', optional: false }],
            instructions: ['Build over ice'],
        });
        expect(app.showEditForm).toBe(false);
        // reloaded the cocktail afterwards
        expect(app.cocktail).toEqual(cocktail);
        expect(app.editSaving).toBe(false);
    });

    it('shows the API error and keeps the modal open', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/2', jsonResponse({ detail: 'name taken' }, { ok: false, status: 400 })],
        ]));
        const app = freshApp('2');
        app.showEditForm = true;
        app.editData.name = 'Wisconsin Old Fashioned';
        await app.saveEdit();
        expect(app.editError).toBe('name taken');
        expect(app.showEditForm).toBe(true);
        expect(app.editSaving).toBe(false);
    });

    it('reports thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down'); }));
        const app = freshApp('2');
        app.editData.name = 'Wisconsin Old Fashioned';
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
        const app = freshApp('2');
        await app.deleteCocktail();
        expect(fetch).not.toHaveBeenCalled();
    });

    it('DELETEs and navigates back to the list', async () => {
        vi.stubGlobal('location', { href: '' });
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/2', jsonResponse({ status: 'deleted' })],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        await app.deleteCocktail();

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/cocktails/2', { method: 'DELETE' });
        expect(window.location.href).toBe('/cocktails');
    });

    it('alerts on network failure', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp('2');
        await app.deleteCocktail();
        expect(alert).toHaveBeenCalledWith('Failed to delete: offline');
    });
});

describe('deleteTasting', () => {
    it('is confirm-gated', async () => {
        vi.stubGlobal('confirm', vi.fn(() => false));
        const app = freshApp('2');
        await app.deleteTasting('1');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('DELETEs the tasting and reloads the history', async () => {
        const remaining = [cocktailTastings()[1]];
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/2/tastings/1', jsonResponse({ status: 'deleted', id: '1' })],
            ['/api/v1/cocktails/2/tastings', jsonResponse(remaining)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        await app.deleteTasting('1');

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/v1/cocktails/2/tastings/1', { method: 'DELETE' });
        expect(app.tastings).toEqual(remaining);
    });

    it('alerts when the API refuses', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/tastings/1', jsonResponse({ detail: 'nope' }, { ok: false, status: 403 })],
        ]));
        const app = freshApp('2');
        await app.deleteTasting('1');
        expect(alert).toHaveBeenCalledWith('Failed to delete tasting');
    });

    it('alerts on network failure', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp('2');
        await app.deleteTasting('1');
        expect(alert).toHaveBeenCalledWith('Failed to delete: offline');
    });
});

// ---------------------------------------------------------------------------
// Edit-tasting modal
// ---------------------------------------------------------------------------

describe('openEditTastingModal', () => {
    it('indexes bottles_used by the recipe ingredient positions', () => {
        const app = freshApp('2');
        app.cocktail = cocktailDetail();
        // Contract data: the API returns bottles_used in ITS OWN order
        // (Angostura before Brandy, not submission order) — mapping by
        // recipe_ingredient name must realign them to recipe positions.
        app.openEditTastingModal(cocktailTastings()[0]);

        expect(app.editingTastingId).toBe('1'); // string id, straight from the API
        expect(app.showEditTastingForm).toBe(true);
        expect(app.editTastingError).toBe('');
        expect(app.editTastingData.taster_name).toBe('Ben');
        expect(app.editTastingData.tasting_date).toBe('2026-07-07');
        expect(app.editTastingData.score).toBe(9);
        expect(app.editTastingData.bottles_used).toEqual([
            { recipe_ingredient: 'Brandy', actual_product: 'Korbel Brandy' },
            { recipe_ingredient: 'Angostura Bitters', actual_product: 'Angostura Bitters' },
            { recipe_ingredient: 'Sugar', actual_product: '' },
            { recipe_ingredient: 'Lemon-Lime Soda', actual_product: '' },
        ]);
        expect(app.editBottleQueries).toEqual({
            0: 'Korbel Brandy', 1: 'Angostura Bitters', 2: '', 3: '',
        });
    });

    it('defaults a null score to 7 and missing fields to empty strings', () => {
        const app = freshApp('2');
        app.cocktail = cocktailDetail();
        // Variant: unscored tasting (the current API always stores the wizard
        // score, so null score is a legacy/synthetic case)
        const unscored = { ...cocktailTastings()[1], score: null, notes: 'no score', bartender: null };
        app.openEditTastingModal(unscored);
        expect(app.editTastingData.score).toBe(7);
        expect(app.editTastingData.bartender).toBe('');
        expect(app.editTastingData.notes).toBe('no score');
    });

    it('copes with the cocktail not being loaded yet', () => {
        const app = freshApp('2');
        app.cocktail = null;
        app.openEditTastingModal(cocktailTastings()[1]);
        expect(app.editTastingData.bottles_used).toEqual([]);
    });
});

// Edit mode reuses the SAME searchBottles implementation (ONE PATH) — the
// 'edit' mode argument only redirects which query/result buckets are used.
describe('searchBottles (edit mode)', () => {
    it('searches by the typed query, reading/writing the edit buckets', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/ingredients/search', jsonResponse(ingredientsSearch())],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        app.editBottleQueries[0] = 'bo';
        await app.searchBottles(0, 'Brandy', 'edit');

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/search?q=bo');
        expect(app.editBottleResults[0].map(r => r.name))
            .toEqual(['Buffalo Trace Bourbon', 'Bourbon']);
        // add-mode buckets untouched
        expect(app.bottleResults).toEqual({});
    });

    it('with no query, defaults to the recipe node plus descendants', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([])],
            ['/api/v1/ingredients?flat=true', jsonResponse(ingredientsFlat())],
            ['/api/v1/ingredients/1/descendants', jsonResponse(whiskeyDescendants())],
        ]));
        const app = freshApp('2');
        await app.searchBottles(0, 'Whiskey', 'edit');
        expect(app.editBottleResults[0].map(r => r.name)).toEqual([
            'Buffalo Trace Bourbon', 'Eagle Rare 10 Year', 'Whiskey', 'Bourbon',
        ]);
    });

    it('ignores the add-mode query for the same slot', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/ingredients/search', jsonResponse(ingredientsSearch())],
            ['/api/v1/ingredients?flat=true', jsonResponse([])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp('2');
        app.bottleSearchQueries[0] = 'korbel'; // add-mode bucket must not leak in
        await app.searchBottles(0, 'Rye', 'edit');
        // empty edit query -> falls back to the recipe ingredient
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/ingredients/search?q=Rye');
        expect(app.editBottleResults[0].map(r => r.name))
            .toEqual(['Buffalo Trace Bourbon', 'Bourbon']);
    });

    it('bails silently on a failed search', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp('2');
        await app.searchBottles(0, 'Brandy', 'edit');
        expect(app.editBottleResults[0]).toBeUndefined();
    });

    it('swallows thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp('2');
        await expect(app.searchBottles(0, 'Brandy', 'edit')).resolves.toBeUndefined();
        expect(console.error).toHaveBeenCalled();
    });
});

describe('selectEditBottle', () => {
    it('records the selection into editTastingData and closes the dropdown', () => {
        const product = ingredientsSearch()[1]; // Buffalo Trace Bourbon
        const app = freshApp('2');
        app.editTastingData = { bottles_used: [] };
        app.editBottleResults[1] = [product];
        app.selectEditBottle(1, product, 'Bourbon');
        expect(app.editTastingData.bottles_used[1]).toEqual({
            recipe_ingredient: 'Bourbon', actual_product: 'Buffalo Trace Bourbon',
        });
        expect(app.editBottleQueries[1]).toBe('Buffalo Trace Bourbon');
        expect(app.editBottleResults[1]).toEqual([]);
    });
});

describe('saveEditTasting', () => {
    // The PATCH body assertions mirror what the modal builds; the contract
    // producer PATCHes these exact payloads to pin the tasting dates.
    function seededApp() {
        const app = freshApp('2');
        app.editingTastingId = '1';
        app.showEditTastingForm = true;
        app.editTastingData = {
            taster_name: 'Ben',
            tasting_date: '2026-07-07',
            score: '9.5',
            notes: 'better',
            bartender: 'Sarah',
            bottles_used: [
                { recipe_ingredient: 'Brandy', actual_product: 'Korbel Brandy' },
                { recipe_ingredient: 'Sugar', actual_product: '' },
            ],
        };
        return app;
    }

    it('PATCHes the tasting with parsed score and empty bottle rows dropped', async () => {
        const tastings = cocktailTastings();
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/2/tastings/1', jsonResponse({ status: 'updated', id: 1 })],
            ['/api/v1/cocktails/2/tastings', jsonResponse(tastings)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = seededApp();
        await app.saveEditTasting();

        const patchCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'PATCH');
        expect(patchCall[0]).toBe('/api/v1/cocktails/2/tastings/1');
        expect(JSON.parse(patchCall[1].body)).toEqual({
            taster_name: 'Ben',
            tasting_date: '2026-07-07',
            score: 9.5,
            notes: 'better',
            bartender: 'Sarah',
            bottles_used: [{ recipe_ingredient: 'Brandy', actual_product: 'Korbel Brandy' }],
        });
        expect(app.showEditTastingForm).toBe(false);
        expect(app.tastings).toEqual(tastings);
    });

    it('sends a null score when the slider value is empty', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/2/tastings/1', jsonResponse({ status: 'updated', id: 1 })],
            ['/api/v1/cocktails/2/tastings', jsonResponse(cocktailTastings())],
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
            ['/api/v1/cocktails/2/tastings/1', jsonResponse({ detail: 'Tasting not found' }, { ok: false, status: 404 })],
        ]));
        const app = seededApp();
        await app.saveEditTasting();
        expect(app.editTastingError).toBe('Failed to save: Tasting not found');
        expect(app.showEditTastingForm).toBe(true);
    });

    it('falls back to the status code when the error body is not JSON', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/2/tastings/1', {
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
        const app = freshApp('2');
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
        const app = freshApp('2');
        const event = keyEvent('a', 'bo');
        app.handleAutocomplete(event, ['Bourbon']);
        expect(event.preventDefault).not.toHaveBeenCalled();
        expect(event.target.value).toBe('bo');
    });

    it('ignores empty input', () => {
        const app = freshApp('2');
        const event = keyEvent('Tab', '   ');
        app.handleAutocomplete(event, ['Bourbon']);
        expect(event.preventDefault).not.toHaveBeenCalled();
    });

    it('prefers a starts-with match and fires an input event for x-model', () => {
        const app = freshApp('2');
        const event = keyEvent('Tab', 'bo');
        const inputSpy = vi.fn();
        event.target.addEventListener('input', inputSpy);
        app.handleAutocomplete(event, ['Absinthe', 'Bourbon', 'Old Bourbon Blend']);
        expect(event.target.value).toBe('Bourbon');
        expect(event.preventDefault).toHaveBeenCalled();
        expect(inputSpy).toHaveBeenCalled();
    });

    it('falls back to a contains match on Enter', () => {
        const app = freshApp('2');
        const event = keyEvent('Enter', 'fashion');
        app.handleAutocomplete(event, ['Old Fashioned', 'Martini']);
        expect(event.target.value).toBe('Old Fashioned');
        expect(event.preventDefault).toHaveBeenCalled();
    });

    it('does nothing when nothing matches', () => {
        const app = freshApp('2');
        const event = keyEvent('Tab', 'zzz');
        app.handleAutocomplete(event, ['Bourbon']);
        expect(event.target.value).toBe('zzz');
        expect(event.preventDefault).not.toHaveBeenCalled();
    });
});
