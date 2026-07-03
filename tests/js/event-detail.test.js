/**
 * Unit tests for the event detail / participation page component
 * (src/reserve_automation/web/static/js/events/event-detail.js).
 *
 * Alpine itself is not loaded; the factory's return value is used directly.
 * init() is exercised with hand-supplied $watch/$refs stubs (Alpine magics)
 * and a stubbed QRCode global (the page loads qrcodejs from a CDN).
 *
 * Fixtures mirror web/routes/events.py:
 *   GET  /api/v1/events/{id}          — bottles/participants shapes
 *   POST /api/v1/events/{id}/join     — {participant_id, participant_name, event_id}
 *                                       + participant_sessions cookie (httponly=False,
 *                                       URL-encoded JSON keyed by event_id)
 *   POST /api/v1/events/{id}/bottles  — {message, bottle}
 * and web/routes/bottles/extraction.py GET /api/v1/bottles/search — {query, results}.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

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

const EVENT_ID = 'ev-detail-42';

function makeEvent(overrides = {}) {
    return {
        event_id: EVENT_ID,
        name: 'Blind Bourbon Bash',
        beverage_type: 'whiskey',
        event_type: 'bottle',
        is_blind: true,
        status: 'open',
        host_name: 'Ben',
        bottles: [
            { bottle_id: '1', bottle_name: 'Bottle #1', bottle_path: '1', blind_number: 1 },
            { bottle_id: '2', bottle_name: 'Bottle #2', bottle_path: '2', blind_number: 2 },
        ],
        participants: {
            'p-ben': {
                participant_id: 'p-ben',
                name: 'Ben',
                tastings: [{ bottle_path: '1', tasting_data: { whiskey_nose: 2 } }],
            },
        },
        ...overrides,
    };
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
        expect(app.qrCodeInstance).toBeNull();
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
            ['/api/v1/me', jsonResponse({ authenticated: true, display_name: 'Ben Smith', permissions: {} })],
            ['/api/v1/events/', jsonResponse(makeEvent())],
        ]));

        const app = freshApp();
        await app.init();

        expect(app.eventUrl).toBe(window.location.origin + '/events/' + EVENT_ID);
        expect(app.participantName).toBe('Ben Smith');
        expect(app.event.name).toBe('Blind Bourbon Bash');
        expect(app.loading).toBe(false);
        expect(app.$watch).toHaveBeenCalledWith('showQRModal', expect.any(Function));
    });

    it('leaves the name empty when /api/v1/me has no display_name or fails', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/me', jsonResponse({ authenticated: false, display_name: null })],
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
        const joinResponse = {
            participant_id: 'p-new',
            participant_name: 'New Guy',
            event_id: EVENT_ID,
        };
        vi.stubGlobal('fetch', routeFetch([
            [`/api/v1/events/${EVENT_ID}/join`, jsonResponse(joinResponse)],
            ['/api/v1/events/', jsonResponse(makeEvent())],
        ]));

        const app = freshApp();
        app.participantName = 'New Guy';
        await app.joinEvent();

        const [url, opts] = fetch.mock.calls[0];
        expect(url).toBe(`/api/v1/events/${EVENT_ID}/join`);
        expect(opts.method).toBe('POST');
        expect(opts.headers).toEqual({ 'Content-Type': 'application/json' });
        expect(JSON.parse(opts.body)).toEqual({ participant_name: 'New Guy' });

        expect(app.participantInfo).toEqual(joinResponse);
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
        app.participantName = 'New Guy';
        await app.joinEvent();
        expect(alert).toHaveBeenCalledWith('Failed to join event: Failed to join event');
        expect(app.joined).toBe(false);
        expect(app.joining).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// searchBottlesToAdd
// ---------------------------------------------------------------------------

describe('searchBottlesToAdd', () => {
    it('clears results for queries under 2 characters without fetching', async () => {
        const app = freshApp();
        app.addBottleResults = [{ bottle_path: '9' }];
        app.addBottleQuery = 'w';
        await app.searchBottlesToAdd();
        expect(app.addBottleResults).toEqual([]);
        expect(fetch).not.toHaveBeenCalled();
    });

    it('queries the search endpoint with encoded query and beverage type', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/search', jsonResponse({ query: 'a b', results: [] })],
        ]));
        const app = freshApp();
        app.event = makeEvent();
        app.addBottleQuery = 'a b';
        await app.searchBottlesToAdd();
        expect(String(fetch.mock.calls[0][0]))
            .toBe('/api/v1/bottles/search?q=a%20b&beverage_type=whiskey');
    });

    it('hides bottles already in the event from the results', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/search', jsonResponse({
                query: 'we',
                results: [
                    { bottle_path: '1', bottle_name: 'Already In Event' },
                    { bottle_path: '3', bottle_name: 'Weller Antique' },
                ],
            })],
        ]));
        const app = freshApp();
        app.event = makeEvent();
        app.addBottleQuery = 'we';
        await app.searchBottlesToAdd();
        expect(app.addBottleResults).toEqual([
            { bottle_path: '3', bottle_name: 'Weller Antique' },
        ]);
    });

    it('handles a missing results key and no loaded event', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/search', jsonResponse({ query: 'we' })],
        ]));
        const app = freshApp();
        app.addBottleQuery = 'well';
        await app.searchBottlesToAdd();
        expect(app.addBottleResults).toEqual([]);
        expect(String(fetch.mock.calls[0][0])).toContain('beverage_type=');
    });

    it('logs and keeps prior results on network failure', async () => {
        const consoleError = vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp();
        app.addBottleQuery = 'well';
        app.addBottleResults = [{ bottle_path: '3' }];
        await app.searchBottlesToAdd();
        expect(consoleError).toHaveBeenCalled();
        expect(app.addBottleResults).toEqual([{ bottle_path: '3' }]);
    });
});

// ---------------------------------------------------------------------------
// addBottleToEvent
// ---------------------------------------------------------------------------

describe('addBottleToEvent', () => {
    it('POSTs the bottle id and reports the blind number on blind events', async () => {
        vi.stubGlobal('fetch', routeFetch([
            [`/api/v1/events/${EVENT_ID}/bottles`, jsonResponse({
                message: 'Bottle added',
                bottle: { bottle_id: '3', bottle_name: 'Bottle #3', blind_number: 3 },
            })],
            ['/api/v1/events/', jsonResponse(makeEvent())],
        ]));

        const app = freshApp();
        app.addBottleQuery = 'well';
        app.addBottleResults = [{ bottle_path: '3', bottle_name: 'Weller Antique' }];
        await app.addBottleToEvent({ bottle_path: '3', bottle_name: 'Weller Antique' });

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

    it('reports the real bottle name on non-blind events', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/bottles', jsonResponse({
                message: 'Bottle added',
                bottle: { bottle_id: '3', bottle_name: 'Weller Antique', blind_number: null },
            })],
            ['/api/v1/events/', jsonResponse(makeEvent({ is_blind: false }))],
        ]));
        const app = freshApp();
        await app.addBottleToEvent({ bottle_path: '3' });
        expect(app.addBottleMessage).toBe('Added Weller Antique');
    });

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
// Blind display helpers + host detection
// ---------------------------------------------------------------------------

describe('displayBottleName (blind redaction)', () => {
    it('shows only the blind number while a blind event is open', () => {
        const app = freshApp();
        app.event = makeEvent({ is_blind: true, status: 'open' });
        expect(app.displayBottleName({ bottle_name: 'Weller 12', blind_number: 2 }))
            .toBe('Bottle #2');
    });

    it('shows the real name once revealed', () => {
        const app = freshApp();
        app.event = makeEvent({ is_blind: true, status: 'revealed' });
        expect(app.displayBottleName({ bottle_name: 'Weller 12', blind_number: 2 }))
            .toBe('Weller 12');
    });

    it('shows the real name on non-blind events and unnumbered bottles', () => {
        const app = freshApp();
        app.event = makeEvent({ is_blind: false, status: 'open' });
        expect(app.displayBottleName({ bottle_name: 'Weller 12', blind_number: 2 }))
            .toBe('Weller 12');

        app.event = makeEvent({ is_blind: true, status: 'open' });
        expect(app.displayBottleName({ bottle_name: 'Weller 12', blind_number: null }))
            .toBe('Weller 12');
    });
});

describe('hasTasted', () => {
    it('is false before joining or before the event loads', () => {
        const app = freshApp();
        expect(app.hasTasted({ bottle_path: '1' })).toBe(false);
        app.participantInfo = { participant_id: 'p-ben' };
        expect(app.hasTasted({ bottle_path: '1' })).toBe(false);
    });

    it('is false when the participant is not in the event roster', () => {
        const app = freshApp();
        app.event = makeEvent();
        app.participantInfo = { participant_id: 'p-ghost' };
        expect(app.hasTasted({ bottle_path: '1' })).toBe(false);
    });

    it('reflects the participant tastings by bottle_path', () => {
        const app = freshApp();
        app.event = makeEvent();
        app.participantInfo = { participant_id: 'p-ben' };
        expect(app.hasTasted({ bottle_path: '1' })).toBe(true);
        expect(app.hasTasted({ bottle_path: '2' })).toBe(false);
    });
});

describe('isHost', () => {
    it('matches the participant name against the event host', () => {
        const app = freshApp();
        app.event = makeEvent({ host_name: 'Ben' });
        app.participantInfo = { participant_name: 'Ben' };
        expect(app.isHost()).toBe(true);
        app.participantInfo = { participant_name: 'Sarah' };
        expect(app.isHost()).toBe(false);
    });

    it('is (quirkily) true before joining or loading — undefined === undefined', () => {
        // Pins existing behavior, extracted verbatim from the template: with no
        // participantInfo and no event both optional chains yield undefined, so
        // the comparison is true. Harmless on the page (the host box sits inside
        // an x-show="joined" gate) but do not "fix" without updating the markup.
        const app = freshApp();
        expect(app.isHost()).toBe(true);

        // Once the event loads (host known) but before joining, it is false.
        app.event = makeEvent({ host_name: 'Ben' });
        expect(app.isHost()).toBe(false);
    });
});
