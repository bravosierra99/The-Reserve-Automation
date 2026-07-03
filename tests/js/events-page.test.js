/**
 * Unit tests for the events list page component
 * (src/reserve_automation/web/static/js/events/events-page.js).
 *
 * Alpine itself is not loaded; the factory's return value is used directly.
 * The 10-second refresh poll is exercised with fake timers.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/events/events-page.js';

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
    return window.eventsApp();
}

// Fixtures mirror web/routes/events.py list_events(): an array of event dicts
// (blind-redacted for non-managers). Fields read by templates/events.html.
const EVENTS = [
    {
        event_id: 'evt-1', name: 'Bourbon Night', event_type: 'bottle',
        beverage_type: 'whiskey', bottles: ['b1', 'b2'], is_blind: true,
        event_mode: 'standard', status: 'open', host_name: 'Ben',
        participants: { p1: { name: 'Sarah' } },
    },
    {
        event_id: 'evt-2', name: 'Flight Club', event_type: 'cocktail',
        beverage_type: 'cocktail', bottles: [], cocktails: ['old-fashioned'],
        is_blind: false, event_mode: 'flight', status: 'closed',
        host_name: 'Sarah', participants: {},
    },
];

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([['/api/v1/events', jsonResponse(EVENTS)]]));
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('confirm', vi.fn(() => true));
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

describe('initial state', () => {
    it('starts loading with no events', () => {
        const app = freshApp();
        expect(app.events).toEqual([]);
        expect(app.loading).toBe(true);
    });
});

describe('loadEvents', () => {
    it('fetches the event list and clears loading', async () => {
        const app = freshApp();
        await app.loadEvents();
        expect(fetch).toHaveBeenCalledWith('/api/v1/events');
        expect(app.events).toEqual(EVENTS);
        expect(app.loading).toBe(false);
    });

    it('logs and clears loading on an HTTP error, keeping prior events', async () => {
        const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/events', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        app.events = EVENTS;
        await app.loadEvents();
        expect(app.events).toEqual(EVENTS); // unchanged
        expect(app.loading).toBe(false);
        expect(errSpy).toHaveBeenCalled();
    });

    it('logs and clears loading when the fetch itself throws', async () => {
        const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down'); }));
        const app = freshApp();
        await app.loadEvents();
        expect(app.events).toEqual([]);
        expect(app.loading).toBe(false);
        expect(errSpy).toHaveBeenCalled();
    });
});

describe('init — 10s refresh poll', () => {
    it('loads immediately, then reloads every 10 seconds', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        await app.init();
        expect(fetch).toHaveBeenCalledTimes(1);
        expect(app.events).toEqual(EVENTS);

        await vi.advanceTimersByTimeAsync(10000);
        expect(fetch).toHaveBeenCalledTimes(2);

        await vi.advanceTimersByTimeAsync(20000);
        expect(fetch).toHaveBeenCalledTimes(4);
    });

    it('does not reload before the 10 second interval elapses', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        await app.init();
        await vi.advanceTimersByTimeAsync(9999);
        expect(fetch).toHaveBeenCalledTimes(1);
    });
});
