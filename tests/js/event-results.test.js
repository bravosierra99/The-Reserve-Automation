/**
 * Unit tests for the event results page component
 * (src/reserve_automation/web/static/js/events/event-results.js).
 *
 * Alpine itself is not loaded; the factory's return value is used directly.
 *
 * The event fixtures are NOT hand-written: they are contract fixtures —
 * real GET /api/v1/events/{id} responses captured and snapshot-verified by
 * tests/contract/test_events_contract.py (see tests/contract/contract.py).
 * July 2026 lesson: this suite previously passed 38 tests against invented
 * fixtures whose field names matched the code's wrong assumptions, while the
 * page rendered undefined in prod. Per-test variants mutate a fresh clone of
 * the contract fixture so the base shape always comes from the real API.
 *
 * Contract flow data (test_events_contract.py): bottles 1=Willett, 2=Weller,
 * 3=Blantons; Alice scored bottle1=9, bottle2=7; Bob scored bottle1=8,
 * bottle3=4 → overall averages 8.5 / 7.0 / 4.0.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
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

// Normalized IDs assigned by the contract snapshot (first-encounter order).
const EVENT_ID = '00000000-0000-4000-8000-000000000001';
const ALICE = '00000000-0000-4000-8000-000000000002';
const BOB = '00000000-0000-4000-8000-000000000003';

const WILLETT = 'Willett - Family Estate Single Barrel';
const WELLER = 'Buffalo Trace - Weller Special Reserve';
const BLANTONS = 'Blantons - Original Single Barrel';

function makeWhiskeyEvent(overrides = {}) {
    return { ...loadContract('event_detail'), ...overrides };
}

function makeWineEvent(overrides = {}) {
    return { ...loadContract('event_detail_wine'), ...overrides };
}

// The wine event's single tasting (Alice on Caymus): AWS 14.5/20 with
// HTML-hostile overall notes — straight from the contract fixture.
function wineTastingData() {
    const event = makeWineEvent();
    const [participant] = Object.values(event.participants);
    return participant.tastings[0].tasting_data;
}

function freshApp() {
    return window.eventResultsApp(EVENT_ID);
}

// Synthetic whiskey scores for variant tests (nose/3+palate/3+finish/3+overall/1)
function whiskeyData(nose, palate, finish, overall, extra = {}) {
    return {
        whiskey_nose: nose, whiskey_palate: palate,
        whiskey_finish: finish, whiskey_overall: overall,
        ...extra,
    };
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
    it('fetches the exact event endpoint and computes rankings from the real response', async () => {
        const event = makeWhiskeyEvent();   // contract status: closed
        vi.stubGlobal('fetch', routeFetch([[`/api/v1/events/${EVENT_ID}`, jsonResponse(event)]]));

        const app = freshApp();
        await app.init();

        expect(fetch).toHaveBeenCalledWith(`/api/v1/events/${EVENT_ID}`);
        expect(app.event).toEqual(event);
        expect(app.loading).toBe(false);
        expect(app.error).toBeNull();
        expect(app.overallRankings.length).toBe(3);
        expect(app.participantRankings.length).toBe(2);
    });

    it('accepts revealed (not yet closed) events too', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/events/', jsonResponse(makeWhiskeyEvent({ status: 'revealed' }))],
        ]));
        const app = freshApp();
        await app.loadEventAndCalculateResults();
        expect(app.error).toBeNull();
        expect(app.overallRankings.length).toBe(3);
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

    it('sums the five wine AWS components of the contract tasting (out of 20)', () => {
        const app = freshApp();
        expect(app.calculateTastingScore(wineTastingData(), 'wine')).toBe(14.5);
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
    it('averages scores per bottle and sorts highest first (contract data)', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        app.calculateOverallRankings();

        expect(app.overallRankings).toEqual([
            {
                bottle_path: '1', bottle_name: WILLETT,
                avg_score: 8.5, tasting_count: 2,        // Alice 9, Bob 8
            },
            {
                bottle_path: '2', bottle_name: WELLER,
                avg_score: 7, tasting_count: 1,          // Alice
            },
            {
                bottle_path: '3', bottle_name: BLANTONS,
                avg_score: 4, tasting_count: 1,          // Bob
            },
        ]);
    });

    it('falls back to the bottle key when the bottle is not in the event list', () => {
        const app = freshApp();
        const event = makeWhiskeyEvent();
        event.participants[ALICE].tastings.push(
            { bottle_id: 'ghost-99', tasting_data: whiskeyData(1, 1, 1, 1) },
        );
        app.event = event;
        app.calculateOverallRankings();

        const ghost = app.overallRankings.find(r => r.bottle_path === 'ghost-99');
        expect(ghost.bottle_name).toBe('ghost-99');
        expect(ghost.avg_score).toBe(4);
    });

    it('produces no rankings when nobody has tasted anything', () => {
        const app = freshApp();
        const event = makeWhiskeyEvent();
        for (const p of Object.values(event.participants)) p.tastings = [];
        app.event = event;
        app.calculateOverallRankings();
        expect(app.overallRankings).toEqual([]);
    });

    it('handles integer bottle_id tastings against string bottle ids (regression)', () => {
        const app = freshApp();
        const event = makeWhiskeyEvent();
        event.participants[BOB].tastings = [
            { bottle_id: 1, tasting_data: whiskeyData(2, 2, 2, 1) },
        ];
        app.event = event;
        app.calculateOverallRankings();
        const willett = app.overallRankings.find(r => r.bottle_path === '1');
        expect(willett.bottle_name).toBe(WILLETT);
        expect(willett.tasting_count).toBe(2);
    });
});

// ---------------------------------------------------------------------------
// Legacy event shape (pre-SQLite tastings: bottle_path + participant name).
// These fixtures are intentionally hand-written — the current API can no
// longer produce this shape, but old events stored it.
// ---------------------------------------------------------------------------

describe('legacy event shape', () => {
    function makeLegacyEvent() {
        const event = makeWhiskeyEvent();
        event.participants = {
            'p-old': {
                participant_id: 'p-old',
                name: 'Old Timer',
                tastings: [{ bottle_path: '2', tasting_data: whiskeyData(3, 3, 3, 1) }],
            },
        };
        return event;
    }

    it('still ranks tastings keyed by bottle_path and reads participant name', () => {
        const app = freshApp();
        app.event = makeLegacyEvent();
        app.calculateOverallRankings();
        app.calculateParticipantRankings();

        expect(app.overallRankings).toEqual([
            { bottle_path: '2', bottle_name: WELLER, avg_score: 10, tasting_count: 1 },
        ]);
        expect(app.participantRankings[0].name).toBe('Old Timer');
    });

    it('opens the modal for legacy tastings', () => {
        const app = freshApp();
        app.event = makeLegacyEvent();
        app.openTastingModal('p-old', '2');
        expect(app.showModal).toBe(true);
        expect(app.modalData.participantName).toBe('Old Timer');
        expect(app.modalData.bottleName).toBe(WELLER);
    });
});

// ---------------------------------------------------------------------------
// calculateParticipantRankings
// ---------------------------------------------------------------------------

describe('calculateParticipantRankings', () => {
    it('builds a per-participant list sorted by score, highest first (contract data)', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        app.calculateParticipantRankings();

        expect(app.participantRankings.length).toBe(2);
        const alice = app.participantRankings.find(p => p.participant_id === ALICE);
        expect(alice.name).toBe('Alice');
        expect(alice.rankings).toEqual([
            { bottle_path: '1', bottle_name: WILLETT, score: 9 },
            { bottle_path: '2', bottle_name: WELLER, score: 7 },
        ]);

        const bob = app.participantRankings.find(p => p.participant_id === BOB);
        expect(bob.name).toBe('Bob');
        expect(bob.rankings).toEqual([
            { bottle_path: '1', bottle_name: WILLETT, score: 8 },
            { bottle_path: '3', bottle_name: BLANTONS, score: 4 },
        ]);
    });

    it('falls back to the bottle key for unknown bottles', () => {
        const app = freshApp();
        const event = makeWhiskeyEvent();
        event.participants[BOB].tastings = [
            { bottle_id: 'gone', tasting_data: whiskeyData(1, 0, 0, 0) },
        ];
        app.event = event;
        app.calculateParticipantRankings();
        const bob = app.participantRankings.find(p => p.participant_id === BOB);
        expect(bob.rankings[0].bottle_name).toBe('gone');
    });
});

// ---------------------------------------------------------------------------
// Lookup helpers
// ---------------------------------------------------------------------------

describe('getTastingForBottle', () => {
    it('finds the tasting for a participant/bottle pair', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        const tasting = app.getTastingForBottle(ALICE, '2');
        expect(app.tastingBottleKey(tasting)).toBe('2');
    });

    it('returns null for an unknown participant', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        expect(app.getTastingForBottle('nobody', '1')).toBeNull();
    });

    it('returns undefined when the participant has not tasted the bottle', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        expect(app.getTastingForBottle(ALICE, '3')).toBeUndefined();
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

    it('renders all five wine sections with scores, notes and the AWS total (contract data)', () => {
        const app = freshApp();
        app.event = makeWineEvent();
        const html = app.formatTastingNotes({ tasting_data: wineTastingData() });

        expect(html).toContain('Appearance');
        expect(html).toContain('2.0/3');
        expect(html).toContain('ruby, clear');           // appearance notes joined, not hashtagged
        expect(html).toContain('Aroma');
        expect(html).toContain('5.0/6');
        expect(html).toContain('#cherry #oak');          // wizard stores aroma notes as nose_notes
        expect(html).toContain('Taste');
        expect(html).toContain('4.0/6');
        expect(html).toContain('#plum');
        expect(html).toContain('Aftertaste');
        expect(html).toContain('#long');
        expect(html).toContain('Overall Impression');
        expect(html).toContain('1.5/2');
        expect(html).toContain('AWS Score: 14.5/20');
    });

    it('escapes HTML in wine overall notes (contract data)', () => {
        const app = freshApp();
        app.event = makeWineEvent();
        const html = app.formatTastingNotes({ tasting_data: wineTastingData() });
        expect(html).toContain('lovely &amp; &lt;bold&gt;');
        expect(html).not.toContain('<bold>');
    });

    it('renders a real saved whiskey tasting (contract data)', () => {
        const app = freshApp();
        const event = makeWhiskeyEvent();
        app.event = event;
        const html = app.formatTastingNotes(event.participants[ALICE].tastings[0]);

        expect(html).toContain('Nose');
        expect(html).toContain('3.0/3');
        expect(html).toContain('#caramel #oak');
        expect(html).toContain('Palate');
        expect(html).toContain('#cherry #baking spice');
        expect(html).toContain('Finish');
        expect(html).toContain('#long #warm');
        expect(html).toContain('Outstanding pour');
        expect(html).toContain('Total: 9.0/10');
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

        expect(html).toContain('2.5/3');
        expect(html).toContain('#spice #oak');
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
    it('populates modalData and opens the modal (contract data)', () => {
        const app = freshApp();
        app.event = makeWhiskeyEvent();
        app.openTastingModal(ALICE, '2');

        expect(app.showModal).toBe(true);
        expect(app.modalData.participantName).toBe('Alice');
        expect(app.modalData.bottleName).toBe(WELLER);
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
        app.openTastingModal(ALICE, '3');
        expect(app.showModal).toBe(false);
    });
});
