/**
 * Unit tests for the create-event picker module
 * (src/reserve_automation/web/static/js/management/event-create.js).
 *
 * The module attaches itself to window (jsdom), same as in the browser.
 * Each test builds a fresh component object the way managementApp() does:
 * initState() spread for state + the module spread for methods.
 *
 * Bottle fixtures are NOT hand-written: they come from the contract fixture
 * management_bottle_search — a real GET /api/v1/management/bottles/search
 * response (full BottleMetadata.model_dump objects, id as a STRING, and no
 * _index field — the July 2026 "_index" regression compared a field search
 * results don't carry) captured by tests/contract/test_management_contract.py.
 * The event-create response comes from the event_create_response contract
 * fixture. Per-test variants are explicit mutations of the loaded objects.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
import '../../src/reserve_automation/web/static/js/management/event-create.js';

// Contract search data: two Buffalo Trace Wellers, ids '1' and '2'.
function searchFixture() {
    return loadContract('management_bottle_search');
}

let WELLER12;    // id '1'
let WELLER_SR;   // id '2'
let CAYMUS;      // synthetic wine variant — explicit mutation of a contract row
let component;

function freshComponent() {
    const mod = window.eventCreateModule();
    // Mirrors managementApp(): state via initState(), methods via spread,
    // plus the bits of surrounding component state the module touches.
    return Object.assign({ mode: 'create-event' }, mod.initState(), mod);
}

beforeEach(() => {
    [WELLER12, WELLER_SR] = searchFixture().bottles;
    CAYMUS = {
        ...WELLER12,
        id: '3', producer: 'Caymus Vineyards', name: 'Cabernet Sauvignon', type: 'wine',
    };
    component = freshComponent();
});

afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

describe('isBottleInEvent', () => {
    it('is false for a different bottle after one is selected (the July 2026 "_index" regression)', () => {
        // The shipped bug: comparison on a field absent from search results
        // (undefined === undefined) marked EVERY result "✓ Added" once any
        // bottle was selected — on a phone that means "can only add one bottle".
        component.addBottleToEvent(WELLER12);

        expect(component.isBottleInEvent(WELLER_SR)).toBe(false);
        expect(component.isBottleInEvent(CAYMUS)).toBe(false);
        expect(component.isBottleInEvent(WELLER12)).toBe(true);
    });

    it('matches on id, not object identity', () => {
        component.addBottleToEvent(WELLER12);
        expect(component.isBottleInEvent({ ...WELLER12 })).toBe(true);
    });
});

describe('addBottleToEvent / removeBottleFromEvent', () => {
    it('adds bottles in order', () => {
        component.addBottleToEvent(WELLER12);
        component.addBottleToEvent(WELLER_SR);
        expect(component.eventSelectedBottles).toEqual([WELLER12, WELLER_SR]);
    });

    it('ignores a duplicate add of the same bottle id', () => {
        component.addBottleToEvent(WELLER12);
        component.addBottleToEvent({ ...WELLER12 });
        expect(component.eventSelectedBottles).toHaveLength(1);
    });

    it('removes by index and frees the bottle for re-adding', () => {
        component.addBottleToEvent(WELLER12);
        component.addBottleToEvent(WELLER_SR);

        component.removeBottleFromEvent(0);

        expect(component.eventSelectedBottles).toEqual([WELLER_SR]);
        expect(component.isBottleInEvent(WELLER12)).toBe(false);
    });
});

describe('canCreateEvent', () => {
    it('requires name, host, and at least one bottle', () => {
        expect(component.canCreateEvent()).toBe(false);

        component.eventName = 'Bourbon Night';
        component.eventHostName = 'Ben';
        expect(component.canCreateEvent()).toBe(false); // no bottles yet

        component.addBottleToEvent(WELLER12);
        expect(component.canCreateEvent()).toBe(true);

        component.eventHostName = '   ';
        expect(component.canCreateEvent()).toBe(false); // whitespace host
    });
});

describe('searchBottlesForEvent', () => {
    it('clears results without fetching when the query is under 2 chars', async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);
        component.eventBottleSearchResults = [WELLER12];

        component.eventBottleSearchQuery = 'a';
        await component.searchBottlesForEvent();

        expect(component.eventBottleSearchResults).toEqual([]);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('fetches the management search endpoint and stores the contract bottles', async () => {
        const contract = searchFixture();
        const fetchMock = vi.fn().mockResolvedValue({
            json: async () => contract,
        });
        vi.stubGlobal('fetch', fetchMock);

        component.eventBottleSearchQuery = 'Weller 12';
        await component.searchBottlesForEvent();

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/v1/management/bottles/search?q=Weller%2012'
        );
        expect(component.eventBottleSearchResults).toEqual(contract.bottles);
        expect(component.eventBottleSearchResults).toHaveLength(2);
        expect(component.eventBottleSearching).toBe(false);
    });

    it('search results carry display_name — the exact label the picker templates render', async () => {
        // management.html renders bottle.display_name (server-composed with
        // year/batch so near-identical bottlings are tellable apart); if the
        // contract payload drops it the picker rows would render blank.
        const contract = searchFixture();
        for (const bottle of contract.bottles) {
            expect(bottle.display_name).toBeTypeOf('string');
            expect(bottle.display_name.length).toBeGreaterThan(0);
        }
    });

    it('debounces: rapid keystrokes trigger a single search after 300ms', () => {
        vi.useFakeTimers();
        const searchSpy = vi.spyOn(component, 'searchBottlesForEvent').mockResolvedValue();

        component.debouncedSearchBottlesForEvent();
        component.debouncedSearchBottlesForEvent();
        component.debouncedSearchBottlesForEvent();

        vi.advanceTimersByTime(299);
        expect(searchSpy).not.toHaveBeenCalled();
        vi.advanceTimersByTime(1);
        expect(searchSpy).toHaveBeenCalledTimes(1);
    });
});

describe('createEvent', () => {
    // Real POST /api/v1/events response (event_create_response contract
    // fixture): event_id is the snapshot's normalized UUID placeholder.
    const EVENT_ID = '00000000-0000-4000-8000-000000000001';

    function stubCreateResponse(fetchMock) {
        fetchMock.mockResolvedValue({
            ok: true,
            json: async () => loadContract('event_create_response'),
        });
    }

    function fillValidEvent() {
        component.eventName = 'Bourbon Night';
        component.eventHostName = 'Ben';
        component.addBottleToEvent(WELLER12);
        component.addBottleToEvent(WELLER_SR);
    }

    it('does nothing when the form is incomplete', async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);

        await component.createEvent();

        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('posts selected bottle ids in order with null blind numbers for a standard event', async () => {
        const fetchMock = vi.fn();
        stubCreateResponse(fetchMock);
        vi.stubGlobal('fetch', fetchMock);
        fillValidEvent();

        await component.createEvent();

        const [url, options] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/v1/events');
        const body = JSON.parse(options.body);
        expect(body.bottle_ids).toEqual(['1', '2']);   // contract ids are strings
        expect(body.blind_numbers).toBeNull();
        expect(body.is_blind).toBe(false);

        expect(component.eventCreated).toBe(true);
        expect(component.eventCreatedUrl).toBe(`/events/${EVENT_ID}`);
        expect(component.eventCreating).toBe(false);
    });

    it('sends a permutation of 1..n as blind numbers for a blind event', async () => {
        const fetchMock = vi.fn();
        stubCreateResponse(fetchMock);
        vi.stubGlobal('fetch', fetchMock);
        fillValidEvent();
        component.addBottleToEvent(CAYMUS);
        component.eventIsBlind = true;

        await component.createEvent();

        const body = JSON.parse(fetchMock.mock.calls[0][1].body);
        expect(body.is_blind).toBe(true);
        expect([...body.blind_numbers].sort()).toEqual([1, 2, 3]);
    });

    it('surfaces the server error and does not mark the event created', async () => {
        // Error shape is hand-written: FastAPI's {detail} error envelope —
        // the contract flow only captures success responses.
        const fetchMock = vi.fn().mockResolvedValue({
            ok: false,
            json: async () => ({ detail: 'Bottle not found' }),
        });
        vi.stubGlobal('fetch', fetchMock);
        const alertMock = vi.fn();
        vi.stubGlobal('alert', alertMock);
        vi.spyOn(console, 'error').mockImplementation(() => {});
        fillValidEvent();

        await component.createEvent();

        expect(alertMock).toHaveBeenCalledWith('Event creation failed: Bottle not found');
        expect(component.eventCreated).toBe(false);
        expect(component.eventCreating).toBe(false);
    });
});

describe('reset / cancel', () => {
    it('resetCreateEvent restores every initState default', () => {
        fillEverything(component);

        component.resetCreateEvent();

        const defaults = window.eventCreateModule().initState();
        for (const [key, value] of Object.entries(defaults)) {
            if (key === 'eventBottleSearchTimeout') continue; // deliberately untouched
            expect(component[key], key).toEqual(value);
        }
    });

    it('cancelCreateEvent leaves create-event mode and resets state', () => {
        fillEverything(component);

        component.cancelCreateEvent();

        expect(component.mode).toBeNull();
        expect(component.eventSelectedBottles).toEqual([]);
        expect(component.eventName).toBe('');
    });
});

function fillEverything(c) {
    c.eventName = 'Bourbon Night';
    c.eventBeverageType = 'whiskey';
    c.eventHostName = 'Ben';
    c.eventIsBlind = true;
    c.eventBottleSearchQuery = 'well';
    c.eventBottleSearchResults = [WELLER12];
    c.eventSelectedBottles = [WELLER12, WELLER_SR];
    c.eventCreated = true;
    c.eventCreatedUrl = '/events/00000000-0000-4000-8000-000000000001';
}
