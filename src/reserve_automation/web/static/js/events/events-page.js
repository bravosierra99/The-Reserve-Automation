/**
 * Events list page component (window.eventsApp).
 *
 * Extracted from templates/events.html (July 2026) so the logic gets vitest
 * unit coverage (tests/js/events-page.test.js). Attached as a WHOLE factory
 * (the established pattern for page root components — see
 * management/management-app.js).
 *
 * Small on purpose: loads the event list and re-polls it every 10 seconds so
 * open-event status badges stay fresh while guests sit on the page.
 */

// #CLAUDE_REQ: State keys and method names here (events, loading, init,
//              loadEvents) MUST match the Alpine bindings in
//              templates/events.html (x-data="eventsApp()"). The markup also
//              reads event fields directly: event_id, name, event_type,
//              beverage_type, bottles, cocktails, is_blind, event_mode,
//              status, host_name, participants.
// #CLAUDE_REQ: GET /api/v1/events must match web/routes/events.py
//              list_events() — returns a JSON array of event dicts
//              (blind-redacted for non-managers).

window.eventsApp = function() {
    return {
        events: [],
        loading: true,

        async init() {
            await this.loadEvents();
            // Refresh events every 10 seconds
            setInterval(() => this.loadEvents(), 10000);
        },

        async loadEvents() {
            try {
                const response = await fetch('/api/v1/events');
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                this.events = await response.json();
                this.loading = false;
            } catch (error) {
                console.error('Failed to load events:', error);
                this.loading = false;
            }
        }
    };
};
