/**
 * Extraction Review page component (window.reviewForm).
 *
 * Extracted from templates/review.html (July 2026) so the logic gets vitest
 * unit coverage (tests/js/review-page.test.js). Attached as a WHOLE factory
 * and returned intact — do not spread the returned object into another
 * component (project convention; spreading freezes any getters).
 *
 * The page shows every tasting from an upload extraction at once for batch
 * review: load extraction (+ bottle match previews), edit fields inline,
 * convert whiskey flavor-note arrays (nose/palate/finish) to/from
 * comma-separated strings for editing, then approve (PUT updated data, POST
 * approve) or reject the whole extraction.
 *
 * extractionId is parsed from the URL path (/review/{extraction_id}) — no
 * Jinja values are needed, so there is no inline bootstrap.
 */
// #CLAUDE_REQ: State keys, method names, and getters here MUST match the Alpine
// bindings in templates/review.html (x-data="reviewForm()",
// x-init="loadExtraction()"). Rename in both places or the page silently
// loses functionality.
// #CLAUDE_REQ: Endpoints must match web/routes/review.py —
// GET  /api/v1/extractions/{extraction_id}  (→ {extraction_id, template_type, data, match_previews, ...})
// PUT  /api/v1/extractions/{extraction_id}  ({extraction_data})
// POST /api/v1/review/{extraction_id}/approve (→ {status, files_created, unmatched, ...})
// POST /api/v1/review/{extraction_id}/reject
// #CLAUDE_REQ: Flavor note keys are the WHISKEY note keys (nose_notes,
// palate_notes, finish_notes) — wine notes use appearance/aroma/taste/aftertaste
// keys and are NOT round-tripped through the *_str fields here. Do not "fix"
// wine tastings to use these keys (see the July 2026 wine note-wiping bug).

window.reviewForm = function() {
    const extractionId = window.location.pathname.split('/').pop();

    return {
        extractionId,
        loading: true,
        error: false,
        errorMessage: '',
        extraction: null,
        matchPreviews: [],
        approving: false,
        rejecting: false,
        approved: false,
        approvalResult: null,

        async loadExtraction() {
            try {
                const response = await fetch(`/api/v1/extractions/${this.extractionId}`);

                if (!response.ok) {
                    throw new Error('Failed to load extraction');
                }

                this.extraction = await response.json();

                // Convert flavor note arrays to comma-separated strings for display
                if (this.extraction.data && this.extraction.data.tastings) {
                    this.extraction.data.tastings.forEach(tasting => {
                        tasting.nose_notes_str = (tasting.nose_notes || []).join(', ');
                        tasting.palate_notes_str = (tasting.palate_notes || []).join(', ');
                        tasting.finish_notes_str = (tasting.finish_notes || []).join(', ');
                    });
                }

                this.matchPreviews = this.extraction.match_previews || [];
                this.loading = false;
            } catch (err) {
                this.error = true;
                this.errorMessage = err.message || 'Failed to load extraction data';
                this.loading = false;
            }
        },

        async approveExtraction() {
            if (!confirm('Save these tastings to your Obsidian vault?')) {
                return;
            }

            this.approving = true;

            try {
                // Convert flavor note strings back to arrays before saving
                if (this.extraction.data && this.extraction.data.tastings) {
                    this.extraction.data.tastings.forEach(tasting => {
                        // Convert comma-separated strings to arrays
                        if (tasting.nose_notes_str) {
                            tasting.nose_notes = tasting.nose_notes_str
                                .split(',')
                                .map(s => s.trim())
                                .filter(s => s.length > 0);
                        }
                        if (tasting.palate_notes_str) {
                            tasting.palate_notes = tasting.palate_notes_str
                                .split(',')
                                .map(s => s.trim())
                                .filter(s => s.length > 0);
                        }
                        if (tasting.finish_notes_str) {
                            tasting.finish_notes = tasting.finish_notes_str
                                .split(',')
                                .map(s => s.trim())
                                .filter(s => s.length > 0);
                        }
                    });
                }

                // Update the extraction data in session
                const updateResponse = await fetch(`/api/v1/extractions/${this.extractionId}`, {
                    method: 'PUT',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        extraction_data: this.extraction.data
                    })
                });

                if (!updateResponse.ok) {
                    throw new Error('Failed to update extraction data');
                }

                // Now approve and save to vault
                const response = await fetch(`/api/v1/review/${this.extractionId}/approve`, {
                    method: 'POST'
                });

                if (!response.ok) {
                    throw new Error('Failed to approve extraction');
                }

                this.approvalResult = await response.json();
                this.approved = true;
            } catch (err) {
                alert(`Error: ${err.message}`);
            } finally {
                this.approving = false;
            }
        },

        async rejectExtraction() {
            if (!confirm('Discard this extraction? This cannot be undone.')) {
                return;
            }

            this.rejecting = true;

            try {
                const response = await fetch(`/api/v1/review/${this.extractionId}/reject`, {
                    method: 'POST'
                });

                if (!response.ok) {
                    throw new Error('Failed to reject extraction');
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
