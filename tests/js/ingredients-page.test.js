/**
 * Unit tests for the ingredients page component
 * (src/reserve_automation/web/static/js/ingredients/ingredients-page.js).
 *
 * Alpine itself is not loaded; the factory's return value is used directly.
 * Alpine magics the component touches ($nextTick, $refs) are stubbed per
 * instance. renderNode() is exercised against real jsdom DOM nodes since the
 * tree renderer is imperative DOM code, not Alpine bindings.
 *
 * API-response fixtures are NOT hand-written: they are contract fixtures —
 * real responses captured and snapshot-verified by
 * tests/contract/test_ingredients_contract.py (see tests/contract/contract.py
 * for the rationale). Per-test variants mutate a fresh clone of the loaded
 * contract object.
 *
 * Contract tree: Bitters > Angostura Bitters; Brandy > Korbel Brandy;
 * Whiskey > Bourbon > (Buffalo Trace Bourbon, Eagle Rare 10 Year). The search
 * fixture is GET /api/v1/ingredients/search?q=bo -> [Bourbon, Buffalo Trace
 * Bourbon]. Two realities the old hand-written fixtures got wrong: ids are
 * STRINGS ("3", not 3), and search matches are FLAT rows — children is
 * always [] and ancestors always [], because the repo returns bare matches
 * (search results never carry subtrees, whatever the tree view shows).
 *
 * The ingredient tree is collection infrastructure: cocktail recipe
 * ingredients are free text matched by name, so the edit (rename) and delete
 * flows get particular attention (exact URLs, payloads, 409 conflict paths).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
import '../../src/reserve_automation/web/static/js/ingredients/ingredients-page.js';

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
    const app = window.ingredientsApp();
    // Alpine magics — stub per instance. $nextTick is a no-op by default so
    // the post-load expandAll scheduling doesn't leak timers into every test.
    app.$nextTick = vi.fn();
    app.$refs = {};
    return app;
}

const ingredientsTree = () => loadContract('ingredients_tree');
const ingredientsSearch = () => loadContract('ingredients_search'); // q=bo
const ingredientDetail = () => loadContract('ingredient_detail');   // Bourbon, id "2"

// Depth-first walk of the contract tree
const TREE_NAMES = [
    'Bitters', 'Angostura Bitters', 'Brandy', 'Korbel Brandy',
    'Whiskey', 'Bourbon', 'Buffalo Trace Bourbon', 'Eagle Rare 10 Year',
];

// Whiskey root: the 3-level branch (Whiskey > Bourbon > two products)
const whiskeyRoot = () => ingredientsTree()[2];

beforeEach(() => {
    document.body.innerHTML = '';
    vi.stubGlobal('fetch', routeFetch([['/api/v1/ingredients', jsonResponse(ingredientsTree())]]));
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('confirm', vi.fn(() => true));
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
    it('starts loading with empty tree, no search, all modals closed', () => {
        const app = freshApp();
        expect(app.tree).toEqual([]);
        expect(app.treeVersion).toBe(0);
        expect(app.loading).toBe(true);
        expect(app.searchQuery).toBe('');
        expect(app.searchMode).toBe(false);
        expect(app.searchResults).toEqual([]);
        expect(app.showViewForm).toBe(false);
        expect(app.showAddForm).toBe(false);
        expect(app.showEditForm).toBe(false);
        expect(app.saving).toBe(false);
        expect(app.formError).toBe('');
        expect(app.editId).toBeNull();
        expect(app.addParent).toBeNull();
        expect(app.allIngredientNames).toEqual([]);
        expect(app.viewData).toEqual({});
        expect(app.formData).toEqual({
            name: '', parent: '', cost: null, volume_ml: null, abv: null, notes: '',
        });
    });
});

// ---------------------------------------------------------------------------
// loadTree
// ---------------------------------------------------------------------------

describe('loadTree', () => {
    it('fetches the tree, bumps treeVersion, and clears loading', async () => {
        const app = freshApp();
        await app.loadTree();
        expect(fetch).toHaveBeenCalledWith('/api/v1/ingredients');
        expect(app.tree).toEqual(ingredientsTree());
        expect(app.treeVersion).toBe(1);
        expect(app.loading).toBe(false);
    });

    it('walks the tree into a flat name list for parent autocomplete', async () => {
        const app = freshApp();
        await app.loadTree();
        expect(app.allIngredientNames).toEqual(TREE_NAMES);
    });

    it('schedules expandAll 50ms after the DOM renders', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.$nextTick = (cb) => cb();
        const expandSpy = vi.spyOn(app, 'expandAll').mockImplementation(() => {});
        await app.loadTree();
        expect(expandSpy).not.toHaveBeenCalled();
        vi.advanceTimersByTime(50);
        expect(expandSpy).toHaveBeenCalledTimes(1);
    });

    it('logs and still clears loading when the fetch fails', async () => {
        const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        await app.loadTree();
        expect(app.tree).toEqual([]);
        expect(app.treeVersion).toBe(0);
        expect(app.loading).toBe(false);
        expect(errSpy).toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------------------
// init — including the #search= deep link from cocktail ingredient links
// ---------------------------------------------------------------------------

describe('init', () => {
    it('loads the tree and does not enter search mode without a hash', async () => {
        vi.stubGlobal('location', { hash: '', pathname: '/ingredients' });
        const app = freshApp();
        await app.init();
        expect(app.tree).toEqual(ingredientsTree());
        expect(app.searchMode).toBe(false);
    });

    it('runs the #search= hash, auto-opens a single result, and clears the hash', async () => {
        const bourbon = ingredientsSearch()[0];
        vi.stubGlobal('location', { hash: '#search=Bourbon', pathname: '/ingredients' });
        const replaceState = vi.spyOn(window.history, 'replaceState').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([bourbon])],
            ['/api/v1/ingredients', jsonResponse(ingredientsTree())],
        ]));
        const app = freshApp();
        await app.init();
        expect(app.searchQuery).toBe('Bourbon');
        expect(app.searchMode).toBe(true);
        expect(app.showViewForm).toBe(true);
        expect(app.viewData.name).toBe('Bourbon');
        expect(replaceState).toHaveBeenCalledWith(null, '', '/ingredients');
    });

    it('decodes URI-encoded search terms and does not auto-open multiple results', async () => {
        vi.stubGlobal('location', { hash: '#search=Buffalo%20Trace', pathname: '/ingredients' });
        vi.spyOn(window.history, 'replaceState').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse(ingredientsSearch())],
            ['/api/v1/ingredients', jsonResponse(ingredientsTree())],
        ]));
        const app = freshApp();
        await app.init();
        expect(app.searchQuery).toBe('Buffalo Trace');
        expect(app.searchResults).toHaveLength(2);
        expect(app.showViewForm).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// doSearch
// ---------------------------------------------------------------------------

describe('doSearch', () => {
    it('exits search mode without fetching when the query is blank', async () => {
        const app = freshApp();
        app.searchQuery = '   ';
        app.searchMode = true;
        app.searchResults = ingredientsSearch();
        await app.doSearch();
        expect(app.searchMode).toBe(false);
        expect(app.searchResults).toEqual([]);
        expect(fetch).not.toHaveBeenCalled();
    });

    it('URL-encodes the query and stores the flat match rows', async () => {
        // Real search matches carry children: [] — the API never returns
        // subtrees from /search, so the results pane renders leaf rows only.
        const results = ingredientsSearch();
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse(results)],
        ]));
        const app = freshApp();
        app.searchQuery = 'Rum & Cola';
        await app.doSearch();
        expect(fetch).toHaveBeenCalledWith('/api/v1/ingredients/search?q=Rum%20%26%20Cola');
        expect(app.searchMode).toBe(true);
        expect(app.searchResults).toEqual(results);
        expect(app.searchResults.every(r => r.children.length === 0)).toBe(true);
    });

    it('schedules expandAll after results render', async () => {
        vi.useFakeTimers();
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse(ingredientsSearch())],
        ]));
        const app = freshApp();
        app.$nextTick = (cb) => cb();
        const expandSpy = vi.spyOn(app, 'expandAll').mockImplementation(() => {});
        app.searchQuery = 'bo';
        await app.doSearch();
        vi.advanceTimersByTime(50);
        expect(expandSpy).toHaveBeenCalledTimes(1);
    });

    it('logs and keeps prior results on a failed search', async () => {
        const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        app.searchQuery = 'Bourbon';
        await app.doSearch();
        expect(app.searchMode).toBe(true);
        expect(app.searchResults).toEqual([]);
        expect(errSpy).toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------------------
// renderNode — the imperative tree renderer
// ---------------------------------------------------------------------------

describe('renderNode', () => {
    function render(node, depth = 0) {
        const app = freshApp();
        const el = document.createElement('div');
        document.body.appendChild(el);
        app.renderNode(node, el, depth);
        // renderNode builds: el > container > [row, childContainer?]
        const container = el.firstElementChild;
        const row = container.firstElementChild;
        const childContainer = container.children[1] || null;
        return { app, el, container, row, childContainer };
    }

    it('renders name, folder icon, and a dot spacer for a childless category', () => {
        // A search match is the real childless-category shape (children: [])
        const { el } = render(ingredientsSearch()[0]); // Bourbon
        expect(el.textContent).toContain('Bourbon');
        expect(el.textContent).toContain('📁');
        expect(el.textContent).toContain('·');
        expect(el.querySelector('button[data-expanded]')).toBeNull();
    });

    it('renders product icon and cost badge for products', () => {
        const product = whiskeyRoot().children[0].children[0]; // Buffalo Trace Bourbon
        const { el } = render(product);
        expect(el.textContent).toContain('🏷️');
        expect(el.textContent).toContain('$29.99');
    });

    it('renders a $0 cost badge for free ingredients', () => {
        // Regression variant (hand-mutated: no free ingredient in the contract
        // tree): `if (node.cost)` hid the badge for a legitimate 0 cost.
        const free = { ...ingredientsSearch()[1], name: 'Tap Water', cost: 0 };
        const { el } = render(free);
        expect(el.textContent).toContain('$0');
    });

    it('indents rows by depth', () => {
        const { row } = render(ingredientsSearch()[0], 2);
        expect(row.style.paddingLeft).toBe('64px'); // 16 + 2*24
    });

    it('renders children recursively inside a hidden container with a collapsed toggle', () => {
        const { el, childContainer } = render(whiskeyRoot());
        const toggle = el.querySelector('button[data-expanded]');
        expect(toggle.dataset.expanded).toBe('false');
        expect(toggle.textContent).toBe('▶');
        expect(el.textContent).toContain('Bourbon');
        expect(el.textContent).toContain('Buffalo Trace Bourbon');
        expect(el.textContent).toContain('Eagle Rare 10 Year');
        // Immediate child container of the root node starts hidden
        expect(childContainer.style.display).toBe('none');
    });

    it('toggle expands and collapses the child container', () => {
        const { el } = render(whiskeyRoot());
        const toggle = el.querySelector('button[data-expanded]');
        toggle.click();
        expect(toggle.dataset.expanded).toBe('true');
        expect(toggle.textContent).toBe('▼');
        toggle.click();
        expect(toggle.dataset.expanded).toBe('false');
        expect(toggle.textContent).toBe('▶');
    });

    it('clicking the row opens the view modal for that node', () => {
        const { app, row } = render(ingredientsSearch()[0]);
        row.click();
        expect(app.showViewForm).toBe(true);
        expect(app.viewData.name).toBe('Bourbon');
    });

    it('clicking + Child opens the add form with this node as parent, without opening view', () => {
        const brandy = ingredientsTree()[1];
        const { app, el } = render(brandy);
        const addChild = [...el.querySelectorAll('button')]
            .find(b => b.textContent === '+ Child');
        addChild.click();
        expect(app.showAddForm).toBe(true);
        expect(app.formData.parent).toBe('Brandy');
        expect(app.addParent).toBe('Brandy');
        expect(app.showViewForm).toBe(false);
    });

    it('clicking Edit opens the edit form for the node, without opening view', () => {
        const product = whiskeyRoot().children[0].children[0]; // Buffalo Trace Bourbon
        const { app, el } = render(product);
        const editBtn = [...el.querySelectorAll('button')]
            .find(b => b.textContent === 'Edit');
        editBtn.click();
        expect(app.showEditForm).toBe(true);
        expect(app.editId).toBe('3'); // string id, straight from the API
        expect(app.showViewForm).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// expandAll / collapseAll
// ---------------------------------------------------------------------------

describe('expandAll / collapseAll', () => {
    it('clicks every collapsed toggle open, then every expanded toggle closed', () => {
        const app = freshApp();
        const el = document.createElement('div');
        document.body.appendChild(el);
        app.renderNode(whiskeyRoot(), el, 0); // Whiskey > Bourbon > products: two toggles
        const toggles = [...document.querySelectorAll('button[data-expanded]')];
        expect(toggles).toHaveLength(2);

        app.expandAll();
        expect(toggles.every(t => t.dataset.expanded === 'true')).toBe(true);
        app.expandAll(); // idempotent — nothing left to expand
        expect(toggles.every(t => t.dataset.expanded === 'true')).toBe(true);

        app.collapseAll();
        expect(toggles.every(t => t.dataset.expanded === 'false')).toBe(true);
    });
});

// ---------------------------------------------------------------------------
// View modal
// ---------------------------------------------------------------------------

describe('viewIngredient / viewIngredientByName / editFromView', () => {
    it('viewIngredient copies the node into viewData and opens the modal', () => {
        const brandy = ingredientsTree()[1];
        const app = freshApp();
        app.viewIngredient(brandy);
        expect(app.viewData).toEqual(brandy);
        expect(app.viewData).not.toBe(brandy); // spread copy
        expect(app.showViewForm).toBe(true);
    });

    it('viewIngredientByName searches, fetches full details for the exact match, and opens it', async () => {
        // The detail response is richer than the search match: ancestors and
        // direct children are only populated by GET /api/v1/ingredients/{id}.
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse(ingredientsSearch())],
            ['/api/v1/ingredients/2', jsonResponse(ingredientDetail())],
        ]));
        const app = freshApp();
        await app.viewIngredientByName('Bourbon');
        expect(fetch).toHaveBeenCalledWith('/api/v1/ingredients/search?q=Bourbon');
        expect(fetch).toHaveBeenCalledWith('/api/v1/ingredients/2');
        expect(app.viewData.ancestors).toEqual(['Whiskey']);
        expect(app.viewData.children.map(c => c.name))
            .toEqual(['Buffalo Trace Bourbon', 'Eagle Rare 10 Year']);
        expect(app.showViewForm).toBe(true);
    });

    it('falls back to the search match when the detail fetch fails', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse(ingredientsSearch())],
            ['/api/v1/ingredients/2', jsonResponse({}, { ok: false, status: 404 })],
        ]));
        const app = freshApp();
        await app.viewIngredientByName('Bourbon');
        expect(app.viewData.name).toBe('Bourbon');
        expect(app.viewData.ancestors).toEqual([]); // search matches carry no ancestors
        expect(app.showViewForm).toBe(true);
    });

    it('does nothing when no exact-name match exists (substring matches ignored)', async () => {
        const product = ingredientsSearch()[1]; // "Buffalo Trace Bourbon" contains "Bourbon"
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/search', jsonResponse([product])],
        ]));
        const app = freshApp();
        await app.viewIngredientByName('Bourbon');
        expect(app.showViewForm).toBe(false);
        expect(fetch).toHaveBeenCalledTimes(1); // no detail fetch
    });

    it('editFromView closes the view modal and opens edit with the viewed data', () => {
        const brandy = ingredientsTree()[1];
        const app = freshApp();
        app.viewIngredient(brandy);
        app.editFromView();
        expect(app.showViewForm).toBe(false);
        expect(app.showEditForm).toBe(true);
        expect(app.editId).toBe('5');
        expect(app.formData.name).toBe('Brandy');
    });
});

// ---------------------------------------------------------------------------
// Form open/close
// ---------------------------------------------------------------------------

describe('form lifecycle', () => {
    it('editIngredient fills the form from a real match row and focuses the name input', () => {
        const app = freshApp();
        const focus = vi.fn();
        app.$refs = { nameInput: { focus } };
        app.$nextTick = (cb) => cb();
        app.editIngredient(ingredientsSearch()[0]); // Bourbon: category, null product fields
        expect(app.editId).toBe('2');
        expect(app.formData).toEqual({
            name: 'Bourbon', parent: 'Whiskey', cost: null, volume_ml: null, abv: null, notes: '',
        });
        expect(app.formError).toBe('');
        expect(app.showEditForm).toBe(true);
        expect(focus).toHaveBeenCalled();
    });

    it('editIngredient keeps legitimate 0 values for cost, volume_ml, and abv', () => {
        // Regression variant (hand-mutated: no zero-value product in the
        // contract tree): `ing.cost || null` blanked 0 in the edit form, so
        // just opening and re-saving an ingredient wiped its zero values.
        const app = freshApp();
        app.editIngredient({
            ...ingredientsSearch()[1], name: 'Fresh Lime Juice',
            cost: 0, volume_ml: 0, abv: 0, notes: '',
        });
        expect(app.formData.cost).toBe(0);
        expect(app.formData.volume_ml).toBe(0);
        expect(app.formData.abv).toBe(0);
    });

    it('openAddForm resets the form and pre-fills the parent when given', () => {
        const app = freshApp();
        app.formData.name = 'leftover';
        app.formError = 'leftover error';
        app.editId = '99';
        app.openAddForm('Whiskey');
        expect(app.showAddForm).toBe(true);
        expect(app.addParent).toBe('Whiskey');
        expect(app.formData).toEqual({
            name: '', parent: 'Whiskey', cost: null, volume_ml: null, abv: null, notes: '',
        });
        expect(app.formError).toBe('');
        expect(app.editId).toBeNull();
    });

    it('openAddForm(null) leaves parent empty for a root ingredient', () => {
        const app = freshApp();
        app.openAddForm(null);
        expect(app.formData.parent).toBe('');
    });

    it('closeModal hides both forms and resets state', () => {
        const app = freshApp();
        app.showAddForm = true;
        app.showEditForm = true;
        app.formData.name = 'pending';
        app.editId = '3';
        app.closeModal();
        expect(app.showAddForm).toBe(false);
        expect(app.showEditForm).toBe(false);
        expect(app.formData.name).toBe('');
        expect(app.editId).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// saveIngredient — the POST/PUT body assertions mirror what the form builds;
// the contract producer (test_ingredients_contract.py) sends these exact
// payloads to the real API.
// ---------------------------------------------------------------------------

describe('saveIngredient', () => {
    it('requires a non-blank name and never fetches without one', async () => {
        const app = freshApp();
        app.formData.name = '   ';
        await app.saveIngredient();
        expect(app.formError).toBe('Name is required');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs a create payload with empty fields nulled out', async () => {
        const app = freshApp();
        app.formData = {
            name: 'Gin', parent: '', cost: null, volume_ml: null, abv: null, notes: '',
        };
        await app.saveIngredient();
        expect(fetch).toHaveBeenCalledWith('/api/v1/ingredients', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'Gin', parent: null, cost: null, volume_ml: null, abv: null, notes: null,
            }),
        });
        expect(app.showAddForm).toBe(false);
        expect(app.saving).toBe(false);
    });

    it('PUTs to the ingredient id when editing (the rename path recipes depend on)', async () => {
        const app = freshApp();
        app.showEditForm = true;
        app.editId = '2'; // ids arrive as strings from the API
        app.formData = {
            name: 'Bourbon Whiskey', parent: 'Whiskey', cost: 25, volume_ml: 750,
            abv: 40, notes: 'renamed',
        };
        await app.saveIngredient();
        expect(fetch).toHaveBeenCalledWith('/api/v1/ingredients/2', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'Bourbon Whiskey', parent: 'Whiskey', cost: 25, volume_ml: 750,
                abv: 40, notes: 'renamed',
            }),
        });
    });

    it('preserves legitimate 0 values for cost, volume_ml, and abv in the payload', async () => {
        // Regression: falsy checks (`!payload.cost`) coerced 0 to null, so a
        // free ingredient (cost 0) or non-alcoholic ingredient (abv 0) was
        // silently saved as "unknown". Only '' / null / undefined may null out.
        const app = freshApp();
        app.formData = {
            name: 'Fresh Lime Juice', parent: 'Brandy', cost: 0, volume_ml: 0,
            abv: 0, notes: '',
        };
        await app.saveIngredient();
        expect(fetch).toHaveBeenCalledWith('/api/v1/ingredients', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: 'Fresh Lime Juice', parent: 'Brandy', cost: 0, volume_ml: 0,
                abv: 0, notes: null,
            }),
        });
    });

    it('nulls out empty-string numeric inputs (cleared form fields)', async () => {
        const app = freshApp();
        app.formData = {
            name: 'Gin', parent: '', cost: '', volume_ml: '', abv: '', notes: '',
        };
        await app.saveIngredient();
        const body = JSON.parse(fetch.mock.calls[0][1].body);
        expect(body.cost).toBeNull();
        expect(body.volume_ml).toBeNull();
        expect(body.abv).toBeNull();
    });

    it('reloads the tree after a successful save', async () => {
        const app = freshApp();
        app.formData.name = 'Gin';
        const loadSpy = vi.spyOn(app, 'loadTree').mockResolvedValue();
        await app.saveIngredient();
        expect(loadSpy).toHaveBeenCalledTimes(1);
    });

    it('re-runs the active search after saving so results stay fresh', async () => {
        const app = freshApp();
        app.formData.name = 'Gin';
        app.searchMode = true;
        app.searchQuery = 'Gin';
        const loadSpy = vi.spyOn(app, 'loadTree').mockResolvedValue();
        const searchSpy = vi.spyOn(app, 'doSearch').mockResolvedValue();
        await app.saveIngredient();
        expect(loadSpy).toHaveBeenCalled();
        expect(searchSpy).toHaveBeenCalledTimes(1);
    });

    it('surfaces the API error detail (e.g. 409 duplicate) and keeps the modal open', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients', jsonResponse(
                { detail: "Ingredient 'Gin' already exists" }, { ok: false, status: 409 })],
        ]));
        const app = freshApp();
        app.showAddForm = true;
        app.formData.name = 'Gin';
        await app.saveIngredient();
        expect(app.formError).toBe("Ingredient 'Gin' already exists");
        expect(app.showAddForm).toBe(true);
        expect(app.saving).toBe(false);
    });

    it('falls back to a generic message when the error body has no detail', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        app.formData.name = 'Gin';
        await app.saveIngredient();
        expect(app.formError).toBe('Failed to save');
    });

    it('shows the exception message when the fetch itself throws', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down'); }));
        const app = freshApp();
        app.formData.name = 'Gin';
        await app.saveIngredient();
        expect(app.formError).toBe('network down');
        expect(app.saving).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// deleteIngredient — confirm-gated; backend 409s protect recipe references
// ---------------------------------------------------------------------------

describe('deleteIngredient', () => {
    it('does nothing without an editId', async () => {
        const app = freshApp();
        await app.deleteIngredient();
        expect(confirm).not.toHaveBeenCalled();
        expect(fetch).not.toHaveBeenCalled();
    });

    it('aborts when the user cancels the confirm', async () => {
        vi.stubGlobal('confirm', vi.fn(() => false));
        const app = freshApp();
        app.editId = '2';
        await app.deleteIngredient();
        expect(confirm).toHaveBeenCalledWith('Delete this ingredient? This cannot be undone.');
        expect(fetch).not.toHaveBeenCalled();
    });

    it('DELETEs the ingredient, closes the modal, and reloads the tree', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/2', jsonResponse({ status: 'deleted', name: 'Bourbon', id: '2' })],
        ]));
        const app = freshApp();
        app.showEditForm = true;
        app.editId = '2';
        const loadSpy = vi.spyOn(app, 'loadTree').mockResolvedValue();
        await app.deleteIngredient();
        expect(fetch).toHaveBeenCalledWith('/api/v1/ingredients/2', { method: 'DELETE' });
        expect(app.showEditForm).toBe(false);
        expect(loadSpy).toHaveBeenCalledTimes(1);
    });

    it('re-runs the active search after a delete', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/2', jsonResponse({ status: 'deleted', name: 'Bourbon', id: '2' })],
        ]));
        const app = freshApp();
        app.editId = '2';
        app.searchMode = true;
        app.searchQuery = 'Bourbon';
        vi.spyOn(app, 'loadTree').mockResolvedValue();
        const searchSpy = vi.spyOn(app, 'doSearch').mockResolvedValue();
        await app.deleteIngredient();
        expect(searchSpy).toHaveBeenCalledTimes(1);
    });

    it('surfaces the 409 detail when the ingredient is referenced by recipes', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/2', jsonResponse(
                { detail: "Cannot delete 'Bourbon': referenced by cocktail recipes" },
                { ok: false, status: 409 })],
        ]));
        const app = freshApp();
        app.showEditForm = true;
        app.editId = '2';
        await app.deleteIngredient();
        expect(app.formError).toBe("Cannot delete 'Bourbon': referenced by cocktail recipes");
        expect(app.showEditForm).toBe(true); // modal stays open
    });

    it('falls back to a generic delete error and shows thrown messages', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/ingredients/2', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        app.editId = '2';
        await app.deleteIngredient();
        expect(app.formError).toBe('Failed to delete');

        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('gone'); }));
        app.formError = '';
        await app.deleteIngredient();
        expect(app.formError).toBe('gone');
    });
});

// ---------------------------------------------------------------------------
// handleAutocomplete
// ---------------------------------------------------------------------------

describe('handleAutocomplete', () => {
    const OPTIONS = TREE_NAMES;

    function keyEvent(key, value) {
        const target = document.createElement('input');
        target.value = value;
        const dispatched = [];
        target.dispatchEvent = vi.fn((e) => { dispatched.push(e.type); return true; });
        return {
            key,
            target,
            preventDefault: vi.fn(),
            dispatched,
        };
    }

    it('ignores keys other than Tab and Enter', () => {
        const app = freshApp();
        const event = keyEvent('a', 'bou');
        app.handleAutocomplete(event, OPTIONS);
        expect(event.preventDefault).not.toHaveBeenCalled();
        expect(event.target.value).toBe('bou');
    });

    it('ignores blank input', () => {
        const app = freshApp();
        const event = keyEvent('Tab', '   ');
        app.handleAutocomplete(event, OPTIONS);
        expect(event.preventDefault).not.toHaveBeenCalled();
    });

    it('completes case-insensitively with the first starts-with match on Tab', () => {
        const app = freshApp();
        const event = keyEvent('Tab', 'bou');
        app.handleAutocomplete(event, OPTIONS);
        expect(event.preventDefault).toHaveBeenCalled();
        expect(event.target.value).toBe('Bourbon');
        expect(event.dispatched).toContain('input'); // syncs x-model
    });

    it('falls back to a contains match on Enter', () => {
        const app = freshApp();
        const event = keyEvent('Enter', 'trace');
        app.handleAutocomplete(event, OPTIONS);
        expect(event.target.value).toBe('Buffalo Trace Bourbon');
    });

    it('prefers starts-with over contains', () => {
        const app = freshApp();
        // 'b' starts Bitters, Brandy, Bourbon…; contains would also hit others
        const event = keyEvent('Tab', 'b');
        app.handleAutocomplete(event, OPTIONS);
        expect(event.target.value).toBe('Bitters');
    });

    it('leaves the value untouched when nothing matches', () => {
        const app = freshApp();
        const event = keyEvent('Tab', 'zzz');
        app.handleAutocomplete(event, OPTIONS);
        expect(event.preventDefault).not.toHaveBeenCalled();
        expect(event.target.value).toBe('zzz');
    });
});
