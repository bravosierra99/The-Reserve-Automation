/**
 * Unit tests for the extraction review page component
 * (src/reserve_automation/web/static/js/review/review-page.js).
 *
 * Alpine itself is not loaded; the factory's return value is used directly.
 *
 * Fixtures are CONTRACT fixtures — real API responses captured and
 * snapshot-verified by tests/contract/test_tastings_contract.py:
 * GET /api/v1/extractions/{id} (review_extraction / review_extraction_wine)
 * and POST /api/v1/review/{id}/approve (review_approve_response). Per-test
 * variants are explicit mutations of a loaded fixture.
 *
 * Contract truths the old hand-written fixtures got wrong: every tasting dict
 * carries ALL TastingNote keys (a wine tasting has nose_notes — null or, for
 * real wine cards, the aroma notes, because TastingNote has no wine-specific
 * note fields), and files_created entries are "db:{id}" strings, not vault
 * paths.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { loadContract } from './helpers/contract.js';
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

// Normalized extraction id assigned by the contract snapshots.
const EXTRACTION_ID = '00000000-0000-4000-8000-000000000001';

// Contract bourbon extraction — data.tastings:
//   [0] 'Weller Special Reserve' (Ben), nose ['caramel','oak'],
//       palate ['cherry'], finish [] — matched preview (confidence ~0.73)
//   [1] 'Mystery Bourbon' ('' taster), all note arrays null — unmatched
function bourbonExtraction() {
    return loadContract('review_extraction');
}

// Contract wine (aws_wine) extraction. TastingNote has no wine-specific note
// fields, so real wine cards store aroma/taste/aftertaste notes under
// nose/palate/finish_notes:
//   [0] 'Cabernet Sauvignon': wine scores 3/5/4/1.5/1.5, appearance ['ruby'],
//       nose ['cassis'], palate ['plum'], finish ['long']
//   [1] 'Mystery Red': wine scores, all note arrays null
function wineExtraction() {
    return loadContract('review_extraction_wine');
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
        const extraction = bourbonExtraction();
        const form = await loadedForm(extraction);

        expect(fetch).toHaveBeenCalledWith(`/api/v1/extractions/${EXTRACTION_ID}`);
        expect(form.extraction.template_type).toBe('bourbon');
        expect(form.matchPreviews).toEqual(extraction.match_previews);
        expect(form.matchPreviews[0]).toMatchObject({
            matched: true, matched_to: 'Buffalo Trace - Weller Special Reserve',
        });
        expect(form.matchPreviews[1]).toMatchObject({ matched: false, matched_to: null });
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

    it('keeps wine scores intact and builds *_str from the shared note keys', async () => {
        const form = await loadedForm(wineExtraction());
        const [t0, t1] = form.extraction.data.tastings;

        // Wine scores keep their wine keys, untouched.
        expect(t0.wine_appearance).toBe(3);
        expect(t0.wine_aroma).toBe(5);
        expect(t0.wine_taste).toBe(4);
        expect(t0.wine_aftertaste).toBe(1.5);
        // Contract truth: real wine cards store aroma/taste/aftertaste notes
        // under nose/palate/finish_notes (TastingNote has no wine note keys),
        // so the editing strings are built from them.
        expect(t0.nose_notes_str).toBe('cassis');
        expect(t0.palate_notes_str).toBe('plum');
        expect(t0.finish_notes_str).toBe('long');
        expect(t0.nose_notes).toEqual(['cassis']);
        // A tasting with null note arrays gets empty editing strings and its
        // arrays are NOT invented.
        expect(t1.nose_notes).toBeNull();
        expect(t1.nose_notes_str).toBe('');
        expect(t1.palate_notes_str).toBe('');
        expect(t1.finish_notes_str).toBe('');
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
        // Contract approval: files_created are "db:{id}" strings; the response
        // also carries bottles_matched and the unmatched tastings.
        const approval = loadContract('review_approve_response');
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

    it('never invents note arrays from empty *_str fields (wine, null-note tasting)', async () => {
        const approval = loadContract('review_approve_response');
        const form = await loadedForm(wineExtraction(), [
            [`/api/v1/review/${EXTRACTION_ID}/approve`, jsonResponse(approval)],
        ]);

        await form.approveExtraction();

        const sent = JSON.parse(
            fetch.mock.calls.find(([, opts]) => opts?.method === 'PUT')[1].body,
        );
        const [t0, t1] = sent.extraction_data.tastings;
        // Wine fields survive intact on both tastings.
        expect(t0.wine_appearance).toBe(3);
        expect(t0.wine_aftertaste).toBe(1.5);
        expect(t1.wine_appearance).toBe(2);
        // t0's populated notes round-trip through the *_str fields...
        expect(t0.nose_notes).toEqual(['cassis']);
        // ...while t1's empty *_str strings never become arrays: the null
        // note arrays are preserved (July 2026 note-wiping regression guard).
        expect(t1.nose_notes).toBeNull();
        expect(t1.palate_notes).toBeNull();
        expect(t1.finish_notes).toBeNull();
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
