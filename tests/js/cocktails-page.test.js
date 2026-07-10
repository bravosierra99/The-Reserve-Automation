/**
 * Unit tests for the cocktail list page component
 * (src/reserve_automation/web/static/js/cocktails/cocktails-page.js).
 *
 * The real base-page module is imported so window.formatApiError is the
 * production implementation. Alpine itself is not loaded; the factory's
 * return value is used directly, which exercises the live filteredCocktails
 * getter the same way Alpine would.
 *
 * API-response fixtures are NOT hand-written: they are contract fixtures —
 * real responses captured and snapshot-verified by
 * tests/contract/test_cocktails_contract.py and
 * tests/contract/test_ingredients_contract.py (see tests/contract/contract.py
 * for the rationale). Per-test variants mutate a fresh clone of the loaded
 * contract object. The only hand-written fixture left is the LLM
 * recipe-search response, which cannot be contract-captured (labelled below).
 *
 * Contract flow data: cocktails (name order) Manhattan (stirred, unscored),
 * Old Fashioned (stirred, unscored), Wisconsin Old Fashioned (built,
 * avg_score 8.5, parent_cocktail "Old Fashioned"). Ingredient tree: Bitters,
 * Brandy, Whiskey roots; products carry cost/volume/abv. NOTE: the real API
 * returns ids as STRINGS ("2", not 2).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
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

const cocktailsList = () => loadContract('cocktails_list');
const cocktailsSearch = () => loadContract('cocktails_search');
const ingredientsFlat = () => loadContract('ingredients_flat');
const createdIngredient = () => loadContract('ingredient_create_response');

const LIST_NAMES = ['Manhattan', 'Old Fashioned', 'Wisconsin Old Fashioned'];
// Depth-first walk order of the contract tree (GET /api/v1/ingredients?flat=true)
const FLAT_NAMES = [
    'Bitters', 'Angostura Bitters', 'Brandy', 'Korbel Brandy',
    'Whiskey', 'Bourbon', 'Buffalo Trace Bourbon', 'Eagle Rare 10 Year',
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
        const list = cocktailsList();
        const fetchMock = routeFetch([
            ['/api/v1/ingredients?flat=true', jsonResponse(ingredientsFlat())],
            ['/api/v1/cocktails', jsonResponse(list)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        await app.init();

        expect(app.cocktails).toEqual(list);
        expect(app.cocktailNames).toEqual(LIST_NAMES);
        expect(app.ingredientNames).toEqual(FLAT_NAMES);
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
        const list = cocktailsList();
        app.cocktails = list;
        expect(app.filteredCocktails).toEqual(list);
    });

    it('filters by method', () => {
        const app = freshApp();
        app.cocktails = cocktailsList();
        app.filterMethod = 'built';
        expect(app.filteredCocktails.map(c => c.name)).toEqual(['Wisconsin Old Fashioned']);
        app.filterMethod = 'stirred';
        expect(app.filteredCocktails.map(c => c.name)).toEqual(['Manhattan', 'Old Fashioned']);
    });

    it('filters by minimum score, excluding unscored cocktails', () => {
        const app = freshApp();
        // Variant: score Manhattan 6 so two cocktails are scored differently;
        // Old Fashioned stays null (the contract's unscored shape).
        const list = cocktailsList();
        list[0].avg_score = 6;
        app.cocktails = list;
        app.filterMinScore = '6';
        // Old Fashioned (avg_score null) must be excluded even though null >= 6 is false anyway
        expect(app.filteredCocktails.map(c => c.name))
            .toEqual(['Manhattan', 'Wisconsin Old Fashioned']);
        app.filterMinScore = '7';
        expect(app.filteredCocktails.map(c => c.name)).toEqual(['Wisconsin Old Fashioned']);
    });

    it('combines method and score filters', () => {
        const app = freshApp();
        app.cocktails = cocktailsList();
        app.filterMethod = 'built';
        app.filterMinScore = '9';
        expect(app.filteredCocktails).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// loadCocktails / loadIngredientNames
// ---------------------------------------------------------------------------

describe('loadCocktails', () => {
    it('hits the bare list endpoint when there is no search query', async () => {
        const list = cocktailsList();
        const fetchMock = routeFetch([['/api/v1/cocktails', jsonResponse(list)]]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        await app.loadCocktails();

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/cocktails');
        expect(app.cocktails).toEqual(list);
        expect(app.loading).toBe(false);
    });

    it('URL-encodes the search query and stores the filtered results', async () => {
        // cocktails_search is the real GET /api/v1/cocktails?q=Old Fashioned response
        const fetchMock = routeFetch([['/api/v1/cocktails', jsonResponse(cocktailsSearch())]]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        app.searchQuery = 'Old Fashioned';
        await app.loadCocktails();

        expect(fetchMock).toHaveBeenCalledWith('/api/v1/cocktails?q=Old%20Fashioned');
        expect(app.cocktailNames).toEqual(['Old Fashioned', 'Wisconsin Old Fashioned']);
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
            ['/api/v1/ingredients?flat=true', jsonResponse(ingredientsFlat())],
        ]));
        const app = freshApp();
        await app.loadIngredientNames();
        expect(app.ingredientNames).toEqual(FLAT_NAMES);
    });

    it('stays silent on failure', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp();
        await expect(app.loadIngredientNames()).resolves.toBeUndefined();
        expect(app.ingredientNames).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// saveCocktail — the POST body assertions mirror what the form builds; the
// contract producer (test_cocktails_contract.py COCKTAIL_SEED) sends these
// exact payloads to the real API.
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
        const list = cocktailsList();
        const fetchMock = routeFetch([
            ['/api/v1/cocktails', (url, opts) =>
                opts && opts.method === 'POST'
                    ? jsonResponse(list[1])
                    : jsonResponse(list)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        app.showCreateForm = true;
        app.newCocktail = {
            name: 'Old Fashioned', description: '', parent_cocktail: 'Whiskey Cocktail',
            method: 'stirred', style: '', glassware: '', garnish: 'orange peel',
            ingredients: [
                { ingredient: 'Bourbon', amount: 2, unit: 'oz', notes: '', optional: false },
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
            ingredients: [{ ingredient: 'Bourbon', amount: 2, unit: 'oz', notes: '', optional: false }],
            instructions: ['Stir'],
        });
        // form closed + reset to the pristine one-row recipe
        expect(app.showCreateForm).toBe(false);
        expect(app.newCocktail.name).toBe('');
        expect(app.newCocktail.ingredients).toEqual([
            { ingredient: '', amount: null, unit: 'oz', notes: '', optional: false },
        ]);
        // list reloaded
        expect(app.cocktails).toEqual(list);
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
// saveNewIngredient (quick-add modal) — the create response is the contract
// fixture (POST /api/v1/ingredients), whose .name the component reads.
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
        const created = createdIngredient(); // Angostura Bitters
        const fetchMock = routeFetch([
            ['/api/v1/ingredients?flat=true', jsonResponse(ingredientsFlat())],
            ['/api/v1/ingredients', (url, opts) =>
                opts && opts.method === 'POST' ? jsonResponse(created) : jsonResponse(ingredientsFlat())],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        app.showNewIngredientForm = true;
        app.newIngredientData = { name: '  Angostura Bitters ', parent: '  ' };
        await app.saveNewIngredient();

        const postCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'POST');
        expect(postCall[0]).toBe('/api/v1/ingredients');
        expect(JSON.parse(postCall[1].body)).toEqual({ name: 'Angostura Bitters', parent: null });
        expect(app.newIngredientSuccess).toBe('Created "Angostura Bitters"!');
        expect(app.ingredientNames).toEqual(FLAT_NAMES);
        // the blank starter row is reused rather than appending
        expect(app.newCocktail.ingredients).toEqual([
            { ingredient: 'Angostura Bitters', amount: null, unit: 'oz', notes: '', optional: false },
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
        const created = createdIngredient();
        const fetchMock = routeFetch([
            ['/api/v1/ingredients?flat=true', jsonResponse(ingredientsFlat())],
            ['/api/v1/ingredients', jsonResponse(created)],
        ]);
        vi.stubGlobal('fetch', fetchMock);

        const app = freshApp();
        app.newCocktail.ingredients = [
            { ingredient: 'Bourbon', amount: 2, unit: 'oz', notes: '', optional: false },
        ];
        app.newIngredientData = { name: 'Angostura Bitters', parent: 'Bitters' };
        await app.saveNewIngredient();

        const postCall = fetchMock.mock.calls.find(([, o]) => o && o.method === 'POST');
        expect(JSON.parse(postCall[1].body)).toEqual({ name: 'Angostura Bitters', parent: 'Bitters' });
        expect(app.newCocktail.ingredients).toEqual([
            { ingredient: 'Bourbon', amount: 2, unit: 'oz', notes: '', optional: false },
            { ingredient: 'Angostura Bitters', amount: null, unit: 'oz', notes: '', optional: false },
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
    // HAND-WRITTEN fixture (not contract-sourced): POST
    // /api/v1/cocktails/search-recipe is LLM-backed (LM Studio) and its
    // response cannot be captured deterministically by the contract producer.
    // Shape: routes/cocktails.py::search_cocktail_recipe (LLM-produced JSON).
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
