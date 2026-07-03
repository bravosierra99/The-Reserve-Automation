/**
 * Unit tests for the event results page component
 * (src/reserve_automation/web/static/js/events/event-results.js).
 *
 * Alpine itself is not loaded; the factory's return value is used directly.
 * Fixtures mirror GET /api/v1/events/{id} (web/routes/events.py): bottles are
 * [{bottle_id, bottle_name, bottle_path, blind_number}] and participants a
 * dict of {name, tastings: [{bottle_path, tasting_data}]}.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/events/event-results.js';

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

const EVENT_ID = 'ev-abc-123';

function freshApp() {
    return window.eventResultsApp(EVENT_ID);
}

// Whiskey scores: nose/3 + palate/3 + finish/3 + overall/1 = /10
function whiskeyData(nose, palate, finish, overall, extra = {}) {
    return {
        whiskey_nose: nose, whiskey_palate: palate,
        whiskey_finish: finish, whiskey_overall: overall,
        ...extra,
    };
}

function makeWhiskeyEvent(overrides = {}) {
    return {
        event_id: EVENT_ID,
        name: 'Whiskey Night',
        beverage_type: 'whiskey',
        is_blind: true,
        status: 'revealed',
        host_name: 'Ben',
        bottles: [
            { bottle_id: '1', bottle_name: 'Weller 12', bottle_path: '1', blind_number: 1 },
            { bottle_id: '2', bottle_name: 'Eagle Rare', bottle_path: '2', blind_number: 2 },
        ],
        participants: {
            'p-ben': {
                participant_id: 'p-ben',
                name: 'Ben',
                tastings: [
                    { bottle_path: '1', tasting_data: whiskeyData(3, 3, 2, 1) },   // 9
                    { bottle_path: '2', tasting_data: whiskeyData(1, 1, 1, 0) },   // 3
                ],
            },
            'p-sarah': {
                participant_id: 'p-sarah',
                name: 'Sarah',
                tastings: [
                    { bottle_path: '1', tasting_data: whiskeyData(2, 2, 2, 1) },   // 7
                ],
            },
        },
        ...overrides,
    };
}

const WINE_DATA = {
    wine_appearance: 2, wine_aroma: 5, wine_taste: 4,
    wine_aftertaste: 2, wine_overall: 1.5,
    appearance_notes: ['ruby', 'clear'],
    aroma_notes: ['cherry', 'oak'],
    taste_notes: ['plum'],
    aftertaste_notes: ['long'],
    overall_notes: 'lovely & <bold>',
};

function makeWineEvent() {
    return makeWhiskeyEvent({
        name: 'Wine Night',
        beverage_type: 'wine',
        participants: {
            'p-ben': {
                participant_id: 'p-ben',
                name: 'Ben',
                tastings: [{ bottle_path: '1', tasting_data: WINE_DATA }],
            },
        },
    });
}

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
// Initial state
// ---------------------------------------------------------------------------

describe('initial state', () => {
    it('captures the eventId passed by the template markup', () => {
        const app = freshApp();
        expect(app.eventId).toBe(EVENT_ID);
    });

    it('starts loading with no event, error, rankings or modal', () => {
        const app = freshApp();
        expect(app.loading).toBe(true);
        expect(app.event).toBeNull();
        expect(app.error).toBeNull();
        expect(app.overallRankings).toEqual([]);
        expect(app.participantRankings).toEqual([]);
        expect(app.showModal).toBe(false);
        expect(app.modalData).toEqual({
            participantName: '', bottleName: '', formattedNotes: '',
        });
    });
});

// ---------------------------------------------------------------------------
// init / loadEventAndCalculateResults
// ---------------------------------------------------------------------------

describe('loadEventAndCalculateResults', () => {
    it('fetches the exact event endpoint and computes rankings on success', async () => {
        const event = makeWhiskeyEvent();
        vi.stubGlobal('fetch', routeFetch([[`/api/v1/events/${EVENT_ID}`, jsonResponse(event)]]));

        const app = freshApp();
        await app.init();

        expect(fetch).toHaveBeenCalledWith(`/api/v1/events/${EVENT_ID}`);
        expect(app.event).toEqual(event);
        expect(app.loading).toBe(false);
        expect(app.error).toBeNull();
        expect(app.overallRankings.length).toBe(2);
        expect(app.participantRankings.length).toBe(2);
    });

    it('accepts closed events too', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/events/', jsonResponse(makeWhiskeyEvent({ status: 'closed' }))],
        ]));
        const app = freshApp();
        await app.loadEventAndCalculateResults();
        expect(app.error).toBeNull();
        expect(app.overallRankings.length).toBe(2);
    });

    it('refuses results for still-open (blind) events — names stay hidden pre-reveal', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/events/', jsonResponse(makeWhiskeyEvent({ status: 'open' }))],
        ]));
        const app = freshApp();
        await app.loadEventAndCalculateResults();
        expect(app.error).toBe('Results are only available after the event has been revealed');
        expect(app.loading).toBe(false);
        expect(app.overallRankings).toEqual([]);
    });

    it('shows a specific message on 404', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/events/', jsonResponse({}, { ok: false, status: 404 })],
        ]));
        const app = freshApp();
        await app.loadEventAndCalculateResults();
        expect(app.error).toBe('Event not found');
        expect(app.loading).toBe(false);
        expect(app.event).toBeNull();
    });

    it('shows a generic error on non-404 HTTP failure', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/events/', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        await app.loadEventAndCalculateResults();
        expect(app.error).toBe('Failed to load event results');
        expect(app.loading).toBe(false);
    });

    it('shows a generic error when fetch rejects', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down'); }));
        const app = freshApp();
        await app.loadEventAndCalculateResults();
        expect(app.error).toBe('Failed to load event results');
        expect(app.loading).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// calculateTastingScore
// ---------------------------------------------------------------------------

describe('calculateTastingScore', () => {
    it('returns 0 for missing tasting data', () => {
        const app = freshApp();
        expect(app.calculateTastingScore(null, 'wine')).toBe(0);
        expect(app.calculateTastingScore(undefined, 'whiskey')).toBe(0);
    });

    it('sums the four whiskey components (out of 10)', () => {
        const app = freshApp();
        expect(app.calculateTastingScore(whiskeyData(3, 3, 3, 1), 'whiskey')).toBe(10);
        expect(app.calculateTastingScore(whiskeyData(1.5, 2, 0.5, 0), 'whiskey')).toBe(4);
    });

    it('sums the five wine AWS components (out of 20)', () => {
        const app = freshApp();
        expect(app.calculateTastingScore(WINE_DATA, 'wine')).toBe(14.5);
    });

    it('treats missing components as 0', () => {
        const app = freshApp();
        expect(app.calculateTastingScore({ whiskey_nose: 2 }, 'whiskey')).toBe(2);
        expect(app.calculateTastingScore({ wine_taste: 3 }, 'wine')).toBe(3);
        expect(app.calculateTastingScore({}, 'wine')).toBe(0);
    });

    it('unwraps double-nested tasting_data (bug fix migration)', () => {
        const app = freshApp();
        const nested = { tasting_data: whiskeyData(3, 3, 2, 1) };
        expect(app.calculateTastingScore(nested, 'whiskey')).toBe(9);
    });

    it('scores non-wine beverage types with the whiskey formula', () => {
        const app = freshApp();
        expect(app.calculateTastingScore(whiskeyData(1, 1, 1, 1), 'anything-else')).toBe(4);
    });
});

// ---------------------------------------------------------------------------
// calculateOverallRankings
// ---------------------------------------------------------------------------

describe('calculateOverallRankings', () => {
    it('averages scores per bottle and sorts highest first', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        app.calculateOverallRankings();

        expect(app.overallRankings).toEqual([
            {
                bottle_path: '1', bottle_name: 'Weller 12',
                avg_score: 8, tasting_count: 2,          // (9 + 7) / 2
            },
            {
                bottle_path: '2', bottle_name: 'Eagle Rare',
                avg_score: 3, tasting_count: 1,
            },
        ]);
    });

    it('falls back to the bottle path when the bottle is not in the event list', () => {
        const app = freshApp();
        const event = makeWhiskeyEvent();
        event.participants['p-ben'].tastings.push(
            { bottle_path: 'ghost-99', tasting_data: whiskeyData(1, 1, 1, 1) },
        );
        app.event = event;
        app.calculateOverallRankings();

        const ghost = app.overallRankings.find(r => r.bottle_path === 'ghost-99');
        expect(ghost.bottle_name).toBe('ghost-99');
        expect(ghost.avg_score).toBe(4);
    });

    it('produces no rankings when nobody has tasted anything', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent({
            participants: { 'p-ben': { participant_id: 'p-ben', name: 'Ben', tastings: [] } },
        });
        app.calculateOverallRankings();
        expect(app.overallRankings).toEqual([]);
    });
});

// ---------------------------------------------------------------------------
// calculateParticipantRankings
// ---------------------------------------------------------------------------

describe('calculateParticipantRankings', () => {
    it('builds a per-participant list sorted by score, highest first', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        app.calculateParticipantRankings();

        expect(app.participantRankings.length).toBe(2);
        const ben = app.participantRankings.find(p => p.participant_id === 'p-ben');
        expect(ben.name).toBe('Ben');
        expect(ben.rankings).toEqual([
            { bottle_path: '1', bottle_name: 'Weller 12', score: 9 },
            { bottle_path: '2', bottle_name: 'Eagle Rare', score: 3 },
        ]);

        const sarah = app.participantRankings.find(p => p.participant_id === 'p-sarah');
        expect(sarah.rankings).toEqual([
            { bottle_path: '1', bottle_name: 'Weller 12', score: 7 },
        ]);
    });

    it('falls back to the bottle path for unknown bottles', () => {
        const app = freshApp();
        const event = makeWhiskeyEvent();
        event.participants['p-sarah'].tastings = [
            { bottle_path: 'gone', tasting_data: whiskeyData(1, 0, 0, 0) },
        ];
        app.event = event;
        app.calculateParticipantRankings();
        const sarah = app.participantRankings.find(p => p.participant_id === 'p-sarah');
        expect(sarah.rankings[0].bottle_name).toBe('gone');
    });
});

// ---------------------------------------------------------------------------
// Lookup helpers
// ---------------------------------------------------------------------------

describe('getTastingForBottle', () => {
    it('finds the tasting for a participant/bottle pair', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        const tasting = app.getTastingForBottle('p-sarah', '1');
        expect(tasting.bottle_path).toBe('1');
    });

    it('returns null for an unknown participant', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        expect(app.getTastingForBottle('nobody', '1')).toBeNull();
    });

    it('returns undefined when the participant has not tasted the bottle', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        expect(app.getTastingForBottle('p-sarah', '2')).toBeUndefined();
    });
});

describe('getBottleName', () => {
    it('resolves the display name from the event bottle list', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        expect(app.getBottleName('2')).toBe('Eagle Rare');
    });

    it('falls back to the raw path when unknown', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        expect(app.getBottleName('missing')).toBe('missing');
    });
});

// ---------------------------------------------------------------------------
// formatTastingNotes / formatNotesAsHashtags / escapeHtml
// ---------------------------------------------------------------------------

describe('formatTastingNotes', () => {
    it('returns a placeholder when there is no tasting data', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        expect(app.formatTastingNotes(null)).toBe('<p class="text-gray-500">No tasting data</p>');
        expect(app.formatTastingNotes({})).toBe('<p class="text-gray-500">No tasting data</p>');
    });

    it('renders all five wine sections with scores, notes and the AWS total', () => {
        const app = freshApp();
        app.event = makeWineEvent();
        const html = app.formatTastingNotes({ tasting_data: WINE_DATA });

        expect(html).toContain('Appearance');
        expect(html).toContain('2.0/3');
        expect(html).toContain('ruby, clear');           // appearance notes joined, not hashtagged
        expect(html).toContain('Aroma');
        expect(html).toContain('5.0/6');
        expect(html).toContain('#cherry #oak');          // hashtag formatting
        expect(html).toContain('Taste');
        expect(html).toContain('4.0/6');
        expect(html).toContain('#plum');
        expect(html).toContain('Aftertaste');
        expect(html).toContain('#long');
        expect(html).toContain('Overall Impression');
        expect(html).toContain('1.5/2');
        expect(html).toContain('AWS Score: 14.5/20');
    });

    it('escapes HTML in wine overall notes', () => {
        const app = freshApp();
        app.event = makeWineEvent();
        const html = app.formatTastingNotes({ tasting_data: WINE_DATA });
        expect(html).toContain('lovely &amp; &lt;bold&gt;');
        expect(html).not.toContain('<bold>');
    });

    it('renders whiskey sections with per-component maxima and the /10 total', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        const data = whiskeyData(2.5, 3, 2, 1, {
            nose_notes: ['caramel'],
            palate_notes: ['spice', 'oak'],
            finish_notes: ['long'],
            notes: 'good <stuff>',
        });
        const html = app.formatTastingNotes({ tasting_data: data });

        expect(html).toContain('Nose');
        expect(html).toContain('2.5/3');
        expect(html).toContain('#caramel');
        expect(html).toContain('Palate');
        expect(html).toContain('#spice #oak');
        expect(html).toContain('Finish');
        expect(html).toContain('#long');
        expect(html).toContain('Overall');
        expect(html).toContain('1.0/1');
        expect(html).toContain('good &lt;stuff&gt;');    // falls back to `notes` and escapes
        expect(html).toContain('Total: 8.5/10');
    });

    it('prefers overall_notes over notes', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        const data = whiskeyData(1, 1, 1, 1, { overall_notes: 'primary', notes: 'fallback' });
        const html = app.formatTastingNotes({ tasting_data: data });
        expect(html).toContain('primary');
        expect(html).not.toContain('fallback');
    });

    it('unwraps double-nested tasting_data', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        const html = app.formatTastingNotes({
            tasting_data: { tasting_data: whiskeyData(3, 3, 3, 1) },
        });
        expect(html).toContain('Total: 10.0/10');
    });

    it('omits note lines when note arrays are empty', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        const html = app.formatTastingNotes({
            tasting_data: whiskeyData(1, 1, 1, 0, { nose_notes: [] }),
        });
        expect(html).not.toContain('#');
    });
});

describe('formatNotesAsHashtags', () => {
    it('prefixes each note with # and joins with spaces', () => {
        const app = freshApp();
        expect(app.formatNotesAsHashtags(['a', 'b c'])).toBe('#a #b c');
    });

    it('returns empty string for null, non-arrays and empty arrays', () => {
        const app = freshApp();
        expect(app.formatNotesAsHashtags(null)).toBe('');
        expect(app.formatNotesAsHashtags('nope')).toBe('');
        expect(app.formatNotesAsHashtags([])).toBe('');
    });
});

describe('escapeHtml', () => {
    it('escapes markup-significant characters', () => {
        const app = freshApp();
        expect(app.escapeHtml('<script>&"')).toBe('&lt;script&gt;&amp;"');
    });
});

// ---------------------------------------------------------------------------
// openTastingModal
// ---------------------------------------------------------------------------

describe('openTastingModal', () => {
    it('populates modalData and opens the modal', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        app.openTastingModal('p-sarah', '1');

        expect(app.showModal).toBe(true);
        expect(app.modalData.participantName).toBe('Sarah');
        expect(app.modalData.bottleName).toBe('Weller 12');
        expect(app.modalData.formattedNotes).toContain('Total: 7.0/10');
    });

    it('does nothing for an unknown participant', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        app.openTastingModal('nobody', '1');
        expect(app.showModal).toBe(false);
        expect(app.modalData.participantName).toBe('');
    });

    it('does nothing when the participant has no tasting for the bottle', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        app.openTastingModal('p-sarah', '2');
        expect(app.showModal).toBe(false);
    });
});
