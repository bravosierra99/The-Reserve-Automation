/**
 * Unit tests for the review-bottles page component
 * (src/reserve_automation/web/static/js/upload/review-bottles.js).
 *
 * The REAL bottle-editor-modal module is imported so factory-time composition
 * is tested for real. Alpine itself is not loaded; the factory's return value
 * is used directly, with $nextTick stubbed where the code calls it.
 *
 * The extraction endpoint streams SSE frames over fetch + ReadableStream (not
 * EventSource), so the stream is faked with a stub reader that hands back
 * encoded `data: {json}\n\n` chunks — the exact wire format of
 * POST /api/v1/bottles/upload/stream (web/routes/bottles/extraction.py).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/bottle-editor-modal.js';
import '../../src/reserve_automation/web/static/js/upload/review-bottles.js';

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
 * /api/v1/bottles/upload/stream does. Objects are encoded as
 * `data: {json}\n\n`; raw strings are sent verbatim (partial frames,
 * malformed data).
 */
function sseResponse(events, { ok = true, status = 200 } = {}) {
    const encoder = new TextEncoder();
    const chunks = events.map((e) =>
        encoder.encode(typeof e === 'string' ? e : `data: ${JSON.stringify(e)}\n\n`)
    );
    let i = 0;
    return {
        ok,
        status,
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
    const app = window.uploadBottlesApp();
    app.$nextTick = (fn) => fn();  // Alpine magic property used on single-bottle complete
    return app;
}

const FILE = new File(['fake-bytes'], 'manifest.pdf', { type: 'application/pdf' });

const BOTTLE_A = { producer: 'Weller', name: 'Special Reserve', type: 'whiskey', year: 2020 };
const BOTTLE_B = { producer: 'Ch. Margaux', name: 'Grand Vin', type: 'wine', year: 2015 };

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([]));
    vi.stubGlobal('alert', vi.fn());
    vi.spyOn(console, 'log').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Initial state + composition
// ---------------------------------------------------------------------------

describe('initial state', () => {
    it('starts with the defaults the template bindings expect', () => {
        const app = freshApp();
        expect(app.selectedFile).toBeNull();
        expect(app.uploadType).toBe('bottle_image');
        expect(app.beverageType).toBe('auto');
        expect(app.expectedCount).toBeNull();
        expect(app.purchaseSource).toBe('');
        expect(app.inventory).toBe(0);
        expect(app.uploadInProgress).toBe(false);
        expect(app.uploadComplete).toBe(false);
        expect(app.uploadError).toBe(false);
        expect(app.uploadErrorMessage).toBe('');
        expect(app.statusHeading).toBe('Processing...');
        expect(app.statusMessage).toBe('Please wait...');
        expect(app.uploadId).toBeNull();
        expect(app.extractedBottles).toEqual([]);
        expect(app.isManifest).toBe(false);
        expect(app.bottleSaved).toEqual({});
    });

    it('embeds a real bottle editor instance at factory-call time', () => {
        const app = freshApp();
        expect(app.bottleEditor).toBeTruthy();
        expect(app.bottleEditor.openUpload).toBeTypeOf('function');
        expect(app.bottleEditor.saveUpload).toBeTypeOf('function');
    });

    it('falls back to an empty editor object when the modal script is missing', () => {
        const original = window.bottleEditorModal;
        window.bottleEditorModal = undefined;
        try {
            const app = window.uploadBottlesApp();
            expect(app.bottleEditor).toEqual({});
        } finally {
            window.bottleEditorModal = original;
        }
    });
});

// ---------------------------------------------------------------------------
// handleFileSelect / resetForm / _headingFor
// ---------------------------------------------------------------------------

describe('handleFileSelect', () => {
    it('stores the first selected file', () => {
        const app = freshApp();
        app.handleFileSelect({ target: { files: [FILE] } });
        expect(app.selectedFile).toBe(FILE);
    });
});

describe('resetForm', () => {
    it('clears the progress/error state and restores the default status text', () => {
        const app = freshApp();
        app.uploadInProgress = true;
        app.uploadComplete = true;
        app.uploadError = true;
        app.uploadErrorMessage = 'boom';
        app.statusHeading = 'Analyzing Image...';
        app.statusMessage = '30s elapsed';

        app.resetForm();

        expect(app.uploadInProgress).toBe(false);
        expect(app.uploadComplete).toBe(false);
        expect(app.uploadError).toBe(false);
        expect(app.uploadErrorMessage).toBe('');
        expect(app.statusHeading).toBe('Processing...');
        expect(app.statusMessage).toBe('Please wait...');
    });
});

describe('_headingFor', () => {
    it('maps every SSE status code the stream endpoint emits', () => {
        const app = freshApp();
        expect(app._headingFor('uploading')).toBe('Uploading...');
        expect(app._headingFor('checking_model')).toBe('Connecting to LM Studio...');
        expect(app._headingFor('model_loading')).toBe('Loading Model...');
        expect(app._headingFor('model_ready')).toBe('Model Ready');
        expect(app._headingFor('extracting')).toBe('Analyzing Image...');
    });

    it('falls back to Processing... for unknown statuses', () => {
        const app = freshApp();
        expect(app._headingFor('some_new_status')).toBe('Processing...');
        expect(app._headingFor(undefined)).toBe('Processing...');
    });
});

// ---------------------------------------------------------------------------
// submitUpload — guards, form payload, HTTP errors
// ---------------------------------------------------------------------------

describe('submitUpload payload', () => {
    it('does nothing without a selected file', async () => {
        const app = freshApp();
        await app.submitUpload();
        expect(fetch).not.toHaveBeenCalled();
        expect(app.uploadInProgress).toBe(false);
    });

    it('POSTs multipart form data to the stream endpoint', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/upload/stream', sseResponse([
                { status: 'complete', upload_id: 'up-1', bottles: [BOTTLE_A, BOTTLE_B], is_manifest: true },
            ])],
        ]));
        const app = freshApp();
        app.selectedFile = FILE;
        app.uploadType = 'manifest';
        app.beverageType = 'wine';
        app.expectedCount = 12;
        app.purchaseSource = 'K&L';
        app.inventory = 1;

        await app.submitUpload();

        const [url, opts] = fetch.mock.calls[0];
        expect(url).toBe('/api/v1/bottles/upload/stream');
        expect(opts.method).toBe('POST');
        expect(opts.body).toBeInstanceOf(FormData);
        expect(opts.body.get('file')).toBe(FILE);
        expect(opts.body.get('upload_type')).toBe('manifest');
        expect(opts.body.get('beverage_type')).toBe('wine');
        expect(opts.body.get('expected_count')).toBe('12');
        expect(opts.body.get('purchase_source')).toBe('K&L');
        expect(opts.body.get('inventory')).toBe('1');
    });

    it('omits expected_count and purchase_source when unset', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/upload/stream', sseResponse([
                { status: 'complete', upload_id: 'up-1', bottles: [BOTTLE_A, BOTTLE_B], is_manifest: false },
            ])],
        ]));
        const app = freshApp();
        app.selectedFile = FILE;

        await app.submitUpload();

        const [, opts] = fetch.mock.calls[0];
        expect(opts.body.get('upload_type')).toBe('bottle_image');
        expect(opts.body.get('beverage_type')).toBe('auto');
        expect(opts.body.get('expected_count')).toBeNull();
        expect(opts.body.get('purchase_source')).toBeNull();
        expect(opts.body.get('inventory')).toBe('0');
    });

    it('a non-ok response surfaces the server detail message', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/upload/stream', jsonResponse({ detail: 'LM Studio unreachable' }, { ok: false, status: 502 })],
        ]));
        const app = freshApp();
        app.selectedFile = FILE;

        await app.submitUpload();

        expect(app.uploadError).toBe(true);
        expect(app.uploadErrorMessage).toBe('LM Studio unreachable');
        expect(app.uploadInProgress).toBe(false);
    });

    it('a non-ok response without a JSON body falls back to the status code', async () => {
        vi.stubGlobal('fetch', routeFetch([
            ['/upload/stream', { ok: false, status: 500, json: async () => { throw new Error('not json'); } }],
        ]));
        const app = freshApp();
        app.selectedFile = FILE;

        await app.submitUpload();

        expect(app.uploadErrorMessage).toBe('Server error 500');
    });
});

// ---------------------------------------------------------------------------
// submitUpload — SSE stream handling
// ---------------------------------------------------------------------------

describe('submitUpload stream handling', () => {
    function appWithStream(events) {
        vi.stubGlobal('fetch', routeFetch([
            ['/api/v1/bottles/upload/stream', sseResponse(events)],
        ]));
        const app = freshApp();
        app.selectedFile = FILE;
        return app;
    }

    it('intermediate statuses drive the heading (via _headingFor) and message', async () => {
        const app = appWithStream([
            { status: 'checking_model', message: 'Connecting to LM Studio (qwen)...' },
            { status: 'extracting', message: 'Analyzing bottle label... (10s elapsed)' },
            { status: 'complete', upload_id: 'up-1', bottles: [BOTTLE_A, BOTTLE_B], is_manifest: false },
        ]);
        app.openBottleEditor = vi.fn();

        await app.submitUpload();

        // The last intermediate event before complete set the display
        expect(app.statusHeading).toBe('Analyzing Image...');
        expect(app.statusMessage).toBe('Analyzing bottle label... (10s elapsed)');
    });

    it('an intermediate event without a message blanks the message line', async () => {
        const app = appWithStream([
            { status: 'model_ready' },
            { status: 'complete', upload_id: 'up-1', bottles: [BOTTLE_A, BOTTLE_B], is_manifest: false },
        ]);
        await app.submitUpload();
        expect(app.statusHeading).toBe('Model Ready');
        expect(app.statusMessage).toBe('');
    });

    it('complete stores the extraction result and flips to the review view', async () => {
        const app = appWithStream([
            { status: 'complete', upload_id: 'up-5', bottles: [BOTTLE_A, BOTTLE_B], is_manifest: true },
        ]);
        app.openBottleEditor = vi.fn();

        await app.submitUpload();

        expect(app.uploadId).toBe('up-5');
        expect(app.extractedBottles).toEqual([BOTTLE_A, BOTTLE_B]);
        expect(app.isManifest).toBe(true);
        expect(app.uploadInProgress).toBe(false);
        expect(app.uploadComplete).toBe(true);
        // Multiple bottles: user picks from the grid, no auto-open
        expect(app.openBottleEditor).not.toHaveBeenCalled();
    });

    it('a single extracted bottle auto-opens the editor on $nextTick', async () => {
        const app = appWithStream([
            { status: 'complete', upload_id: 'up-6', bottles: [BOTTLE_A], is_manifest: false },
        ]);
        app.openBottleEditor = vi.fn();

        await app.submitUpload();

        expect(app.openBottleEditor).toHaveBeenCalledWith(0);
    });

    it('complete with missing bottles/is_manifest fields defaults them', async () => {
        const app = appWithStream([{ status: 'complete', upload_id: 'up-7' }]);
        await app.submitUpload();
        expect(app.extractedBottles).toEqual([]);
        expect(app.isManifest).toBe(false);
        expect(app.uploadComplete).toBe(true);
    });

    it('an error event aborts with the streamed message', async () => {
        const app = appWithStream([
            { status: 'uploading', message: 'Saving image...' },
            { status: 'error', message: "the model 'qwen' didn't load in time" },
        ]);
        await app.submitUpload();
        expect(app.uploadError).toBe(true);
        expect(app.uploadErrorMessage).toBe("the model 'qwen' didn't load in time");
        expect(app.uploadInProgress).toBe(false);
    });

    it('an error event without a message uses the fallback text', async () => {
        const app = appWithStream([{ status: 'error' }]);
        await app.submitUpload();
        expect(app.uploadErrorMessage).toBe('Extraction failed');
    });

    it('reassembles events split across chunks and skips malformed frames', async () => {
        const app = appWithStream([
            'data: {not-json}\n\n',
            ': comment line\n\n',
            'data: {"status":"comp',
            'lete","upload_id":"up-9","bottles":[{"producer":"Weller"}],"is_manifest":false}\n\n',
        ]);
        app.openBottleEditor = vi.fn();

        await app.submitUpload();

        expect(app.uploadError).toBe(false);
        expect(app.uploadId).toBe('up-9');
        expect(app.uploadComplete).toBe(true);
    });

    it('KNOWN QUIRK: a stream that ends without a complete event leaves the spinner up', async () => {
        // Extracted verbatim: nothing after the read loop resets
        // uploadInProgress, so a truncated stream strands the progress view.
        const app = appWithStream([{ status: 'extracting', message: 'working' }]);
        await app.submitUpload();
        expect(app.uploadInProgress).toBe(true);
        expect(app.uploadComplete).toBe(false);
        expect(app.uploadError).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// openBottleEditor
// ---------------------------------------------------------------------------

describe('openBottleEditor', () => {
    function appWithEditor() {
        const app = freshApp();
        app.uploadId = 'up-3';
        app.bottleEditor = {
            openUpload: vi.fn(),
            saveUpload: vi.fn(async () => {}),
        };
        return app;
    }

    it('passes manifest navigation context for multi-bottle manifests', () => {
        const app = appWithEditor();
        app.isManifest = true;
        app.extractedBottles = [BOTTLE_A, BOTTLE_B];

        app.openBottleEditor(1);

        expect(app.bottleEditor.openUpload).toHaveBeenCalledWith(BOTTLE_B, 'up-3', {
            bottles: [BOTTLE_A, BOTTLE_B],
            currentIndex: 1,
        });
    });

    it('opens single bottles without manifest context', () => {
        const app = appWithEditor();
        app.isManifest = false;
        app.extractedBottles = [BOTTLE_A];

        app.openBottleEditor(0);

        expect(app.bottleEditor.openUpload).toHaveBeenCalledWith(BOTTLE_A, 'up-3');
    });

    it('a single-bottle manifest also skips the navigation context', () => {
        const app = appWithEditor();
        app.isManifest = true;
        app.extractedBottles = [BOTTLE_A];

        app.openBottleEditor(0);

        expect(app.bottleEditor.openUpload).toHaveBeenCalledWith(BOTTLE_A, 'up-3');
    });

    it('wraps saveUpload so a save marks the card in bottleSaved', async () => {
        const app = appWithEditor();
        app.isManifest = true;
        app.extractedBottles = [BOTTLE_A, BOTTLE_B];
        const originalSave = app.bottleEditor.saveUpload;

        app.openBottleEditor(1);
        expect(app.bottleSaved[1]).toBeUndefined();

        await app.bottleEditor.saveUpload();

        expect(originalSave).toHaveBeenCalledTimes(1);
        expect(app.bottleSaved[1]).toBe(true);
        expect(app.bottleSaved[0]).toBeUndefined();
    });
});
