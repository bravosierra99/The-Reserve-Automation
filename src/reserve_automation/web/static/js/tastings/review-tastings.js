/**
 * Tasting Review page component (window.tastingReview).
 *
 * Extracted from templates/review_tastings.html (July 2026) so the logic gets
 * vitest unit coverage (tests/js/review-tastings.test.js). Attached as a WHOLE
 * factory — it defines live getters (currentTasting, tasting, isWine,
 * computedWineScore, computed100ptScore, computedWhiskeyScore); spreading the
 * returned object elsewhere would invoke the getters once and freeze them into
 * static values.
 *
 * The page drives the one-at-a-time review flow for tastings extracted from an
 * uploaded tasting card: load session, edit tasting data, match to a vault
 * bottle (candidates + debounced search modal), approve/skip each tasting, or
 * reject the whole batch.
 *
 * Load order: components/tasting-form-mixin.js must load first (this factory
 * merges it at call time). The template must also set window.PAGE_DATA
 * (extractionId) in a tiny inline bootstrap BEFORE Alpine initializes — the
 * value is Jinja-rendered and cannot live in this static file.
 */
// #CLAUDE_REQ: State keys, method names, and getters here MUST match the Alpine
// bindings in templates/review_tastings.html (x-data="tastingReview()",
// x-init="loadSession()") AND the shared component
// templates/components/tasting_scores_form.html (which expects `tasting`,
// `isWine`, computed*Score, and the tastingFormMixin note methods/inputs).
// #CLAUDE_REQ: Endpoints must match web/routes/tastings.py —
// GET  /api/v1/tastings/{extraction_id}            (session + stats + current_index)
// PUT  /api/v1/tastings/{extraction_id}/{index}    ({tasting_data})
// POST /api/v1/tastings/{extraction_id}/{index}/match ({bottle_path} → duplicate_warning)
// POST /api/v1/tastings/{extraction_id}/{index}/approve (→ stats)
// POST /api/v1/tastings/{extraction_id}/{index}/skip    (→ stats)
// POST /api/v1/tastings/{extraction_id}/reject-all
// and web/routes/bottles.py — GET /api/v1/bottles/search?q=&beverage_type=&limit=20 (→ {results}).
// #CLAUDE_REQ: extractionId is read from window.PAGE_DATA.extractionId, set by an
// inline bootstrap in templates/review_tastings.html ({{ extraction_id | tojson }}).

window.tastingReview = function() {
    const extractionId = (window.PAGE_DATA || {}).extractionId || '';

    // Merge in the tasting form mixin for shared note management
    const mixin = typeof tastingFormMixin === 'function' ? tastingFormMixin() : {};

    return {
        // Include mixin properties
        ...mixin,

        extractionId,
        loading: true,
        error: false,
        errorMessage: '',
        session: null,
        currentIndex: 0,
        stats: { approved: 0, skipped: 0, remaining: 0, all_done: false },
        searchQuery: '',
        searchResults: [],
        searching: false,
        showSearchModal: false,
        searchTimeout: null,
        approving: false,
        skipping: false,
        // Note: the event-context banner (session?.event_id) was removed — upload sessions never carry event_id (see routes/upload.py TODO); restoring it requires API support.
        participantSession: null,  // Store event session info (used only to auto-fill taster_name)

        get currentTasting() {
            if (!this.session?.tastings) return null;
            return this.session.tastings[this.currentIndex];
        },

        // Getter for shared component compatibility (component expects 'tasting')
        get tasting() {
            return this.currentTasting?.tasting_data || {};
        },

        // Required by shared component
        get isWine() {
            return this.session?.template_type === 'aws_wine';
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

        // Called by shared component when tasting data changes
        onTastingChange() {
            this.saveTastingData();
        },

        async loadSession() {
            try {
                const response = await fetch(`/api/v1/tastings/${this.extractionId}`);
                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.detail || 'Failed to load session');
                }
                const data = await response.json();
                this.session = data;
                this.currentIndex = data.current_index || 0;
                this.stats = data.stats || { approved: 0, skipped: 0, remaining: 0, all_done: false };

                // Auto-fill taster name from participant session if available
                this.participantSession = this.getParticipantSession();
                if (this.participantSession && this.participantSession.participant_name) {
                    // Fill all tastings with the participant name
                    this.session.tastings.forEach(tasting => {
                        if (tasting.tasting_data && !tasting.tasting_data.taster_name) {
                            tasting.tasting_data.taster_name = this.participantSession.participant_name;
                        }
                    });
                }

                // Clear note inputs when loading
                if (typeof this.clearNoteInputs === 'function') {
                    this.clearNoteInputs();
                }
                this.loading = false;
            } catch (err) {
                this.error = true;
                this.errorMessage = err.message || 'Failed to load tasting session';
                this.loading = false;
            }
        },

        getParticipantSession() {
            const cookies = document.cookie.split(';').reduce((acc, cookie) => {
                const [key, value] = cookie.trim().split('=');
                acc[key] = value;
                return acc;
            }, {});

            if (cookies.participant_sessions) {
                try {
                    const allSessions = JSON.parse(decodeURIComponent(cookies.participant_sessions));
                    // Review page doesn't have event context
                    // Only auto-fill if user is in exactly one event
                    const eventIds = Object.keys(allSessions);
                    if (eventIds.length === 1) {
                        // Only participant_name is consumed (taster auto-fill);
                        // approve reads event context server-side, not from us.
                        return {
                            participant_name: allSessions[eventIds[0]].participant_name
                        };
                    }
                    // Multiple events - can't determine which to use
                    return null;
                } catch (e) {
                    console.error('Failed to parse participant_sessions cookie:', e);
                    return null;
                }
            }
            return null;
        },

        prevTasting() {
            if (this.currentIndex > 0) {
                this.currentIndex--;
                this.searchResults = [];
                this.searchQuery = '';
                if (typeof this.clearNoteInputs === 'function') this.clearNoteInputs();
            }
        },

        nextTasting() {
            if (this.currentIndex < this.session.actual_count - 1) {
                this.currentIndex++;
                this.searchResults = [];
                this.searchQuery = '';
                if (typeof this.clearNoteInputs === 'function') this.clearNoteInputs();
            }
        },

        goToTasting(index) {
            this.currentIndex = index;
            this.searchResults = [];
            this.searchQuery = '';
            if (typeof this.clearNoteInputs === 'function') this.clearNoteInputs();
        },

        async saveTastingData() {
            if (!this.currentTasting) return;

            try {
                await fetch(`/api/v1/tastings/${this.extractionId}/${this.currentIndex}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tasting_data: this.currentTasting.tasting_data })
                });
            } catch (err) {
                console.error('Failed to save tasting data:', err);
            }
        },

        async selectMatch(bottlePath) {
            try {
                const response = await fetch(`/api/v1/tastings/${this.extractionId}/${this.currentIndex}/match`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bottle_path: bottlePath })
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    console.error('Match selection failed:', response.status, errorText);
                    throw new Error(`HTTP ${response.status}: ${errorText}`);
                }

                const data = await response.json();

                // Force Alpine reactivity by reassigning the tasting object
                const updatedTasting = {
                    ...this.session.tastings[this.currentIndex],
                    selected_match: bottlePath,
                    status: 'matched',
                    duplicate_warning: data.duplicate_warning
                };

                // Replace the tasting in the array
                this.session.tastings[this.currentIndex] = updatedTasting;

                // Force reactivity by reassigning the entire tastings array
                this.session.tastings = [...this.session.tastings];

                this.searchResults = [];
            } catch (err) {
                console.error('Failed to select match:', err.message);
                alert('Failed to select match: ' + err.message);
            }
        },

        async selectMatchFromSearch(bottlePath) {
            await this.selectMatch(bottlePath);
            this.showSearchModal = false;
            this.searchQuery = '';
            this.searchResults = [];
        },

        clearMatch() {
            // Force Alpine reactivity by reassigning the tasting object
            const updatedTasting = {
                ...this.session.tastings[this.currentIndex],
                selected_match: null,
                status: 'extracted'
            };

            // Replace the tasting in the array
            this.session.tastings[this.currentIndex] = updatedTasting;

            // Force reactivity by reassigning the entire tastings array
            this.session.tastings = [...this.session.tastings];
        },

        getSelectedMatchThumbnail() {
            const match = this.currentTasting?.match_candidates?.find(
                c => c.bottle_path === this.currentTasting?.selected_match
            );
            return match?.thumbnail_url || null;
        },

        getSelectedMatchName() {
            const match = this.currentTasting?.match_candidates?.find(
                c => c.bottle_path === this.currentTasting?.selected_match
            );
            return match?.bottle_name || this.currentTasting?.selected_match;
        },

        getSelectedMatchConfidence() {
            const match = this.currentTasting?.match_candidates?.find(
                c => c.bottle_path === this.currentTasting?.selected_match
            );
            return match?.confidence || 0;
        },

        debouncedSearch() {
            // Clear existing timeout
            if (this.searchTimeout) {
                clearTimeout(this.searchTimeout);
            }

            // If query is empty, clear results
            if (!this.searchQuery.trim()) {
                this.searchResults = [];
                this.searching = false;
                return;
            }

            // Set new timeout to search after 100ms of no typing
            this.searching = true;
            this.searchTimeout = setTimeout(() => {
                this.searchBottles();
            }, 100);
        },

        async searchBottles() {
            if (!this.searchQuery.trim()) {
                this.searchResults = [];
                this.searching = false;
                return;
            }

            try {
                const url = `/api/v1/bottles/search?q=${encodeURIComponent(this.searchQuery)}&beverage_type=${this.session.beverage_type}&limit=20`;
                const response = await fetch(url, {
                    credentials: 'same-origin'
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    console.error('Search failed:', response.status, errorText);
                    throw new Error(`Search failed: ${response.status} - ${errorText}`);
                }

                const data = await response.json();
                this.searchResults = data.results || [];
            } catch (err) {
                console.error('Search error:', err);
                alert('Search failed: ' + err.message);
                this.searchResults = [];
            } finally {
                this.searching = false;
            }
        },

        async approveTasting() {
            if (!this.currentTasting?.selected_match) return;

            this.approving = true;
            try {
                const response = await fetch(`/api/v1/tastings/${this.extractionId}/${this.currentIndex}/approve`, {
                    method: 'POST'
                });

                if (!response.ok) {
                    const data = await response.json();
                    throw new Error(data.detail || 'Failed to approve');
                }

                const data = await response.json();
                this.session.tastings[this.currentIndex].status = 'approved';
                this.stats = data.stats;

                // Move to next unapproved tasting
                if (!this.stats.all_done) {
                    this.findNextPending();
                }
            } catch (err) {
                alert('Failed to approve: ' + err.message);
            } finally {
                this.approving = false;
            }
        },

        async skipTasting() {
            this.skipping = true;
            try {
                const response = await fetch(`/api/v1/tastings/${this.extractionId}/${this.currentIndex}/skip`, {
                    method: 'POST'
                });

                if (!response.ok) throw new Error('Failed to skip');

                const data = await response.json();
                this.session.tastings[this.currentIndex].status = 'skipped';
                this.stats = data.stats;

                // Move to next unapproved tasting
                if (!this.stats.all_done) {
                    this.findNextPending();
                }
            } catch (err) {
                alert('Failed to skip: ' + err.message);
            } finally {
                this.skipping = false;
            }
        },

        findNextPending() {
            for (let i = 0; i < this.session.tastings.length; i++) {
                const t = this.session.tastings[i];
                if (t.status !== 'approved' && t.status !== 'skipped') {
                    this.currentIndex = i;
                    return;
                }
            }
        },

        async rejectAll() {
            if (!confirm('Discard all tastings? This cannot be undone.')) return;

            try {
                const response = await fetch(`/api/v1/tastings/${this.extractionId}/reject-all`, {
                    method: 'POST'
                });

                if (!response.ok) throw new Error('Failed to reject');

                window.location.href = '/upload';
            } catch (err) {
                alert('Failed to reject: ' + err.message);
            }
        }
    };
};
