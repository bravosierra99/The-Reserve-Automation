/**
 * Unit tests for the base-page components loaded on every page
 * (src/reserve_automation/web/static/js/components/base-page.js):
 * authNav, backupBanner, and the shared formatApiError helper.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/base-page.js';

function jsonResponse(data, { ok = true, status = 200 } = {}) {
    return { ok, status, json: async () => data };
}

function routeFetch(routes) {
    return vi.fn(async (url) => {
        for (const [needle, responder] of routes) {
            if (String(url).includes(needle)) {
                return typeof responder === 'function' ? responder(url) : responder;
            }
        }
        return jsonResponse({});
    });
}

beforeEach(() => {
    vi.stubGlobal('fetch', routeFetch([]));
});

afterEach(() => {
    vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// authNav
// ---------------------------------------------------------------------------

describe('authNav', () => {
    it('loads identity and permissions from /api/v1/me', async () => {
        const nav = window.authNav();
        global.fetch = routeFetch([
            ['/api/v1/me', jsonResponse({
                display_name: 'Ben',
                role: 'admin',
                permissions: { bottles_view: true, management_access: true },
            })],
        ]);

        await nav.init();

        expect(nav.displayName).toBe('Ben');
        expect(nav.role).toBe('admin');
        expect(nav.p.management_access).toBe(true);
        expect(nav.mobileOpen).toBe(false);
    });

    it('defaults to all links visible when /me is unreachable (fail-open nav, auth still gates routes)', async () => {
        const nav = window.authNav();
        global.fetch = vi.fn(async () => { throw new Error('offline'); });

        await nav.init();

        expect(nav.p.bottles_view).toBe(true);
        expect(nav.p.management_access).toBe(true);
        expect(nav.displayName).toBe('');
    });

    it('tolerates a /me response without permissions', async () => {
        const nav = window.authNav();
        global.fetch = routeFetch([['/api/v1/me', jsonResponse({})]]);
        await nav.init();
        expect(nav.p).toEqual({});
        expect(nav.displayName).toBe('');
    });
});

// ---------------------------------------------------------------------------
// backupBanner
// ---------------------------------------------------------------------------

describe('backupBanner', () => {
    function bannerWith(me, backupStatus) {
        const banner = window.backupBanner();
        global.fetch = routeFetch([
            ['/api/v1/me', jsonResponse(me)],
            ['/api/v1/admin/backup-status', backupStatus === null
                ? jsonResponse({}, { ok: false, status: 403 })
                : jsonResponse(backupStatus)],
        ]);
        return banner;
    }

    const ADMIN = { permissions: { management_access: true } };

    it('stays hidden for non-admin users and never asks for backup status', async () => {
        const banner = window.backupBanner();
        global.fetch = routeFetch([
            ['/api/v1/me', jsonResponse({ permissions: { bottles_view: true } })],
        ]);

        await banner.init();

        expect(banner.visible).toBe(false);
        const urls = global.fetch.mock.calls.map(c => c[0]);
        expect(urls).not.toContain('/api/v1/admin/backup-status');
    });

    it('stays hidden when backups are healthy', async () => {
        const banner = bannerWith(ADMIN, { status: 'ok', age_minutes: 5 });
        await banner.init();
        expect(banner.visible).toBe(false);
    });

    it('shows red on backup error', async () => {
        const banner = bannerWith(ADMIN, { status: 'error', error: 'disk full' });
        await banner.init();
        expect(banner.visible).toBe(true);
        expect(banner.level).toBe('red');
        expect(banner.message).toContain('disk full');
    });

    it('shows amber when the status file is missing', async () => {
        const banner = bannerWith(ADMIN, { status: 'unknown' });
        await banner.init();
        expect(banner.level).toBe('amber');
        expect(banner.message).toContain('status file missing');
    });

    it('escalates by staleness: amber at 30+ min, red at 120+ min', async () => {
        const amber = bannerWith(ADMIN, { status: 'ok', age_minutes: 45 });
        await amber.init();
        expect(amber.level).toBe('amber');
        expect(amber.message).toContain('45 minutes ago');

        const red = bannerWith(ADMIN, { status: 'ok', age_minutes: 180 });
        await red.init();
        expect(red.level).toBe('red');
        expect(red.message).toContain('3 hour');
    });

    it('treats a null age as healthy (no banner)', async () => {
        const banner = bannerWith(ADMIN, { status: 'ok', age_minutes: null });
        await banner.init();
        expect(banner.visible).toBe(false);
    });

    it('swallows fetch failures silently — the banner must never break a page', async () => {
        const banner = window.backupBanner();
        global.fetch = vi.fn(async () => { throw new Error('offline'); });
        await expect(banner.init()).resolves.toBeUndefined();
        expect(banner.visible).toBe(false);
    });
});

// ---------------------------------------------------------------------------
// formatApiError — the "[object Object]" killer
// ---------------------------------------------------------------------------

describe('formatApiError', () => {
    const fmt = window.formatApiError;

    it('passes plain strings through', () => {
        expect(fmt('bottle not found')).toBe('bottle not found');
    });

    it('falls back for empty/missing detail', () => {
        expect(fmt(undefined)).toBe('Request failed');
        expect(fmt(null, 'Save failed')).toBe('Save failed');
        expect(fmt('')).toBe('Request failed');
    });

    it('formats FastAPI 422 error lists with field locations', () => {
        const detail = [
            { loc: ['body', 'tasting', 'taster_name'], msg: 'Field required' },
            { loc: ['body', 'score'], msg: 'Input should be a valid number' },
        ];
        expect(fmt(detail)).toBe(
            'tasting.taster_name: Field required; score: Input should be a valid number'
        );
    });

    it('formats a single error object', () => {
        expect(fmt({ loc: ['body', 'name'], msg: 'Field required' })).toBe('name: Field required');
        expect(fmt({ message: 'boom' })).toBe('boom');
    });

    it('never renders [object Object]', () => {
        expect(fmt([{ weird: 'shape' }])).not.toContain('[object Object]');
        expect(fmt({ weird: 'shape' })).not.toContain('[object Object]');
    });

    it('handles primitive list entries and empty lists', () => {
        expect(fmt(['a', 'b'])).toBe('a; b');
        expect(fmt([])).toBe('Request failed');
    });
});

describe('modalScrollLock', () => {
    // Shared body-scroll lock for every modal — iOS Safari otherwise chains
    // modal touch-scrolls to the page body (the modal rebounds and the page
    // behind scrolls, hiding footer buttons).
    afterEach(() => {
        document.body.style.overflow = '';
    });

    it('locks page scroll while a modal is open', () => {
        window.modalScrollLock(true);
        expect(document.body.style.overflow).toBe('hidden');
    });

    it('releases page scroll when the last modal closes', () => {
        window.modalScrollLock(true);
        window.modalScrollLock(false);
        expect(document.body.style.overflow).toBe('');
    });

    it('accepts the x-effect combined-flags expression shape (truthy/falsy)', () => {
        window.modalScrollLock(false || true);
        expect(document.body.style.overflow).toBe('hidden');
        window.modalScrollLock(false || false);
        expect(document.body.style.overflow).toBe('');
    });
});
