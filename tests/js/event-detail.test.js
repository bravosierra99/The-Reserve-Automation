/**
 * Unit tests for the event detail / participation page component
 * (src/reserve_automation/web/static/js/events/event-detail.js).
 *
 * Alpine itself is not loaded; the factory's return value is used directly.
 * init() is exercised with hand-supplied $watch/$refs stubs (Alpine magics)
 * and a stubbed QRCode global (the page loads qrcodejs from a CDN).
 *
 * API fixtures are NOT hand-written: they are contract fixtures — real
 * responses captured and snapshot-verified by
 * tests/contract/test_events_contract.py (see tests/contract/contract.py):
 *   event_detail_blind_open   GET  /api/v1/events/{id} (open blind event:
 *                             3 redacted bottles, Alice + Bob joined)
 *   me                        GET  /api/v1/me (display_name prefill)
 *   event_join_response       POST /api/v1/events/{id}/join
 *   event_bottle_search       GET  /api/v1/bottles/search (MatchCandidate:
 *                             the DB id lives in bottle_path; no bottle_id)
 *   event_add_bottle_response       POST .../bottles on a blind event
 *                             (identity-redacted; NO bottle_path key)
 *   event_add_bottle_response_open  same POST on a non-blind event
 *                             (full EventBottle echo)
 * Per-test variants are explicit mutations of a fresh clone. Hand-written
 * shapes remain only for error responses and the participant_sessions cookie
 * (browser state, not an API body).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
import '../../src/reserve_automation/web/static/js/events/event-detail.js';

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

// The contract event's normalized id (first UUID the snapshot encountered).
const EVENT_ID = '00000000-0000-4000-8000-000000000001';

function makeEvent(overrides = {}) {
    return { ...loadContract('event_detail_blind_open'), ...overrides };
}

// UUID placeholders are per-fixture (see contract.py): the join response's
// event_id normalized differently there, so pin it to this event explicitly.
function makeJoinResponse(overrides = {}) {
    return { ...loadContract('event_join_response'), event_id: EVENT_ID, ...overrides };
}

function freshApp() {
    const app = window.eventDetailApp(EVENT_ID);
    // Alpine magics used by init(); supplied by Alpine on the real page.
    app.$watch = vi.fn();
    app.$refs = { qrcode: { innerHTML: 'stale' } };
    return app;
}

function setSessionsCookie(sessions) {
    document.cookie = 'participant_sessions=' + encodeURIComponent(JSON.stringify(sessions));
}

function clearSessionsCookie() {
    document.cookie = 'participant_sessions=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
}

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([]));
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('confirm', vi.fn(() => true));
    const QRCodeMock = vi.fn();
    QRCodeMock.CorrectLevel = { H: 'H-level' };
    vi.stubGlobal('QRCode', QRCodeMock);
});

afterEach(() => {
    clearSessionsCookie();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

describe('initial state', () => {
    it('captures the eventId passed by the template markup', () => {
        expect(window.eventDetailApp(EVENT_ID).eventId).toBe(EVENT_ID);
    });

    it('starts loading, not joined, with empty add-bottle state', () => {
        const app = window.eventDetailApp(EVENT_ID);
        expect(app.loading).toBe(true);
        expect(app.event).toBeNull();
        expect(app.participantInfo).toBeNull();
        expect(app.participantName).toBe('');
        expect(app.joining).toBe(false);
        expect(app.joined).toBe(false);
        expect(app.showQRModal).toBe(false);
        expect(app.eventUrl).toBe('');
        expect(app.addBottleQuery).toBe('');
        expect(app.addBottleResults).toEqual([]);
        expect(app.addBottleMessage).toBe('');
        expect(app.addBottleError).toBe(false);
        expect(app.addingBottle).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// init
// ---------------------------------------------------------------------------

describe('init', () => {
    it('builds the share URL, prefills the name from /api/v1/me and loads the event', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/me', jsonResponse(loadContract('me'))],
            ['/api/v1/events/', jsonResponse(makeEvent())],
        ]));

        const app = freshApp();
        await app.init();

        expect(app.eventUrl).toBe(window.location.origin + '/events/' + EVENT_ID);
        expect(app.participantName).toBe('Admin');   // me.display_name
        expect(app.event.name).toBe('Contract Whiskey Night');
        expect(app.loading).toBe(false);
        expect(app.$watch).toHaveBeenCalledWith('showQRModal', expect.any(Function));
    });

    it('leaves the name empty when /api/v1/me has no display_name or fails', async () => {
        const me = loadContract('me');
        me.authenticated = false;
        me.display_name = null;
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/me', jsonResponse(me)],
            ['/api/v1/events/', jsonResponse(makeEvent())],
        ]));
        const app = freshApp();
        await app.init();
        expect(app.participantName).toBe('');
    });

    it('survives a network error on /api/v1/me', async () => {
        vi.stubGlobal('fetch', vi.fn(async (url) => {
            if (String(url).includes('/api/v1/me')) throw new Error('offline');
            return jsonResponse(makeEvent());
        }));
        const app = freshApp();
        await app.init();
        expect(app.participantName).toBe('');
        expect(app.event).not.toBeNull();
    });

    it('restores a joined session from the participant_sessions cookie', async () => {
        setSessionsCookie({
            [EVENT_ID]: { participant_id: 'p-cookie', participant_name: 'Cookie Ben' },
        });
        vi.stubGlobal('fetch', routeFetch([['/api/v1/events/', jsonResponse(makeEvent())]]));

        const app = freshApp();
        await app.init();

        expect(app.joined).toBe(true);
        expect(app.participantInfo).toEqual({
            event_id: EVENT_ID,
            participant_id: 'p-cookie',
            participant_name: 'Cookie Ben',
        });
    });

    it('polls the event every 5 seconds', async () => {
        vi.useFakeTimers();
        vi.stubGlobal('fetch', routeFetch([['/api/v1/events/', jsonResponse(makeEvent())]]));

        const app = freshApp();
        await app.init();

        const callsAfterInit = fetch.mock.calls.length;
        vi.advanceTimersByTime(5000);
        expect(fetch.mock.calls.length).toBe(callsAfterInit + 1);
        expect(String(fetch.mock.calls.at(-1)[0])).toBe(`/api/v1/events/${EVENT_ID}`);
        vi.advanceTimersByTime(5000);
        expect(fetch.mock.calls.length).toBe(callsAfterInit + 2);
    });
});

// ---------------------------------------------------------------------------
// QR modal watcher (registered in init, driven here directly)
// ---------------------------------------------------------------------------

describe('showQRModal watcher', () => {
    async function initApp() {
        vi.stubGlobal('fetch', routeFetch([['/api/v1/events/', jsonResponse(makeEvent())]]));
        const app = freshApp();
        await app.init();
        const watcher = app.$watch.mock.calls.find(c => c[0] === 'showQRModal')[1];
        return { app, watcher };
    }

    it('clears the old QR code and renders a 256px code on desktop', async () => {
        const { app, watcher } = await initApp();
        vi.useFakeTimers();
        window.innerWidth = 1024;

        watcher(true);
        expect(app.$refs.qrcode.innerHTML).toBe('');
        expect(QRCode).not.toHaveBeenCalled();

        vi.advanceTimersByTime(100);
        expect(QRCode).toHaveBeenCalledWith(app.$refs.qrcode, {
            text: window.location.origin + '/events/' + EVENT_ID,
            width: 256,
            height: 256,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: 'H-level',
        });
    });

    it('renders a larger 280px code on mobile widths', async () => {
        const { watcher } = await initApp();
        vi.useFakeTimers();
        window.innerWidth = 375;

        watcher(true);
        vi.advanceTimersByTime(100);
        expect(QRCode.mock.calls[0][1].width).toBe(280);
        expect(QRCode.mock.calls[0][1].height).toBe(280);
    });

    it('does nothing when the modal closes', async () => {
        const { app, watcher } = await initApp();
        vi.useFakeTimers();
        app.$refs.qrcode.innerHTML = 'existing';
        watcher(false);
        vi.advanceTimersByTime(100);
        expect(app.$refs.qrcode.innerHTML).toBe('existing');
        expect(QRCode).not.toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------------------
// loadEvent
// ---------------------------------------------------------------------------

describe('loadEvent', () => {
    it('stores the payload from the exact event endpoint', async () => {
        const event = makeEvent();
        vi.stubGlobal('fetch', routeFetch([[`/api/v1/events/${EVENT_ID}`, jsonResponse(event)]]));
        const app = freshApp();
        await app.loadEvent();
        expect(fetch).toHaveBeenCalledWith(`/api/v1/events/${EVENT_ID}`);
        expect(app.event).toEqual(event);
        expect(app.loading).toBe(false);
        expect(app.error).toBeNull();
        // The contract shape the page depends on: redacted bottles pre-reveal,
        // participants keyed by id carrying participant_name (NOT name).
        expect(app.event.bottles[0]).toEqual({
            bottle_id: '1', bottle_name: 'Bottle #1', bottle_path: '1', blind_number: 1,
        });
        const participants = Object.values(app.event.participants);
        expect(participants.map(p => p.participant_name)).toEqual(['Alice', 'Bob']);
    });

    it('reports a 404 as Event not found', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/events/', jsonResponse({}, { ok: false, status: 404 })],
        ]));
        const app = freshApp();
        await app.loadEvent();
        expect(app.error).toBe('Event not found');
        expect(app.loading).toBe(false);
    });

    it('reports other HTTP failures generically', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/events/', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        await app.loadEvent();
        expect(app.error).toBe('Failed to load event');
    });

    it('reports network errors generically', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp();
        await app.loadEvent();
        expect(app.error).toBe('Failed to load event');
        expect(app.loading).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// checkParticipantSession — participant_sessions cookie parsing
// ---------------------------------------------------------------------------

describe('checkParticipantSession', () => {
    it('joins when the cookie holds a session for this event', async () => {
        setSessionsCookie({
            'other-event': { participant_id: 'x', participant_name: 'X' },
            [EVENT_ID]: { participant_id: 'p-77', participant_name: 'Sarah' },
        });
        const app = freshApp();
        await app.checkParticipantSession();
        expect(app.joined).toBe(true);
        expect(app.participantInfo).toEqual({
            event_id: EVENT_ID,
            participant_id: 'p-77',
            participant_name: 'Sarah',
        });
    });

    it('stays unjoined when the cookie only covers other events', async () => {
        setSessionsCookie({ 'other-event': { participant_id: 'x', participant_name: 'X' } });
        const app = freshApp();
        await app.checkParticipantSession();
        expect(app.joined).toBe(false);
        expect(app.participantInfo).toBeNull();
    });

    it('stays unjoined with no cookie at all', async () => {
        const app = freshApp();
        await app.checkParticipantSession();
        expect(app.joined).toBe(false);
    });

    it('tolerates a malformed cookie', async () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        document.cookie = 'participant_sessions=%7Bnot-json';
        const app = freshApp();
        await app.checkParticipantSession();
        expect(app.joined).toBe(false);
        expect(consoleError).toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------------------
// joinEvent
// ---------------------------------------------------------------------------

describe('joinEvent', () => {
    it('does nothing for a blank name', async () => {
        const app = freshApp();
        app.participantName = '   ';
        await app.joinEvent();
        expect(fetch).not.toHaveBeenCalled();
        expect(app.joined).toBe(false);
    });

    it('POSTs the exact join payload, stores participantInfo and reloads the event', async () => {
        const joinResponse = makeJoinResponse();   // Alice's real join response
        vi.stubGlobal('fetch', routeFetch([
            [`/api/v1/events/${EVENT_ID}/join`, jsonResponse(joinResponse)],
            ['/api/v1/events/', jsonResponse(makeEvent())],
        ]));

        const app = freshApp();
        app.participantName = 'Alice';
        await app.joinEvent();

        const [url, opts] = fetch.mock.calls[0];
        expect(url).toBe(`/api/v1/events/${EVENT_ID}/join`);
        expect(opts.method).toBe('POST');
        expect(opts.headers).toEqual({ 'Content-Type': 'application/json' });
        expect(JSON.parse(opts.body)).toEqual({ participant_name: 'Alice' });

        expect(app.participantInfo).toEqual(joinResponse);
        expect(app.participantInfo.participant_name).toBe('Alice');
        expect(app.joined).toBe(true);
        expect(app.joining).toBe(false);
        expect(app.event).not.toBeNull();   // reloaded after joining
    });

    it('alerts and stays unjoined on failure', async () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/join', jsonResponse({}, { ok: false, status: 400 })],
        ]));
        const app = freshApp();
        app.participantName = 'Alice';
        await app.joinEvent();
        expect(alert).toHaveBeenCalledWith('Failed to join event: Failed to join event');
        expect(app.joined).toBe(false);
        expect(app.joining).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// searchBottlesToAdd — contract fixture event_bottle_search holds the real
// MatchCandidate shape: the DB id is in bottle_path, there is NO bottle_id.
// ---------------------------------------------------------------------------

describe('searchBottlesToAdd', () => {
    it('clears results for queries under 2 characters without fetching', async () => {
        const app = freshApp();
        app.addBottleResults = loadContract('event_bottle_search').results;
        app.addBottleQuery = 'w';
        await app.searchBottlesToAdd();
        expect(app.addBottleResults).toEqual([]);
        expect(fetch).not.toHaveBeenCalled();
    });

    it('queries the search endpoint with encoded query and beverage type', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/search', jsonResponse(loadContract('event_bottle_search'))],
        ]));
        const app = freshApp();
        app.event = makeEvent();
        app.addBottleQuery = 'a b';
        await app.searchBottlesToAdd();
        expect(String(fetch.mock.calls[0][0]))
            .toBe('/api/v1/bottles/search?q=a%20b&beverage_type=whiskey');
    });

    it('hides bottles already in the event from the results (contract data)', async () => {
        // The contract search hit (Blantons, bottle_path '3') is already the
        // event's bottle 3 — the page must not offer to add it twice.
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/search', jsonResponse(loadContract('event_bottle_search'))],
        ]));
        const app = freshApp();
        app.event = makeEvent();
        app.addBottleQuery = 'blanton';
        await app.searchBottlesToAdd();
        expect(app.addBottleResults).toEqual([]);
    });

    it('offers the full MatchCandidate when the bottle is not yet in the event', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/search', jsonResponse(loadContract('event_bottle_search'))],
        ]));
        const app = freshApp();
        const event = makeEvent();
        event.bottles = event.bottles.filter(b => b.bottle_id !== '3');
        app.event = event;
        app.addBottleQuery = 'blanton';
        await app.searchBottlesToAdd();
        expect(app.addBottleResults).toEqual([{
            bottle_path: '3',
            bottle_name: 'Blantons - Original Single Barrel',
            producer: 'Blantons',
            vintage: null,
            confidence: 0.35,
            thumbnail_url: null,
            beverage_type: 'whiskey',
        }]);
    });

    it('dedupes legacy event bottles that carry only bottle_path (no bottle_id)', async () => {
        // Regression: the dedupe set used to be built from b.bottle_id only, so a
        // legacy event bottle without bottle_id collected `undefined` and its
        // search hit (keyed by bottle_path) reappeared in the results.
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/search', jsonResponse(loadContract('event_bottle_search'))],
        ]));
        const app = freshApp();
        const event = makeEvent();
        // Legacy row: strip bottle_id from the Blantons event bottle.
        event.bottles = event.bottles.map(b =>
            b.bottle_id === '3'
                ? { bottle_name: b.bottle_name, bottle_path: '3', blind_number: b.blind_number }
                : b);
        app.event = event;
        app.addBottleQuery = 'blanton';
        await app.searchBottlesToAdd();
        expect(app.addBottleResults).toEqual([]);
    });

    it('handles a missing results key and no loaded event', async () => {
        const noResults = loadContract('event_bottle_search');
        delete noResults.results;
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/search', jsonResponse(noResults)],
        ]));
        const app = freshApp();
        app.addBottleQuery = 'blanton';
        await app.searchBottlesToAdd();
        expect(app.addBottleResults).toEqual([]);
        expect(String(fetch.mock.calls[0][0])).toContain('beverage_type=');
    });

    it('logs and keeps prior results on network failure', async () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp();
        const prior = loadContract('event_bottle_search').results;
        app.addBottleQuery = 'blanton';
        app.addBottleResults = prior;
        await app.searchBottlesToAdd();
        expect(consoleError).toHaveBeenCalled();
        expect(app.addBottleResults).toEqual(prior);
    });
});

// ---------------------------------------------------------------------------
// addBottleToEvent
// ---------------------------------------------------------------------------

describe('addBottleToEvent', () => {
    it('POSTs the search result\'s bottle_path as bottle_id and reports the blind number', async () => {
        // Blind-event contract response: identity-redacted (bottle_name is
        // "Bottle #3", no bottle_path key).
        vi.stubGlobal('fetch', routeFetch([
            [`/api/v1/events/${EVENT_ID}/bottles`,
                jsonResponse(loadContract('event_add_bottle_response'))],
            ['/api/v1/events/', jsonResponse(makeEvent())],
        ]));

        const [candidate] = loadContract('event_bottle_search').results;
        const app = freshApp();
        app.addBottleQuery = 'blanton';
        app.addBottleResults = [candidate];
        await app.addBottleToEvent(candidate);

        const [url, opts] = fetch.mock.calls[0];
        expect(url).toBe(`/api/v1/events/${EVENT_ID}/bottles`);
        expect(opts.method).toBe('POST');
        expect(JSON.parse(opts.body)).toEqual({ bottle_id: '3' });

        expect(app.addBottleMessage).toBe('Added as Bottle #3');
        expect(app.addBottleError).toBe(false);
        expect(app.addBottleQuery).toBe('');
        expect(app.addBottleResults).toEqual([]);
        expect(app.addingBottle).toBe(false);
        expect(app.event).not.toBeNull();   // event reloaded
    });

    it('reports the real bottle name on non-blind events (contract data)', async () => {
        // Non-blind contract response: full EventBottle echo, blind_number null.
        vi.stubGlobal('fetch', routeFetch([
            ['/bottles', jsonResponse(loadContract('event_add_bottle_response_open'))],
            ['/api/v1/events/', jsonResponse(makeEvent({ is_blind: false }))],
        ]));
        const app = freshApp();
        await app.addBottleToEvent({ bottle_path: '2' });
        expect(app.addBottleMessage).toBe('Added Buffalo Trace - Weller Special Reserve');
    });

    // Error responses below are hand-written: assert_contract snapshots the
    // happy-path flow; the {detail} shape is FastAPI's HTTPException format.
    it('surfaces the API error detail on failure', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/bottles', jsonResponse(
                { detail: 'Bottle is already in this event' },
                { ok: false, status: 409 },
            )],
        ]));
        const app = freshApp();
        await app.addBottleToEvent({ bottle_path: '1' });
        expect(app.addBottleError).toBe(true);
        expect(app.addBottleMessage).toBe('Bottle is already in this event');
        expect(app.addingBottle).toBe(false);
    });

    it('falls back to a generic error when no detail is provided', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/bottles', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        await app.addBottleToEvent({ bottle_path: '1' });
        expect(app.addBottleMessage).toBe('Failed to add bottle');
    });
});

// ---------------------------------------------------------------------------
// Host detection
// ---------------------------------------------------------------------------

describe('isHost', () => {
    it('matches the participant name against the event host', () => {
        const app = freshApp();
        app.event = makeEvent();                       // contract host_name: Ben
        app.participantInfo = makeJoinResponse();      // Alice joined
        expect(app.isHost()).toBe(false);
        app.participantInfo = makeJoinResponse({ participant_name: 'Ben' });
        expect(app.isHost()).toBe(true);
    });

    it('is (quirkily) true before joining or loading — undefined === undefined', () => {
        // Pins existing behavior, extracted verbatim from the template: with no
        // participantInfo and no event both optional chains yield undefined, so
        // the comparison is true. Harmless on the page (the host box sits inside
        // an x-show="joined" gate) but do not "fix" without updating the markup.
        const app = freshApp();
        expect(app.isHost()).toBe(true);

        // Once the event loads (host known) but before joining, it is false.
        app.event = makeEvent();
        expect(app.isHost()).toBe(false);
    });
});
