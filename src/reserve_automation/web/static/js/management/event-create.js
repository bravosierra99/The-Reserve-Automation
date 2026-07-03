/**
 * Create Event Module
 *
 * Provides state and methods for the create-event panel in management.html
 * (event details form + bottle search picker + event creation).
 *
 * Extracted from inline template JS so the picker logic is unit-testable
 * (see tests/js/event-create.test.js). The July 2026 "_index" bug — every
 * search result showed "✓ Added" after one selection because the picker
 * compared a field that doesn't exist on search results — lived here and
 * was invisible to all API-level tests.
 *
 * Usage (same pattern as tasting-review.js):
 *   const eventCreate = window.eventCreateModule ? window.eventCreateModule() : {};
 *   const eventCreateState = eventCreate.initState ? eventCreate.initState() : {};
 *   // In managementApp return:
 *   ...eventCreateState  // (state section)
 *   ...eventCreate       // (methods section)
 */

// #CLAUDE_REQ: State keys and method names here MUST match the Alpine bindings in
// management.html's "Create Event Mode" section (x-model="eventName",
// @click="addBottleToEvent(bottle)", etc.). Rename in both places or the panel
// silently breaks — the template only fails at click-time in the browser.
// #CLAUDE_REQ: Bottle identity is bottle.id (string). Search results come from
// /api/v1/management/bottles/search (BottleMetadata.model_dump) and have NO
// _index field — never compare on fields the search payload doesn't carry.

window.eventCreateModule = function() {
    return {
        initState() {
            return {
                eventName: '',
                eventBeverageType: 'wine',
                eventHostName: '',
                eventIsBlind: false,
                eventBottleSearchQuery: '',
                eventBottleSearchTimeout: null,
                eventBottleSearching: false,
                eventBottleSearchResults: [],
                eventSelectedBottles: [],
                eventCreating: false,
                eventCreated: false,
                eventCreatedUrl: '',
            };
        },

        debouncedSearchBottlesForEvent() {
            clearTimeout(this.eventBottleSearchTimeout);
            this.eventBottleSearchTimeout = setTimeout(() => this.searchBottlesForEvent(), 300);
        },

        async searchBottlesForEvent() {
            if (!this.eventBottleSearchQuery || this.eventBottleSearchQuery.length < 2) {
                this.eventBottleSearchResults = [];
                return;
            }

            this.eventBottleSearching = true;
            try {
                const response = await fetch(`/api/v1/management/bottles/search?q=${encodeURIComponent(this.eventBottleSearchQuery)}`);
                const data = await response.json();
                this.eventBottleSearchResults = data.bottles;
            } catch (error) {
                console.error('Bottle search failed:', error);
                alert('Bottle search failed: ' + error.message);
            } finally {
                this.eventBottleSearching = false;
            }
        },

        addBottleToEvent(bottle) {
            if (!this.isBottleInEvent(bottle)) {
                this.eventSelectedBottles.push(bottle);
            }
        },

        removeBottleFromEvent(index) {
            this.eventSelectedBottles.splice(index, 1);
        },

        isBottleInEvent(bottle) {
            // Compare on id — search results have no _index field, and
            // undefined === undefined made every result look "added".
            return this.eventSelectedBottles.some(b => b.id === bottle.id);
        },

        canCreateEvent() {
            return this.eventName.trim() !== '' &&
                   this.eventHostName.trim() !== '' &&
                   this.eventSelectedBottles.length > 0;
        },

        async createEvent() {
            if (!this.canCreateEvent()) return;

            this.eventCreating = true;
            try {
                // Build bottle IDs and blind numbers
                const bottleIds = this.eventSelectedBottles.map(b => b.id);

                // Generate randomized blind numbers for blind tastings
                let blindNumbers = null;
                if (this.eventIsBlind) {
                    // Create array [1, 2, 3, ..., n]
                    blindNumbers = Array.from({length: bottleIds.length}, (_, i) => i + 1);
                    // Shuffle using Fisher-Yates algorithm
                    for (let i = blindNumbers.length - 1; i > 0; i--) {
                        const j = Math.floor(Math.random() * (i + 1));
                        [blindNumbers[i], blindNumbers[j]] = [blindNumbers[j], blindNumbers[i]];
                    }
                }

                const requestData = {
                    name: this.eventName,
                    beverage_type: this.eventBeverageType,
                    is_blind: this.eventIsBlind,
                    host_name: this.eventHostName,
                    bottle_ids: bottleIds,
                    blind_numbers: blindNumbers
                };

                const response = await fetch('/api/v1/events', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestData)
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Failed to create event');
                }

                const event = await response.json();
                this.eventCreatedUrl = `/events/${event.event_id}`;
                this.eventCreated = true;
            } catch (error) {
                console.error('Event creation failed:', error);
                alert('Event creation failed: ' + error.message);
            } finally {
                this.eventCreating = false;
            }
        },

        cancelCreateEvent() {
            this.mode = null;
            this.resetCreateEvent();
        },

        resetCreateEvent() {
            // Reset to defaults but leave the debounce timer handle alone so a
            // pending debounce can still be cancelled by the next keystroke.
            const { eventBottleSearchTimeout, ...defaults } = this.initState();
            Object.assign(this, defaults);
        },
    };
};
