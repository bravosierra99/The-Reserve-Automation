/**
 * Unit tests for the events list page component
 * (src/reserve_automation/web/static/js/events/events-page.js).
 *
 * Alpine itself is not loaded; the factory's return value is used directly.
 * The 10-second refresh poll is exercised with fake timers.
 *
 * The event-list fixture is NOT hand-written: it is the events_list contract
 * fixture — a real GET /api/v1/events response captured and snapshot-verified
 * by tests/contract/test_events_contract.py (see tests/contract/contract.py).
 * Notably, bottles are objects ({bottle_id, bottle_name, bottle_path,
 * blind_number}) and participants are keyed by id carrying participant_name —
 * the old hand-written fixture had string bottles and {name} participants.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
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

// Real GET /api/v1/events response: the whiskey and wine contract events.
function makeEventsList() {
    return loadContract('events_list');
}

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([['/api/v1/events', jsonResponse(makeEventsList())]]));
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
        expect(app.events).toEqual(makeEventsList());
        expect(app.loading).toBe(false);
    });

    it('stores the fields templates/events.html renders, in list order', async () => {
        const app = freshApp();
        await app.loadEvents();

        // Newest first: the contract flow creates the wine event after the
        // whiskey event, and /api/v1/events orders by created_at desc.
        expect(app.events.map(e => e.name))
            .toEqual(['Contract Wine Night', 'Contract Whiskey Night']);
        const [wine, whiskey] = app.events;

        // Card header + badges read these directly.
        expect(whiskey.event_type).toBe('bottle');
        expect(whiskey.beverage_type).toBe('whiskey');
        expect(whiskey.is_blind).toBe(true);
        expect(whiskey.event_mode).toBe('standard');
        expect(whiskey.status).toBe('closed');
        expect(whiskey.host_name).toBe('Ben');

        // "N bottles" uses bottles.length — bottles are OBJECTS, not strings.
        expect(whiskey.bottles).toHaveLength(3);
        expect(whiskey.bottles[0]).toEqual({
            bottle_id: '1',
            bottle_name: 'Willett - Family Estate Single Barrel',
            bottle_path: '1',
            blind_number: 1,
        });
        expect(whiskey.cocktails).toEqual([]);

        // Participant count uses Object.keys(participants).length.
        expect(Object.keys(whiskey.participants)).toHaveLength(2);
        expect(Object.values(whiskey.participants).map(p => p.participant_name))
            .toEqual(['Alice', 'Bob']);

        expect(wine.beverage_type).toBe('wine');
        expect(wine.bottles).toHaveLength(2);
        expect(Object.keys(wine.participants)).toHaveLength(1);
    });

    it('logs and clears loading on an HTTP error, keeping prior events', async () => {
        const errSpy = vi.spyOn(console, 'error').mockImplementation(() => {});
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/events', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        const prior = makeEventsList();
        app.events = prior;
        await app.loadEvents();
        expect(app.events).toEqual(prior); // unchanged
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
        expect(app.events).toEqual(makeEventsList());

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
