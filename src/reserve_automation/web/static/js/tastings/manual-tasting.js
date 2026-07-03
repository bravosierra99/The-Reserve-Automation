/**
 * Manual Tasting Wizard
 *
 * The full Alpine component for the /tastings page (manual_tasting.html):
 * the 3-step manual entry wizard (taster info → bottle selection → tasting
 * form), event-mode behavior (participant cookie session, blind bottles,
 * edit-existing-tasting), and the tasting-card upload flow.
 *
 * Unlike the management modules, this attaches the whole factory rather than
 * an initState()/methods pair: the component defines getters (tasting,
 * isWine, computedWineScore, ...) that the spread operator would invoke and
 * flatten into static values, so the object must be returned intact.
 *
 * Load order: components/tasting-form-mixin.js must load first (this factory
 * merges it at call time).
 *
 * Unit tests: tests/js/manual-tasting.test.js (npm test).
 */
// #CLAUDE_REQ: State keys, method names, and getters here MUST match the Alpine
// bindings in templates/manual_tasting.html AND the shared component
// templates/components/tasting_scores_form.html (which expects `tasting`,
// `isWine`, computed*Score, and the tastingFormMixin note methods/inputs).
// #CLAUDE_REQ: The save payload shape MUST match /api/v1/manual-tasting/save
// (web/routes/tastings.py) — mode, beverage_type, taster_name, tasting_date,
// selected_bottle_path, tasting_data (+ event_id/participant_id in event mode).

window.manualTastingWizard = function() {
    // Merge in the tasting form mixin for shared note management
    const mixin = typeof tastingFormMixin === 'function' ? tastingFormMixin() : {};

    return {
        // Include mixin properties
        ...mixin,

        // Mode toggle: 'manual' or 'upload'
        tastingMode: 'manual',

        // Upload tasting card state
        uploadExpectedCount: null,
        cardSelectedFile: null,
        cardPreviewUrl: null,
        cardUploading: false,
        cardUploadComplete: false,
        cardExtractionId: null,
        cardTastingsCount: 0,
        cardError: false,
        cardErrorMessage: '',

        // UI State (no server session - all state is local)
        _currentStep: 'taster_info',
        loading: false,
        error: false,
        errorMessage: '',
        saving: false,

        // Autocomplete suggestions
        acTasterNames: [],
        acPlaces: [],
        acThemes: [],

        // Step 1 data
        tasterName: '',
        tastingDate: new Date().toISOString().split('T')[0],
        beverageType: 'wine',
        participantSession: null,  // Store event session info (from cookie, not server session)

        // Step 2 data
        selectedBottle: null,
        showSearchModal: false,
        searchQuery: '',
        searchResults: [],
        searching: false,
        searchTimeout: null,
        eventBottles: [],  // Bottles in the event (for event mode)
        eventIsBlind: false,  // Whether event is blind
        eventRevealed: false,  // Whether event has been revealed
        eventData: null,  // Full event data (for checking tasted bottles)

        // Step 3 data - internal storage
        tastingData: {
            place: '',
            theme: '',
            days_from_crack: null,
            fill_level: null,
            color: '',
            // Wine scores
            wine_appearance: 0,
            wine_aroma: 0,
            wine_taste: 0,
            wine_aftertaste: 0,
            wine_overall: 0,
            // Whiskey scores
            whiskey_nose: 0,
            whiskey_palate: 0,
            whiskey_finish: 0,
            whiskey_overall: 0,
            // Notes
            appearance_notes: [],  // Wine-specific
            nose_notes: [],
            palate_notes: [],
            finish_notes: [],
            overall_notes: ''
        },

        // Getter for shared component compatibility (component expects 'tasting')
        get tasting() {
            return this.tastingData;
        },

        // Required by shared component
        get isWine() {
            return this.beverageType === 'wine';
        },

        // Computed scores - must be defined here, not in the mixin,
        // because spread invokes getters and stores static values.
        get computedWineScore() {
            const t = this.tasting || {};
            return (t.wine_appearance || 0) +
                   (t.wine_aroma || 0) +
                   (t.wine_taste || 0) +
                   (t.wine_aftertaste || 0) +
                   (t.wine_overall || 0);
        },
        get computed100ptScore() {
            return 50 + (this.computedWineScore / 20) * 50;
        },
        get computedWhiskeyScore() {
            const t = this.tasting || {};
            return (t.whiskey_nose || 0) +
                   (t.whiskey_palate || 0) +
                   (t.whiskey_finish || 0) +
                   (t.whiskey_overall || 0);
        },

        // Computed - all local, no server session
        get currentStep() {
            return this._currentStep;
        },

        get currentStepNumber() {
            const steps = { taster_info: 1, bottle_selection: 2, tasting_form: 3 };
            return steps[this.currentStep] || 1;
        },

        get canProceed() {
            if (this.currentStep === 'taster_info') {
                return this.tasterName && this.tastingDate && this.beverageType;
            } else if (this.currentStep === 'bottle_selection') {
                return this.selectedBottle !== null;
            }
            return true;
        },

        get isEventMode() {
            // Explicitly check if we're in event mode based on participant session
            return this.participantSession !== null && this.participantSession.event_id !== undefined;
        },

        // Actions
        async init() {
            // Sessionless wizard - all state is local, no server session needed
            // Check URL parameters to determine if we're in event mode
            const urlParams = new URLSearchParams(window.location.search);
            const isEventMode = urlParams.get('event_mode') === 'true';
            const eventId = urlParams.get('event_id');

            // Set participantSession based on URL mode (not server session)
            if (isEventMode && eventId) {
                this.participantSession = this.getParticipantSession(eventId);
                if (!this.participantSession) {
                    console.error('Event mode requested but no participant session found');
                    this.participantSession = null;
                }
            } else {
                // Standalone/Obsidian mode
                this.participantSession = null;
            }

            if (this.participantSession) {
                // Lock taster name to event participant name
                this.tasterName = this.participantSession.participant_name;

                // Load event data to get beverage type and bottles
                if (this.participantSession.event_id) {
                    try {
                        const eventResponse = await fetch(`/api/v1/events/${this.participantSession.event_id}`);
                        if (eventResponse.ok) {
                            const eventData = await eventResponse.json();
                            this.eventData = eventData;
                            this.beverageType = eventData.beverage_type;
                            this.eventIsBlind = eventData.is_blind;
                            this.eventRevealed = eventData.status === 'revealed';

                            // Transform event bottles for display
                            this.eventBottles = eventData.bottles.map(bottle => {
                                let thumbnail_url = `/api/v1/bottle-label/${bottle.bottle_path}`;
                                let display_name = bottle.bottle_name;
                                if (eventData.is_blind && eventData.status === 'open' && bottle.blind_number) {
                                    display_name = `Bottle #${bottle.blind_number}`;
                                }

                                return {
                                    bottle_path: bottle.bottle_path,
                                    bottle_name: display_name,
                                    blind_number: bottle.blind_number,
                                    thumbnail_url: thumbnail_url,
                                    producer: '',
                                    confidence: 1.0,
                                    beverage_type: eventData.beverage_type
                                };
                            });

                            if (eventData.is_blind) {
                                this.eventBottles.sort((a, b) => (a.blind_number || 0) - (b.blind_number || 0));
                            }
                        }
                    } catch (e) {
                        console.error('Failed to load event:', e);
                    }
                }

                // Skip step 1 in event mode - go directly to bottle selection
                this._currentStep = 'bottle_selection';
            }

            // Restore cached preferences (non-event mode only)
            if (!this.participantSession) {
                this.tasterName = localStorage.getItem('tasting_taster_name') || '';
                this.beverageType = localStorage.getItem('tasting_beverage_type') || 'wine';
                this.tastingData.place = localStorage.getItem('tasting_place') || '';
            }

            // Pre-select bottle if navigated from the bottles page
            if (!this.participantSession) {
                const preselectData = sessionStorage.getItem('preselect_bottle');
                if (preselectData) {
                    try {
                        const bottle = JSON.parse(preselectData);
                        sessionStorage.removeItem('preselect_bottle');
                        this.selectedBottle = bottle;
                        if (bottle.beverage_type && (bottle.beverage_type === 'wine' || bottle.beverage_type === 'whiskey')) {
                            this.beverageType = bottle.beverage_type;
                            localStorage.setItem('tasting_beverage_type', bottle.beverage_type);
                        }
                    } catch (e) {
                        console.error('Failed to parse preselected bottle:', e);
                    }
                }
            }

            // Load autocomplete suggestions
            try {
                const [tasters, places, themes] = await Promise.all([
                    fetch('/api/v1/autocomplete/tastings/taster_name').then(r => r.ok ? r.json() : []),
                    fetch('/api/v1/autocomplete/tastings/place').then(r => r.ok ? r.json() : []),
                    fetch('/api/v1/autocomplete/tastings/theme').then(r => r.ok ? r.json() : []),
                ]);
                this.acTasterNames = tasters;
                this.acPlaces = places;
                this.acThemes = themes;
            } catch (e) { /* non-critical */ }
        },

        getParticipantSession(eventId) {
            const cookies = document.cookie.split(';').reduce((acc, cookie) => {
                const [key, value] = cookie.trim().split('=');
                acc[key] = value;
                return acc;
            }, {});

            if (cookies.participant_sessions) {
                try {
                    const allSessions = JSON.parse(decodeURIComponent(cookies.participant_sessions));
                    if (allSessions[eventId]) {
                        return {
                            event_id: eventId,
                            participant_id: allSessions[eventId].participant_id,
                            participant_name: allSessions[eventId].participant_name
                        };
                    }
                } catch (e) {
                    console.error('Failed to parse participant_sessions cookie:', e);
                    return null;
                }
            }
            return null;
        },

        // Step navigation - all local, no server calls
        nextStep() {
            if (!this.canProceed) return;

            if (this._currentStep === 'taster_info') {
                this._currentStep = 'bottle_selection';
            } else if (this._currentStep === 'bottle_selection') {
                this._currentStep = 'tasting_form';
            }
        },

        previousStep() {
            if (this._currentStep === 'bottle_selection' && !this.isEventMode) {
                // Only go back to taster_info in non-event mode
                this._currentStep = 'taster_info';
            } else if (this._currentStep === 'tasting_form') {
                this._currentStep = 'bottle_selection';
                // Clear selection when going back to force re-selection
                this.selectedBottle = null;
                this.resetTastingData();
            }
        },

        // ---- Upload tasting card methods ----
        handleCardFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;
            this.cardSelectedFile = file;
            this.cardPreviewUrl = URL.createObjectURL(file);
        },

        clearCardFile() {
            this.cardSelectedFile = null;
            this.cardPreviewUrl = null;
            if (this.$refs.cardFileInput) this.$refs.cardFileInput.value = '';
            this.cardUploadComplete = false;
            this.cardTastingsCount = 0;
        },

        async uploadCardFile() {
            if (!this.cardSelectedFile) return;

            this.cardUploading = true;
            this.cardError = false;
            this.cardUploadComplete = false;

            const formData = new FormData();
            formData.append('file', this.cardSelectedFile);
            if (this.uploadExpectedCount) {
                formData.append('expected_count', this.uploadExpectedCount);
            }

            try {
                const response = await fetch('/api/v1/tastings/upload-card', {
                    method: 'POST',
                    body: formData,
                });

                if (!response.ok) throw new Error('Upload failed');

                const result = await response.json();
                this.cardExtractionId = result.extraction_id;
                this.cardTastingsCount = result.tastings_count || 0;
                this.cardUploadComplete = true;
            } catch (err) {
                this.cardError = true;
                this.cardErrorMessage = err.message || 'Failed to upload tasting card.';
            } finally {
                this.cardUploading = false;
            }
        },

        cancelWizard() {
            if (!confirm('Are you sure you want to cancel? All entered data will be lost.')) {
                return;
            }

            // Just redirect - no server session to clear
            if (this.participantSession && this.participantSession.event_id) {
                window.location.href = `/events/${this.participantSession.event_id}`;
            } else {
                window.location.href = '/bottles';
            }
        },

        async saveTasting() {
            this.saving = true;

            try {
                // Parse comma-separated notes from input fields into arrays
                const parseNotes = (input) => {
                    if (!input?.trim()) return [];
                    return input.split(',').map(n => n.trim()).filter(n => n.length > 0);
                };

                if (this.isWine) {
                    this.tastingData.appearance_notes = parseNotes(this.appearanceNotesInput);
                    this.tastingData.nose_notes = parseNotes(this.aromaNotesInput);
                    this.tastingData.palate_notes = parseNotes(this.tasteNotesInput);
                    this.tastingData.finish_notes = parseNotes(this.aftertasteNotesInput);
                } else {
                    this.tastingData.nose_notes = parseNotes(this.noseNotesInput);
                    this.tastingData.palate_notes = parseNotes(this.palateNotesInput);
                    this.tastingData.finish_notes = parseNotes(this.finishNotesInput);
                }

                // Build the complete save request - no session needed
                const saveRequest = {
                    mode: this.isEventMode ? 'event' : 'obsidian',
                    beverage_type: this.beverageType,
                    taster_name: this.tasterName,
                    tasting_date: this.tastingDate,
                    selected_bottle_path: this.selectedBottle.bottle_path,
                    tasting_data: this.tastingData
                };

                // Add event-specific fields if in event mode
                if (this.isEventMode && this.participantSession) {
                    saveRequest.event_id = this.participantSession.event_id;
                    saveRequest.participant_id = this.participantSession.participant_id;
                }

                // Single POST with all data
                const response = await fetch('/api/v1/manual-tasting/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(saveRequest)
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to save tasting');
                }

                const result = await response.json();

                // Cache preferences for next time
                localStorage.setItem('tasting_taster_name', this.tasterName);
                localStorage.setItem('tasting_beverage_type', this.beverageType);
                if (this.tastingData.place) {
                    localStorage.setItem('tasting_place', this.tastingData.place);
                }

                if (result.event_id) {
                    // Event mode - redirect back to event page
                    alert('Tasting saved successfully!');
                    window.location.href = `/events/${result.event_id}`;
                } else {
                    // Obsidian mode - show file path and redirect to bottles
                    alert(`Tasting saved successfully to ${result.file_path}`);
                    window.location.href = '/bottles';
                }
            } catch (e) {
                alert('Error: ' + (e.message || 'Failed to save tasting'));
            } finally {
                this.saving = false;
            }
        },

        // Bottle search
        debouncedSearch() {
            clearTimeout(this.searchTimeout);
            this.searchTimeout = setTimeout(() => this.searchBottles(), 300);
        },

        async searchBottles() {
            if (!this.searchQuery || this.searchQuery.length < 2) {
                this.searchResults = [];
                return;
            }

            this.searching = true;
            try {
                // Add event_id to search if we're in an event
                let url = `/api/v1/bottles/search?q=${encodeURIComponent(this.searchQuery)}&beverage_type=${this.beverageType}`;
                if (this.participantSession && this.participantSession.event_id) {
                    url += `&event_id=${this.participantSession.event_id}`;
                }

                const response = await fetch(url);
                if (response.ok) {
                    const data = await response.json();
                    this.searchResults = data.results || [];
                }
            } catch (e) {
                console.error('Search failed:', e);
            } finally {
                this.searching = false;
            }
        },

        selectBottle(bottle) {
            // Clear tasting data when selecting a NEW bottle
            // This prevents data from a previous bottle being saved to the new one
            if (this.selectedBottle && this.selectedBottle.bottle_path !== bottle.bottle_path) {
                this.resetTastingData();
            }
            this.selectedBottle = bottle;
            this.showSearchModal = false;
            this.searchQuery = '';
            this.searchResults = [];
        },

        async selectBottleAndContinue(bottle) {
            // Clear tasting data when selecting a NEW bottle
            if (this.selectedBottle && this.selectedBottle.bottle_path !== bottle.bottle_path) {
                this.resetTastingData();
            }
            this.selectedBottle = bottle;
            // Automatically proceed to next step (tasting form)
            await this.nextStep();
        },

        resetTastingData() {
            // Reset tasting data to defaults (preserves place/theme)
            this.tastingData = {
                place: '',
                theme: '',
                days_from_crack: null,
                fill_level: null,
                color: '',
                wine_appearance: 0,
                wine_aroma: 0,
                wine_taste: 0,
                wine_aftertaste: 0,
                wine_overall: 0,
                whiskey_nose: 0,
                whiskey_palate: 0,
                whiskey_finish: 0,
                whiskey_overall: 0,
                appearance_notes: [],
                nose_notes: [],
                palate_notes: [],
                finish_notes: [],
                overall_notes: ''
            };
            // Clear note input fields
            if (typeof this.clearNoteInputs === 'function') {
                this.clearNoteInputs();
            }
        },

        hasBottleBeenTasted(bottle) {
            // Check if this bottle has been tasted by the current participant
            if (!this.participantSession || !this.eventData) return false;

            const participant = this.eventData.participants[this.participantSession.participant_id];
            if (!participant) return false;

            return participant.tastings.some(t => t.bottle_path === bottle.bottle_path);
        },

        async editBottleTasting(bottle) {
            // Load existing tasting data and open form for editing
            if (!this.participantSession || !this.eventData) return;

            const participant = this.eventData.participants[this.participantSession.participant_id];
            if (!participant) return;

            const existingTasting = participant.tastings.find(t => t.bottle_path === bottle.bottle_path);
            if (!existingTasting) return;

            // Select the bottle
            this.selectedBottle = bottle;

            // Load the existing tasting data into the form
            // Unwrap if double-nested (bug fix migration)
            let tastingData = existingTasting.tasting_data;
            if (tastingData && tastingData.tasting_data) {
                tastingData = tastingData.tasting_data;
            }

            // Merge with defaults to ensure all fields exist, especially note arrays
            this.tastingData = {
                place: '',
                theme: '',
                days_from_crack: null,
                fill_level: null,
                color: '',
                wine_appearance: 0,
                wine_aroma: 0,
                wine_taste: 0,
                wine_aftertaste: 0,
                wine_overall: 0,
                whiskey_nose: 0,
                whiskey_palate: 0,
                whiskey_finish: 0,
                whiskey_overall: 0,
                appearance_notes: [],
                nose_notes: [],
                palate_notes: [],
                finish_notes: [],
                overall_notes: '',
                ...tastingData  // Overlay existing data
            };

            // Ensure note arrays are arrays (not null/undefined)
            this.tastingData.appearance_notes = this.tastingData.appearance_notes || [];
            this.tastingData.nose_notes = this.tastingData.nose_notes || [];
            this.tastingData.palate_notes = this.tastingData.palate_notes || [];
            this.tastingData.finish_notes = this.tastingData.finish_notes || [];

            // Clear note input fields
            if (typeof this.clearNoteInputs === 'function') {
                this.clearNoteInputs();
            }

            // Navigate directly to tasting form - no server session needed
            this._currentStep = 'tasting_form';
        }

        // Note management functions are provided by tastingFormMixin
    };
};
