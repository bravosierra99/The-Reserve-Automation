/**
 * Unit tests for the tasting review module
 * (src/reserve_automation/web/static/js/management/tasting-review.js).
 *
 * Built like managementApp(): initState() spread for state + module spread
 * for methods.
 *
 * The tasting fixtures are NOT hand-written: they are contract fixtures —
 * real GET /api/v1/management/tastings rows captured and snapshot-verified by
 * tests/contract/test_management_contract.py (see tests/contract/contract.py).
 * Contract flow data: whiskey bottle:1 (Ben, 2026-07-01, 8.5/10, notes keyed
 * nose/palate/finish), wine bottle:2 (Sarah, 2026-07-03, 92.5/100, notes
 * keyed appearance/aroma/taste/aftertaste — the wine note-wiping regression
 * tests depend on that keying), cocktail cocktail:1 (Ben, 2026-07-05, 8/10,
 * Bourbon → Weller Special Reserve). The whiskey and the cocktail share
 * numeric id 1, so the kind-qualified row key is exercised by real data.
 * Per-test variants are explicit mutations of a fresh contract clone.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
import '../../src/reserve_automation/web/static/js/management/tasting-review.js';

function contractTastings() {
    return loadContract('management_tastings');
}

function freshComponent() {
    const mod = window.tastingReviewModule();
    return Object.assign({}, mod.initState(), mod);
}

let component;
let WHISKEY_TASTING;
let WINE_TASTING;
let COCKTAIL_TASTING;

beforeEach(() => {
    component = freshComponent();
    const rows = contractTastings().tastings;
    WHISKEY_TASTING = rows.find(t => t.type === 'whiskey');
    WINE_TASTING = rows.find(t => t.type === 'wine');
    COCKTAIL_TASTING = rows.find(t => t.type === 'cocktail');
});

afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
});

describe('formatting helpers', () => {
    it('trFmt rounds to one decimal and drops trailing .0', () => {
        expect(component.trFmt(8)).toBe('8');
        expect(component.trFmt(8.55)).toBe('8.6');
        expect(component.trFmt(8.04)).toBe('8');
        expect(component.trFmt(null)).toBe('—');
        expect(component.trFmt(undefined)).toBe('—');
    });

    it('trFormatScore appends the type-specific score label (contract data)', () => {
        expect(component.trFormatScore(WHISKEY_TASTING)).toBe('8.5/10');
        expect(component.trFormatScore(WINE_TASTING)).toBe('92.5/100');
        expect(component.trFormatScore(COCKTAIL_TASTING)).toBe('8/10');
        expect(component.trFormatScore({ ...WHISKEY_TASTING, total_score: null })).toBe('—');
    });

    it('trScoreBarPct clamps to 0-100', () => {
        expect(component.trScoreBarPct(WHISKEY_TASTING)).toBe(85);
        expect(component.trScoreBarPct({ ...WHISKEY_TASTING, total_score: 12 })).toBe(100);
        expect(component.trScoreBarPct({ ...WHISKEY_TASTING, total_score: null })).toBe(0);
    });

    it('trScoreBarColor buckets by percentage', () => {
        expect(component.trScoreBarColor({ total_score: 9.5, max_score: 10 })).toBe('bg-green-500');
        expect(component.trScoreBarColor(WINE_TASTING)).toBe('bg-green-500');       // 92.5%
        expect(component.trScoreBarColor(WHISKEY_TASTING)).toBe('bg-blue-500');      // 85%
        expect(component.trScoreBarColor({ total_score: 6.5, max_score: 10 })).toBe('bg-yellow-500');
        expect(component.trScoreBarColor({ total_score: 3, max_score: 10 })).toBe('bg-red-400');
        expect(component.trScoreBarColor({ total_score: null, max_score: 10 })).toBe('bg-gray-300');
    });

    it('trFormatExtra formats fill level with % and missing values as em-dash', () => {
        expect(component.trFormatExtra(WHISKEY_TASTING, 'fill_level')).toBe('80%');
        expect(component.trFormatExtra(WHISKEY_TASTING, 'days_from_crack')).toBe('12');
        expect(component.trFormatExtra(COCKTAIL_TASTING, 'bartender')).toBe('Ben');
        expect(component.trFormatExtra({ fill_level: null }, 'fill_level')).toBe('—');
    });

    it('trFormatNoteSection joins arrays and passes strings through (contract data)', () => {
        expect(component.trFormatNoteSection(WHISKEY_TASTING.notes, 'nose')).toBe('caramel, oak');
        expect(component.trFormatNoteSection(WHISKEY_TASTING.notes, 'overall')).toBe('Great pour');
        expect(component.trFormatNoteSection(WHISKEY_TASTING.notes, 'missing')).toBe('');
        expect(component.trFormatNoteSection(null, 'nose')).toBe('');
    });
});

describe('sorting and rows', () => {
    it('trSort toggles direction on the same column, resets on a new one', () => {
        expect(component.trSortColumn).toBe('date');
        expect(component.trSortDir).toBe('desc');

        component.trSort('date');
        expect(component.trSortDir).toBe('asc');

        component.trSort('taster');
        expect(component.trSortColumn).toBe('taster');
        expect(component.trSortDir).toBe('asc');

        component.trSort('date');
        expect(component.trSortDir).toBe('desc');  // date defaults to desc
    });

    it('trRowKey is kind-qualified so bottle #1 and cocktail #1 are distinct rows', () => {
        // The contract data really does contain both a bottle tasting and a
        // cocktail tasting with id 1.
        expect(component.trRowKey(WHISKEY_TASTING)).toBe('bottle:1');
        expect(component.trRowKey(COCKTAIL_TASTING)).toBe('cocktail:1');
    });

    it('trToggleRow expands/collapses and closes any open edit form', () => {
        component.trEditingId = 'bottle:9';
        component.trToggleRow(WHISKEY_TASTING);
        expect(component.trIsExpanded(WHISKEY_TASTING)).toBe(true);
        expect(component.trEditingId).toBeNull();

        component.trToggleRow(WHISKEY_TASTING);
        expect(component.trIsExpanded(WHISKEY_TASTING)).toBe(false);
    });
});

describe('filters', () => {
    it('trHasActiveFilters reflects every filter input', () => {
        expect(component.trHasActiveFilters()).toBeFalsy();
        component.trFilterSearch = 'weller';
        expect(component.trHasActiveFilters()).toBeTruthy();
        component.trFilterSearch = '';
        component.trTypeFilters = { variety: 'Cabernet Sauvignon' };
        expect(component.trHasActiveFilters()).toBeTruthy();
    });

    it('trResetFilters clears everything back to defaults', () => {
        Object.assign(component, {
            trFilterType: 'wine', trFilterTaster: 'Ben', trFilterSearch: 'x',
            trFilterMinScore: 80, trFilterMaxScore: 95,
            trFilterDateFrom: '2026-01-01', trFilterDateTo: '2026-06-01',
            trTypeFilters: { variety: 'Cab' }, trExpandedKey: 'bottle:1',
        });
        component.trResetFilters();
        expect(component.trHasActiveFilters()).toBeFalsy();
        expect(component.trFilterType).toBe('all');
        expect(component.trExpandedKey).toBeNull();
    });

    it('type-specific filters only exist for a concrete selected type', () => {
        expect(component.trActiveTypeFilters()).toEqual([]);
        component.trFilterType = 'wine';
        expect(component.trActiveTypeFilters().map(f => f.key)).toContain('variety');
        expect(component.trExtraColumns().map(c => c.key)).toContain('aws_score');
    });
});

describe('loadTastings', () => {
    it('stores tastings, tasters, and filter options from the API (contract data)', async () => {
        const contract = contractTastings();
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true,
            json: async () => contract,
        }));

        await component.loadTastings();

        expect(component.trAllTastings).toEqual(contract.tastings);
        expect(component.trAllTastings).toHaveLength(3);
        expect(component.trTasters).toEqual(['Ben', 'Sarah']);
        expect(component.trFilterOptionsData).toEqual(contract.filter_options);
        expect(component.trFilterOptions('variety')).toEqual(['Cabernet Sauvignon']);
        expect(component.trLoading).toBe(false);
        expect(component.trError).toBeNull();
    });

    it('captures server errors', async () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));
        await component.loadTastings();
        expect(component.trError).toBe('Server error 500');
        expect(component.trLoading).toBe(false);
    });
});

describe('edit buffer (trStartEdit)', () => {
    const evt = () => ({ stopPropagation: vi.fn() });

    it('loads whiskey scores and notes as editable strings', () => {
        component.trStartEdit(WHISKEY_TASTING, evt());
        expect(component.trIsEditing(WHISKEY_TASTING)).toBe(true);
        expect(component.trEditData.nose).toBe(2.5);
        expect(component.trEditData.nose_notes).toBe('caramel, oak');
        expect(component.trEditData.palate_notes).toBe('cherry');
        expect(component.trEditData.overall_notes).toBe('Great pour');
        expect(component.trEditData.days_from_crack).toBe(12);
    });

    it('loads wine notes from their wine keys (the July 2026 note-wiping regression)', () => {
        // Wine notes come back keyed appearance/aroma/taste/aftertaste — the
        // contract fixture proves the real API sends them that way. The old
        // code read nose/palate/finish, loaded '' for every wine section, and
        // trSaveEdit then sent those empty strings back — silently erasing the
        // aroma and aftertaste notes whenever a wine score was edited.
        component.trStartEdit(WINE_TASTING, evt());
        expect(component.trEditData.appearance_notes).toBe('ruby');
        expect(component.trEditData.aroma_notes).toBe('blackberry, cassis');
        expect(component.trEditData.taste_notes).toBe('tannic');
        expect(component.trEditData.aftertaste_notes).toBe('long');
        expect(component.trEditData.overall_notes).toBe('Lovely');
    });

    it('routes cocktail edits to the modal instead of the inline form', () => {
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));
        component.trStartEdit(COCKTAIL_TASTING, evt());
        expect(component.trEditingId).toBeNull();
        expect(component.trCocktailModalTasting).toEqual(COCKTAIL_TASTING);
    });

    it('trCancelEdit discards the buffer', () => {
        component.trStartEdit(WHISKEY_TASTING, evt());
        component.trCancelEdit(evt());
        expect(component.trEditingId).toBeNull();
        expect(component.trEditData).toEqual({});
    });
});

describe('trSaveEdit payloads', () => {
    const evt = () => ({ stopPropagation: vi.fn() });

    function stubPatch() {
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => ({ tastings: [], tasters: [], filter_options: {} }),
        });
        vi.stubGlobal('fetch', fetchMock);
        return fetchMock;
    }

    it('whiskey: sends whiskey_* scores and note strings', async () => {
        component.trStartEdit(WHISKEY_TASTING, evt());
        const fetchMock = stubPatch();
        component.trEditData.nose = '2.8';
        component.trEditData.nose_notes = 'caramel, oak, smoke';

        await component.trSaveEdit(WHISKEY_TASTING, evt());

        const [url, opts] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/v1/management/tastings/bottle/1');
        expect(opts.method).toBe('PATCH');
        const body = JSON.parse(opts.body);
        expect(body.whiskey_nose).toBe(2.8);
        expect(body.nose_notes).toBe('caramel, oak, smoke');
        expect(body.days_from_crack).toBe(12);
        expect(body.fill_level).toBe(80);
        // Edit closed + list reloaded
        expect(component.trEditingId).toBeNull();
        expect(fetchMock).toHaveBeenCalledTimes(2);
    });

    it('wine: an untouched edit round-trips every note section unchanged (regression)', async () => {
        // The exact user story that lost data: open a wine tasting, tweak a
        // score, save. All four note sections must survive.
        component.trStartEdit(WINE_TASTING, evt());
        const fetchMock = stubPatch();
        component.trEditData.aroma = '5.5';

        await component.trSaveEdit(WINE_TASTING, evt());

        const body = JSON.parse(fetchMock.mock.calls[0][1].body);
        expect(body.wine_aroma).toBe(5.5);
        expect(body.appearance_notes).toBe('ruby');
        expect(body.nose_notes).toBe('blackberry, cassis');    // wine aroma → nose_notes column
        expect(body.palate_notes).toBe('tannic');               // wine taste → palate_notes column
        expect(body.finish_notes).toBe('long');                 // wine aftertaste → finish_notes column
        expect(body.overall_notes).toBe('Lovely');
    });

    it('wine: edited note fields are sent to their backend columns', async () => {
        component.trStartEdit(WINE_TASTING, evt());
        const fetchMock = stubPatch();
        component.trEditData.aroma_notes = 'blackberry, cassis, violet';
        component.trEditData.aftertaste_notes = 'long, silky';

        await component.trSaveEdit(WINE_TASTING, evt());

        const body = JSON.parse(fetchMock.mock.calls[0][1].body);
        expect(body.nose_notes).toBe('blackberry, cassis, violet');
        expect(body.finish_notes).toBe('long, silky');
    });

    it('alerts and keeps the edit form open when the server rejects the save', async () => {
        component.trStartEdit(WHISKEY_TASTING, evt());
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422 }));
        const alertMock = vi.fn();
        vi.stubGlobal('alert', alertMock);

        await component.trSaveEdit(WHISKEY_TASTING, evt());

        expect(alertMock).toHaveBeenCalledWith('Failed to save: Server error 422');
        expect(component.trEditingId).toBe('bottle:1');
    });
});

describe('delete and hide', () => {
    const evt = () => ({ stopPropagation: vi.fn() });

    it('trDeleteTasting removes only the confirmed row (kind-qualified)', async () => {
        // Real contract data: the whiskey (bottle) and the cocktail share id 1.
        component.trAllTastings = [WHISKEY_TASTING, WINE_TASTING, COCKTAIL_TASTING];
        vi.stubGlobal('confirm', vi.fn().mockReturnValue(true));
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: true,
            // Real DELETE response shape (contract fixture) — the component
            // ignores the body, but this is what the API actually sends.
            json: async () => loadContract('management_tasting_delete_response'),
        }));

        await component.trDeleteTasting(WHISKEY_TASTING, evt());

        expect(component.trAllTastings.map(t => component.trRowKey(t)))
            .toEqual(['bottle:2', 'cocktail:1']);
    });

    it('trDeleteTasting does nothing when the user cancels the confirm', async () => {
        component.trAllTastings = [WHISKEY_TASTING];
        vi.stubGlobal('confirm', vi.fn().mockReturnValue(false));
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);

        await component.trDeleteTasting(WHISKEY_TASTING, evt());

        expect(fetchMock).not.toHaveBeenCalled();
        expect(component.trAllTastings).toHaveLength(1);
    });

    it('trToggleHidden PATCHes and flips the row in place', async () => {
        component.trAllTastings = [{ ...WHISKEY_TASTING }];
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true,
            json: async () => loadContract('management_tasting_update_response'),
        });
        vi.stubGlobal('fetch', fetchMock);

        await component.trToggleHidden(component.trAllTastings[0], evt());

        const body = JSON.parse(fetchMock.mock.calls[0][1].body);
        expect(body).toEqual({ hidden: true });
        expect(component.trAllTastings[0].hidden).toBe(true);
    });
});

describe('cocktail edit modal', () => {
    it('trOpenCocktailModal builds bottles_used from the recipe ingredient order (contract data)', async () => {
        // The real recipe as GET /api/v1/cocktails/{id} returns it: Bourbon +
        // Sweet Vermouth; the tasting only recorded a bottle for Bourbon.
        const recipe = loadContract('management_cocktail_detail');
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => recipe }));

        await component.trOpenCocktailModal(COCKTAIL_TASTING);

        expect(component.trCocktailModalOpen).toBe(true);
        expect(component.trCocktailModalRecipe).toEqual(recipe);
        expect(component.trCocktailEditData.bottles_used).toEqual([
            { recipe_ingredient: 'Bourbon', actual_product: 'Weller Special Reserve' },
            { recipe_ingredient: 'Sweet Vermouth', actual_product: '' },
        ]);
        expect(component.trCocktailBottleQueries[0]).toBe('Weller Special Reserve');
        expect(component.trCocktailEditData.score).toBe(8);
        expect(component.trCocktailEditData.notes).toBe('Well balanced');
    });

    it('trCocktailSelectBottle records the chosen product and clears its results', () => {
        component.trCocktailEditData = { bottles_used: [{ recipe_ingredient: 'Bourbon', actual_product: '' }] };
        component.trCocktailBottleResults = { 0: [{ name: 'Weller' }] };

        component.trCocktailSelectBottle(0, { name: 'Weller' }, 'Bourbon');

        expect(component.trCocktailEditData.bottles_used[0]).toEqual(
            { recipe_ingredient: 'Bourbon', actual_product: 'Weller' });
        expect(component.trCocktailBottleQueries[0]).toBe('Weller');
        expect(component.trCocktailBottleResults[0]).toEqual([]);
    });

    it('trCocktailSaveEdit surfaces failures in the modal instead of closing it', async () => {
        component.trCocktailModalTasting = COCKTAIL_TASTING;
        component.trCocktailModalOpen = true;
        component.trCocktailEditData = {
            taster_name: 'Ben', tasting_date: '2026-07-05', score: 8,
            notes: '', bartender: 'Ben', bottles_used: [],
        };
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));

        await component.trCocktailSaveEdit();

        expect(component.trCocktailModalOpen).toBe(true);
        expect(component.trCocktailEditError).toBe('Failed to save: Server error 500');
    });
});
