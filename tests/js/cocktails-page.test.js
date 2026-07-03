/**
 * Unit tests for the cocktail list page component
 * (src/reserve_automation/web/static/js/cocktails/cocktails-page.js).
 *
 * The real base-page module is imported so window.formatApiError is the
 * production implementation. Alpine itself is not loaded; the factory's
 * return value is used directly, which exercises the live filteredCocktails
 * getter the same way Alpine would.
 *
 * Fixtures mirror the API response shapes in web/routes/cocktails.py
 * (_cocktail_to_dict) and web/routes/ingredients.py (_ingredient_to_dict).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/base-page.js';
import '../../src/reserve_automation/web/static/js/cocktails/cocktails-page.js';

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
    return window.cocktailsApp();
}

// Shape: routes/cocktails.py::_cocktail_to_dict
const COCKTAILS = [
    {
        id: 1, name: 'Old Fashioned', description: 'A classic',
        ingredients: [{ ingredient: 'bourbon', amount: 2, unit: 'oz', notes: null, optional: false }],
        instructions: ['Stir'], garnish: 'orange peel', glassware: 'rocks',
        method: 'stirred', style: 'classic', serving_size: 1, stars: null,
        photo: null, avg_score: 8.5,
    },
    {
        id: 2, name: 'Daiquiri', description: null,
        ingredients: [{ ingredient: 'rum', amount: 2, unit: 'oz', notes: null, optional: false }],
        instructions: ['Shake'], garnish: 'lime wheel', glassware: 'coupe',
        method: 'shaken', style: 'sour', serving_size: 1, stars: null,
        photo: null, avg_score: 6,
    },
    {
        id: 3, name: 'Moscow Mule', description: null,
        ingredients: [{ ingredient: 'vodka', amount: 2, unit: 'oz', notes: null, optional: false }],
        instructions: ['Build'], garnish: 'lime', glassware: 'copper mug',
        method: 'built', style: 'highball', serving_size: 1, stars: null,
        photo: null, avg_score: null,
    },
];

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
// Initial state + init
// ---------------------------------------------------------------------------

describe('initial state', () => {
    it('starts loading with empty filters and a one-row blank recipe form', () => {
        const app = freshApp();
        expect(app.cocktails).toEqual([]);
        expect(app.loading).toBe(true);
        expect(app.searchQuery).toBe('');
        expect(app.filterMethod).toBe('');
        expect(app.filterMinScore).toBe('');
        expect(app.showCreateForm).toBe(false);
        expect(app.newCocktail.name).toBe('');
        expect(app.newCocktail.ingredients).toEqual([
            { ingredient: '', amount: null, unit: 'oz', notes: '', optional: false },
        ]);
        expect(app.newCocktail.instructions).toEqual(['']);
        expect(app.newIngredientData).toEqual({ name: '', parent: '' });
    });

    it('init loads cocktails then ingredient names (Alpine calls it automatically)', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/cocktails', jsonResponse(COCKTAILS)],
            ['/api/v1/ingredients?flat=true', jsonResponse([
                { id: 3, name: 'Bourbon', cost: null, abv: null, is_product: false, ancestors: [] },
            ])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        await app.init();

        expect(app.cocktails).toEqual(COCKTAILS);
        expect(app.cocktailNames).toEqual(['Old Fashioned', 'Daiquiri', 'Moscow Mule']);
        expect(app.ingredientNames).toEqual(['Bourbon']);
        expect(app.loading).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// filteredCocktails getter
// ---------------------------------------------------------------------------

describe('filteredCocktails', () => {
    it('passes everything through with no filters, as a live getter', () => {
        const app = freshApp();
        expect(app.filteredCocktails).toEqual([]);
        app.cocktails = COCKTAILS;
        expect(app.filteredCocktails).toEqual(COCKTAILS);
    });

    it('filters by method', () => {
        const app = freshApp();
        app.cocktails = COCKTAILS;
        app.filterMethod = 'shaken';
        expect(app.filteredCocktails.map(c => c.name)).toEqual(['Daiquiri']);
    });

    it('filters by minimum score, excluding unscored cocktails', () => {
        const app = freshApp();
        app.cocktails = COCKTAILS;
        app.filterMinScore = '6';
        // Moscow Mule (avg_score null) must be excluded even though null >= 6 is false anyway
        expect(app.filteredCocktails.map(c => c.name)).toEqual(['Old Fashioned', 'Daiquiri']);
        app.filterMinScore = '7';
        expect(app.filteredCocktails.map(c => c.name)).toEqual(['Old Fashioned']);
    });

    it('combines method and score filters', () => {
        const app = freshApp();
        app.cocktails = COCKTAILS;
        app.filterMethod = 'stirred';
        app.filterMinScore = '9';
        expect(app.filteredCocktails).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// loadCocktails / loadIngredientNames
// ---------------------------------------------------------------------------

describe('loadCocktails', () => {
    it('hits the bare list endpoint when there is no search query', async () => {
        const fetchMock = routeFetch([['/api/v1/cocktails', jsonResponse(COCKTAILS)]]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        await app.loadCocktails();

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/cocktails');
        expect(app.cocktails).toEqual(COCKTAILS);
        expect(app.loading).toBe(false);
    });

    it('URL-encodes the search query', async () => {
        const fetchMock = routeFetch([['/api/v1/cocktails', jsonResponse([COCKTAILS[0]])]]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        app.searchQuery = 'old & new';
        await app.loadCocktails();

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/cocktails?q=old%20%26%20new');
        expect(app.cocktailNames).toEqual(['Old Fashioned']);
    });

    it('swallows HTTP errors and clears loading', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails', jsonResponse({ detail: 'boom' }, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        await app.loadCocktails();
        expect(app.cocktails).toEqual([]);
        expect(app.loading).toBe(false);
        expect(console.error).toHaveBeenCalled();
    });
});

describe('loadIngredientNames', () => {
    it('maps the flat ingredient list to names', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients?flat=true', jsonResponse([
                { id: 1, name: 'Bourbon', cost: null, abv: null, is_product: false, ancestors: [] },
                { id: 2, name: 'Lime Juice', cost: null, abv: null, is_product: false, ancestors: [] },
            ])],
        ]));
        const app = freshApp();
        await app.loadIngredientNames();
        expect(app.ingredientNames).toEqual(['Bourbon', 'Lime Juice']);
    });

    it('stays silent on failure', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp();
        await expect(app.loadIngredientNames()).resolves.toBeUndefined();
        expect(app.ingredientNames).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// saveCocktail
// ---------------------------------------------------------------------------

describe('saveCocktail', () => {
    it('requires a name before hitting the API', async () => {
        const app = freshApp();
        app.newCocktail.name = '  ';
        await app.saveCocktail();
        expect(app.formError).toBe('Name is required');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs the recipe with blank rows filtered and empty strings nulled, then resets', async () => {
        const fetchMock = routeFetch([
            ['/api/v1/cocktails', (url, opts) =>
                opts && opts.method === 'POST'
                    ? jsonResponse(COCKTAILS[0])
                    : jsonResponse(COCKTAILS)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        app.showCreateForm = true;
        app.newCocktail = {
            name: 'Old Fashioned', description: '', parent_cocktail: 'Whiskey Cocktail',
            method: 'stirred', style: '', glassware: '', garnish: 'orange peel',
            ingredients: [
                { ingredient: 'bourbon', amount: 2, unit: 'oz', notes: '', optional: false },
                { ingredient: '  ', amount: null, unit: 'oz', notes: '', optional: false },
            ],
            instructions: ['Stir', '  '],
        };
        await app.saveCocktail();

        const postCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'POST');
        expect(postCall[0]).toBe('/api/v1/cocktails');
        expect(JSON.parse(postCall[1].body)).toEqual({
            name: 'Old Fashioned',
            description: null,
            parent_cocktail: 'Whiskey Cocktail',
            method: 'stirred',
            style: null,
            glassware: null,
            garnish: 'orange peel',
            ingredients: [{ ingredient: 'bourbon', amount: 2, unit: 'oz', notes: '', optional: false }],
            instructions: ['Stir'],
        });
        // form closed + reset to the pristine one-row recipe
        expect(app.showCreateForm).toBe(false);
        expect(app.newCocktail.name).toBe('');
        expect(app.newCocktail.ingredients).toEqual([
            { ingredient: '', amount: null, unit: 'oz', notes: '', optional: false },
        ]);
        // list reloaded
        expect(app.cocktails).toEqual(COCKTAILS);
        expect(app.saving).toBe(false);
    });

    it('shows the API error and keeps the form open', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails', jsonResponse({ detail: 'already exists' }, { ok: false, status: 409 })],
        ]));
        const app = freshApp();
        app.showCreateForm = true;
        app.newCocktail.name = 'Old Fashioned';
        await app.saveCocktail();
        expect(app.formError).toBe('already exists');
        expect(app.showCreateForm).toBe(true);
        expect(app.saving).toBe(false);
    });

    it('formats 422 validation lists into readable text', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails', jsonResponse(
                { detail: [{ loc: ['body', 'name'], msg: 'field required' }] },
                { ok: false, status: 422 },
            )],
        ]));
        const app = freshApp();
        app.newCocktail.name = 'X';
        await app.saveCocktail();
        expect(app.formError).toBe('name: field required');
    });

    it('reports thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('down'); }));
        const app = freshApp();
        app.newCocktail.name = 'X';
        await app.saveCocktail();
        expect(app.formError).toBe('down');
        expect(app.saving).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// saveNewIngredient (quick-add modal)
// ---------------------------------------------------------------------------

describe('saveNewIngredient', () => {
    it('requires a name', async () => {
        const app = freshApp();
        app.newIngredientData.name = '  ';
        await app.saveNewIngredient();
        expect(app.newIngredientError).toBe('Name is required');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs trimmed name with a null parent when blank, and fills the empty last row', async () => {
        vi.useFakeTimers();
        const created = { id: 5, name: 'Green Chartreuse', cost: null, abv: 55, is_product: false, ancestors: [] };
        const fetchMock = routeFetch([
            ['/api/v1/ingredients?flat=true', jsonResponse([created])],
            ['/api/v1/ingredients', (url, opts) =>
                opts && opts.method === 'POST' ? jsonResponse(created) : jsonResponse([created])],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        app.showNewIngredientForm = true;
        app.newIngredientData = { name: '  Green Chartreuse ', parent: '  ' };
        await app.saveNewIngredient();

        const postCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'POST');
        expect(postCall[0]).toBe('/api/v1/ingredients');
        expect(JSON.parse(postCall[1].body)).toEqual({ name: 'Green Chartreuse', parent: null });
        expect(app.newIngredientSuccess).toBe('Created "Green Chartreuse"!');
        expect(app.ingredientNames).toEqual(['Green Chartreuse']);
        // the blank starter row is reused rather than appending
        expect(app.newCocktail.ingredients).toEqual([
            { ingredient: 'Green Chartreuse', amount: null, unit: 'oz', notes: '', optional: false },
        ]);
        expect(app.savingNewIngredient).toBe(false);

        // modal auto-closes after 1s
        expect(app.showNewIngredientForm).toBe(true);
        vi.advanceTimersByTime(1000);
        expect(app.showNewIngredientForm).toBe(false);
        expect(app.newIngredientData).toEqual({ name: '', parent: '' });
        expect(app.newIngredientSuccess).toBe('');
    });

    it('appends a new recipe row when the last row is already filled, sending the parent', async () => {
        vi.useFakeTimers();
        const created = { id: 6, name: 'Rittenhouse Rye', cost: 28, abv: 50, is_product: true, ancestors: ['Rye'] };
        const fetchMock = routeFetch([
            ['/api/v1/ingredients?flat=true', jsonResponse([created])],
            ['/api/v1/ingredients', jsonResponse(created)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        app.newCocktail.ingredients = [
            { ingredient: 'bourbon', amount: 2, unit: 'oz', notes: '', optional: false },
        ];
        app.newIngredientData = { name: 'Rittenhouse Rye', parent: 'Rye' };
        await app.saveNewIngredient();

        const postCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'POST');
        expect(JSON.parse(postCall[1].body)).toEqual({ name: 'Rittenhouse Rye', parent: 'Rye' });
        expect(app.newCocktail.ingredients).toEqual([
            { ingredient: 'bourbon', amount: 2, unit: 'oz', notes: '', optional: false },
            { ingredient: 'Rittenhouse Rye', amount: null, unit: 'oz', notes: '', optional: false },
        ]);
    });

    it('shows the API error and keeps the modal open', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients', jsonResponse({ detail: 'duplicate' }, { ok: false, status: 409 })],
        ]));
        const app = freshApp();
        app.showNewIngredientForm = true;
        app.newIngredientData = { name: 'Dup', parent: '' };
        await app.saveNewIngredient();
        expect(app.newIngredientError).toBe('duplicate');
        expect(app.showNewIngredientForm).toBe(true);
        expect(app.savingNewIngredient).toBe(false);
    });

    it('reports thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp();
        app.newIngredientData = { name: 'X', parent: '' };
        await app.saveNewIngredient();
        expect(app.newIngredientError).toBe('offline');
        expect(app.savingNewIngredient).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// searchRecipe (LLM recipe lookup)
// ---------------------------------------------------------------------------

describe('searchRecipe', () => {
    // Shape: routes/cocktails.py::search_cocktail_recipe (LLM-produced JSON)
    const RECIPE = {
        name: 'Margarita',
        description: 'Tequila, lime, orange liqueur',
        method: 'shaken',
        style: 'sour',
        glassware: 'coupe',
        garnish: 'lime wheel',
        ingredients: [
            { ingredient: 'Tequila', amount: 2.0, unit: 'oz', notes: 'blanco' },
            { ingredient: 'Lime Juice', amount: 0.75, unit: 'oz' },
        ],
        instructions: ['Shake with ice', 'Strain into a coupe'],
    };

    it('requires a query', async () => {
        const app = freshApp();
        app.recipeSearchQuery = '  ';
        await app.searchRecipe();
        expect(app.recipeSearchError).toBe('Please enter a cocktail name');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs the query, populates the create form, and auto-closes after 1.5s', async () => {
        vi.useFakeTimers();
        const fetchMock = routeFetch([
            ['/api/v1/cocktails/search-recipe', jsonResponse(RECIPE)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        app.showRecipeSearch = true;
        app.recipeSearchQuery = 'Margarita';
        await app.searchRecipe();

        const [url, opts] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/v1/cocktails/search-recipe');
        expect(opts.method).toBe('POST');
        expect(JSON.parse(opts.body)).toEqual({ query: 'Margarita' });

        expect(app.newCocktail.name).toBe('Margarita');
        expect(app.newCocktail.method).toBe('shaken');
        expect(app.newCocktail.ingredients).toEqual(RECIPE.ingredients);
        expect(app.newCocktail.instructions).toEqual(RECIPE.instructions);
        // recipe has no parent_cocktail -> defaults to ''
        expect(app.newCocktail.parent_cocktail).toBe('');
        expect(app.recipeSearchSuccess).toBe('Recipe loaded! Review and edit before saving.');
        expect(app.recipeSearching).toBe(false);

        expect(app.showRecipeSearch).toBe(true);
        vi.advanceTimersByTime(1500);
        expect(app.showRecipeSearch).toBe(false);
        expect(app.recipeSearchQuery).toBe('');
        expect(app.recipeSearchSuccess).toBe('');
    });

    it('falls back to the typed name and blank rows for sparse LLM output', async () => {
        vi.useFakeTimers();
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/search-recipe', jsonResponse({})],
        ]));
        const app = freshApp();
        app.recipeSearchQuery = 'Mystery Drink';
        await app.searchRecipe();
        expect(app.newCocktail.name).toBe('Mystery Drink');
        expect(app.newCocktail.ingredients).toEqual([
            { ingredient: '', amount: null, unit: 'oz', notes: '', optional: false },
        ]);
        expect(app.newCocktail.instructions).toEqual(['']);
    });

    it('shows the API error and keeps the modal open', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/cocktails/search-recipe', jsonResponse({ detail: 'LLM unavailable' }, { ok: false, status: 503 })],
        ]));
        const app = freshApp();
        app.showRecipeSearch = true;
        app.recipeSearchQuery = 'Margarita';
        await app.searchRecipe();
        expect(app.recipeSearchError).toBe('LLM unavailable');
        expect(app.showRecipeSearch).toBe(true);
        expect(app.recipeSearching).toBe(false);
    });

    it('reports thrown errors', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('timeout'); }));
        const app = freshApp();
        app.recipeSearchQuery = 'Margarita';
        await app.searchRecipe();
        expect(app.recipeSearchError).toBe('timeout');
        expect(app.recipeSearching).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// handleAutocomplete
// ---------------------------------------------------------------------------

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
        const app = freshApp();
        const event = keyEvent('ArrowDown', 'mar');
        app.handleAutocomplete(event, ['Margarita']);
        expect(event.preventDefault).not.toHaveBeenCalled();
        expect(event.target.value).toBe('mar');
    });

    it('ignores empty input', () => {
        const app = freshApp();
        const event = keyEvent('Enter', '  ');
        app.handleAutocomplete(event, ['Margarita']);
        expect(event.preventDefault).not.toHaveBeenCalled();
    });

    it('prefers a starts-with match and fires an input event for x-model', () => {
        const app = freshApp();
        const event = keyEvent('Tab', 'mar');
        const inputSpy = vi.fn();
        event.target.addEventListener('input', inputSpy);
        app.handleAutocomplete(event, ['Amargo', 'Margarita']);
        expect(event.target.value).toBe('Margarita');
        expect(event.preventDefault).toHaveBeenCalled();
        expect(inputSpy).toHaveBeenCalled();
    });

    it('falls back to a contains match', () => {
        const app = freshApp();
        const event = keyEvent('Enter', 'garita');
        app.handleAutocomplete(event, ['Margarita', 'Mai Tai']);
        expect(event.target.value).toBe('Margarita');
    });

    it('does nothing when nothing matches', () => {
        const app = freshApp();
        const event = keyEvent('Tab', 'zzz');
        app.handleAutocomplete(event, ['Margarita']);
        expect(event.target.value).toBe('zzz');
        expect(event.preventDefault).not.toHaveBeenCalled();
    });
});
