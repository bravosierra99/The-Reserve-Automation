/**
 * Event detail / participation page component (window.eventDetailApp).
 *
 * Extracted from templates/event_detail.html (July 2026) so the join /
 * session / add-bottle logic gets vitest unit coverage
 * (tests/js/event-detail.test.js). Attached as a WHOLE factory per the repo's
 * extraction convention so Alpine receives exactly the object the inline
 * script used to build.
 *
 * The event id is passed by the template markup:
 *   x-data="eventDetailApp('{{ event_id }}')"
 * so no Jinja values live in this file.
 *
 * Runtime dependencies (page-provided, not imported here):
 *   - QRCode global from the qrcodejs CDN script (loaded by the template);
 *     only touched inside the showQRModal $watch callback.
 *   - Alpine magics this.$watch / this.$refs (init only).
 */

// #CLAUDE_REQ: State keys and method names here MUST match the Alpine bindings
//              in templates/event_detail.html (x-data="eventDetailApp(...)").
//              Rename in both places or the page silently loses functionality.
// #CLAUDE_REQ: Endpoints must match web/routes/events.py and
//              web/routes/bottles/extraction.py:
//              GET  /api/v1/me                        (health.py — display_name prefill)
//              GET  /api/v1/events/{id}               (blind bottles redacted pre-reveal)
//              POST /api/v1/events/{id}/join          -> {participant_id, participant_name, event_id}
//                   and sets the participant_sessions cookie (httponly=False,
//                   URL-encoded JSON keyed by event_id) that
//                   checkParticipantSession() parses.
//              GET  /api/v1/bottles/search?q=&beverage_type=  -> {query, results}
//              POST /api/v1/events/{id}/bottles       -> {message, bottle:{bottle_name, blind_number,...}}

window.eventDetailApp = function eventDetailApp(eventId) {
    return {
        eventId: eventId,
        event: null,
        participantInfo: null,
        participantName: '',
        loading: true,
        error: null,
        joining: false,
        joined: false,
        showQRModal: false,
        eventUrl: '',
        addBottleQuery: '',
        addBottleResults: [],
        addBottleMessage: '',
        addBottleError: false,
        addingBottle: false,

        async init() {
            this.eventUrl = window.location.origin + '/events/' + this.eventId;
            // Pre-fill participant name from auth identity
            try {
                const meResp = await fetch('/api/v1/me');
                if (meResp.ok) {
                    const me = await meResp.json();
                    if (me.display_name) this.participantName = me.display_name;
                }
            } catch (e) { /* ignore */ }
            await this.loadEvent();
            await this.checkParticipantSession();
            // Refresh every 5 seconds
            setInterval(() => this.loadEvent(), 5000);

            // Watch for QR modal and generate QR code
            this.$watch('showQRModal', (value) => {
                if (value) {
                    // Clear previous QR code
                    this.$refs.qrcode.innerHTML = '';
                    // Generate new QR code
                    setTimeout(() => {
                        // Larger QR code on mobile for easier scanning
                        const isMobile = window.innerWidth < 768;
                        const qrSize = isMobile ? 280 : 256;

                        new QRCode(this.$refs.qrcode, {
                            text: this.eventUrl,
                            width: qrSize,
                            height: qrSize,
                            colorDark: "#000000",
                            colorLight: "#ffffff",
                            correctLevel: QRCode.CorrectLevel.H
                        });
                    }, 100);
                }
            });
        },

        async loadEvent() {
            try {
                const response = await fetch(`/api/v1/events/${this.eventId}`);
                if (!response.ok) {
                    if (response.status === 404) {
                        this.error = 'Event not found';
                    } else {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    this.loading = false;
                    return;
                }
                this.event = await response.json();
                this.loading = false;
            } catch (error) {
                console.error('Failed to load event:', error);
                this.error = 'Failed to load event';
                this.loading = false;
            }
        },

        async checkParticipantSession() {
            // Check if we have a participant sessions cookie (multi-event)
            const cookies = document.cookie.split(';').reduce((acc, cookie) => {
                const [key, value] = cookie.trim().split('=');
                acc[key] = value;
                return acc;
            }, {});

            if (cookies.participant_sessions) {
                try {
                    const allSessions = JSON.parse(decodeURIComponent(cookies.participant_sessions));

                    // Check if we have a session for this specific event
                    if (allSessions[this.eventId]) {
                        this.participantInfo = {
                            event_id: this.eventId,
                            participant_id: allSessions[this.eventId].participant_id,
                            participant_name: allSessions[this.eventId].participant_name
                        };
                        this.joined = true;
                    }
                } catch (e) {
                    console.error('Failed to parse participant sessions:', e);
                }
            }
        },

        async joinEvent() {
            if (!this.participantName.trim()) return;

            this.joining = true;
            try {
                const response = await fetch(`/api/v1/events/${this.eventId}/join`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ participant_name: this.participantName })
                });

                if (!response.ok) {
                    throw new Error('Failed to join event');
                }

                this.participantInfo = await response.json();
                this.joined = true;
                await this.loadEvent();
            } catch (error) {
                console.error('Failed to join event:', error);
                alert('Failed to join event: ' + error.message);
            } finally {
                this.joining = false;
            }
        },

        async searchBottlesToAdd() {
            this.addBottleMessage = '';
            if (!this.addBottleQuery || this.addBottleQuery.length < 2) {
                this.addBottleResults = [];
                return;
            }
            try {
                const url = `/api/v1/bottles/search?q=${encodeURIComponent(this.addBottleQuery)}&beverage_type=${this.event?.beverage_type || ''}`;
                const response = await fetch(url);
                if (response.ok) {
                    const data = await response.json();
                    // Hide bottles already in the event.
                    // #CLAUDE_REQ: Two different id fields meet here. Event bottles
                    //              carry both bottle_id and bottle_path (events.py
                    //              sets bottle_path = str(bottle_id) in the DB era);
                    //              search results (MatchCandidate) carry the DB id
                    //              ONLY in a field named bottle_path — there is no
                    //              bottle_id on search results. Key event bottles by
                    //              bottle_id with a bottle_path fallback (legacy rows)
                    //              and match against the result's bottle_path.
                    const inEvent = new Set((this.event?.bottles || []).map(b => b.bottle_id ?? b.bottle_path));
                    this.addBottleResults = (data.results || []).filter(r => !inEvent.has(r.bottle_path));
                }
            } catch (e) {
                console.error('Bottle search failed:', e);
            }
        },

        async addBottleToEvent(result) {
            this.addingBottle = true;
            this.addBottleMessage = '';
            this.addBottleError = false;
            try {
                const response = await fetch(`/api/v1/events/${this.eventId}/bottles`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    // #CLAUDE_REQ: NOT a typo — result.bottle_path holds the DB id
                    //              (search results have no bottle_id field), and the
                    //              endpoint's request field is named bottle_id.
                    body: JSON.stringify({ bottle_id: result.bottle_path })
                });
                const data = await response.json();
                if (!response.ok) {
                    throw new Error(data.detail || 'Failed to add bottle');
                }
                this.addBottleMessage = data.bottle.blind_number
                    ? `Added as Bottle #${data.bottle.blind_number}`
                    : `Added ${data.bottle.bottle_name}`;
                this.addBottleQuery = '';
                this.addBottleResults = [];
                await this.loadEvent();
            } catch (e) {
                this.addBottleError = true;
                this.addBottleMessage = e.message;
            } finally {
                this.addingBottle = false;
            }
        },

        isHost() {
            return this.participantInfo?.participant_name === this.event?.host_name;
        }
    };
};
