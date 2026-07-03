/**
 * Management page root component (window.managementApp).
 *
 * Extracted from templates/management.html (July 2026) so the logic gets
 * vitest unit coverage (tests/js/management-app.test.js). Attached as a WHOLE
 * factory — it defines live getters (filteredTastings, trComputedAvg,
 * dcFilteredValues); spreading the returned object elsewhere would invoke the
 * getters once and freeze them into static values.
 *
 * Composes three window modules at call time (all soft-guarded, but the page
 * must load them BEFORE this file for full functionality):
 *   - components/bottle-editor-modal.js  (window.bottleEditorModal)
 *   - management/tasting-review.js       (window.tastingReviewModule)
 *   - management/event-create.js         (window.eventCreateModule)
 *
 * NOTE: a retired single-bottle-verify UI (buildBatchReviewUI /
 * buildInlineMetadataSection / verifyBottle / applySelectedUpdates /
 * toggleField and an Alpine-v2 checkbox delegation listener) was removed
 * during extraction — nothing in the markup referenced it and its onclick
 * handlers targeted an Alpine.store('app') that was never registered.
 */

// #CLAUDE_REQ: State/method/getter names here MUST match the Alpine bindings in
//              templates/management.html (x-data="managementApp()"). Rename in
//              both places or the page silently loses functionality.
// #CLAUDE_REQ: Batch endpoints must match web/routes/management/ routes:
//              /api/v1/management/bottles/batch-verify, /api/v1/management/batch/{id}/status,
//              /api/v1/management/bottles/update-fields, /api/v1/management/field-values,
//              /api/v1/management/bulk-rename.

window.managementApp = function() {
    // Import tasting review module (if available)
    const tastingReview = window.tastingReviewModule ? window.tastingReviewModule() : {};
    const tastingReviewState = tastingReview.initState ? tastingReview.initState() : {};

    // Initialize bottle editor modal
    const bottleEditor = window.bottleEditorModal ? window.bottleEditorModal() : {};

    // Import create-event module (state + picker logic — see /static/js/management/event-create.js)
    const eventCreate = window.eventCreateModule ? window.eventCreateModule() : {};
    const eventCreateState = eventCreate.initState ? eventCreate.initState() : {};

    return {
        mode: null,

        // Shared verification state
        verifying: false,
        verificationResult: null,
        approvedFields: {},
        applying: false,
        appliedSuccessfully: false,

        // Batch mode
        batchStarting: false,
        batchId: null,
        batchStatus: { total: 0, completed: 0, with_changes: 0, errors: 0 },
        batchResults: [],
        pendingReviews: [],
        pollInterval: null,
        batchApprovedFields: {},
        batchCollapsedStates: {},
        batchAppliedStates: {},

        // Create event mode (state from external module - see /static/js/management/event-create.js)
        ...eventCreateState,

        // Manage events mode
        managedEvents: [],
        manageEventsLoading: false,
        peekingBottles: {},  // Track which events are showing bottle mapping

        // Bulk import ingredients
        bulkQuery: '',
        bulkParent: '',
        bulkResults: [],
        bulkSearching: false,
        bulkSaving: false,
        bulkError: '',
        bulkSuccess: '',
        bulkIngredientNames: [],

        // Data cleanup mode
        dcTab: 'tastings',
        dcField: 'taster_name',
        dcValues: [],
        dcLoading: false,
        dcSearch: '',
        dcSort: 'count-desc',

        // Toast notifications
        toasts: [],
        toastIdCounter: 0,

        // Bottle editor modal
        bottleEditor: bottleEditor,

        // Tasting review mode state (from external module)
        ...tastingReviewState,

        // Computed property for filtered/sorted tastings
        get filteredTastings() {
            let tastings = this.trAllTastings;

            // Hide hidden tastings unless the toggle is on
            if (!this.trShowHidden) {
                tastings = tastings.filter(t => !t.hidden);
            }

            if (this.trFilterType !== 'all') {
                tastings = tastings.filter(t => t.type === this.trFilterType);
            }
            if (this.trFilterTaster) {
                tastings = tastings.filter(t => t.taster === this.trFilterTaster);
            }
            if (this.trFilterSearch) {
                const q = this.trFilterSearch.toLowerCase();
                tastings = tastings.filter(t => {
                    if (t.bottle_name.toLowerCase().includes(q)) return true;
                    if (t.type === 'cocktail' && Array.isArray(t.bottles_used)) {
                        return t.bottles_used.some(bu =>
                            bu.recipe_ingredient.toLowerCase().includes(q) ||
                            bu.actual_product.toLowerCase().includes(q)
                        );
                    }
                    return false;
                });
            }
            // Type-specific dropdown filters (exact match)
            for (const [key, val] of Object.entries(this.trTypeFilters)) {
                if (val) {
                    tastings = tastings.filter(t => t[key] === val);
                }
            }
            // Type-specific text search filters (partial match)
            for (const [key, val] of Object.entries(this.trTypeFilterSearch)) {
                if (val) {
                    const q = val.toLowerCase();
                    tastings = tastings.filter(t => t[key] && t[key].toLowerCase().includes(q));
                }
            }
            if (this.trFilterMinScore !== '' && this.trFilterMinScore !== null) {
                const min = parseFloat(this.trFilterMinScore);
                tastings = tastings.filter(t => {
                    if (t.total_score === null || t.total_score === undefined) return false;
                    return (t.total_score / t.max_score) * 100 >= min;
                });
            }
            if (this.trFilterMaxScore !== '' && this.trFilterMaxScore !== null) {
                const max = parseFloat(this.trFilterMaxScore);
                tastings = tastings.filter(t => {
                    if (t.total_score === null || t.total_score === undefined) return false;
                    return (t.total_score / t.max_score) * 100 <= max;
                });
            }
            if (this.trFilterDateFrom) {
                tastings = tastings.filter(t => t.date >= this.trFilterDateFrom);
            }
            if (this.trFilterDateTo) {
                tastings = tastings.filter(t => t.date <= this.trFilterDateTo);
            }

            // Sort (nulls always sink to bottom regardless of direction)
            return [...tastings].sort((a, b) => {
                let va, vb;
                if (this.trSortColumn === 'total_score') {
                    va = (a.total_score !== null && a.total_score !== undefined) ? (a.total_score / a.max_score) : null;
                    vb = (b.total_score !== null && b.total_score !== undefined) ? (b.total_score / b.max_score) : null;
                } else {
                    va = a[this.trSortColumn] ?? null;
                    vb = b[this.trSortColumn] ?? null;
                }
                if (va === null && vb === null) return 0;
                if (va === null) return 1;
                if (vb === null) return -1;
                if (typeof va === 'string') va = va.toLowerCase();
                if (typeof vb === 'string') vb = vb.toLowerCase();
                if (va < vb) return this.trSortDir === 'asc' ? -1 : 1;
                if (va > vb) return this.trSortDir === 'asc' ? 1 : -1;
                return 0;
            });
        },

        // Normalized average score for filtered tastings (0–100 scale)
        get trComputedAvg() {
            const tastings = this.filteredTastings;
            const withScores = tastings.filter(t => t.total_score !== null && t.total_score !== undefined);
            if (!withScores.length) return null;
            const avg = withScores.reduce((s, t) => s + (t.total_score / t.max_score) * 100, 0) / withScores.length;
            return avg.toFixed(1);
        },

        async init() {
            // Pre-fill host name from auth identity
            try {
                const resp = await fetch('/api/v1/me');
                if (resp.ok) {
                    const me = await resp.json();
                    if (me.display_name) this.eventHostName = me.display_name;
                }
            } catch (e) { /* ignore */ }
            // Pre-load autocomplete data for bottle editor forms
            if (this.bottleEditor && this.bottleEditor.loadAutocomplete) {
                this.bottleEditor.loadAutocomplete();
            }
        },

        selectMode(m) {
            this.mode = m;
            if (m === 'manage-events') {
                this.loadManagedEvents();
            } else if (m === 'bulk-import') {
                this.loadBulkIngredientNames();
            } else if (m === 'tasting-review') {
                this.loadTastings();
            } else if (m === 'data-cleanup') {
                this.loadCleanupValues();
            }
        },

        async loadCleanupValues() {
            this.dcLoading = true;
            this.dcValues = [];
            this.dcSearch = '';
            try {
                const resp = await fetch(`/api/v1/management/field-values?scope=${this.dcTab}&field=${this.dcField}`);
                if (resp.ok) {
                    const rows = await resp.json();
                    this.dcValues = rows.map(r => ({ ...r, renameInput: '', saving: false }));
                }
            } catch (e) { console.error(e); }
            finally { this.dcLoading = false; }
        },

        get dcFilteredValues() {
            let items = this.dcValues;
            const q = this.dcSearch.trim().toLowerCase();
            if (q) items = items.filter(i => i.value.toLowerCase().includes(q));
            const [by, dir] = this.dcSort.split('-');
            return [...items].sort((a, b) => {
                if (by === 'value') return dir === 'asc' ? a.value.localeCompare(b.value) : b.value.localeCompare(a.value);
                return dir === 'asc' ? a.count - b.count : b.count - a.count;
            });
        },

        dcSelectField(tab, field) {
            this.dcTab = tab;
            this.dcField = field;
            this.loadCleanupValues();
        },

        async dcApplyRename(item) {
            const newValue = (item.renameInput || '').trim();
            if (!newValue || newValue === item.value) return;
            item.saving = true;
            try {
                const resp = await fetch('/api/v1/management/bulk-rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ scope: this.dcTab, field: this.dcField, old_value: item.value, new_value: newValue }),
                });
                if (resp.ok) {
                    const data = await resp.json();
                    this.showToast(`Renamed ${data.updated} record${data.updated !== 1 ? 's' : ''}: "${item.value}" → "${newValue}"`, 'success', 3000);
                    await this.loadCleanupValues();
                } else {
                    const err = await resp.json().catch(() => ({}));
                    this.showToast(err.detail || 'Rename failed', 'error', 4000);
                }
            } catch (e) {
                this.showToast('Rename failed: ' + e.message, 'error', 4000);
            } finally {
                item.saving = false;
            }
        },

        // Bulk import ingredients
        async loadBulkIngredientNames() {
            try {
                const response = await fetch('/api/v1/ingredients?flat=true');
                if (response.ok) {
                    const ingredients = await response.json();
                    this.bulkIngredientNames = ingredients.map(i => i.name);
                }
            } catch (error) {
                console.error('Failed to load ingredient names:', error);
            }
        },

        async doBulkSearch() {
            if (!this.bulkQuery.trim()) return;
            this.bulkSearching = true;
            this.bulkError = '';
            this.bulkSuccess = '';
            this.bulkResults = [];

            try {
                const response = await fetch('/api/v1/ingredients/bulk-search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        query: this.bulkQuery,
                        parent: this.bulkParent || null,
                    })
                });
                if (!response.ok) {
                    const error = await response.json();
                    this.bulkError = error.detail || 'Search failed';
                    return;
                }
                const data = await response.json();
                this.bulkResults = data.results || [];
                if (this.bulkResults.length === 0) {
                    this.bulkError = 'No results found. Try a different query.';
                }
            } catch (error) {
                this.bulkError = error.message;
            } finally {
                this.bulkSearching = false;
            }
        },

        async doBulkSave() {
            const selected = this.bulkResults.filter(r => r.selected);
            if (selected.length === 0) {
                this.bulkError = 'No items selected';
                return;
            }

            this.bulkSaving = true;
            this.bulkError = '';
            this.bulkSuccess = '';

            try {
                const response = await fetch('/api/v1/ingredients/bulk-save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        parent: this.bulkParent || null,
                        ingredients: this.bulkResults,
                    })
                });
                if (!response.ok) {
                    const error = await response.json();
                    this.bulkError = error.detail || 'Save failed';
                    return;
                }
                const data = await response.json();
                const savedCount = data.saved ? data.saved.length : 0;
                const skippedCount = data.skipped ? data.skipped.length : 0;
                this.bulkSuccess = `Saved ${savedCount} ingredients` + (skippedCount > 0 ? `, skipped ${skippedCount}` : '');
                this.bulkResults = [];
                // Refresh ingredient names for parent autocomplete
                await this.loadBulkIngredientNames();
            } catch (error) {
                this.bulkError = error.message;
            } finally {
                this.bulkSaving = false;
            }
        },

        // Toast notification system
        showToast(message, type = 'success', duration = 2000) {
            const id = ++this.toastIdCounter;
            const toast = { id, message, type };
            this.toasts.push(toast);

            // Auto-dismiss after duration
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, duration);
        },

        // Tasting review functions (from external module - see /static/js/management/tasting-review.js)
        ...tastingReview,

        // ============================================================================
        // Batch Verification and Event Management Functions
        // ============================================================================

        initBatchResult(result) {
            // Initialize all change checkboxes as checked
            if (result.changes) {
                for (const field in result.changes) {
                    const fieldKey = `${result.bottle_index}_${field}`;
                    if (!(fieldKey in this.batchApprovedFields)) {
                        this.batchApprovedFields[fieldKey] = true;
                    }
                }
            }
            // Initialize collapsed and applied states
            if (!(result.bottle_index in this.batchCollapsedStates)) {
                this.batchCollapsedStates[result.bottle_index] = false;
            }
            if (!(result.bottle_index in this.batchAppliedStates)) {
                this.batchAppliedStates[result.bottle_index] = false;
            }
        },

        getMetadataFields(bottle) {
            const fields = [
                { key: 'producer', label: 'Producer/Distiller' },
                { key: 'name', label: 'Name' },
                { key: 'year', label: 'Year/Vintage' },
                { key: 'beverage_type', label: 'Beverage Type' },
                { key: 'country', label: 'Country' },
                { key: 'region', label: 'Region' },
                { key: 'abv', label: 'ABV' }
            ];

            if (bottle.type === 'wine') {
                fields.push({ key: 'variety', label: 'Variety' });
                fields.push({ key: 'vineyard', label: 'Vineyard' });
            } else {
                fields.push({ key: 'age_statement', label: 'Age Statement' });
                fields.push({ key: 'proof', label: 'Proof' });
                fields.push({ key: 'mash_bill', label: 'Mash Bill' });
                fields.push({ key: 'barrel_type', label: 'Barrel Type' });
            }

            // Additional common fields
            fields.push({ key: 'price', label: 'Price' });
            fields.push({ key: 'purchase_source', label: 'Where Purchased' });
            fields.push({ key: 'inventory', label: 'Inventory Count' });

            return fields;
        },

        async applyBatchUpdate(result, idx) {
            // Get only approved fields from this result's changes
            const updates = {};
            for (const field in result.changes) {
                const fieldKey = `${result.bottle_index}_${field}`;
                // Only include if checkbox is checked (true)
                if (this.batchApprovedFields[fieldKey] === true) {
                    updates[field] = result.changes[field].new;
                }
            }

            if (Object.keys(updates).length === 0) {
                alert('No changes selected to apply');
                return;
            }

            this.applying = true;

            try {
                const response = await fetch('/api/v1/management/bottles/update-fields', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: result.original,
                        updates: updates
                    })
                }).catch(err => {
                    console.error('Fetch error:', err);
                    throw err;
                });

                let responseData;
                try {
                    responseData = await response.json();
                } catch (jsonError) {
                    console.error('Failed to parse JSON:', jsonError);
                    const text = await response.text();
                    console.error('Response text:', text);
                    throw new Error('Invalid response from server');
                }

                if (response.ok) {
                    this.applying = false;
                    this.batchAppliedStates[result.bottle_index] = true;

                    // Auto-collapse after brief success message (800ms)
                    setTimeout(() => {
                        this.batchCollapsedStates[result.bottle_index] = true;
                    }, 800);
                } else {
                    throw new Error(responseData.detail || 'Update failed');
                }
            } catch (error) {
                console.error('Update failed:', error);
                alert('Update failed: ' + error.message);
                this.applying = false;
            }
        },

        async startBatchVerification() {
            this.batchStarting = true;
            try {
                const response = await fetch('/api/v1/management/bottles/batch-verify', {
                    method: 'POST'
                });
                const data = await response.json();
                this.batchId = data.batch_id;
                this.batchStatus = data.status;

                // Start polling for updates
                this.pollInterval = setInterval(() => this.pollBatchStatus(), 2000);
            } catch (error) {
                console.error('Failed to start batch:', error);
                alert('Failed to start batch: ' + error.message);
            } finally {
                this.batchStarting = false;
            }
        },

        async pollBatchStatus() {
            if (!this.batchId) return;

            try {
                const response = await fetch(`/api/v1/management/batch/${this.batchId}/status`);
                const data = await response.json();
                this.batchStatus = data.status;
                this.batchResults = data.results;

                // Update pending reviews (only bottles with changes that haven't been reviewed)
                this.pendingReviews = this.batchResults.filter(r =>
                    r.status === 'completed' && r.has_changes && !r.reviewed
                );

                // Initialize verification result for first pending
                if (this.pendingReviews.length > 0 && !this.verificationResult) {
                    const first = this.pendingReviews[0];
                    this.verificationResult = {
                        original: first.original,
                        updated: first.updated,
                        changes: first.changes,
                        metadata: first.metadata
                    };

                    // Initialize approved fields
                    this.approvedFields = {};
                    for (const field in first.changes) {
                        this.approvedFields[field] = true;
                    }
                }

                // Stop polling if complete
                if (data.status.status === 'complete') {
                    clearInterval(this.pollInterval);
                }
            } catch (error) {
                console.error('Failed to poll status:', error);
            }
        },

        exitBatch() {
            if (this.pollInterval) {
                clearInterval(this.pollInterval);
            }
            this.batchId = null;
            this.batchStatus = { total: 0, completed: 0, with_changes: 0, errors: 0 };
            this.batchResults = [];
            this.pendingReviews = [];
            this.verificationResult = null;
            this.mode = null;
        },

        // Create event functions (from external module - see /static/js/management/event-create.js)
        ...eventCreate,

        // Manage Events Functions
        async loadManagedEvents() {
            this.manageEventsLoading = true;
            try {
                const response = await fetch('/api/v1/events');
                if (!response.ok) {
                    throw new Error('Failed to load events');
                }
                this.managedEvents = await response.json();
            } catch (error) {
                console.error('Failed to load events:', error);
                alert('Failed to load events: ' + error.message);
            } finally {
                this.manageEventsLoading = false;
            }
        },

        async revealEventBottles(eventId) {
            if (!confirm('Reveal all bottle names to participants? This cannot be undone.')) return;

            try {
                const response = await fetch(`/api/v1/events/${eventId}/reveal`, {
                    method: 'PUT'
                });

                if (!response.ok) {
                    throw new Error('Failed to reveal bottles');
                }

                await this.loadManagedEvents();
                this.showToast('Bottles revealed successfully!');
            } catch (error) {
                console.error('Failed to reveal bottles:', error);
                alert('Failed to reveal bottles: ' + error.message);
            }
        },

        async closeEventFromManagement(eventId) {
            if (!confirm('Close this event? No more tastings will be allowed.')) return;

            try {
                const response = await fetch(`/api/v1/events/${eventId}/close`, {
                    method: 'PUT'
                });

                if (!response.ok) {
                    throw new Error('Failed to close event');
                }

                await this.loadManagedEvents();
                this.showToast('Event closed successfully!');
            } catch (error) {
                console.error('Failed to close event:', error);
                alert('Failed to close event: ' + error.message);
            }
        },

        async deleteEventFromManagement(eventId) {
            if (!confirm('Delete this event permanently? This cannot be undone.')) return;

            try {
                const response = await fetch(`/api/v1/events/${eventId}`, {
                    method: 'DELETE'
                });

                if (!response.ok) {
                    throw new Error('Failed to delete event');
                }

                await this.loadManagedEvents();
                this.showToast('Event deleted successfully!');
            } catch (error) {
                console.error('Failed to delete event:', error);
                alert('Failed to delete event: ' + error.message);
            }
        },
    };
};
