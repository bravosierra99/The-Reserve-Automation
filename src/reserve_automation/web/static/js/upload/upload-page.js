/**
 * Import page root component (window.uploadForm).
 *
 * Extracted from templates/upload.html (July 2026) so the logic gets vitest
 * unit coverage (tests/js/upload-page.test.js). Attached as a WHOLE factory —
 * the object must be returned intact (do not spread it into another object;
 * spreading would also break any future getters).
 *
 * Composes window.bottleEditorModal at init() time (soft-guarded, but the page
 * must load components/bottle-editor-modal.js BEFORE this file for the review
 * modal to work).
 *
 * The upload path streams the extraction over fetch + ReadableStream (SSE
 * framing, `data: {json}\n\n`), NOT EventSource — the POST body (multipart
 * file) rules EventSource out. Heartbeat/progress events keep the request
 * under the nginx/Cloudflare idle timeouts; see uploadFile() comments.
 */

// #CLAUDE_REQ: State/method names here MUST match the Alpine bindings in
//              templates/upload.html (x-data="uploadForm()") — e.g.
//              manifestBottles/_enrichStatus drive the manifest review panel
//              markup. Rename in both places or the page silently breaks.
// #CLAUDE_REQ: The SSE contract MUST match web/routes/bottles/extraction.py
//              POST /api/v1/bottles/upload/stream: text/event-stream of JSON
//              events {status, message, ...}; on "complete" the event carries
//              {upload_id, bottles, is_manifest}; on "error" a message.
// #CLAUDE_REQ: Enrichment endpoints must match web/routes/management/core.py:
//              POST /api/v1/management/bottles/verify -> {task_id}, then poll
//              GET /api/v1/management/tasks/{task_id}/status -> {status, ...}.
// #CLAUDE_REQ: Autocomplete endpoint must match web/routes/autocomplete.py
//              (GET /api/v1/autocomplete/bottles/purchase_source -> [str]).

window.uploadForm = function uploadForm() {
    return {
        // Bottle editor will be initialized in init()
        bottleEditor: null,
        uploadType: null,  // 'bottle' or 'manifest'
        selectedFile: null,
        previewUrl: null,
        uploading: false,
        statusMessage: '',  // Live progress text streamed from the extraction SSE
        uploadId: null,  // upload_id from the extraction "complete" event (bottle + manifest)
        bottles: [],  // Extracted bottles
        error: false,
        errorMessage: '',
        sessionExpired: false,  // True when a stream request 401s / Access-redirects (lapsed login)
        purchaseSource: '',  // Where bottle was purchased
        acPurchaseSources: [],  // Autocomplete suggestions for purchase source
        inventory: 0,  // Number of bottles in inventory
        // Manifest only: how many line items the user counted on the document.
        // Sent as expected_count so the extractor can tell it came up short —
        // it matters most on phone photos, where a tight crop can clip the
        // quantity column and whole rows sit under glare. '' = don't send.
        expectedCount: '',
        imageLoadHandled: false,  // Flag to ensure we only auto-scroll once

        // Manifest panel state
        manifestBottles: [],
        showManifestPanel: false,

        async init() {
            // Initialize bottle editor modal after all scripts have loaded
            this.bottleEditor = window.bottleEditorModal ? window.bottleEditorModal() : {};
            if (this.bottleEditor && this.bottleEditor.loadAutocomplete) {
                this.bottleEditor.loadAutocomplete();
            }

            // Pre-warm the vision model: LM Studio JIT-loads on first inference,
            // so without this the first import pays the full model load after the
            // Import click. Fire-and-forget — the upload pre-flight still covers
            // a cold model if this fails.
            fetch('/api/v1/bottles/warm-model', { method: 'POST' }).catch(() => {});

            // Load purchase_source autocomplete
            try {
                const resp = await fetch('/api/v1/autocomplete/bottles/purchase_source');
                if (resp.ok) this.acPurchaseSources = await resp.json();
            } catch (e) { /* ignore */ }

            // Prevent iOS scroll restoration on page load
            if ('scrollRestoration' in history) {
                history.scrollRestoration = 'manual';
            }
        },

        handleFileSelect(event) {
            const file = event.target.files[0];
            if (!file) return;

            this.selectedFile = file;
            this.previewUrl = URL.createObjectURL(file);
            this.imageLoadHandled = false;  // Reset flag for new image

            // Auto-scroll to center button in view (one time only)
            setTimeout(() => {
                if (this.$refs.uploadButton && !this.imageLoadHandled) {
                    this.imageLoadHandled = true;

                    // Scroll to button - 'center' alignment for best view of both image and button
                    this.$refs.uploadButton.scrollIntoView({
                        behavior: 'smooth',
                        block: 'center',
                        inline: 'nearest'
                    });
                }
            }, 300);
        },

        clearFile() {
            this.selectedFile = null;
            this.previewUrl = null;
            this.$refs.fileInput.value = '';
            this.imageLoadHandled = false;  // Reset flag
        },

        clearError() {
            this.error = false;
            this.errorMessage = '';
            this.clearFile();
        },

        startParallelEnrichment() {
            // Concurrency limiter: keep at most N enrichments running at once.
            // As each finishes the next queued bottle starts immediately.
            // NOTE: Keep at 1 — LM Studio is single-threaded; concurrent calls
            // cause the second request to wait 60+ seconds for the first,
            // hitting the 120s HTTP timeout. Serial is actually faster overall.
            const CONCURRENCY = 1;
            let active = 0;
            let nextIdx = 0;

            const startNext = () => {
                while (active < CONCURRENCY && nextIdx < this.manifestBottles.length) {
                    const idx = nextIdx++;
                    active++;
                    this.enrichManifestBottle(idx).finally(() => {
                        active--;
                        startNext();
                    });
                }
            };

            startNext();
        },

        async enrichManifestBottle(idx) {
            const bottle = this.manifestBottles[idx];
            bottle._enrichStatus = 'enriching';
            try {
                // Strip internal _fields before sending
                const bottleData = Object.fromEntries(
                    Object.entries(bottle).filter(([k]) => !k.startsWith('_'))
                );
                // Clean numeric empties
                ['year','price','inventory','abv','proof'].forEach(f => {
                    if (bottleData[f] === '') bottleData[f] = null;
                });

                const response = await fetch('/api/v1/management/bottles/verify', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bottle: bottleData })
                });
                if (!response.ok) throw new Error('Failed to start enrichment');

                const { task_id } = await response.json();
                bottle._taskId = task_id;

                const result = await this.pollManifestEnrichment(task_id);
                bottle._enrichResult = result;
                bottle._enrichStatus = 'ready';
            } catch (e) {
                bottle._enrichStatus = 'failed';
                bottle._enrichError = e.message;
            }
        },

        async pollManifestEnrichment(taskId) {
            const maxAttempts = 60;
            const interval = 2000;
            let attempts = 0;
            while (attempts < maxAttempts) {
                const response = await fetch(`/api/v1/management/tasks/${taskId}/status`);
                if (!response.ok) throw new Error('Failed to poll task');
                const result = await response.json();
                if (result.status === 'complete') return result;
                if (result.status === 'failed') throw new Error(result.error || 'Task failed');
                await new Promise(r => setTimeout(r, interval));
                attempts++;
            }
            throw new Error('Enrichment timed out');
        },

        async retryEnrichment(idx) {
            this.manifestBottles[idx]._enrichError = null;
            await this.enrichManifestBottle(idx);
        },

        openBottleForReview(bottle) {
            if (bottle._enrichStatus === 'enriching') return;
            // Open modal for single bottle (no manifestContext → no prev/next nav)
            this.bottleEditor.openUpload(bottle, this.uploadId, null, bottle._enrichResult || null);
            // Set save callback so we can mark the card as saved and advance to next
            this.bottleEditor._onSaveCallback = () => {
                bottle._enrichStatus = 'saved';
                this.advanceToNextReady(bottle);
            };
            // Set skip callback so we can mark the card as skipped and advance to next
            this.bottleEditor._onSkipCallback = () => {
                bottle._enrichStatus = 'skipped';
                this.advanceToNextReady(bottle);
            };
        },

        advanceToNextReady(currentBottle) {
            setTimeout(() => {
                const next = this.manifestBottles.find(
                    b => b !== currentBottle && b._enrichStatus === 'ready'
                );
                if (next) {
                    this.openBottleForReview(next);
                    const el = document.getElementById('bottle-editor-scroll');
                    if (el) el.scrollTop = 0;
                } else {
                    this.bottleEditor.close();
                }
            }, 350);
        },

        resetManifest() {
            this.showManifestPanel = false;
            this.manifestBottles = [];
            // Unlike purchaseSource/inventory (deliberately sticky defaults),
            // the count belongs to the document just finished. Carrying it to
            // the next manifest would feed the extractor a wrong hint.
            this.expectedCount = '';
        },

        handleSessionExpired() {
            // A background upload call hit a lapsed login. Show the re-login
            // prompt instead of a generic error (the finally{} block in
            // uploadFile clears `uploading`/`statusMessage`).
            this.error = false;
            this.sessionExpired = true;
        },

        async uploadFile() {
            if (!this.selectedFile || !this.uploadType) return;

            this.uploading = true;
            this.error = false;
            this.sessionExpired = false;

            const formData = new FormData();
            formData.append('file', this.selectedFile);

            let endpoint;
            if (this.uploadType === 'bottle') {
                formData.append('upload_type', 'bottle_image');
                formData.append('beverage_type', 'auto');
                if (this.purchaseSource) {
                    formData.append('purchase_source', this.purchaseSource);
                }
                formData.append('inventory', this.inventory);
                endpoint = '/api/v1/bottles/upload/stream';
            } else if (this.uploadType === 'manifest') {
                formData.append('upload_type', 'manifest');
                formData.append('beverage_type', 'auto');
                if (this.purchaseSource) {
                    formData.append('purchase_source', this.purchaseSource);
                }
                formData.append('inventory', this.inventory);
                // Optional. Omit entirely when blank or not a positive number —
                // the backend treats a missing expected_count as "no hint", and
                // sending a bogus one would actively mislead the extractor.
                const expected = parseInt(this.expectedCount, 10);
                if (Number.isFinite(expected) && expected > 0) {
                    formData.append('expected_count', expected);
                }
                endpoint = '/api/v1/bottles/upload/stream';
            }

            try {
                // Stream the extraction over SSE. The response starts within ~1s
                // and emits heartbeat events throughout, so the request stays under
                // the upstream proxy idle-timeout instead of blocking ~100s on a
                // single response — a blocking request trips nginx/Cloudflare and
                // looks like a failure even though the backend extraction succeeds.
                const response = await fetch(endpoint, {
                    method: 'POST',
                    body: formData,
                    // 'manual' so a Cloudflare Access login redirect (302 to a
                    // cross-origin domain) surfaces as an opaqueredirect we can
                    // detect, instead of fetch following it and throwing an
                    // opaque "Failed to fetch" that looks like a server outage.
                    redirect: 'manual'
                });

                // Lapsed login: app returns 401 for /api/*, or Access intercepts
                // the POST with a redirect (opaqueredirect under redirect:'manual').
                // A background fetch can't be sent to an interactive login, so
                // prompt a reload rather than showing a generic failure.
                if (response.status === 401 || response.type === 'opaqueredirect') {
                    this.handleSessionExpired();
                    return;
                }

                if (!response.ok) {
                    let detail = `Server error ${response.status}`;
                    try { const e = await response.json(); detail = e.detail || detail; } catch (_) {}
                    throw new Error(detail);
                }

                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let result = null;

                streaming:
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const parts = buffer.split('\n\n');
                    buffer = parts.pop();  // keep incomplete trailing chunk
                    for (const part of parts) {
                        const line = part.trim();
                        if (!line.startsWith('data: ')) continue;
                        let event;
                        try { event = JSON.parse(line.slice(6)); } catch (_) { continue; }
                        if (event.status === 'complete') {
                            result = event;
                            break streaming;
                        } else if (event.status === 'error') {
                            throw new Error(event.message || 'Extraction failed');
                        } else {
                            // Heartbeat / progress — keep the user informed.
                            this.statusMessage = event.message || '';
                        }
                    }
                }

                if (!result) {
                    throw new Error('Upload ended before completion. Please try again.');
                }

                // Extraction complete — hand the bottles straight to the review
                // UI (modal for single/multi bottle, panel for manifests).
                this.uploadId = result.upload_id;
                this.bottles = result.bottles || [];

                if (this.bottles.length === 0) {
                    throw new Error('No bottles extracted from image');
                }

                if (!this.bottleEditor || !this.bottleEditor.openUpload) {
                    throw new Error('Bottle editor not initialized. Please refresh the page.');
                }

                if (this.bottles.length === 1) {
                    // Single bottle - open modal directly (unchanged flow)
                    this.bottleEditor.openUpload(this.bottles[0], this.uploadId, null);
                    this.clearFile();
                    this.uploadType = null;
                } else if (this.uploadType === 'manifest') {
                    // Manifest: show panel with parallel enrichment
                    this.manifestBottles = this.bottles.map((b, i) => ({
                        ...b, _idx: i, _enrichStatus: 'enriching',
                        _taskId: null, _enrichResult: null, _enrichError: null
                    }));
                    this.showManifestPanel = true;
                    this.clearFile();
                    this.uploadType = null;
                    this.startParallelEnrichment();
                } else {
                    // Multiple bottles (non-manifest) - open modal with navigation
                    this.bottleEditor.openUpload(
                        this.bottles[0],
                        this.uploadId,
                        { bottles: this.bottles, currentIndex: 0 }
                    );
                    this.clearFile();
                    this.uploadType = null;
                }
            } catch (err) {
                this.error = true;
                this.errorMessage = err.message || 'Failed to upload file. Please try again.';
            } finally {
                this.uploading = false;
                this.statusMessage = '';
            }
        }
    };
};
