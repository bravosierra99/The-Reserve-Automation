/**
 * Unit tests for the create-event picker module
 * (src/reserve_automation/web/static/js/management/event-create.js).
 *
 * The module attaches itself to window (jsdom), same as in the browser.
 * Each test builds a fresh component object the way managementApp() does:
 * initState() spread for state + the module spread for methods.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/management/event-create.js';

// Search results come from /api/v1/management/bottles/search
// (BottleMetadata.model_dump) — note: NO _index field. Shapes here must stay
// search-result-shaped or the regression tests test the wrong thing.
const WELLER = { id: '1', producer: 'Weller', name: 'Original Wheated Bourbon', type: 'whiskey' };
const BUFFALO = { id: '2', producer: 'Buffalo Trace', name: 'Kentucky Straight Bourbon', type: 'whiskey' };
const CAYMUS = { id: '3', producer: 'Caymus', name: 'Cabernet Sauvignon 2021', type: 'wine' };

function freshComponent() {
    const mod = window.eventCreateModule();
    // Mirrors managementApp(): state via initState(), methods via spread,
    // plus the bits of surrounding component state the module touches.
    return Object.assign({ mode: 'create-event' }, mod.initState(), mod);
}

let component;

beforeEach(() => {
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
        component.addBottleToEvent(WELLER);

        expect(component.isBottleInEvent(BUFFALO)).toBe(false);
        expect(component.isBottleInEvent(CAYMUS)).toBe(false);
        expect(component.isBottleInEvent(WELLER)).toBe(true);
    });

    it('matches on id, not object identity', () => {
        component.addBottleToEvent(WELLER);
        expect(component.isBottleInEvent({ ...WELLER })).toBe(true);
    });
});

describe('addBottleToEvent / removeBottleFromEvent', () => {
    it('adds bottles in order', () => {
        component.addBottleToEvent(WELLER);
        component.addBottleToEvent(BUFFALO);
        expect(component.eventSelectedBottles).toEqual([WELLER, BUFFALO]);
    });

    it('ignores a duplicate add of the same bottle id', () => {
        component.addBottleToEvent(WELLER);
        component.addBottleToEvent({ ...WELLER });
        expect(component.eventSelectedBottles).toHaveLength(1);
    });

    it('removes by index and frees the bottle for re-adding', () => {
        component.addBottleToEvent(WELLER);
        component.addBottleToEvent(BUFFALO);

        component.removeBottleFromEvent(0);

        expect(component.eventSelectedBottles).toEqual([BUFFALO]);
        expect(component.isBottleInEvent(WELLER)).toBe(false);
    });
});

describe('canCreateEvent', () => {
    it('requires name, host, and at least one bottle', () => {
        expect(component.canCreateEvent()).toBe(false);

        component.eventName = 'Bourbon Night';
        component.eventHostName = 'Ben';
        expect(component.canCreateEvent()).toBe(false); // no bottles yet

        component.addBottleToEvent(WELLER);
        expect(component.canCreateEvent()).toBe(true);

        component.eventHostName = '   ';
        expect(component.canCreateEvent()).toBe(false); // whitespace host
    });
});

describe('searchBottlesForEvent', () => {
    it('clears results without fetching when the query is under 2 chars', async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);
        component.eventBottleSearchResults = [WELLER];

        component.eventBottleSearchQuery = 'a';
        await component.searchBottlesForEvent();

        expect(component.eventBottleSearchResults).toEqual([]);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('fetches the management search endpoint with the encoded query', async () => {
        const fetchMock = vi.fn().mockResolvedValue({
            json: async () => ({ bottles: [WELLER, BUFFALO] }),
        });
        vi.stubGlobal('fetch', fetchMock);

        component.eventBottleSearchQuery = 'wheated bourbon';
        await component.searchBottlesForEvent();

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/v1/management/bottles/search?q=wheated%20bourbon'
        );
        expect(component.eventBottleSearchResults).toEqual([WELLER, BUFFALO]);
        expect(component.eventBottleSearching).toBe(false);
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
    function stubCreateResponse(fetchMock) {
        fetchMock.mockResolvedValue({
            ok: true,
            json: async () => ({ event_id: 'evt-123' }),
        });
    }

    function fillValidEvent() {
        component.eventName = 'Bourbon Night';
        component.eventHostName = 'Ben';
        component.addBottleToEvent(WELLER);
        component.addBottleToEvent(BUFFALO);
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
        expect(body.bottle_ids).toEqual(['1', '2']);
        expect(body.blind_numbers).toBeNull();
        expect(body.is_blind).toBe(false);

        expect(component.eventCreated).toBe(true);
        expect(component.eventCreatedUrl).toBe('/events/evt-123');
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
    c.eventBottleSearchResults = [WELLER];
    c.eventSelectedBottles = [WELLER, BUFFALO];
    c.eventCreated = true;
    c.eventCreatedUrl = '/events/evt-123';
}
