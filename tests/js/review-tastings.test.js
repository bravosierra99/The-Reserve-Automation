/**
 * Unit tests for the tasting review page component
 * (src/reserve_automation/web/static/js/tastings/review-tastings.js).
 *
 * The REAL tasting-form-mixin is imported so composition is tested for real —
 * tastingReview() must merge its note inputs/methods exactly like the page
 * does. Alpine itself is not loaded; the factory's return value is used
 * directly, which exercises the live getters (currentTasting, tasting, isWine,
 * computedWineScore, computed100ptScore, computedWhiskeyScore) the same way
 * Alpine would.
 *
 * Fixtures mirror the real API shapes in web/routes/tastings.py:
 * GET /api/v1/tastings/{id} (session), POST .../match ({duplicate_warning}),
 * POST .../approve and .../skip ({stats}), and web/routes/bottles.py
 * GET /api/v1/bottles/search ({results}).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/tasting-form-mixin.js';
import '../../src/reserve_automation/web/static/js/tastings/review-tastings.js';

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

const EXTRACTION_ID = 'ext-abc-123';

// Mirrors the GET /api/v1/tastings/{extraction_id} response (routes/tastings.py
// get_tasting_session → response_data). Note the per-type tasting_data keys:
// wine sessions carry wine_appearance/wine_aroma/wine_taste/wine_aftertaste,
// whiskey (bourbon) sessions carry whiskey_nose/whiskey_palate/whiskey_finish.
function wineSession() {
    return {
        extraction_id: EXTRACTION_ID,
        beverage_type: 'wine',
        template_type: 'aws_wine',
        expected_count: 2,
        actual_count: 2,
        count_mismatch: false,
        current_index: 0,
        tastings: [
            {
                status: 'extracted',
                selected_match: null,
                duplicate_warning: null,
                match_candidates: [
                    {
                        bottle_path: 'Cellar/Wine/Grand Cru.md',
                        bottle_name: 'Grand Cru',
                        producer: 'Domaine X',
                        confidence: 0.92,
                        thumbnail_url: '/media/bottles/1/label.jpg',
                    },
                    {
                        bottle_path: 'Cellar/Wine/Petit Verdot.md',
                        bottle_name: 'Petit Verdot',
                        producer: 'Domaine Y',
                        confidence: 0.41,
                        thumbnail_url: null,
                    },
                ],
                tasting_data: {
                    bottle_name: 'Grand Cru',
                    taster_name: '',
                    tasting_date: '2026-07-01',
                    place: '',
                    theme: '',
                    wine_appearance: 3,
                    wine_aroma: 5,
                    wine_taste: 4,
                    wine_aftertaste: 1.5,
                    wine_overall: 1.5,
                },
            },
            {
                status: 'extracted',
                selected_match: null,
                duplicate_warning: null,
                match_candidates: [],
                tasting_data: {
                    bottle_name: 'Mystery Red',
                    taster_name: 'Sarah',
                    tasting_date: '2026-07-01',
                    place: '',
                    theme: '',
                    wine_appearance: 2,
                    wine_aroma: 3,
                    wine_taste: 3,
                    wine_aftertaste: 1,
                    wine_overall: 1,
                },
            },
        ],
        stats: { approved: 0, skipped: 0, remaining: 2, all_done: false },
    };
}

function bourbonSession() {
    const session = wineSession();
    session.beverage_type = 'whiskey';
    session.template_type = 'bourbon';
    session.tastings[0].tasting_data = {
        bottle_name: 'Weller 12',
        taster_name: 'Ben',
        tasting_date: '2026-07-01',
        whiskey_nose: 2.5,
        whiskey_palate: 2.5,
        whiskey_finish: 2,
        whiskey_overall: 0.8,
    };
    return session;
}

function clearParticipantCookie() {
    document.cookie = 'participant_sessions=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
}

function setParticipantCookie(sessions) {
    document.cookie = 'participant_sessions=' + encodeURIComponent(JSON.stringify(sessions));
}

function freshApp() {
    return window.tastingReview();
}

async function loadedApp(session = wineSession(), routes = []) {
    // Custom routes first: the bare session URL is a prefix of every
    // sub-path (…/match, …/approve, …) and would shadow them.
    vi.stubGlobal('fetch', routeFetch([
        ...routes,
        [`/api/v1/tastings/${EXTRACTION_ID}`, jsonResponse(session)],
    ]));
    const app = freshApp();
    await app.loadSession();
    return app;
}

beforeEach(() => {
    window.PAGE_DATA = { extractionId: EXTRACTION_ID };
    vi.stubGlobal('fetch', routeFetch([]));
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('confirm', vi.fn(() => true));
});

afterEach(() => {
    delete window.PAGE_DATA;
    clearParticipantCookie();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Initial state & composition
// ---------------------------------------------------------------------------

describe('initial state', () => {
    it('reads extractionId from window.PAGE_DATA (the Jinja bootstrap)', () => {
        expect(freshApp().extractionId).toBe(EXTRACTION_ID);
    });

    it('falls back to an empty extractionId when PAGE_DATA is missing', () => {
        delete window.PAGE_DATA;
        expect(freshApp().extractionId).toBe('');
    });

    it('starts loading with default stats and no session', () => {
        const app = freshApp();
        expect(app.loading).toBe(true);
        expect(app.error).toBe(false);
        expect(app.session).toBeNull();
        expect(app.currentIndex).toBe(0);
        expect(app.stats).toEqual({ approved: 0, skipped: 0, remaining: 0, all_done: false });
        expect(app.searchQuery).toBe('');
        expect(app.searchResults).toEqual([]);
        expect(app.showSearchModal).toBe(false);
        expect(app.approving).toBe(false);
        expect(app.skipping).toBe(false);
        expect(app.participantSession).toBeNull();
    });

    it('merges the tasting form mixin (note inputs + methods)', () => {
        const app = freshApp();
        expect(app.noseNotesInput).toBe('');
        expect(app.aromaNotesInput).toBe('');
        expect(app.clearNoteInputs).toBeTypeOf('function');
        expect(app.addNoseNote).toBeTypeOf('function');
    });
});

// ---------------------------------------------------------------------------
// Getters — the reason this factory is attached whole, never spread
// ---------------------------------------------------------------------------

describe('getters', () => {
    it('currentTasting is null without a session and live once loaded', async () => {
        const app = freshApp();
        expect(app.currentTasting).toBeNull();

        await loadedApp().then(loaded => {
            expect(loaded.currentTasting.tasting_data.bottle_name).toBe('Grand Cru');
            loaded.currentIndex = 1;
            expect(loaded.currentTasting.tasting_data.bottle_name).toBe('Mystery Red');
        });
    });

    it('tasting proxies the current tasting_data (or {} when absent)', async () => {
        const app = freshApp();
        expect(app.tasting).toEqual({});

        const loaded = await loadedApp();
        expect(loaded.tasting.bottle_name).toBe('Grand Cru');
    });

    it('isWine keys off template_type === aws_wine', async () => {
        const wine = await loadedApp(wineSession());
        expect(wine.isWine).toBe(true);

        const bourbon = await loadedApp(bourbonSession());
        expect(bourbon.isWine).toBe(false);
    });

    it('computedWineScore sums the WINE keys (appearance/aroma/taste/aftertaste/overall)', async () => {
        const app = await loadedApp(wineSession());
        // 3 + 5 + 4 + 1.5 + 1.5
        expect(app.computedWineScore).toBe(15);
    });

    it('computed100ptScore maps the 20-pt wine score onto 50-100', async () => {
        const app = await loadedApp(wineSession());
        expect(app.computed100ptScore).toBe(50 + (15 / 20) * 50);
    });

    it('computedWhiskeyScore sums the WHISKEY keys (nose/palate/finish/overall)', async () => {
        const app = await loadedApp(bourbonSession());
        // 2.5 + 2.5 + 2 + 0.8
        expect(app.computedWhiskeyScore).toBeCloseTo(7.8);
    });

    it('wine keys never leak into the whiskey score and vice versa', async () => {
        const app = await loadedApp(wineSession());
        expect(app.computedWhiskeyScore).toBe(0);

        const bourbon = await loadedApp(bourbonSession());
        expect(bourbon.computedWineScore).toBe(0);
    });

    it('score getters stay live as the current index moves', async () => {
        const app = await loadedApp(wineSession());
        expect(app.computedWineScore).toBe(15);
        app.currentIndex = 1;
        expect(app.computedWineScore).toBe(10);
    });
});

// ---------------------------------------------------------------------------
// loadSession
// ---------------------------------------------------------------------------

describe('loadSession', () => {
    it('fetches the session, applies current_index and stats, ends loading', async () => {
        const session = wineSession();
        session.current_index = 1;
        session.stats = { approved: 1, skipped: 0, remaining: 1, all_done: false };
        const app = await loadedApp(session);

        expect(fetch).toHaveBeenCalledWith(`/api/v1/tastings/${EXTRACTION_ID}`);
        expect(app.session.template_type).toBe('aws_wine');
        expect(app.currentIndex).toBe(1);
        expect(app.stats.approved).toBe(1);
        expect(app.loading).toBe(false);
        expect(app.error).toBe(false);
    });

    it('defaults current_index and stats when the payload omits them', async () => {
        const session = wineSession();
        delete session.current_index;
        delete session.stats;
        const app = await loadedApp(session);

        expect(app.currentIndex).toBe(0);
        expect(app.stats).toEqual({ approved: 0, skipped: 0, remaining: 0, all_done: false });
    });

    it('clears note inputs on load', async () => {
        vi.stubGlobal('fetch', routeFetch([
            [`/api/v1/tastings/${EXTRACTION_ID}`, jsonResponse(wineSession())],
        ]));
        const app = freshApp();
        app.noseNotesInput = 'leftover';
        app.aromaNotesInput = 'stale';
        await app.loadSession();
        expect(app.noseNotesInput).toBe('');
        expect(app.aromaNotesInput).toBe('');
    });

    it('auto-fills empty taster names from a single-event participant cookie', async () => {
        setParticipantCookie({ 'evt-1': { participant_id: 'p-9', participant_name: 'Alice' } });
        const app = await loadedApp(wineSession());

        expect(app.participantSession).toEqual({
            event_id: 'evt-1',
            participant_id: 'p-9',
            participant_name: 'Alice',
        });
        // Empty taster filled, existing taster preserved.
        expect(app.session.tastings[0].tasting_data.taster_name).toBe('Alice');
        expect(app.session.tastings[1].tasting_data.taster_name).toBe('Sarah');
    });

    it('does not auto-fill when the cookie holds multiple events', async () => {
        setParticipantCookie({
            'evt-1': { participant_id: 'p-1', participant_name: 'Alice' },
            'evt-2': { participant_id: 'p-2', participant_name: 'Bob' },
        });
        const app = await loadedApp(wineSession());

        expect(app.participantSession).toBeNull();
        expect(app.session.tastings[0].tasting_data.taster_name).toBe('');
    });

    it('surfaces the API detail message on failure', async () => {
        vi.stubGlobal('fetch', routeFetch([
            [`/api/v1/tastings/${EXTRACTION_ID}`,
                jsonResponse({ detail: 'Invalid or expired session' }, { ok: false, status: 401 })],
        ]));
        const app = freshApp();
        await app.loadSession();

        expect(app.error).toBe(true);
        expect(app.errorMessage).toBe('Invalid or expired session');
        expect(app.loading).toBe(false);
        expect(app.session).toBeNull();
    });

    it('handles network failure with the fallback message path', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom'); }));
        const app = freshApp();
        await app.loadSession();

        expect(app.error).toBe(true);
        expect(app.errorMessage).toBe('boom');
        expect(app.loading).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// getParticipantSession
// ---------------------------------------------------------------------------

describe('getParticipantSession', () => {
    it('returns null with no participant cookie', () => {
        expect(freshApp().getParticipantSession()).toBeNull();
    });

    it('returns the session for exactly one event', () => {
        setParticipantCookie({ 'evt-7': { participant_id: 'p-3', participant_name: 'Cara' } });
        expect(freshApp().getParticipantSession()).toEqual({
            event_id: 'evt-7',
            participant_id: 'p-3',
            participant_name: 'Cara',
        });
    });

    it('returns null (and logs) on a malformed cookie', () => {
        const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        document.cookie = 'participant_sessions=not-json';
        expect(freshApp().getParticipantSession()).toBeNull();
        expect(errSpy).toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------

describe('navigation', () => {
    it('prevTasting is a no-op at index 0', async () => {
        const app = await loadedApp();
        app.prevTasting();
        expect(app.currentIndex).toBe(0);
    });

    it('next/prev move the index and reset search state + note inputs', async () => {
        const app = await loadedApp();
        app.searchQuery = 'well';
        app.searchResults = [{ bottle_path: 'x' }];
        app.noseNotesInput = 'oak';

        app.nextTasting();
        expect(app.currentIndex).toBe(1);
        expect(app.searchQuery).toBe('');
        expect(app.searchResults).toEqual([]);
        expect(app.noseNotesInput).toBe('');

        app.prevTasting();
        expect(app.currentIndex).toBe(0);
    });

    it('nextTasting stops at the last tasting', async () => {
        const app = await loadedApp();
        app.currentIndex = 1;
        app.nextTasting();
        expect(app.currentIndex).toBe(1);
    });

    it('goToTasting jumps directly and resets search state', async () => {
        const app = await loadedApp();
        app.searchQuery = 'q';
        app.goToTasting(1);
        expect(app.currentIndex).toBe(1);
        expect(app.searchQuery).toBe('');
    });
});

// ---------------------------------------------------------------------------
// saveTastingData
// ---------------------------------------------------------------------------

describe('saveTastingData', () => {
    it('does nothing without a current tasting', async () => {
        const app = freshApp();
        await app.saveTastingData();
        expect(fetch).not.toHaveBeenCalled();
    });

    it('PUTs the current tasting_data to the per-index endpoint', async () => {
        const app = await loadedApp();
        fetch.mockClear();
        app.currentIndex = 1;
        await app.saveTastingData();

        expect(fetch).toHaveBeenCalledWith(
            `/api/v1/tastings/${EXTRACTION_ID}/1`,
            {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tasting_data: app.session.tastings[1].tasting_data }),
            },
        );
    });

    it('swallows save errors (logs, does not throw or alert)', async () => {
        const app = await loadedApp();
        const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));

        await expect(app.saveTastingData()).resolves.toBeUndefined();
        expect(errSpy).toHaveBeenCalled();
        expect(alert).not.toHaveBeenCalled();
    });

    it('is triggered by onTastingChange (shared component hook)', async () => {
        const app = await loadedApp();
        fetch.mockClear();
        app.onTastingChange();
        await Promise.resolve();
        expect(fetch).toHaveBeenCalledWith(
            `/api/v1/tastings/${EXTRACTION_ID}/0`,
            expect.objectContaining({ method: 'PUT' }),
        );
    });
});

// ---------------------------------------------------------------------------
// Match selection
// ---------------------------------------------------------------------------

describe('selectMatch / clearMatch', () => {
    it('POSTs the bottle_path and applies the match + duplicate warning', async () => {
        const app = await loadedApp(wineSession(), [
            ['/match', jsonResponse({
                status: 'matched',
                selected_match: 'Cellar/Wine/Grand Cru.md',
                duplicate_warning: 'Ben already tasted this on 2026-07-01',
            })],
        ]);
        const originalArray = app.session.tastings;

        await app.selectMatch('Cellar/Wine/Grand Cru.md');

        expect(fetch).toHaveBeenCalledWith(
            `/api/v1/tastings/${EXTRACTION_ID}/0/match`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ bottle_path: 'Cellar/Wine/Grand Cru.md' }),
            },
        );
        const t = app.session.tastings[0];
        expect(t.selected_match).toBe('Cellar/Wine/Grand Cru.md');
        expect(t.status).toBe('matched');
        expect(t.duplicate_warning).toBe('Ben already tasted this on 2026-07-01');
        // Reactivity nudge: the array is reassigned, not mutated in place.
        expect(app.session.tastings).not.toBe(originalArray);
        expect(app.searchResults).toEqual([]);
    });

    it('alerts (and leaves the tasting untouched) when the match POST fails', async () => {
        const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        const app = await loadedApp(wineSession(), [
            ['/match', jsonResponse({ detail: 'nope' }, { ok: false, status: 500 })],
        ]);

        await app.selectMatch('Cellar/Wine/Grand Cru.md');

        expect(alert).toHaveBeenCalledWith(expect.stringContaining('HTTP 500'));
        expect(app.session.tastings[0].selected_match).toBeNull();
        expect(errSpy).toHaveBeenCalled();
    });

    it('selectMatchFromSearch also closes the modal and clears the query', async () => {
        const app = await loadedApp(wineSession(), [
            ['/match', jsonResponse({ status: 'matched', duplicate_warning: null })],
        ]);
        app.showSearchModal = true;
        app.searchQuery = 'grand';

        await app.selectMatchFromSearch('Cellar/Wine/Grand Cru.md');

        expect(app.session.tastings[0].selected_match).toBe('Cellar/Wine/Grand Cru.md');
        expect(app.showSearchModal).toBe(false);
        expect(app.searchQuery).toBe('');
        expect(app.searchResults).toEqual([]);
    });

    it('clearMatch resets the match locally with a fresh array', async () => {
        const app = await loadedApp();
        app.session.tastings[0].selected_match = 'Cellar/Wine/Grand Cru.md';
        app.session.tastings[0].status = 'matched';
        const originalArray = app.session.tastings;

        app.clearMatch();

        expect(app.session.tastings[0].selected_match).toBeNull();
        expect(app.session.tastings[0].status).toBe('extracted');
        expect(app.session.tastings).not.toBe(originalArray);
    });
});

describe('selected match display helpers', () => {
    it('resolve thumbnail/name/confidence from the matching candidate', async () => {
        const app = await loadedApp();
        app.session.tastings[0].selected_match = 'Cellar/Wine/Grand Cru.md';

        expect(app.getSelectedMatchThumbnail()).toBe('/media/bottles/1/label.jpg');
        expect(app.getSelectedMatchName()).toBe('Grand Cru');
        expect(app.getSelectedMatchConfidence()).toBe(0.92);
    });

    it('fall back when the selected path is not among the candidates', async () => {
        const app = await loadedApp();
        app.session.tastings[0].selected_match = 'Cellar/Wine/From Search.md';

        expect(app.getSelectedMatchThumbnail()).toBeNull();
        expect(app.getSelectedMatchName()).toBe('Cellar/Wine/From Search.md');
        expect(app.getSelectedMatchConfidence()).toBe(0);
    });
});

// ---------------------------------------------------------------------------
// Search (debounce + fetch)
// ---------------------------------------------------------------------------

describe('debouncedSearch / searchBottles', () => {
    it('debounces: only one search fires after 100ms of quiet', async () => {
        vi.useFakeTimers();
        const app = await loadedApp(wineSession(), [
            ['/api/v1/bottles/search', jsonResponse({ results: [{ bottle_path: 'a' }] })],
        ]);
        fetch.mockClear();

        app.searchQuery = 'gra';
        app.debouncedSearch();
        app.searchQuery = 'gran';
        app.debouncedSearch();
        expect(app.searching).toBe(true);
        expect(fetch).not.toHaveBeenCalled();

        await vi.advanceTimersByTimeAsync(100);

        expect(fetch).toHaveBeenCalledTimes(1);
        expect(app.searchResults).toEqual([{ bottle_path: 'a' }]);
        expect(app.searching).toBe(false);
    });

    it('an emptied query clears results without fetching', async () => {
        const app = await loadedApp();
        fetch.mockClear();
        app.searchResults = [{ bottle_path: 'stale' }];
        app.searchQuery = '   ';

        app.debouncedSearch();

        expect(app.searchResults).toEqual([]);
        expect(app.searching).toBe(false);
        expect(fetch).not.toHaveBeenCalled();
    });

    it('searchBottles hits the search endpoint with encoded query, beverage type and limit', async () => {
        const app = await loadedApp(wineSession(), [
            ['/api/v1/bottles/search', jsonResponse({ results: [] })],
        ]);
        fetch.mockClear();
        app.searchQuery = 'grand cru';

        await app.searchBottles();

        expect(fetch).toHaveBeenCalledWith(
            '/api/v1/bottles/search?q=grand%20cru&beverage_type=wine&limit=20',
            { credentials: 'same-origin' },
        );
    });

    it('alerts and clears results when the search endpoint errors', async () => {
        const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        const app = await loadedApp(wineSession(), [
            ['/api/v1/bottles/search', jsonResponse({ detail: 'boom' }, { ok: false, status: 500 })],
        ]);
        app.searchQuery = 'x';
        app.searchResults = [{ bottle_path: 'stale' }];

        await app.searchBottles();

        expect(alert).toHaveBeenCalledWith(expect.stringContaining('Search failed'));
        expect(app.searchResults).toEqual([]);
        expect(app.searching).toBe(false);
        expect(errSpy).toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------------------
// Approve / skip / reject
// ---------------------------------------------------------------------------

describe('approveTasting', () => {
    it('refuses to approve without a selected match', async () => {
        const app = await loadedApp();
        fetch.mockClear();
        await app.approveTasting();
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs approve, marks the tasting, adopts stats and advances to next pending', async () => {
        const app = await loadedApp(wineSession(), [
            ['/approve', jsonResponse({
                status: 'approved',
                file_created: 'Cellar/Tastings/x.md',
                stats: { approved: 1, skipped: 0, remaining: 1, all_done: false },
            })],
        ]);
        app.session.tastings[0].selected_match = 'Cellar/Wine/Grand Cru.md';

        await app.approveTasting();

        expect(fetch).toHaveBeenCalledWith(
            `/api/v1/tastings/${EXTRACTION_ID}/0/approve`,
            { method: 'POST' },
        );
        expect(app.session.tastings[0].status).toBe('approved');
        expect(app.stats.approved).toBe(1);
        expect(app.currentIndex).toBe(1); // findNextPending moved on
        expect(app.approving).toBe(false);
    });

    it('stays put when the stats say all done', async () => {
        const app = await loadedApp(wineSession(), [
            ['/approve', jsonResponse({
                status: 'approved',
                file_created: 'f.md',
                stats: { approved: 1, skipped: 1, remaining: 0, all_done: true },
            })],
        ]);
        app.session.tastings[0].selected_match = 'Cellar/Wine/Grand Cru.md';
        app.session.tastings[1].status = 'skipped';

        await app.approveTasting();

        expect(app.currentIndex).toBe(0);
        expect(app.stats.all_done).toBe(true);
    });

    it('alerts with the API detail on failure and resets approving', async () => {
        const app = await loadedApp(wineSession(), [
            ['/approve', jsonResponse({ detail: 'No bottle selected for this tasting' }, { ok: false, status: 400 })],
        ]);
        app.session.tastings[0].selected_match = 'Cellar/Wine/Grand Cru.md';

        await app.approveTasting();

        expect(alert).toHaveBeenCalledWith('Failed to approve: No bottle selected for this tasting');
        expect(app.session.tastings[0].status).toBe('extracted');
        expect(app.approving).toBe(false);
    });
});

describe('skipTasting', () => {
    it('POSTs skip, marks the tasting, adopts stats and advances', async () => {
        const app = await loadedApp(wineSession(), [
            ['/skip', jsonResponse({
                status: 'skipped',
                stats: { approved: 0, skipped: 1, remaining: 1, all_done: false },
            })],
        ]);

        await app.skipTasting();

        expect(fetch).toHaveBeenCalledWith(
            `/api/v1/tastings/${EXTRACTION_ID}/0/skip`,
            { method: 'POST' },
        );
        expect(app.session.tastings[0].status).toBe('skipped');
        expect(app.stats.skipped).toBe(1);
        expect(app.currentIndex).toBe(1);
        expect(app.skipping).toBe(false);
    });

    it('alerts on failure and resets skipping', async () => {
        const app = await loadedApp(wineSession(), [
            ['/skip', jsonResponse({}, { ok: false, status: 500 })],
        ]);

        await app.skipTasting();

        expect(alert).toHaveBeenCalledWith('Failed to skip: Failed to skip');
        expect(app.skipping).toBe(false);
    });
});

describe('findNextPending', () => {
    it('lands on the first tasting that is neither approved nor skipped', async () => {
        const app = await loadedApp();
        app.session.tastings[0].status = 'approved';
        app.currentIndex = 0;
        app.findNextPending();
        expect(app.currentIndex).toBe(1);
    });

    it('leaves the index alone when everything is processed', async () => {
        const app = await loadedApp();
        app.session.tastings[0].status = 'approved';
        app.session.tastings[1].status = 'skipped';
        app.currentIndex = 1;
        app.findNextPending();
        expect(app.currentIndex).toBe(1);
    });
});

describe('rejectAll', () => {
    beforeEach(() => {
        vi.stubGlobal('location', { href: '' });
    });

    it('is gated behind confirm', async () => {
        confirm.mockReturnValueOnce(false);
        const app = await loadedApp();
        fetch.mockClear();

        await app.rejectAll();

        expect(fetch).not.toHaveBeenCalled();
        expect(location.href).toBe('');
    });

    it('POSTs reject-all and redirects to /upload', async () => {
        const app = await loadedApp(wineSession(), [
            ['/reject-all', jsonResponse({ status: 'rejected' })],
        ]);

        await app.rejectAll();

        expect(fetch).toHaveBeenCalledWith(
            `/api/v1/tastings/${EXTRACTION_ID}/reject-all`,
            { method: 'POST' },
        );
        expect(location.href).toBe('/upload');
    });

    it('alerts and stays on the page when rejection fails', async () => {
        const app = await loadedApp(wineSession(), [
            ['/reject-all', jsonResponse({}, { ok: false, status: 500 })],
        ]);

        await app.rejectAll();

        expect(alert).toHaveBeenCalledWith('Failed to reject: Failed to reject');
        expect(location.href).toBe('');
    });
});
