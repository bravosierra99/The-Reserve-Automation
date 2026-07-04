/**
 * Unit tests for the import page root component
 * (src/reserve_automation/web/static/js/upload/upload-page.js).
 *
 * The REAL bottle-editor-modal module is imported so init()'s composition is
 * tested for real. Alpine itself is not loaded; the factory's return value is
 * used directly with $refs stubbed the way Alpine would provide them.
 *
 * The extraction endpoint streams SSE frames over fetch + ReadableStream (not
 * EventSource), so the stream is faked with a stub reader that hands back
 * encoded `data: {json}\n\n` chunks — the exact wire format of
 * POST /api/v1/bottles/upload/stream (web/routes/bottles/extraction.py).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/bottle-editor-modal.js';
import '../../src/reserve_automation/web/static/js/upload/upload-page.js';

function jsonResponse(data, { ok = true, status = 200 } = {}) {
    return {
        ok,
        status,
        json: async () => data,
        text: async () => JSON.stringify(data),
    };
}

function routeFetch(routes) {
    return vi.fn(async (url, opts) => {
        for (const [needle, responder] of routes) {
            if (String(url).includes(needle)) {
                return typeof responder === 'function' ? responder(url, opts) : responder;
            }
        }
        return jsonResponse({});
    });
}

/**
 * Build a fetch Response whose body streams SSE frames the way
 * /api/v1/bottles/upload/stream does. Each event may be an object (encoded
 * as `data: {json}\n\n`) or a raw string chunk (sent verbatim, for testing
 * partial-frame buffering and malformed data).
 */
function sseResponse(events, { ok = true, status = 200, type = 'basic' } = {}) {
    const encoder = new TextEncoder();
    const chunks = events.map((e) =>
        encoder.encode(typeof e === 'string' ? e : `data: ${JSON.stringify(e)}\n\n`)
    );
    let i = 0;
    return {
        ok,
        status,
        type,
        json: async () => ({}),
        body: {
            getReader: () => ({
                read: async () =>
                    i < chunks.length
                        ? { done: false, value: chunks[i++] }
                        : { done: true, value: undefined },
            }),
        },
    };
}

function freshApp() {
    const app = window.uploadForm();
    // Alpine magic properties the component uses
    app.$refs = {
        fileInput: { value: 'stale.jpg' },
        uploadButton: { scrollIntoView: vi.fn() },
    };
    return app;
}

const FILE = new File(['fake-bytes'], 'label.jpg', { type: 'image/jpeg' });

const BOTTLE_A = { producer: 'Weller', name: 'Special Reserve', type: 'whiskey', year: 2020 };
const BOTTLE_B = { producer: 'Ch. Margaux', name: 'Grand Vin', type: 'wine', year: 2015 };

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([]));
    vi.stubGlobal('alert', vi.fn());
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    URL.createObjectURL = vi.fn(() => 'blob:preview-1');
});

afterEach(() => {
    delete URL.createObjectURL;
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

describe('initial state', () => {
    it('starts with a clean slate matching the template bindings', () => {
        const app = freshApp();
        expect(app.bottleEditor).toBeNull();
        expect(app.uploadType).toBeNull();
        expect(app.selectedFile).toBeNull();
        expect(app.uploading).toBe(false);
        expect(app.statusMessage).toBe('');
        expect(app.error).toBe(false);
        expect(app.sessionExpired).toBe(false);
        expect(app.purchaseSource).toBe('');
        expect(app.acPurchaseSources).toEqual([]);
        expect(app.inventory).toBe(0);
        expect(app.manifestBottles).toEqual([]);
        expect(app.showManifestPanel).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// init() — modal composition + autocomplete
// ---------------------------------------------------------------------------

describe('init', () => {
    it('composes the real bottle editor modal and kicks off its autocomplete', async () => {
        const app = freshApp();
        await app.init();
        expect(app.bottleEditor).toBeTruthy();
        expect(app.bottleEditor.openUpload).toBeTypeOf('function');
        // loadAutocomplete on the real modal fires field fetches
        const urls = fetch.mock.calls.map(([u]) => String(u));
        expect(urls.some((u) => u.startsWith('/api/v1/autocomplete/bottles/'))).toBe(true);
    });

    it('loads purchase_source autocomplete suggestions', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/autocomplete/bottles/purchase_source', jsonResponse(['Total Wine', 'K&L'])],
            ['/api/v1/autocomplete/bottles/', jsonResponse([])],
        ]));
        const app = freshApp();
        await app.init();
        expect(app.acPurchaseSources).toEqual(['Total Wine', 'K&L']);
    });

    it('leaves suggestions empty when the autocomplete response is not ok', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/autocomplete/bottles/purchase_source', jsonResponse({ detail: 'nope' }, { ok: false, status: 500 })],
            ['/api/v1/autocomplete/bottles/', jsonResponse([])],
        ]));
        const app = freshApp();
        await app.init();
        expect(app.acPurchaseSources).toEqual([]);
    });

    it('survives a network failure on the autocomplete fetch', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('offline'); }));
        const app = freshApp();
        await expect(app.init()).resolves.toBeUndefined();
        expect(app.acPurchaseSources).toEqual([]);
    });

    it('falls back to an empty editor object when the modal script is missing', async () => {
        const original = window.bottleEditorModal;
        window.bottleEditorModal = undefined;
        try {
            const app = freshApp();
            await app.init();
            expect(app.bottleEditor).toEqual({});
        } finally {
            window.bottleEditorModal = original;
        }
    });
});

// ---------------------------------------------------------------------------
// handleFileSelect / clearFile / clearError
// ---------------------------------------------------------------------------

describe('handleFileSelect', () => {
    it('ignores an empty selection', () => {
        const app = freshApp();
        app.handleFileSelect({ target: { files: [] } });
        expect(app.selectedFile).toBeNull();
        expect(app.previewUrl).toBeNull();
    });

    it('stores the file, builds a preview URL and auto-scrolls once after 300ms', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.handleFileSelect({ target: { files: [FILE] } });

        expect(app.selectedFile).toBe(FILE);
        expect(URL.createObjectURL).toHaveBeenCalledWith(FILE);
        expect(app.previewUrl).toBe('blob:preview-1');
        expect(app.imageLoadHandled).toBe(false);
        expect(app.$refs.uploadButton.scrollIntoView).not.toHaveBeenCalled();

        await vi.advanceTimersByTimeAsync(300);
        expect(app.imageLoadHandled).toBe(true);
        expect(app.$refs.uploadButton.scrollIntoView).toHaveBeenCalledWith({
            behavior: 'smooth',
            block: 'center',
            inline: 'nearest',
        });
        expect(app.$refs.uploadButton.scrollIntoView).toHaveBeenCalledTimes(1);
    });

    it('does not crash when the upload button ref is absent', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.$refs.uploadButton = null;
        app.handleFileSelect({ target: { files: [FILE] } });
        await vi.advanceTimersByTimeAsync(300);
        expect(app.imageLoadHandled).toBe(false);
    });
});

describe('clearFile / clearError', () => {
    it('clearFile resets file state and the native input', () => {
        const app = freshApp();
        app.selectedFile = FILE;
        app.previewUrl = 'blob:preview-1';
        app.imageLoadHandled = true;

        app.clearFile();

        expect(app.selectedFile).toBeNull();
        expect(app.previewUrl).toBeNull();
        expect(app.$refs.fileInput.value).toBe('');
        expect(app.imageLoadHandled).toBe(false);
    });

    it('clearError clears the error flags and delegates to clearFile', () => {
        const app = freshApp();
        app.error = true;
        app.errorMessage = 'boom';
        app.selectedFile = FILE;
        app.clearError();
        expect(app.error).toBe(false);
        expect(app.errorMessage).toBe('');
        expect(app.selectedFile).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// uploadFile — guards, form payload, session expiry, HTTP errors
// ---------------------------------------------------------------------------

describe('uploadFile guards and payload', () => {
    it('does nothing without a selected file', async () => {
        const app = freshApp();
        app.uploadType = 'bottle';
        await app.uploadFile();
        expect(fetch).not.toHaveBeenCalled();
    });

    it('does nothing without an upload type', async () => {
        const app = freshApp();
        app.selectedFile = FILE;
        await app.uploadFile();
        expect(fetch).not.toHaveBeenCalled();
    });

    it('POSTs multipart form data to the stream endpoint with redirect:"manual" (bottle)', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/upload/stream', sseResponse([
                { status: 'complete', upload_id: 'up-1', bottles: [BOTTLE_A], is_manifest: false },
            ])],
        ]));
        const app = freshApp();
        app.bottleEditor = { openUpload: vi.fn() };
        app.selectedFile = FILE;
        app.uploadType = 'bottle';
        app.inventory = 2;

        await app.uploadFile();

        const [url, opts] = fetch.mock.calls[0];
        expect(url).toBe('/api/v1/bottles/upload/stream');
        expect(opts.method).toBe('POST');
        expect(opts.redirect).toBe('manual');
        expect(opts.body).toBeInstanceOf(FormData);
        expect(opts.body.get('file')).toBe(FILE);
        expect(opts.body.get('upload_type')).toBe('bottle_image');
        expect(opts.body.get('beverage_type')).toBe('auto');
        expect(opts.body.get('inventory')).toBe('2');
        expect(opts.body.get('purchase_source')).toBeNull();
    });

    it('includes purchase_source when set and sends upload_type=manifest for manifests', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/upload/stream', sseResponse([
                { status: 'complete', upload_id: 'up-2', bottles: [BOTTLE_A], is_manifest: true },
            ])],
        ]));
        const app = freshApp();
        app.bottleEditor = { openUpload: vi.fn() };
        app.selectedFile = FILE;
        app.uploadType = 'manifest';
        app.purchaseSource = 'Total Wine';

        await app.uploadFile();

        const [, opts] = fetch.mock.calls[0];
        expect(opts.body.get('upload_type')).toBe('manifest');
        expect(opts.body.get('purchase_source')).toBe('Total Wine');
    });

    it('a 401 shows the session-expired prompt, not a generic error', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/upload/stream', jsonResponse({}, { ok: false, status: 401 })],
        ]));
        const app = freshApp();
        app.selectedFile = FILE;
        app.uploadType = 'bottle';

        await app.uploadFile();

        expect(app.sessionExpired).toBe(true);
        expect(app.error).toBe(false);
        expect(app.uploading).toBe(false);
    });

    it('an opaqueredirect (Cloudflare Access login) also shows session-expired', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/upload/stream', { ok: false, status: 0, type: 'opaqueredirect', json: async () => ({}) }],
        ]));
        const app = freshApp();
        app.selectedFile = FILE;
        app.uploadType = 'bottle';

        await app.uploadFile();

        expect(app.sessionExpired).toBe(true);
        expect(app.error).toBe(false);
    });

    it('a non-ok response surfaces the server detail message', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/upload/stream', jsonResponse({ detail: 'LM Studio unreachable' }, { ok: false, status: 502 })],
        ]));
        const app = freshApp();
        app.selectedFile = FILE;
        app.uploadType = 'bottle';

        await app.uploadFile();

        expect(app.error).toBe(true);
        expect(app.errorMessage).toBe('LM Studio unreachable');
        expect(app.uploading).toBe(false);
    });

    it('a non-ok response without a JSON body falls back to the status code', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/upload/stream', { ok: false, status: 500, type: 'basic', json: async () => { throw new Error('not json'); } }],
        ]));
        const app = freshApp();
        app.selectedFile = FILE;
        app.uploadType = 'bottle';

        await app.uploadFile();

        expect(app.errorMessage).toBe('Server error 500');
    });
});

// ---------------------------------------------------------------------------
// uploadFile — SSE stream handling
// ---------------------------------------------------------------------------

describe('uploadFile stream handling', () => {
    function appWithStream(events, { uploadType = 'bottle' } = {}) {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/upload/stream', sseResponse(events)],
        ]));
        const app = freshApp();
        app.bottleEditor = { openUpload: vi.fn() };
        app.selectedFile = FILE;
        app.uploadType = uploadType;
        return app;
    }

    it('heartbeat events update statusMessage mid-stream; finally clears it', async () => {
        const seen = [];
        const app = appWithStream([
            { status: 'extracting', message: 'Analyzing bottle label... (15s elapsed)' },
            { status: 'complete', upload_id: 'up-1', bottles: [BOTTLE_A], is_manifest: false },
        ]);
        const editor = app.bottleEditor;
        editor.openUpload.mockImplementation(() => seen.push(app.statusMessage));

        await app.uploadFile();

        // statusMessage held the heartbeat text while streaming...
        expect(seen).toEqual(['Analyzing bottle label... (15s elapsed)']);
        // ...and is cleared by the finally block
        expect(app.statusMessage).toBe('');
        expect(app.uploading).toBe(false);
    });

    it('an error event aborts with the streamed message', async () => {
        const app = appWithStream([
            { status: 'checking_model', message: 'Connecting...' },
            { status: 'error', message: "the model 'qwen' didn't load in time" },
        ]);
        await app.uploadFile();
        expect(app.error).toBe(true);
        expect(app.errorMessage).toBe("the model 'qwen' didn't load in time");
    });

    it('an error event without a message uses the fallback text', async () => {
        const app = appWithStream([{ status: 'error' }]);
        await app.uploadFile();
        expect(app.errorMessage).toBe('Extraction failed');
    });

    it('a stream that ends without a complete event is an error', async () => {
        const app = appWithStream([{ status: 'uploading', message: 'Saving image...' }]);
        await app.uploadFile();
        expect(app.error).toBe(true);
        expect(app.errorMessage).toBe('Upload ended before completion. Please try again.');
    });

    it('reassembles events split across chunks and skips malformed frames', async () => {
        const app = appWithStream([
            'data: {not-json}\n\n',
            ': comment line\n\n',
            'data: {"status":"comp',
            'lete","upload_id":"up-9","bottles":[{"producer":"Weller","name":"12"}],"is_manifest":false}\n\n',
        ]);
        await app.uploadFile();
        expect(app.error).toBe(false);
        expect(app.uploadId).toBe('up-9');
        expect(app.bottleEditor.openUpload).toHaveBeenCalledTimes(1);
    });

    it('complete with zero bottles is an error', async () => {
        const app = appWithStream([
            { status: 'complete', upload_id: 'up-1', bottles: [], is_manifest: false },
        ]);
        await app.uploadFile();
        expect(app.error).toBe(true);
        expect(app.errorMessage).toBe('No bottles extracted from image');
    });

    it('complete with a missing bottles field is treated as zero bottles', async () => {
        const app = appWithStream([{ status: 'complete', upload_id: 'up-1' }]);
        await app.uploadFile();
        expect(app.bottles).toEqual([]);
        expect(app.errorMessage).toBe('No bottles extracted from image');
    });

    it('errors when the bottle editor never initialized', async () => {
        const app = appWithStream([
            { status: 'complete', upload_id: 'up-1', bottles: [BOTTLE_A], is_manifest: false },
        ]);
        app.bottleEditor = null;
        await app.uploadFile();
        expect(app.error).toBe(true);
        expect(app.errorMessage).toBe('Bottle editor not initialized. Please refresh the page.');
    });

    it('single bottle: opens the modal directly and resets the form', async () => {
        const app = appWithStream([
            { status: 'complete', upload_id: 'up-1', bottles: [BOTTLE_A], is_manifest: false },
        ]);
        await app.uploadFile();

        expect(app.bottleEditor.openUpload).toHaveBeenCalledWith(BOTTLE_A, 'up-1', null);
        expect(app.uploadId).toBe('up-1');
        expect(app.selectedFile).toBeNull();
        expect(app.uploadType).toBeNull();
        expect(app.error).toBe(false);
    });

    it('multiple bottles (non-manifest): opens the modal with navigation context', async () => {
        const app = appWithStream([
            { status: 'complete', upload_id: 'up-3', bottles: [BOTTLE_A, BOTTLE_B], is_manifest: false },
        ]);
        await app.uploadFile();

        expect(app.bottleEditor.openUpload).toHaveBeenCalledWith(
            BOTTLE_A, 'up-3', { bottles: [BOTTLE_A, BOTTLE_B], currentIndex: 0 }
        );
        expect(app.showManifestPanel).toBe(false);
    });

    it('manifest with multiple bottles: opens the review panel and starts enrichment', async () => {
        const app = appWithStream(
            [{ status: 'complete', upload_id: 'up-4', bottles: [BOTTLE_A, BOTTLE_B], is_manifest: true }],
            { uploadType: 'manifest' }
        );
        app.startParallelEnrichment = vi.fn();

        await app.uploadFile();

        expect(app.showManifestPanel).toBe(true);
        expect(app.manifestBottles).toHaveLength(2);
        expect(app.manifestBottles[0]).toMatchObject({
            ...BOTTLE_A, _idx: 0, _enrichStatus: 'enriching',
            _taskId: null, _enrichResult: null, _enrichError: null,
        });
        expect(app.startParallelEnrichment).toHaveBeenCalledTimes(1);
        expect(app.bottleEditor.openUpload).not.toHaveBeenCalled();
        expect(app.uploadType).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// Manifest enrichment (verify + task polling)
// ---------------------------------------------------------------------------

describe('enrichManifestBottle', () => {
    it('POSTs the bottle with _fields stripped and numeric empties nulled', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/management/bottles/verify', jsonResponse({ task_id: 't-1', status: 'processing' })],
            ['/api/v1/management/tasks/t-1/status', jsonResponse({ status: 'complete', changes: { region: 'Kentucky' } })],
        ]));
        const app = freshApp();
        app.manifestBottles = [{
            producer: 'Weller', name: '12', year: '', price: '', abv: '', proof: '', inventory: '',
            _idx: 0, _enrichStatus: 'enriching', _taskId: null, _enrichResult: null, _enrichError: null,
        }];

        await app.enrichManifestBottle(0);

        const verifyCall = fetch.mock.calls.find(([u]) => String(u).includes('/bottles/verify'));
        const [url, opts] = verifyCall;
        expect(url).toBe('/api/v1/management/bottles/verify');
        expect(opts.method).toBe('POST');
        expect(opts.headers).toEqual({ 'Content-Type': 'application/json' });
        expect(JSON.parse(opts.body)).toEqual({
            bottle: {
                producer: 'Weller', name: '12',
                year: null, price: null, abv: null, proof: null, inventory: null,
            },
        });

        expect(app.manifestBottles[0]._taskId).toBe('t-1');
        expect(app.manifestBottles[0]._enrichStatus).toBe('ready');
        expect(app.manifestBottles[0]._enrichResult).toEqual({ status: 'complete', changes: { region: 'Kentucky' } });
    });

    it('marks the bottle failed when the verify request fails', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/bottles/verify', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        app.manifestBottles = [{ producer: 'X', _enrichStatus: 'enriching' }];

        await app.enrichManifestBottle(0);

        expect(app.manifestBottles[0]._enrichStatus).toBe('failed');
        expect(app.manifestBottles[0]._enrichError).toBe('Failed to start enrichment');
    });

    it('marks the bottle failed when the task reports failure', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/bottles/verify', jsonResponse({ task_id: 't-2' })],
            ['/tasks/t-2/status', jsonResponse({ status: 'failed', error: 'LLM timeout' })],
        ]));
        const app = freshApp();
        app.manifestBottles = [{ producer: 'X', _enrichStatus: 'enriching' }];

        await app.enrichManifestBottle(0);

        expect(app.manifestBottles[0]._enrichStatus).toBe('failed');
        expect(app.manifestBottles[0]._enrichError).toBe('LLM timeout');
    });
});

describe('pollManifestEnrichment', () => {
    it('polls every 2s until the task completes', async () => {
        vi.useFakeTimers();
        let polls = 0;
        vi.stubGlobal('fetch', routeFetch([
            ['/tasks/t-1/status', () => {
                polls++;
                return jsonResponse(polls < 3 ? { status: 'processing' } : { status: 'complete', changes: {} });
            }],
        ]));
        const app = freshApp();

        const promise = app.pollManifestEnrichment('t-1');
        await vi.advanceTimersByTimeAsync(2 * 2000);
        const result = await promise;

        expect(result).toEqual({ status: 'complete', changes: {} });
        expect(polls).toBe(3);
        expect(fetch).toHaveBeenCalledWith('/api/v1/management/tasks/t-1/status');
    });

    it('throws the generic message when a failed task has no error field', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/tasks/', jsonResponse({ status: 'failed' })],
        ]));
        const app = freshApp();
        await expect(app.pollManifestEnrichment('t-9')).rejects.toThrow('Task failed');
    });

    it('throws when a poll request is not ok', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/tasks/', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        await expect(app.pollManifestEnrichment('t-9')).rejects.toThrow('Failed to poll task');
    });

    it('times out after 60 attempts', async () => {
        vi.useFakeTimers();
        vi.stubGlobal('fetch', routeFetch([
            ['/tasks/', jsonResponse({ status: 'processing' })],
        ]));
        const app = freshApp();

        const promise = app.pollManifestEnrichment('t-slow');
        const assertion = expect(promise).rejects.toThrow('Enrichment timed out');
        await vi.advanceTimersByTimeAsync(60 * 2000);
        await assertion;
        expect(fetch).toHaveBeenCalledTimes(60);
    });
});

describe('startParallelEnrichment', () => {
    it('runs enrichments serially (CONCURRENCY = 1, LM Studio is single-threaded)', async () => {
        const app = freshApp();
        app.manifestBottles = [{}, {}, {}];
        const resolvers = [];
        app.enrichManifestBottle = vi.fn(
            () => new Promise((resolve) => resolvers.push(resolve))
        );

        app.startParallelEnrichment();
        expect(app.enrichManifestBottle).toHaveBeenCalledTimes(1);
        expect(app.enrichManifestBottle).toHaveBeenLastCalledWith(0);

        resolvers[0]();
        await new Promise((r) => setTimeout(r));
        expect(app.enrichManifestBottle).toHaveBeenCalledTimes(2);
        expect(app.enrichManifestBottle).toHaveBeenLastCalledWith(1);

        resolvers[1]();
        await new Promise((r) => setTimeout(r));
        expect(app.enrichManifestBottle).toHaveBeenCalledTimes(3);

        resolvers[2]();
        await new Promise((r) => setTimeout(r));
        expect(app.enrichManifestBottle).toHaveBeenCalledTimes(3);  // no 4th bottle
    });

    it('advances past a bottle whose enrichment failed (enrichManifestBottle resolves after catching)', async () => {
        // enrichManifestBottle never rejects — it catches internally and marks
        // the bottle failed — so the .finally() chain always reaches the next
        // bottle. Simulate that real contract here.
        vi.stubGlobal('fetch', routeFetch([
            ['/bottles/verify', jsonResponse({}, { ok: false, status: 500 })],
        ]));
        const app = freshApp();
        app.manifestBottles = [
            { producer: 'A', _enrichStatus: 'enriching' },
            { producer: 'B', _enrichStatus: 'enriching' },
        ];

        app.startParallelEnrichment();
        await new Promise((r) => setTimeout(r));

        expect(app.manifestBottles[0]._enrichStatus).toBe('failed');
        expect(app.manifestBottles[1]._enrichStatus).toBe('failed');
    });
});

describe('retryEnrichment', () => {
    it('clears the previous error and re-runs enrichment for that index', async () => {
        const app = freshApp();
        app.manifestBottles = [{ _enrichError: 'old failure' }];
        app.enrichManifestBottle = vi.fn(async () => {});

        await app.retryEnrichment(0);

        expect(app.manifestBottles[0]._enrichError).toBeNull();
        expect(app.enrichManifestBottle).toHaveBeenCalledWith(0);
    });
});

// ---------------------------------------------------------------------------
// Manifest review flow (modal integration)
// ---------------------------------------------------------------------------

describe('openBottleForReview', () => {
    function appWithEditor() {
        const app = freshApp();
        app.uploadId = 'up-7';
        app.bottleEditor = { openUpload: vi.fn(), close: vi.fn() };
        return app;
    }

    it('refuses to open a bottle that is still enriching', () => {
        const app = appWithEditor();
        app.openBottleForReview({ _enrichStatus: 'enriching' });
        expect(app.bottleEditor.openUpload).not.toHaveBeenCalled();
    });

    it('opens the modal with the preloaded enrich result and no manifest nav', () => {
        const app = appWithEditor();
        const bottle = { producer: 'Weller', _enrichStatus: 'ready', _enrichResult: { changes: { region: 'KY' } } };
        app.openBottleForReview(bottle);
        expect(app.bottleEditor.openUpload).toHaveBeenCalledWith(
            bottle, 'up-7', null, { changes: { region: 'KY' } }
        );
    });

    it('passes null when there is no enrich result (failed bottles reviewed anyway)', () => {
        const app = appWithEditor();
        const bottle = { producer: 'X', _enrichStatus: 'failed', _enrichResult: undefined };
        app.openBottleForReview(bottle);
        expect(app.bottleEditor.openUpload).toHaveBeenCalledWith(bottle, 'up-7', null, null);
    });

    it('the save callback marks the card saved and advances', () => {
        const app = appWithEditor();
        app.advanceToNextReady = vi.fn();
        const bottle = { _enrichStatus: 'ready', _enrichResult: null };

        app.openBottleForReview(bottle);
        app.bottleEditor._onSaveCallback();

        expect(bottle._enrichStatus).toBe('saved');
        expect(app.advanceToNextReady).toHaveBeenCalledWith(bottle);
    });

    it('the skip callback marks the card skipped and advances', () => {
        const app = appWithEditor();
        app.advanceToNextReady = vi.fn();
        const bottle = { _enrichStatus: 'ready', _enrichResult: null };

        app.openBottleForReview(bottle);
        app.bottleEditor._onSkipCallback();

        expect(bottle._enrichStatus).toBe('skipped');
        expect(app.advanceToNextReady).toHaveBeenCalledWith(bottle);
    });
});

describe('advanceToNextReady', () => {
    it('after 350ms opens the next ready bottle and resets the modal scroll', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.bottleEditor = { openUpload: vi.fn(), close: vi.fn() };
        const current = { _enrichStatus: 'saved' };
        const next = { _enrichStatus: 'ready' };
        app.manifestBottles = [current, { _enrichStatus: 'enriching' }, next];
        app.openBottleForReview = vi.fn();

        const scrollEl = document.createElement('div');
        scrollEl.id = 'bottle-editor-scroll';
        scrollEl.scrollTop = 400;
        document.body.appendChild(scrollEl);

        app.advanceToNextReady(current);
        expect(app.openBottleForReview).not.toHaveBeenCalled();
        await vi.advanceTimersByTimeAsync(350);

        expect(app.openBottleForReview).toHaveBeenCalledWith(next);
        expect(scrollEl.scrollTop).toBe(0);
        expect(app.bottleEditor.close).not.toHaveBeenCalled();
        scrollEl.remove();
    });

    it('skips the current bottle even if it still reads ready', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.bottleEditor = { close: vi.fn() };
        const current = { _enrichStatus: 'ready' };
        app.manifestBottles = [current];
        app.openBottleForReview = vi.fn();

        app.advanceToNextReady(current);
        await vi.advanceTimersByTimeAsync(350);

        expect(app.openBottleForReview).not.toHaveBeenCalled();
        expect(app.bottleEditor.close).toHaveBeenCalled();
    });

    it('closes the modal when nothing is left to review', async () => {
        vi.useFakeTimers();
        const app = freshApp();
        app.bottleEditor = { close: vi.fn() };
        app.manifestBottles = [{ _enrichStatus: 'saved' }, { _enrichStatus: 'skipped' }];

        app.advanceToNextReady(app.manifestBottles[0]);
        await vi.advanceTimersByTimeAsync(350);

        expect(app.bottleEditor.close).toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------------------
// Small state helpers
// ---------------------------------------------------------------------------

describe('resetManifest / handleSessionExpired', () => {
    it('resetManifest hides the panel and empties the list', () => {
        const app = freshApp();
        app.showManifestPanel = true;
        app.manifestBottles = [{ producer: 'X' }];
        app.resetManifest();
        expect(app.showManifestPanel).toBe(false);
        expect(app.manifestBottles).toEqual([]);
    });

    it('handleSessionExpired swaps the generic error for the re-login prompt', () => {
        const app = freshApp();
        app.error = true;
        app.handleSessionExpired();
        expect(app.error).toBe(false);
        expect(app.sessionExpired).toBe(true);
    });
});
