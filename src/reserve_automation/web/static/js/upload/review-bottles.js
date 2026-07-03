/**
 * Review-bottles page component (window.uploadBottlesApp).
 *
 * Extracted from templates/review_bottles.html (July 2026) so the logic gets
 * vitest unit coverage (tests/js/review-bottles.test.js). Attached as a WHOLE
 * factory — the object must be returned intact (do not spread it elsewhere).
 *
 * Composes window.bottleEditorModal at factory-call time (soft-guarded, but
 * the page must load components/bottle-editor-modal.js BEFORE this file for
 * the review modal to work).
 *
 * Like upload-page.js, the extraction streams over fetch + ReadableStream
 * (SSE framing, `data: {json}\n\n`), NOT EventSource — the POST body
 * (multipart file) rules EventSource out.
 */

// #CLAUDE_REQ: State/method names here MUST match the Alpine bindings in
//              templates/review_bottles.html (x-data="uploadBottlesApp()") —
//              e.g. extractedBottles/bottleSaved/isManifest drive the bottle
//              grid markup. Rename in both places or the page silently breaks.
// #CLAUDE_REQ: The SSE contract MUST match web/routes/bottles/extraction.py
//              POST /api/v1/bottles/upload/stream: text/event-stream of JSON
//              events {status, message, ...}; on "complete" the event carries
//              {upload_id, bottles, is_manifest}; on "error" a message. The
//              _headingFor() map mirrors the intermediate status codes emitted
//              there (uploading/checking_model/model_loading/model_ready/
//              extracting).

window.uploadBottlesApp = function uploadBottlesApp() {
    // Initialize bottle editor modal
    const bottleEditor = window.bottleEditorModal ? window.bottleEditorModal() : {};

    return {
        // Upload form state
        selectedFile: null,
        uploadType: 'bottle_image',
        beverageType: 'auto',
        expectedCount: null,
        purchaseSource: '',
        inventory: 0,

        // Upload progress
        uploadInProgress: false,
        uploadComplete: false,
        uploadError: false,
        uploadErrorMessage: '',

        // Status feedback during extraction
        statusHeading: 'Processing...',
        statusMessage: 'Please wait...',

        // Extracted data
        uploadId: null,
        extractedBottles: [],
        isManifest: false,
        bottleSaved: {},  // Track which bottles have been saved

        // Bottle editor modal
        bottleEditor: bottleEditor,

        // Handle file selection
        handleFileSelect(event) {
            this.selectedFile = event.target.files[0];
        },

        // Reset form after an error
        resetForm() {
            this.uploadInProgress = false;
            this.uploadComplete = false;
            this.uploadError = false;
            this.uploadErrorMessage = '';
            this.statusHeading = 'Processing...';
            this.statusMessage = 'Please wait...';
        },

        // Map SSE status codes to heading text
        _headingFor(status) {
            const headings = {
                uploading: 'Uploading...',
                checking_model: 'Connecting to LM Studio...',
                model_loading: 'Loading Model...',
                model_ready: 'Model Ready',
                extracting: 'Analyzing Image...',
            };
            return headings[status] || 'Processing...';
        },

        // Submit upload via SSE streaming endpoint
        async submitUpload() {
            if (!this.selectedFile) return;

            this.uploadInProgress = true;
            this.uploadError = false;
            this.statusHeading = 'Uploading...';
            this.statusMessage = 'Saving image...';

            try {
                const formData = new FormData();
                formData.append('file', this.selectedFile);
                formData.append('upload_type', this.uploadType);
                formData.append('beverage_type', this.beverageType);
                if (this.expectedCount) {
                    formData.append('expected_count', this.expectedCount);
                }
                if (this.purchaseSource) {
                    formData.append('purchase_source', this.purchaseSource);
                }
                formData.append('inventory', this.inventory);

                const response = await fetch('/api/v1/bottles/upload/stream', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) {
                    let detail = `Server error ${response.status}`;
                    try {
                        const err = await response.json();
                        detail = err.detail || detail;
                    } catch (_) {}
                    throw new Error(detail);
                }

                // Read the SSE stream
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    buffer += decoder.decode(value, { stream: true });

                    // SSE events are separated by double newlines
                    const parts = buffer.split('\n\n');
                    buffer = parts.pop(); // keep incomplete trailing chunk

                    for (const part of parts) {
                        const line = part.trim();
                        if (!line.startsWith('data: ')) continue;
                        let event;
                        try {
                            event = JSON.parse(line.slice(6));
                        } catch (_) {
                            continue;
                        }

                        const status = event.status;

                        if (status === 'complete') {
                            this.uploadId = event.upload_id;
                            this.extractedBottles = event.bottles || [];
                            this.isManifest = event.is_manifest || false;
                            this.uploadInProgress = false;
                            this.uploadComplete = true;

                            if (this.extractedBottles.length === 1) {
                                this.$nextTick(() => this.openBottleEditor(0));
                            }
                            return;

                        } else if (status === 'error') {
                            throw new Error(event.message || 'Extraction failed');

                        } else {
                            // Intermediate status — update display
                            this.statusHeading = this._headingFor(status);
                            this.statusMessage = event.message || '';
                        }
                    }
                }

            } catch (error) {
                console.error('Upload failed:', error);
                this.uploadInProgress = false;
                this.uploadError = true;
                this.uploadErrorMessage = error.message || 'An unexpected error occurred. Please try again.';
            }
        },

        // Open bottle editor modal
        openBottleEditor(index) {
            const bottle = this.extractedBottles[index];

            if (this.isManifest && this.extractedBottles.length > 1) {
                // Manifest with multiple bottles - pass context for navigation
                const manifestContext = {
                    bottles: this.extractedBottles,
                    currentIndex: index
                };
                this.bottleEditor.openUpload(bottle, this.uploadId, manifestContext);
            } else {
                // Single bottle
                this.bottleEditor.openUpload(bottle, this.uploadId);
            }

            // Override save handler to track saved bottles
            const originalSave = this.bottleEditor.saveUpload.bind(this.bottleEditor);
            this.bottleEditor.saveUpload = async function() {
                await originalSave();
                // Mark bottle as saved
                this.bottleSaved[index] = true;
            }.bind(this);
        }
    };
};
