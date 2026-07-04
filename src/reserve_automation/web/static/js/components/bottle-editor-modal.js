/**
 * Unified Bottle Editor Modal Component
 *
 * Works in two modes:
 * - Management mode: Loads bottle from vault, saves immediately
 * - Upload mode: Works with client-side data, saves with duplicate detection
 */

window.bottleEditorModal = function() {
    return {
        // Modal state
        isOpen: false,
        mode: null,           // 'management' or 'upload'
        readOnly: false,      // When true, hides edit controls (for non-admin users)

        // Bottle data
        bottle: null,         // Reactive bottle data
        originalBottle: null, // For reset functionality

        // Context-specific state
        bottleId: null,          // For management mode (opaque bottle ID)
        uploadId: null,          // For upload mode
        manifestContext: null,   // { bottles: [...], currentIndex: 0 }
        _onSaveCallback: null,   // Called after successful save (manifest panel integration)
        _onSkipCallback: null,   // Called after skip in duplicate dialog (manifest panel integration)

        // Label operations
        tempLabelPath: null,
        labelSearchResults: [],
        labelDownloadedOriginal: null,
        labelDownloadedCropped: null,
        labelCropPreview: null,

        // Cropper instances
        cropperInstance: null,
        cropperDownloadedInstance: null,
        manualCropActive: false,
        manualCropImageSrc: null,
        manualCropDownloadedActive: false,
        manualCropDownloadedSrc: null,

        // Metadata editing
        editableBottle: {},

        // Enrichment/verification
        searchResult: null,
        verifying: false,
        verifyingProgress: '',  // Progress message during verification
        verifyingTaskId: null,  // Current verification task ID
        approvedChanges: {},
        hasChanges: false,  // Simple boolean for x-show reactivity

        // Duplicate detection (upload mode)
        duplicates: [],
        duplicateAction: null,  // Radio button value: 'save_new', 'replace', or 'skip' (set after duplicate dialog shown)
        selectedDuplicate: null,  // Which duplicate is selected (bottle ID)
        showDuplicateDialog: false,
        selectedDuplicateAction: null, // 'new', 'replace', 'skip'
        // Manual duplicate override: when fuzzy matching surfaces nothing (or the
        // wrong thing), the user can search the whole collection and pick the real
        // bottle to replace. Feeds the SAME selectedDuplicate/replace path.
        manualMatchQuery: '',
        manualMatchResults: [],
        manualMatchSearching: false,

        // Tasting summary (management mode)
        tastingSummary: null,

        // Tasting list/detail view (management mode)
        tastingsList: [],           // Full list of tastings
        showTastingsList: false,    // Whether list is expanded
        selectedTasting: null,      // Currently selected tasting for detail view
        loadingTastings: false,     // Loading state

        // Autocomplete data (populated once per page load)
        acData: {
            producer: [], region: [], country: [], variety: [],
            beverage_type: [], style: [], vineyard: [], purchase_source: [],
        },
        _acLoaded: false,

        // UI state
        saving: false,
        saveSuccess: false,
        savedBottleId: null,     // Set after single-bottle upload save; enables post-save nav buttons
        labelActionInProgress: false,
        currentLabelTimestamp: Date.now(),

        async loadAutocomplete() {
            if (this._acLoaded) return;
            try {
                const fields = Object.keys(this.acData);
                const results = await Promise.all(
                    fields.map(f => fetch(`/api/v1/autocomplete/bottles/${f}`).then(r => r.ok ? r.json() : []))
                );
                fields.forEach((f, i) => { this.acData[f] = results[i]; });
                this._acLoaded = true;
            } catch (e) {
                console.warn('Autocomplete load failed:', e);
            }
        },

        /**
         * Open modal in management mode (existing bottle from vault)
         */
        async openManagement(bottle, readOnly = false) {
            console.log('Opening management modal with bottle:', bottle, 'readOnly:', readOnly);
            this.mode = 'management';
            this.readOnly = readOnly;
            this.bottle = { ...bottle };
            this.originalBottle = { ...bottle };
            this.bottleId = bottle.id;
            console.log('Set bottleId to:', this.bottleId);
            this.uploadId = null;
            this.manifestContext = null;

            // Initialize editable bottle data
            this.initializeEditableBottle();

            // Load tasting summary
            await this.loadTastingSummary();

            // Open modal
            this.isOpen = true;
            window.modalScrollLock(true);

            // Reset state
            this.resetState();
        },

        /**
         * Open modal in upload mode (new bottle, client-side data)
         */
        async openUpload(bottle, uploadId, manifestContext = null, preloadedEnrichResult = null) {
            console.log('openUpload called with uploadId:', uploadId);
            this.mode = 'upload';
            this.bottle = { ...bottle };
            this.originalBottle = { ...bottle };
            this.uploadId = uploadId;
            console.log('Set this.uploadId to:', this.uploadId);
            this.manifestContext = manifestContext;
            this.bottleId = null;

            // Initialize editable bottle data
            this.initializeEditableBottle();

            // Open modal
            this.isOpen = true;
            window.modalScrollLock(true);

            // Reset state
            this.resetState();

            // Pre-load enrichment result if provided (manifest panel enrichment)
            if (preloadedEnrichResult) {
                this.searchResult = preloadedEnrichResult;
                this.hasChanges = preloadedEnrichResult.changes && Object.keys(preloadedEnrichResult.changes).length > 0;
                this.approvedChanges = {};
            }

            console.log('After opening, mode:', this.mode, 'uploadId:', this.uploadId);

            // AUTOMATICALLY check for duplicates in upload mode (don't await to avoid blocking modal)
            this.manualCheckDuplicates().catch(err => {
                console.error('Auto duplicate check failed:', err);
            });
        },

        /**
         * Initialize editable bottle fields from bottle data
         */
        initializeEditableBottle() {
            const b = this.bottle;
            const isWine = b.type === 'wine';

            this.editableBottle = {
                producer: b.producer || '',
                name: b.name || '',
                year: b.year || '',
                beverage_type: b.beverage_type || '',

                // Common fields
                price: b.price || '',
                inventory: b.inventory || '',
                purchase_source: b.purchase_source || '',
                purchase_link: b.purchase_link || '',

                // Wine-specific
                ...(isWine ? {
                    country: b.country || '',
                    region: b.region || '',
                    variety: b.variety || '',
                    vineyard: b.vineyard || '',
                    abv: b.abv || '',
                    style: b.style || '',
                    points: b.points || '',
                    stars: b.stars || '',
                    buy: b.buy || '',
                    value_for_money: b.value_for_money || ''
                } : {}),

                // Whiskey-specific
                ...(!isWine ? {
                    region: b.region || '',
                    age_statement: b.age_statement || '',
                    proof: b.proof || '',
                    mash_bill: b.mash_bill || '',
                    barrel_type: b.barrel_type || '',
                    batch_number: b.batch_number || '',
                    bottle_number: b.bottle_number || '',
                    bottle_opened_date: b.bottle_opened_date || ''
                } : {})
            };
        },

        /**
         * Reset transient state (errors, search results, etc.)
         */
        resetState() {
            this.searchResult = null;
            this.verifying = false;
            this.approvedChanges = {};
            this._onSaveCallback = null;
            this._onSkipCallback = null;
            this.saving = false;
            this.saveSuccess = false;
            this.savedBottleId = null;
            this.labelActionInProgress = false;
            this.labelSearchResults = [];
            this.duplicates = [];
            this.duplicateAction = null;  // Reset to null so first save attempt checks for duplicates
            this.selectedDuplicate = null;
            this.showDuplicateDialog = false;
            this.manualMatchQuery = '';
            this.manualMatchResults = [];
            this.manualMatchSearching = false;
            // Reset tasting list state
            this.tastingsList = [];
            this.showTastingsList = false;
            this.selectedTasting = null;
            this.loadingTastings = false;
            this.cancelManualCrop();
            this.cancelManualCropDownloaded();
        },

        /**
         * Close modal
         */
        close() {
            // Cleanup cropper instances
            this.cancelManualCrop();
            this.cancelManualCropDownloaded();

            this.isOpen = false;
            window.modalScrollLock(false);

            // Clear state after animation
            setTimeout(() => {
                this.mode = null;
                this.bottle = null;
                this.originalBottle = null;
                this.bottleId = null;
                this.uploadId = null;
                this.manifestContext = null;
                this.editableBottle = {};
                this.resetState();
            }, 300);
        },

        /**
         * After a single-bottle upload save, navigate to manual tasting with the bottle pre-selected
         */
        startTasting() {
            const bottle = this.bottle;
            const id = this.savedBottleId;
            if (!bottle || !id) return;

            const preselect = {
                bottle_path: id,
                bottle_name: `${bottle.producer} - ${bottle.name}`,
                producer: bottle.producer,
                beverage_type: bottle.type,
                thumbnail_url: `/api/v1/labels/thumbnail?id=${encodeURIComponent(id)}&size=200`,
            };
            sessionStorage.setItem('preselect_bottle', JSON.stringify(preselect));
            window.location.href = '/manual-tasting';
        },

        /**
         * Save bottle (context-aware)
         */
        async save() {
            if (this.mode === 'upload') {
                await this.saveUpload();
            } else {
                await this.saveManagement();
            }
        },

        /**
         * Save for management mode (direct to vault)
         */
        async saveManagement() {
            this.saving = true;
            this.saveSuccess = false;

            try {
                // Update bottle object with editable fields
                Object.assign(this.bottle, this.editableBottle);

                // Clean bottle data - convert empty strings to null for numeric fields
                const cleanBottle = { ...this.bottle };
                if (cleanBottle.year === '') cleanBottle.year = null;
                if (cleanBottle.price === '') cleanBottle.price = null;
                if (cleanBottle.inventory === '') cleanBottle.inventory = null;
                if (cleanBottle.abv === '') cleanBottle.abv = null;
                if (cleanBottle.proof === '') cleanBottle.proof = null;

                const response = await fetch('/api/v1/management/bottles/update-fields', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: cleanBottle,
                        changes: this.approvedChanges
                    })
                });

                if (!response.ok) {
                    throw new Error('Failed to save bottle');
                }

                this.saveSuccess = true;

                // Show success toast
                this.showToast('✓ Bottle saved successfully!', 'success');

                // Wait briefly for user to see the success state, then close
                setTimeout(() => {
                    this.close();

                    // Reload the page to show updated bottle in grid
                    window.location.reload();
                }, 800);

            } catch (error) {
                console.error('Save failed:', error);
                this.showToast('✗ Save failed: ' + error.message, 'error');
            } finally {
                this.saving = false;
            }
        },

        /**
         * Save for upload mode (with duplicate detection)
         */
        async saveUpload() {
            // Check duplicate action if duplicates exist
            if (this.duplicates && this.duplicates.length > 0) {
                if (this.duplicateAction === 'skip') {
                    // Skip this bottle
                    if (this.manifestContext) {
                        await this.nextBottle();
                    } else {
                        if (this._onSkipCallback) { this._onSkipCallback(); this._onSkipCallback = null; }
                        this.close();
                    }
                    return;
                }
            }

            this.saving = true;

            try {
                // Update bottle object with editable fields
                Object.assign(this.bottle, this.editableBottle);

                // Clean bottle data - convert empty strings to null for numeric fields
                const cleanBottle = { ...this.bottle };
                if (cleanBottle.year === '') cleanBottle.year = null;
                if (cleanBottle.price === '') cleanBottle.price = null;
                if (cleanBottle.inventory === '') cleanBottle.inventory = null;
                if (cleanBottle.abv === '') cleanBottle.abv = null;
                if (cleanBottle.proof === '') cleanBottle.proof = null;

                // CRITICAL: Ensure type field is present for duplicate detection
                // The type field (wine/whiskey/etc) determines which vault directory to search
                if (!cleanBottle.type) {
                    console.error('Missing type field in bottle data! Cannot save without type.');
                    console.error('Bottle data:', cleanBottle);
                    throw new Error('Missing bottle type field');
                }

                console.log('Saving bottle with type:', cleanBottle.type);
                console.log('Duplicate action:', this.duplicateAction);
                console.log('Selected duplicate:', this.selectedDuplicate);

                // Determine force_save and replace_bottle_id based on radio button selection
                let force_save = false;
                let replace_bottle_id = null;

                if (this.duplicateAction === 'save_new') {
                    force_save = true;
                } else if (this.duplicateAction === 'replace' && this.selectedDuplicate) {
                    replace_bottle_id = this.selectedDuplicate;
                }

                const response = await fetch('/api/v1/bottles/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: cleanBottle,
                        upload_id: this.uploadId,
                        temp_label_path: this.tempLabelPath,
                        force_save: force_save,
                        replace_bottle_id: replace_bottle_id
                    })
                });

                const result = await response.json();

                if (result.status === 'duplicate_found') {
                    // Show duplicate dialog, pre-selecting "Save as New" as the safest default
                    this.duplicates = result.duplicates;
                    this.showDuplicateDialog = true;
                    this.duplicateAction = 'save_new';  // Pre-select radio button
                    this.saving = false;
                    return;
                }

                if (!response.ok) {
                    throw new Error(result.error || 'Failed to save bottle');
                }

                // Success!
                this.showToast('✓ Bottle saved to vault!', 'success');

                // Handle manifest navigation
                if (this.manifestContext) {
                    await this.nextBottle();
                } else {
                    // Fire save callback if set (manifest panel integration)
                    if (this._onSaveCallback) {
                        this._onSaveCallback(this.bottle);
                        this._onSaveCallback = null;
                        // advanceToNextReady (called from callback) handles close and navigation
                    } else {
                        // Show post-save actions so user can go straight to tasting
                        this.savedBottleId = result.id;
                    }
                }

            } catch (error) {
                console.error('Save failed:', error);
                this.showToast('✗ Save failed: ' + error.message, 'error');
            } finally {
                this.saving = false;
            }
        },

        /**
         * Handle duplicate resolution
         */
        async handleDuplicateResolution(action, duplicateBottleId = null) {
            console.log('🔧 handleDuplicateResolution called:', { action, duplicateBottleId });
            this.selectedDuplicateAction = action;

            if (action === 'skip') {
                console.log('🔧 Skip action - closing dialog');
                this.showDuplicateDialog = false;
                if (this.manifestContext) {
                    await this.nextBottle();
                } else {
                    if (this._onSkipCallback) { this._onSkipCallback(); this._onSkipCallback = null; }
                    this.close();
                }
                return;
            }

            console.log('🔧 Setting saving = true');
            this.saving = true;

            try {
                // Update bottle object with editable fields (same as saveUpload/saveManagement)
                Object.assign(this.bottle, this.editableBottle);

                // Clean bottle data - convert empty strings to null for numeric fields
                const cleanBottle = { ...this.bottle };
                if (cleanBottle.year === '') cleanBottle.year = null;
                if (cleanBottle.price === '') cleanBottle.price = null;
                if (cleanBottle.inventory === '') cleanBottle.inventory = null;
                if (cleanBottle.abv === '') cleanBottle.abv = null;
                if (cleanBottle.proof === '') cleanBottle.proof = null;

                const requestBody = {
                    bottle: cleanBottle,
                    upload_id: this.uploadId,
                    temp_label_path: this.tempLabelPath,
                    force_save: action === 'new',
                    replace_bottle_id: action === 'replace' ? duplicateBottleId : null
                };

                console.log('🔧 Sending save request with:', {
                    action,
                    force_save: requestBody.force_save,
                    replace_bottle_id: requestBody.replace_bottle_id,
                    upload_id: requestBody.upload_id
                });

                const response = await fetch('/api/v1/bottles/save', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(requestBody)
                });

                const result = await response.json();

                if (!response.ok) {
                    throw new Error(result.error || 'Failed to save bottle');
                }

                this.showToast(action === 'replace' ? 'Bottle replaced successfully!' : 'Bottle saved as new!');
                this.showDuplicateDialog = false;

                // Handle manifest navigation
                if (this.manifestContext) {
                    await this.nextBottle();
                } else {
                    // Fire save callback if set (manifest panel integration)
                    if (this._onSaveCallback) { this._onSaveCallback(this.bottle); this._onSaveCallback = null; }
                    this.close();
                }

            } catch (error) {
                console.error('Save failed:', error);
                alert('Save failed: ' + error.message);
            } finally {
                this.saving = false;
            }
        },

        /**
         * Manually check for duplicates
         */
        async manualCheckDuplicates() {
            console.log('Manual duplicate check triggered');
            this.saving = true;

            try {
                // Update bottle object with current editable fields
                Object.assign(this.bottle, this.editableBottle);

                // Clean bottle data
                const cleanBottle = { ...this.bottle };
                if (cleanBottle.year === '') cleanBottle.year = null;
                if (cleanBottle.price === '') cleanBottle.price = null;
                if (cleanBottle.inventory === '') cleanBottle.inventory = null;
                if (cleanBottle.abv === '') cleanBottle.abv = null;
                if (cleanBottle.proof === '') cleanBottle.proof = null;

                // Ensure type field is present
                if (!cleanBottle.type) {
                    console.error('Missing type field in bottle data!');
                    throw new Error('Missing bottle type field');
                }

                console.log('Checking for duplicates with bottle:', cleanBottle);

                const response = await fetch('/api/v1/bottles/check-duplicates', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(cleanBottle)
                });

                if (!response.ok) {
                    throw new Error('Failed to check duplicates');
                }

                const result = await response.json();

                console.log('Duplicate check result:', result);

                // Store duplicates for inline display (not as dialog)
                this.duplicates = result.duplicates || [];

                if (this.duplicates.length > 0) {
                    this.duplicateAction = 'save_new';  // Pre-select safest default when inline panel appears
                    console.log(`Found ${this.duplicates.length} potential duplicates`);
                } else {
                    console.log('No duplicates found');
                }

            } catch (error) {
                console.error('Duplicate check failed:', error);
                this.duplicates = [];
            } finally {
                this.saving = false;
            }
        },

        /**
         * Manual duplicate override: search the whole collection so the user can
         * pick the real match when fuzzy scoring missed it (or chose wrong), then
         * Replace it. Reuses the admin-only management search endpoint and feeds
         * the same selectedDuplicate/replace path the fuzzy cards use.
         */
        async manualMatchSearch() {
            const q = (this.manualMatchQuery || '').trim();
            if (!q) {
                this.manualMatchResults = [];
                return;
            }
            this.manualMatchSearching = true;
            try {
                const resp = await fetch(
                    `/api/v1/management/bottles/search?q=${encodeURIComponent(q)}`
                );
                if (!resp.ok) throw new Error('Search failed');
                const data = await resp.json();
                const results = data.bottles || [];
                // Surface same-type bottles first (the usual replace target), but
                // keep all — this is an explicit override, the user decides.
                const myType = this.bottle?.type;
                results.sort((a, b) => (b.type === myType) - (a.type === myType));
                this.manualMatchResults = results;
            } catch (error) {
                console.error('Manual match search failed:', error);
                this.manualMatchResults = [];
            } finally {
                this.manualMatchSearching = false;
            }
        },

        /**
         * Navigate to next bottle (manifest upload only)
         */
        async nextBottle() {
            if (!this.manifestContext) return;

            const ctx = this.manifestContext;
            if (ctx.currentIndex < ctx.bottles.length - 1) {
                ctx.currentIndex++;
                const nextBottle = ctx.bottles[ctx.currentIndex];
                this.openUpload(nextBottle, this.uploadId, ctx);
            } else {
                // All bottles processed
                this.showToast('All bottles processed!');
                this.close();
            }
        },

        /**
         * Navigate to previous bottle (manifest upload only)
         */
        async previousBottle() {
            if (!this.manifestContext) return;

            const ctx = this.manifestContext;
            if (ctx.currentIndex > 0) {
                ctx.currentIndex--;
                const prevBottle = ctx.bottles[ctx.currentIndex];
                this.openUpload(prevBottle, this.uploadId, ctx);
            }
        },

        /**
         * Skip current bottle (manifest upload only)
         */
        async skipBottle() {
            if (!this.manifestContext) {
                this.close();
                return;
            }

            // Just move to next bottle
            await this.nextBottle();
        },

        /**
         * Enrich metadata via web search (async with polling)
         */
        async enrichMetadata() {
            this.verifying = true;
            this.verifyingProgress = 'Starting verification...';
            this.searchResult = null;
            this.hasChanges = false;

            try {
                // Update bottle object with current editable fields before verification
                Object.assign(this.bottle, this.editableBottle);

                // Clean bottle data
                const cleanBottle = { ...this.bottle };
                if (cleanBottle.year === '') cleanBottle.year = null;
                if (cleanBottle.price === '') cleanBottle.price = null;
                if (cleanBottle.inventory === '') cleanBottle.inventory = null;
                if (cleanBottle.abv === '') cleanBottle.abv = null;
                if (cleanBottle.proof === '') cleanBottle.proof = null;

                console.log('Starting async enrichment for bottle:', cleanBottle);

                // Start the async verification task
                const response = await fetch('/api/v1/management/bottles/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bottle: cleanBottle })
                });

                const startResult = await response.json();

                if (!response.ok) {
                    throw new Error(startResult.error || 'Failed to start verification');
                }

                // Get task ID
                this.verifyingTaskId = startResult.task_id;
                this.verifyingProgress = 'Searching web for bottle information...';
                console.log('Verification task started:', this.verifyingTaskId);

                // Poll for task completion
                const result = await this.pollTaskStatus(this.verifyingTaskId);

                // Check if enrichment actually succeeded
                if (result.metadata && result.metadata.verified === false) {
                    throw new Error(result.metadata.error || 'Enrichment verification failed');
                }

                this.searchResult = result;
                this.approvedChanges = {};

                // Set hasChanges boolean for reactive x-show
                this.hasChanges = result.changes && Object.keys(result.changes).length > 0;

                this.verifyingProgress = 'Complete!';
                console.log('Enrichment completed with', Object.keys(result.changes || {}).length, 'changes');

            } catch (error) {
                console.error('Enrichment failed:', error);
                console.error('Error details:', error);
                this.showToast('✗ Search failed: ' + error.message, 'error');
            } finally {
                this.verifying = false;
                this.verifyingProgress = '';
                this.verifyingTaskId = null;
            }
        },

        /**
         * Poll a task status endpoint until completion or timeout.
         *
         * @param {string} taskId - The task ID to poll
         * @returns {Promise<object>} - Resolves with final task result or rejects on timeout/error
         */
        async pollTaskStatus(taskId) {
            const maxAttempts = 60;
            const interval = 2000;
            let attempts = 0;
            let elapsedSeconds = 0;

            while (attempts < maxAttempts) {
                try {
                    const response = await fetch(`/api/v1/management/tasks/${taskId}/status`);

                    if (!response.ok) {
                        if (response.status === 404) {
                            throw new Error('Task not found');
                        }
                        throw new Error(`Failed to get task status: ${response.statusText}`);
                    }

                    const result = await response.json();
                    console.log('Task status:', result.status);

                    // Update progress message based on status
                    if (result.status === 'queued') {
                        this.verifyingProgress = 'Queued for verification...';
                    } else if (result.status === 'processing') {
                        this.verifyingProgress = `Searching web for bottle information... (${elapsedSeconds}s)`;
                    }

                    // Show "taking longer than expected" after 30 seconds
                    if (elapsedSeconds >= 30) {
                        this.verifyingProgress = `Still searching... (${elapsedSeconds}s) - This may take a while`;
                    }

                    // Check if task is complete
                    if (result.status === 'complete') {
                        return result;
                    }

                    // Check if task failed
                    if (result.status === 'failed') {
                        throw new Error(result.error || 'Task failed');
                    }

                    // Wait before next poll
                    await new Promise(resolve => setTimeout(resolve, interval));
                    attempts++;
                    elapsedSeconds += interval / 1000;

                } catch (error) {
                    // On network error, retry a few times
                    if (attempts < 3) {
                        console.warn('Polling error, retrying...', error);
                        await new Promise(resolve => setTimeout(resolve, interval));
                        attempts++;
                        continue;
                    }
                    throw error;
                }
            }

            // Timeout
            throw new Error('Verification timed out - please try again');
        },

        /**
         * Apply selected metadata changes
         */
        applySelectedChanges() {
            if (!this.searchResult || !this.approvedChanges) return;

            // Apply only the checked changes to editableBottle
            for (const [field, isApproved] of Object.entries(this.approvedChanges)) {
                if (isApproved && this.searchResult.changes[field]) {
                    this.editableBottle[field] = this.searchResult.changes[field].new;
                }
            }

            // Clear search results
            this.searchResult = null;
            this.approvedChanges = {};

            this.showToast('✓ Selected changes applied to form', 'success');
        },

        /**
         * Apply all suggested metadata changes
         */
        applyAllChanges() {
            if (!this.searchResult || !this.searchResult.changes) return;

            // Apply all changes to editableBottle
            for (const [field, change] of Object.entries(this.searchResult.changes)) {
                this.editableBottle[field] = change.new;
            }

            // Clear search results
            this.searchResult = null;
            this.approvedChanges = {};

            this.showToast('✓ All changes applied to form', 'success');
        },

        /**
         * Cancel/dismiss metadata changes
         */
        cancelChanges() {
            this.searchResult = null;
            this.approvedChanges = {};
            this.hasChanges = false;
            this.showToast('Changes cancelled', 'info');
        },

        /**
         * Load tasting summary (management mode only)
         */
        async loadTastingSummary() {
            if (!this.bottleId) return;

            try {
                const response = await fetch('/api/v1/bottles/tastings-summary', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        bottle: this.bottle
                    })
                });
                const result = await response.json();

                if (response.ok) {
                    this.tastingSummary = result;
                }
            } catch (error) {
                console.error('Failed to load tasting summary:', error);
            }
        },

        /**
         * Load full list of tastings with scores and notes
         */
        async loadTastingsList() {
            if (!this.bottleId || this.loadingTastings) return;

            this.loadingTastings = true;

            try {
                const response = await fetch('/api/v1/bottles/tastings-list', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        bottle: this.bottle
                    })
                });
                const result = await response.json();

                if (response.ok) {
                    this.tastingsList = result.tastings || [];
                }
            } catch (error) {
                console.error('Failed to load tastings list:', error);
            } finally {
                this.loadingTastings = false;
            }
        },

        /**
         * Toggle tastings list visibility (and load if needed)
         */
        async toggleTastingsList() {
            if (!this.showTastingsList) {
                // Expanding - load tastings if not already loaded
                if (this.tastingsList.length === 0 && this.tastingSummary?.tasting_count > 0) {
                    await this.loadTastingsList();
                }
            }
            this.showTastingsList = !this.showTastingsList;
            this.selectedTasting = null;  // Close detail view when collapsing
        },

        /**
         * Select a tasting to show full details
         */
        selectTasting(tasting) {
            this.selectedTasting = tasting;
        },

        /**
         * Close tasting detail view and return to list
         */
        closeTastingDetail() {
            this.selectedTasting = null;
        },

        /**
         * Format tasting notes array as hashtags for display
         */
        formatNotesAsHashtags(notes) {
            if (!notes || !Array.isArray(notes) || notes.length === 0) {
                return '';
            }
            return notes.map(note => `#${note.replace(/\s+/g, '_')}`).join(' ');
        },

        /**
         * Manual crop current label
         */
        async startManualCrop() {
            this.manualCropActive = true;

            let imageSrc;
            if (this.mode === 'management') {
                // Use bottle ID to fetch label via API
                imageSrc = `/api/v1/labels/view?id=${encodeURIComponent(this.bottleId)}&t=${Date.now()}`;
            } else {
                // Upload mode - use temp label
                imageSrc = `/api/v1/temp-images/${this.uploadId}/label.jpg?t=${Date.now()}`;
            }

            this.manualCropImageSrc = imageSrc;

            // Initialize Cropper.js after image loads
            // Use setTimeout to ensure DOM is updated
            setTimeout(async () => {
                const image = document.getElementById('manualCropImage');
                if (image) {
                    console.log('Initializing cropper on image:', image.src);
                    try {
                        this.cropperInstance = await window.cropperManager.initializeCropper(
                            image,
                            {},
                            (error) => {
                                console.error('Cropper error callback:', error);
                                alert('Failed to load image. Please try again.');
                                this.cancelManualCrop();
                            }
                        );
                        console.log('Cropper initialized successfully');
                    } catch (error) {
                        console.error('Cropper init failed:', error);
                        alert('Failed to initialize cropper: ' + error.message);
                    }
                } else {
                    console.error('Image element not found with ID: manualCropImage');
                }
            }, 200);
        },

        /**
         * Accept manual crop and send to backend
         */
        async acceptManualCrop() {
            if (!this.cropperInstance) return;

            this.labelActionInProgress = true;

            try {
                const endpoint = this.mode === 'management'
                    ? '/api/v1/management/labels/manual-crop'
                    : '/api/v1/bottles/manual-crop-temp';

                // Clean bottle data - convert empty strings to null for numeric fields
                const cleanBottle = { ...this.bottle };
                if (cleanBottle.year === '') cleanBottle.year = null;
                if (cleanBottle.price === '') cleanBottle.price = null;
                if (cleanBottle.inventory === '') cleanBottle.inventory = null;
                if (cleanBottle.abv === '') cleanBottle.abv = null;
                if (cleanBottle.proof === '') cleanBottle.proof = null;

                const additionalData = this.mode === 'management'
                    ? { bottle_id: this.bottleId }
                    : { upload_id: this.uploadId };

                await window.cropperManager.completeCrop(
                    this.cropperInstance,
                    endpoint,
                    additionalData,
                    (result) => {
                        console.log('Crop success:', result);
                        this.showToast('Label cropped successfully!');
                        this.currentLabelTimestamp = Date.now();
                        this.cancelManualCrop();
                    },
                    (error) => {
                        console.error('Crop error:', error);
                        alert('Manual crop failed: ' + error.message);
                    }
                );

            } finally {
                this.labelActionInProgress = false;
            }
        },

        /**
         * Cancel manual crop
         */
        cancelManualCrop() {
            if (this.cropperInstance) {
                window.cropperManager.destroyCropper(this.cropperInstance);
                this.cropperInstance = null;
            }
            this.manualCropActive = false;
            this.manualCropImageSrc = null;
        },

        /**
         * Cancel manual crop for downloaded image
         */
        cancelManualCropDownloaded() {
            if (this.cropperDownloadedInstance) {
                window.cropperManager.destroyCropper(this.cropperDownloadedInstance);
                this.cropperDownloadedInstance = null;
            }
            this.manualCropDownloadedActive = false;
            this.manualCropDownloadedSrc = null;
        },

        /**
         * Search for label images on the web
         */
        async searchForLabelReplacement() {
            this.labelActionInProgress = true;
            try {
                const response = await fetch('/api/v1/bottles/search-labels', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.bottle)
                });

                if (!response.ok) {
                    let detail = `Label search failed (${response.status})`;
                    try {
                        const error = await response.json();
                        detail = error.detail || detail;
                    } catch (e) { /* non-JSON error body */ }
                    throw new Error(detail);
                }

                const data = await response.json();
                this.labelSearchResults = data.images || [];
                console.log(`Found ${this.labelSearchResults.length} label candidates`);
            } catch (error) {
                console.error('Label search failed:', error);
                alert('Label search failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        /**
         * Auto-crop existing label
         */
        async cropExistingLabel() {
            this.labelActionInProgress = true;
            try {
                // Mode-aware, like acceptManualCrop: management crops a committed
                // label (by bottle_id); upload crops the temp uploaded image (by
                // upload_id), which has no saved bottle yet.
                const endpoint = this.mode === 'management'
                    ? '/api/v1/management/labels/crop-current'
                    : '/api/v1/bottles/auto-crop-temp';
                const body = this.mode === 'management'
                    ? { bottle_id: this.bottleId }
                    : { upload_id: this.uploadId };

                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(body)
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Crop failed');
                }

                await response.json();

                if (this.mode === 'management') {
                    // Management commits a preview that the user accepts/discards.
                    this.labelCropPreview = `/api/v1/labels/view?id=${encodeURIComponent(this.bottleId)}&file=label_preview.jpg&t=${Date.now()}`;
                    this.showToast('Label cropped! Review the preview below.');
                } else {
                    // Upload mode overwrites the temp label in place (like manual
                    // crop); just refresh the cache-busted preview.
                    this.currentLabelTimestamp = Date.now();
                    this.showToast('Label auto-cropped successfully!');
                }
            } catch (error) {
                console.error('Crop failed:', error);
                alert('Crop failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        /**
         * Accept auto-crop preview and replace label
         */
        async acceptCropPreview() {
            this.labelActionInProgress = true;
            try {
                const response = await fetch('/api/v1/management/labels/accept-crop', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle_id: this.bottleId
                    })
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Accept crop failed');
                }

                await response.json();
                this.labelCropPreview = null;
                this.currentLabelTimestamp = Date.now();
                this.showToast('Label updated successfully!');
            } catch (error) {
                console.error('Accept crop failed:', error);
                alert('Accept crop failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        /**
         * Cancel auto-crop preview
         */
        cancelCropPreview() {
            this.labelCropPreview = null;
        },

        /**
         * Upload custom label image
         */
        async uploadCustomLabel(event) {
            const file = event.target.files[0];
            if (!file) return;

            this.labelActionInProgress = true;
            try {
                const formData = new FormData();
                formData.append('file', file);
                formData.append('bottle', JSON.stringify(this.bottle));

                if (this.mode === 'upload') {
                    formData.append('upload_id', this.uploadId);
                }

                const endpoint = this.mode === 'management'
                    ? '/api/v1/management/labels/upload-custom'
                    : '/api/v1/bottles/upload-custom-label';

                const response = await fetch(endpoint, {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    let detail = `Upload failed (${response.status})`;
                    try {
                        const error = await response.json();
                        detail = error.detail || detail;
                    } catch (e) { /* non-JSON error body */ }
                    throw new Error(detail);
                }

                await response.json();
                this.currentLabelTimestamp = Date.now();
                this.showToast('Custom label uploaded successfully!');

                // Clear file input
                event.target.value = '';
            } catch (error) {
                console.error('Upload failed:', error);
                alert('Upload failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        /**
         * Download and use selected search result
         */
        async useSelectedSearchImage(imageUrl) {
            this.labelActionInProgress = true;
            try {
                const response = await fetch('/api/v1/management/labels/download-image', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle_id: this.bottleId,
                        image_url: imageUrl
                    })
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Download failed');
                }

                const data = await response.json();
                // Use bottle ID to view the downloaded label
                this.labelDownloadedOriginal = `/api/v1/labels/view?id=${encodeURIComponent(this.bottleId)}&file=label_download.jpg&t=${Date.now()}`;
                this.showToast('Label downloaded! You can crop it or use as-is.');
                // Clear search results to show downloaded image
                this.labelSearchResults = [];
            } catch (error) {
                console.error('Download failed:', error);
                alert('Download failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        /**
         * Use downloaded label (with or without cropping)
         */
        async useDownloadedLabel(useCropped) {
            this.labelActionInProgress = true;
            try {
                const response = await fetch('/api/v1/management/labels/use-downloaded', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle_id: this.bottleId,
                        use_cropped: useCropped
                    })
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to use downloaded label');
                }

                await response.json();
                this.labelDownloadedOriginal = null;
                this.labelDownloadedCropped = null;
                this.currentLabelTimestamp = Date.now();
                this.showToast('Label updated successfully!');
            } catch (error) {
                console.error('Use downloaded failed:', error);
                alert('Use downloaded failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        /**
         * Start manual crop for downloaded image
         */
        async startManualCropDownloaded() {
            this.manualCropDownloadedActive = true;
            this.manualCropDownloadedSrc = this.labelDownloadedOriginal;

            // Initialize Cropper.js after image loads
            setTimeout(async () => {
                const image = document.getElementById('manualCropDownloadedImage');
                if (image) {
                    console.log('Initializing cropper on downloaded image:', image.src);
                    try {
                        this.cropperDownloadedInstance = await window.cropperManager.initializeCropper(
                            image,
                            {},
                            (error) => {
                                console.error('Cropper error callback:', error);
                                alert('Failed to load image. Please try again.');
                                this.cancelManualCropDownloaded();
                            }
                        );
                        console.log('Downloaded cropper initialized successfully');
                    } catch (error) {
                        console.error('Downloaded cropper init failed:', error);
                        alert('Failed to initialize cropper: ' + error.message);
                    }
                } else {
                    console.error('Image element not found with ID: manualCropDownloadedImage');
                }
            }, 200);
        },

        /**
         * Accept manual crop of downloaded image
         */
        async acceptManualCropDownloaded() {
            if (!this.cropperDownloadedInstance) return;

            this.labelActionInProgress = true;

            try {
                await window.cropperManager.completeCrop(
                    this.cropperDownloadedInstance,
                    '/api/v1/management/labels/manual-crop-downloaded',
                    { bottle_id: this.bottleId },
                    async (result) => {
                        // Now use the cropped version
                        await this.useDownloadedLabel(true);
                        this.cancelManualCropDownloaded();
                    },
                    (error) => {
                        alert('Manual crop failed: ' + error.message);
                    }
                );

            } finally {
                this.labelActionInProgress = false;
            }
        },

        /**
         * Get field label for display
         */
        getFieldLabel(fieldName) {
            const labels = {
                producer: 'Producer/Distiller',
                name: 'Name',
                year: 'Year/Vintage',
                type: 'Type',
                region: 'Region',
                country: 'Country',
                variety: 'Variety',
                vineyard: 'Vineyard',
                abv: 'ABV',
                style: 'Style',
                age_statement: 'Age Statement',
                proof: 'Proof',
                mash_bill: 'Mash Bill',
                barrel_type: 'Barrel Type',
                price: 'Price',
                inventory: 'Inventory'
            };
            return labels[fieldName] || fieldName;
        },

        /**
         * Show toast notification
         */
        showToast(message, type = 'info') {
            // Create toast element
            const toast = document.createElement('div');
            toast.className = `fixed bottom-4 right-4 px-6 py-3 rounded-lg shadow-lg text-white font-semibold z-50 transform transition-all duration-300 ${
                type === 'success' ? 'bg-green-600' :
                type === 'error' ? 'bg-red-600' :
                'bg-blue-600'
            }`;
            toast.textContent = message;
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(20px)';

            document.body.appendChild(toast);

            // Animate in
            setTimeout(() => {
                toast.style.opacity = '1';
                toast.style.transform = 'translateY(0)';
            }, 10);

            // Remove after 3 seconds
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transform = 'translateY(20px)';
                setTimeout(() => toast.remove(), 300);
            }, 3000);
        }
    };
};
