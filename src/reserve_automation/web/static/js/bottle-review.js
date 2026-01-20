/**
 * Bottle Review Form Module
 * Handles PDF extraction review, enrichment, label selection, and approval workflow
 */

window.bottleReviewForm = function() {
    const extractionId = window.location.pathname.split('/').pop();

    return {
        extractionId,
        loading: true,
        error: false,
        errorMessage: '',
        extraction: null,
        currentIndex: 0,
        currentBottle: null,
        enriching: false,
        enrichmentChanges: null,
        enrichmentSuggestions: null,
        approving: false,
        approved: false,
        approvalResult: null,
        rejecting: false,
        findingLabels: false,
        selectedCandidateUrl: null,
        processingLabel: false,
        labelPreview: null,
        labelChoice: null,
        showManualUpload: false,
        manualUploadFile: null,
        manualUploadPreview: null,
        checkingDuplicates: false,
        reExtracting: false,

        async loadExtraction() {
            try {
                const response = await fetch(`/api/v1/bottles/${this.extractionId}`, {
                    credentials: 'include'  // Include cookies in request
                });

                if (!response.ok) {
                    throw new Error('Failed to load extraction');
                }

                this.extraction = await response.json();
                this.currentIndex = this.extraction.current_bottle_index || 0;
                this.currentBottle = this.extraction.bottles[this.currentIndex];
                this.loading = false;

                // Automatically check for duplicates after loading
                await this.checkDuplicates();

                // Auto-trigger label search if in label selection stage and no candidates yet
                const inLabelStage = this.currentBottle.stage === 'extracted' || this.currentBottle.stage === 'enriched';
                const noCandidates = !this.currentBottle.label_candidates;
                const noLabelSelected = !this.currentBottle.selected_label && this.currentBottle.label_choice !== 'none';

                if (inLabelStage && noCandidates && noLabelSelected) {
                    console.log('Auto-triggering label search for uploaded bottle image');
                    await this.findLabels();
                }

            } catch (err) {
                this.error = true;
                this.errorMessage = err.message || 'Failed to load extraction data';
                this.loading = false;
            }
        },

        async enrichBottle() {
            this.enriching = true;
            this.enrichmentSuggestions = null;  // Clear previous suggestions

            try {
                // Send current bottle data (with user edits) for enrichment
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/enrich/${this.currentIndex}`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        bottle: this.currentBottle.bottle
                    })
                });

                if (!response.ok) {
                    throw new Error('Failed to enrich bottle');
                }

                const result = await response.json();

                // DON'T automatically apply changes - show suggestions instead
                if (result.status === 'suggestions_ready') {
                    this.enrichmentSuggestions = result.suggestions;
                    this.currentBottle.enrichment_meta = result.enrichment_meta;
                    this.currentBottle.stage = 'enriched';

                    console.log(`Got ${Object.keys(result.suggestions).length} enrichment suggestions`);
                } else {
                    // Old format (shouldn't happen with new backend)
                    this.currentBottle.bottle = result.bottle;
                    this.currentBottle.enrichment_meta = result.enrichment_meta;
                    this.currentBottle.stage = 'enriched';
                    this.enrichmentChanges = result.enrichment_meta?.changes || {};
                }

                // Update duplicate check results if returned
                if (result.potential_duplicates !== undefined) {
                    this.currentBottle.potential_duplicates = result.potential_duplicates;
                }

            } catch (err) {
                alert(`Enrichment failed: ${err.message}`);
            } finally {
                this.enriching = false;
            }
        },

        acceptSuggestion(field) {
            if (this.enrichmentSuggestions && this.enrichmentSuggestions[field]) {
                // Apply the suggested value to the bottle
                this.currentBottle.bottle[field] = this.enrichmentSuggestions[field].suggested;

                // Force Alpine.js reactivity by reassigning the object
                this.currentBottle.bottle = {...this.currentBottle.bottle};

                // Remove from suggestions list
                delete this.enrichmentSuggestions[field];

                console.log(`Applied suggestion for ${field}`);

                // Persist to session
                this.updateBottle();
            }
        },

        rejectSuggestion(field) {
            if (this.enrichmentSuggestions && this.enrichmentSuggestions[field]) {
                // Just remove from suggestions list without applying
                delete this.enrichmentSuggestions[field];

                console.log(`Rejected suggestion for ${field}`);
            }
        },

        acceptAllSuggestions() {
            if (this.enrichmentSuggestions) {
                // Apply all suggestions
                for (const [field, suggestion] of Object.entries(this.enrichmentSuggestions)) {
                    this.currentBottle.bottle[field] = suggestion.suggested;
                }

                // Force Alpine.js reactivity by reassigning the object
                this.currentBottle.bottle = {...this.currentBottle.bottle};

                // Clear all suggestions
                this.enrichmentSuggestions = {};

                console.log('Applied all suggestions');

                // Persist to session
                this.updateBottle();
            }
        },

        async updateBottle() {
            // Save any user edits to session
            try {
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/update/${this.currentIndex}`, {
                    method: 'PUT',
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        bottle: this.currentBottle.bottle
                    })
                });

                if (!response.ok) {
                    throw new Error('Failed to update bottle');
                }

            } catch (err) {
                console.error('Update failed:', err);
                throw err;
            }
        },

        async approveBottle() {
            this.approving = true;

            try {
                // First update any user edits
                await this.updateBottle();

                // Then approve and save
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/approve/${this.currentIndex}`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (!response.ok) {
                    throw new Error('Failed to approve bottle');
                }

                this.approvalResult = await response.json();
                this.approved = true;

            } catch (err) {
                alert(`Error: ${err.message}`);
            } finally {
                this.approving = false;
            }
        },

        async nextBottle() {
            // Move to next bottle
            if (this.currentIndex < this.extraction.bottles.length - 1) {
                this.currentIndex++;
                await this.loadCurrentBottle();
            }
        },

        async previousBottle() {
            // Move to previous bottle
            if (this.currentIndex > 0) {
                this.currentIndex--;
                await this.loadCurrentBottle();
            }
        },

        async loadCurrentBottle() {
            // Load the bottle at currentIndex
            this.currentBottle = this.extraction.bottles[this.currentIndex];

            // Reset label-related state
            this.labelPreview = null;
            this.labelChoice = null;
            this.selectedCandidateUrl = null;
            this.showManualUpload = false;
            this.manualUploadFile = null;
            this.manualUploadPreview = null;

            // Reset enrichment suggestions
            this.enrichmentSuggestions = null;
            this.approved = false;
            this.approvalResult = null;
        },

        async findLabels() {
            this.findingLabels = true;

            try {
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/find-labels/${this.currentIndex}`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (!response.ok) {
                    throw new Error('Failed to find labels');
                }

                const result = await response.json();

                // Update current bottle with label candidates
                this.currentBottle.label_candidates = result.label_candidates;

                // Auto-select the first candidate (uploaded image if available)
                if (result.label_candidates && result.label_candidates.length > 0) {
                    const firstCandidate = result.label_candidates[0];
                    this.selectedCandidateUrl = firstCandidate.url;

                    // If it's the uploaded image, show a helpful message
                    if (firstCandidate.source === 'uploaded_image') {
                        console.log('Auto-selected your uploaded image as label');
                    }
                }

            } catch (err) {
                alert(`Label search failed: ${err.message}`);
            } finally {
                this.findingLabels = false;
            }
        },

        selectLabelCandidate(url) {
            this.selectedCandidateUrl = url;
        },

        async downloadAndCropLabel() {
            if (!this.selectedCandidateUrl) {
                return;
            }

            this.processingLabel = true;

            try {
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/select-label/${this.currentIndex}`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        label_url: this.selectedCandidateUrl,
                        use_crop: true  // Initial request, will let user choose
                    })
                });

                if (!response.ok) {
                    throw new Error('Failed to process label');
                }

                const result = await response.json();

                // Reload bottle data from session to get the selected_label with full paths
                const reloadResponse = await fetch(`/api/v1/bottles/${this.extractionId}`);
                if (reloadResponse.ok) {
                    this.extraction = await reloadResponse.json();
                    this.currentBottle = this.extraction.bottles[this.currentIndex];
                    console.log('Reloaded bottle data, selected_label:', this.currentBottle.selected_label);
                }

                // Show crop approval UI
                this.labelPreview = {
                    has_crop: result.has_crop,
                    original_preview: `/api/v1/temp-images/${this.extractionId}/${result.original_filename}`,
                    cropped_preview: result.has_crop ? `/api/v1/temp-images/${this.extractionId}/${result.cropped_filename}` : null
                };

                // Store result for later confirmation
                this.labelPreview.result = result;

            } catch (err) {
                alert(`Label processing failed: ${err.message}`);
            } finally {
                this.processingLabel = false;
            }
        },

        async confirmLabelChoice(useCrop) {
            // User confirmed their choice - just update the use_crop field
            // DON'T overwrite the whole object - it has full paths from the backend!
            this.currentBottle.selected_label.use_crop = useCrop;
            this.currentBottle.label_choice = useCrop ? 'cropped' : 'original';

            // Update session with the user's final choice
            try {
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/update/${this.currentIndex}`, {
                    method: 'PUT',
                    credentials: 'include',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        bottle: this.currentBottle.bottle,
                        selected_label: this.currentBottle.selected_label,
                        label_choice: this.currentBottle.label_choice
                    })
                });

                if (!response.ok) {
                    throw new Error('Failed to update label choice in session');
                }

                console.log(`Updated session: ${useCrop ? 'cropped' : 'original'} label selected`);
                console.log('Selected label paths:', this.currentBottle.selected_label);
            } catch (err) {
                console.error('Failed to update label choice:', err);
                alert(`Warning: Label choice may not be saved correctly: ${err.message}`);
            }

            // Clear preview UI
            this.labelPreview = null;
            this.labelChoice = this.currentBottle.label_choice;
        },

        cancelLabelSelection() {
            // User cancelled - go back to candidate selection
            this.labelPreview = null;
            this.selectedCandidateUrl = null;
        },

        async searchAgain() {
            // Clear previous selection and search again
            this.selectedCandidateUrl = null;
            await this.findLabels();
        },

        async checkDuplicates() {
            this.checkingDuplicates = true;

            try {
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/check-duplicates/${this.currentIndex}`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (!response.ok) {
                    throw new Error('Failed to check duplicates');
                }

                const result = await response.json();

                // Force Alpine.js reactivity by replacing the whole bottle object
                const updatedBottle = { ...this.currentBottle };
                updatedBottle.potential_duplicates = result.duplicates;

                // Initialize duplicate_action if not set (default to save_new if duplicates found)
                if (!updatedBottle.duplicate_action) {
                    if (result.duplicates.length > 0) {
                        // Default to save_new when duplicates are found
                        updatedBottle.duplicate_action = 'save_new';
                    }
                }

                this.currentBottle = updatedBottle;

                // Also update in the extraction bottles array
                this.extraction.bottles[this.currentIndex] = updatedBottle;

                console.log('Duplicates found:', result.duplicates.length);

            } catch (err) {
                alert(`Duplicate check failed: ${err.message}`);
            } finally {
                this.checkingDuplicates = false;
            }
        },

        async skipBottle() {
            if (!confirm('Skip this bottle? It will not be saved to your vault.')) {
                return;
            }

            try {
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/skip/${this.currentIndex}`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (!response.ok) {
                    throw new Error('Failed to skip bottle');
                }

                // Mark bottle as skipped in local state
                this.currentBottle.skipped = true;

                // Move to next bottle
                await this.nextBottle();

            } catch (err) {
                alert(`Error skipping bottle: ${err.message}`);
            }
        },

        async reExtract() {
            if (!confirm('Re-run extraction? This will replace all extracted bottles with a new attempt.')) {
                return;
            }

            this.reExtracting = true;

            try {
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/re-extract`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (!response.ok) {
                    throw new Error('Re-extraction failed');
                }

                // Reload the page to show new extraction
                window.location.reload();

            } catch (err) {
                alert(`Re-extraction failed: ${err.message}`);
                this.reExtracting = false;
            }
        },

        handleManualUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            this.manualUploadFile = file;

            // Show preview
            const reader = new FileReader();
            reader.onload = (e) => {
                this.manualUploadPreview = e.target.result;
            };
            reader.readAsDataURL(file);
        },

        async uploadManualLabel(tryCrop) {
            if (!this.manualUploadFile) return;

            this.processingLabel = true;

            try {
                // Create FormData to upload file
                const formData = new FormData();
                formData.append('file', this.manualUploadFile);
                formData.append('try_crop', tryCrop);

                const response = await fetch(`/api/v1/bottles/${this.extractionId}/upload-label/${this.currentIndex}`, {
                    method: 'POST',
                    credentials: 'include',
                    body: formData
                });

                if (!response.ok) {
                    throw new Error('Failed to upload label');
                }

                const result = await response.json();

                if (tryCrop) {
                    // Show crop approval UI
                    this.labelPreview = {
                        has_crop: result.has_crop,
                        original_preview: `/api/v1/temp-images/${this.extractionId}/${result.original_filename}`,
                        cropped_preview: result.has_crop ? `/api/v1/temp-images/${this.extractionId}/${result.cropped_filename}` : null,
                        result: result
                    };
                    this.showManualUpload = false;
                } else {
                    // Use as-is without crop approval
                    this.currentBottle.selected_label = {
                        url: 'manual_upload',
                        use_crop: false,
                        ...result
                    };
                    this.currentBottle.label_choice = 'original';
                    this.showManualUpload = false;
                    this.manualUploadFile = null;
                    this.manualUploadPreview = null;
                }

            } catch (err) {
                alert(`Upload failed: ${err.message}`);
            } finally {
                this.processingLabel = false;
            }
        },

        cancelManualUpload() {
            this.showManualUpload = false;
            this.manualUploadFile = null;
            this.manualUploadPreview = null;
        },

        resetLabelSelection() {
            // Clear all label-related state to start over
            this.currentBottle.selected_label = null;
            this.currentBottle.label_choice = null;
            this.currentBottle.label_candidates = null;
            this.labelPreview = null;
            this.labelChoice = null;
            this.selectedCandidateUrl = null;
            this.showManualUpload = false;
            this.manualUploadFile = null;
            this.manualUploadPreview = null;
        },

        skipLabel() {
            // User doesn't want any of the candidates
            if (!confirm('Skip label selection? You can add your own label.jpg file later.')) {
                return;
            }

            this.currentBottle.label_choice = 'none';
            this.currentBottle.label_candidates = null;
            this.selectedCandidateUrl = null;
        },

        async rejectAll() {
            if (!confirm('Discard all bottles? This cannot be undone.')) {
                return;
            }

            this.rejecting = true;

            try {
                const response = await fetch(`/api/v1/bottles/${this.extractionId}/reject`, {
                    method: 'POST',
                    credentials: 'include'
                });

                if (!response.ok) {
                    throw new Error('Failed to reject bottles');
                }

                // Redirect to upload page
                window.location.href = '/upload';

            } catch (err) {
                alert(`Error: ${err.message}`);
                this.rejecting = false;
            }
        }
    };
};
