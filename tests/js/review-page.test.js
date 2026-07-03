/**
 * Unit tests for the extraction review page component
 * (src/reserve_automation/web/static/js/review/review-page.js).
 *
 * Alpine itself is not loaded; the factory's return value is used directly.
 * Fixtures mirror the real API shapes in web/routes/review.py:
 * GET /api/v1/extractions/{id} → {extraction_id, extraction_type,
 * upload_filename, template_type, data, match_previews}, PUT the same path
 * with {extraction_data}, POST /api/v1/review/{id}/approve →
 * {status, files_created, unmatched, ...}, POST /api/v1/review/{id}/reject.
 *
 * Per-type note keys are pinned here: the *_str round-trip touches ONLY the
 * whiskey note keys (nose_notes/palate_notes/finish_notes). Wine tastings keep
 * their appearance/aroma/taste/aftertaste fields untouched (July 2026
 * note-wiping regression guard).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/review/review-page.js';

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

const EXTRACTION_ID = 'ext-42';

// Mirrors GET /api/v1/extractions/{extraction_id} (routes/review.py
// get_extraction) for a bourbon tasting card. Note the whiskey note keys.
function bourbonExtraction() {
    return {
        extraction_id: EXTRACTION_ID,
        extraction_type: 'tasting',
        upload_filename: 'card.jpg',
        template_type: 'bourbon',
        data: {
            template_type: 'bourbon',
            tastings: [
                {
                    bottle_name: 'Weller 12',
                    taster_name: 'Ben',
                    tasting_date: '2026-07-01',
                    days_from_crack: 30,
                    fill_level: 80,
                    whiskey_nose: 2.5,
                    whiskey_palate: 2.5,
                    whiskey_finish: 2,
                    whiskey_overall: 0.8,
                    nose_notes: ['caramel', 'oak'],
                    palate_notes: ['cherry'],
                    finish_notes: [],
                    overall_notes: 'Great pour',
                },
            ],
        },
        match_previews: [
            { matched: true, matched_to: 'Weller 12', confidence: 0.91 },
        ],
    };
}

// A wine (aws_wine) extraction: scores use the WINE keys and there are no
// whiskey note arrays at all.
function wineExtraction() {
    return {
        extraction_id: EXTRACTION_ID,
        extraction_type: 'tasting',
        upload_filename: 'card.jpg',
        template_type: 'aws_wine',
        data: {
            template_type: 'aws_wine',
            tastings: [
                {
                    bottle_name: 'Grand Cru',
                    taster_name: 'Sarah',
                    tasting_date: '2026-07-01',
                    wine_appearance: 3,
                    wine_aroma: 5,
                    wine_taste: 4,
                    wine_aftertaste: 1.5,
                    wine_overall: 1.5,
                    overall_notes: 'Lovely',
                },
            ],
        },
        match_previews: [
            { matched: false },
        ],
    };
}

function freshForm() {
    return window.reviewForm();
}

async function loadedForm(extraction = bourbonExtraction(), routes = []) {
    // Custom routes first so a test's responder for the same URL (e.g. the
    // PUT-failure case) is not shadowed by the default GET route.
    vi.stubGlobal('fetch', routeFetch([
        ...routes,
        [`/api/v1/extractions/${EXTRACTION_ID}`, jsonResponse(extraction)],
    ]));
    const form = freshForm();
    await form.loadExtraction();
    return form;
}

beforeEach(() => {
    vi.stubGlobal('location', { pathname: `/review/${EXTRACTION_ID}`, href: '' });
    vi.stubGlobal('fetch', routeFetch([]));
    vi.stubGlobal('alert', vi.fn());
    vi.stubGlobal('confirm', vi.fn(() => true));
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Initial state
// ---------------------------------------------------------------------------

describe('initial state', () => {
    it('parses extractionId from the URL path (/review/{id})', () => {
        expect(freshForm().extractionId).toBe(EXTRACTION_ID);
    });

    it('starts loading with everything else reset', () => {
        const form = freshForm();
        expect(form.loading).toBe(true);
        expect(form.error).toBe(false);
        expect(form.errorMessage).toBe('');
        expect(form.extraction).toBeNull();
        expect(form.matchPreviews).toEqual([]);
        expect(form.approving).toBe(false);
        expect(form.rejecting).toBe(false);
        expect(form.approved).toBe(false);
        expect(form.approvalResult).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// loadExtraction
// ---------------------------------------------------------------------------

describe('loadExtraction', () => {
    it('fetches the extraction and exposes match previews', async () => {
        const form = await loadedForm();

        expect(fetch).toHaveBeenCalledWith(`/api/v1/extractions/${EXTRACTION_ID}`);
        expect(form.extraction.template_type).toBe('bourbon');
        expect(form.matchPreviews).toEqual([
            { matched: true, matched_to: 'Weller 12', confidence: 0.91 },
        ]);
        expect(form.loading).toBe(false);
        expect(form.error).toBe(false);
    });

    it('joins whiskey note arrays into comma-separated *_str fields for editing', async () => {
        const form = await loadedForm();
        const t = form.extraction.data.tastings[0];

        expect(t.nose_notes_str).toBe('caramel, oak');
        expect(t.palate_notes_str).toBe('cherry');
        expect(t.finish_notes_str).toBe('');
        // Original arrays untouched by the display conversion.
        expect(t.nose_notes).toEqual(['caramel', 'oak']);
    });

    it('leaves wine tastings alone apart from empty *_str placeholders', async () => {
        const form = await loadedForm(wineExtraction());
        const t = form.extraction.data.tastings[0];

        // Wine scores keep their wine keys, untouched.
        expect(t.wine_appearance).toBe(3);
        expect(t.wine_aroma).toBe(5);
        expect(t.wine_taste).toBe(4);
        expect(t.wine_aftertaste).toBe(1.5);
        // No whiskey note arrays are invented on wine tastings...
        expect(t.nose_notes).toBeUndefined();
        expect(t.palate_notes).toBeUndefined();
        expect(t.finish_notes).toBeUndefined();
        // ...only the (empty) editing strings.
        expect(t.nose_notes_str).toBe('');
        expect(t.palate_notes_str).toBe('');
        expect(t.finish_notes_str).toBe('');
    });

    it('defaults matchPreviews to [] when the payload omits them', async () => {
        const extraction = bourbonExtraction();
        delete extraction.match_previews;
        const form = await loadedForm(extraction);
        expect(form.matchPreviews).toEqual([]);
    });

    it('flags an error state on a failed response', async () => {
        vi.stubGlobal('fetch', routeFetch([
            [`/api/v1/extractions/${EXTRACTION_ID}`, jsonResponse({}, { ok: false, status: 404 })],
        ]));
        const form = freshForm();
        await form.loadExtraction();

        expect(form.error).toBe(true);
        expect(form.errorMessage).toBe('Failed to load extraction');
        expect(form.loading).toBe(false);
        expect(form.extraction).toBeNull();
    });

    it('handles network failure with the fallback message path', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('boom'); }));
        const form = freshForm();
        await form.loadExtraction();

        expect(form.error).toBe(true);
        expect(form.errorMessage).toBe('boom');
        expect(form.loading).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// approveExtraction
// ---------------------------------------------------------------------------

describe('approveExtraction', () => {
    it('is gated behind confirm', async () => {
        confirm.mockReturnValueOnce(false);
        const form = await loadedForm();
        fetch.mockClear();

        await form.approveExtraction();

        expect(fetch).not.toHaveBeenCalled();
        expect(form.approving).toBe(false);
        expect(form.approved).toBe(false);
    });

    it('converts *_str back to arrays, PUTs the data, then POSTs approve', async () => {
        const approval = {
            status: 'approved',
            files_created: ['Cellar/Tastings/a.md'],
            unmatched: [],
        };
        const form = await loadedForm(bourbonExtraction(), [
            [`/api/v1/review/${EXTRACTION_ID}/approve`, jsonResponse(approval)],
        ]);
        const t = form.extraction.data.tastings[0];
        t.nose_notes_str = ' pepper ,caramel,, vanilla ';
        t.palate_notes_str = 'oak';
        t.finish_notes_str = '';

        await form.approveExtraction();

        // Whiskey keys round-trip: trimmed, empties dropped.
        expect(t.nose_notes).toEqual(['pepper', 'caramel', 'vanilla']);
        expect(t.palate_notes).toEqual(['oak']);
        // Empty string is falsy → existing array untouched (current behavior).
        expect(t.finish_notes).toEqual([]);

        const putCall = fetch.mock.calls.find(([, opts]) => opts?.method === 'PUT');
        expect(putCall[0]).toBe(`/api/v1/extractions/${EXTRACTION_ID}`);
        expect(putCall[1].headers).toEqual({ 'Content-Type': 'application/json' });
        expect(JSON.parse(putCall[1].body)).toEqual({ extraction_data: form.extraction.data });

        expect(fetch).toHaveBeenCalledWith(
            `/api/v1/review/${EXTRACTION_ID}/approve`,
            { method: 'POST' },
        );
        expect(form.approvalResult).toEqual(approval);
        expect(form.approved).toBe(true);
        expect(form.approving).toBe(false);
    });

    it('does not fabricate whiskey note arrays on wine tastings when approving', async () => {
        const form = await loadedForm(wineExtraction(), [
            [`/api/v1/review/${EXTRACTION_ID}/approve`, jsonResponse({ status: 'approved', files_created: [], unmatched: [] })],
        ]);

        await form.approveExtraction();

        const sent = JSON.parse(
            fetch.mock.calls.find(([, opts]) => opts?.method === 'PUT')[1].body,
        );
        const t = sent.extraction_data.tastings[0];
        // Wine fields survive intact; empty *_str never became note arrays.
        expect(t.wine_appearance).toBe(3);
        expect(t.wine_aftertaste).toBe(1.5);
        expect(t.nose_notes).toBeUndefined();
        expect(t.palate_notes).toBeUndefined();
        expect(t.finish_notes).toBeUndefined();
        expect(form.approved).toBe(true);
    });

    it('alerts and never approves when the PUT fails (no approve POST fired)', async () => {
        const form = await loadedForm(bourbonExtraction(), [
            [`/api/v1/extractions/${EXTRACTION_ID}`, (url, opts) =>
                opts?.method === 'PUT'
                    ? jsonResponse({}, { ok: false, status: 500 })
                    : jsonResponse(bourbonExtraction())],
        ]);

        await form.approveExtraction();

        expect(alert).toHaveBeenCalledWith('Error: Failed to update extraction data');
        const approveCalls = fetch.mock.calls.filter(([url]) => String(url).includes('/approve'));
        expect(approveCalls).toHaveLength(0);
        expect(form.approved).toBe(false);
        expect(form.approving).toBe(false);
    });

    it('alerts when the approve POST fails', async () => {
        const form = await loadedForm(bourbonExtraction(), [
            [`/api/v1/review/${EXTRACTION_ID}/approve`, jsonResponse({}, { ok: false, status: 500 })],
        ]);

        await form.approveExtraction();

        expect(alert).toHaveBeenCalledWith('Error: Failed to approve extraction');
        expect(form.approved).toBe(false);
        expect(form.approvalResult).toBeNull();
        expect(form.approving).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// rejectExtraction
// ---------------------------------------------------------------------------

describe('rejectExtraction', () => {
    it('is gated behind confirm', async () => {
        confirm.mockReturnValueOnce(false);
        const form = await loadedForm();
        fetch.mockClear();

        await form.rejectExtraction();

        expect(fetch).not.toHaveBeenCalled();
        expect(form.rejecting).toBe(false);
        expect(location.href).toBe('');
    });

    it('POSTs reject and redirects to /upload', async () => {
        const form = await loadedForm(bourbonExtraction(), [
            [`/api/v1/review/${EXTRACTION_ID}/reject`, jsonResponse({ status: 'rejected' })],
        ]);

        await form.rejectExtraction();

        expect(fetch).toHaveBeenCalledWith(
            `/api/v1/review/${EXTRACTION_ID}/reject`,
            { method: 'POST' },
        );
        expect(location.href).toBe('/upload');
    });

    it('alerts and resets rejecting on failure', async () => {
        const form = await loadedForm(bourbonExtraction(), [
            [`/api/v1/review/${EXTRACTION_ID}/reject`, jsonResponse({}, { ok: false, status: 500 })],
        ]);

        await form.rejectExtraction();

        expect(alert).toHaveBeenCalledWith('Error: Failed to reject extraction');
        expect(form.rejecting).toBe(false);
        expect(location.href).toBe('');
    });
});
