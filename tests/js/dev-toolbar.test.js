/**
 * Unit tests for the dev-mode role switcher
 * (src/reserve_automation/web/static/js/components/dev-toolbar.js).
 *
 * The bug these exist for (Sept 2026): the role cookie carried an
 * unconditional `Secure`, so on plain-http LAN access — the ONLY context where
 * this toolbar is ever visible — the browser silently dropped it. Clicking
 * "Guest" reloaded the page still as admin, with no error.
 *
 * jsdom's cookie jar does enforce Secure-on-http (a Secure cookie set from an
 * http: document is not readable back), so the end-to-end assertion is real.
 * The pure builder is asserted separately so the protocol branch stays covered
 * even if that jsdom behaviour ever changes.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/dev-toolbar.js';

function clearCookies() {
    for (const c of document.cookie.split(';')) {
        const name = c.split('=')[0].trim();
        if (name) document.cookie = `${name}=;path=/;max-age=0`;
    }
}

// jsdom's window.location is non-configurable, so the suite stubs the global
// the way the other page tests do. NOTE: this does NOT move the document's own
// URL — that stays jsdom's default http://localhost:3000, which is what makes
// the Secure-cookie assertions below real rather than simulated.
beforeEach(() => {
    clearCookies();
    vi.stubGlobal('location', { protocol: 'http:', href: '', reload: vi.fn() });
});

afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    clearCookies();
});

describe('devRoleCookieString', () => {
    it('omits Secure over plain http so the browser will store it', () => {
        const s = window.devRoleCookieString('guest', 'http:');
        expect(s).toContain('dev_role_override=guest');
        expect(s).toContain('path=/');
        expect(s).toContain('samesite=strict');
        expect(s).not.toContain('secure');
    });

    it('keeps Secure over https', () => {
        expect(window.devRoleCookieString('guest', 'https:')).toContain('secure');
    });
});

describe('switchRole over plain http (LAN access)', () => {
    it('actually stores the cookie and reloads', () => {
        // jsdom's default document URL is http://localhost:3000 — plain http,
        // which is what the LAN box serves.
        expect(location.protocol).toBe('http:');

        const t = window.devToolbar();
        t.currentRole = 'admin';
        t.switchRole('guest');

        expect(document.cookie).toContain('dev_role_override=guest');
        expect(t.error).toBe('');
        expect(location.reload).toHaveBeenCalled();
    });

    it('REGRESSION: an unconditional Secure attribute is caught, not silent', () => {
        // Re-introduce the original bug by forcing the https branch while the
        // document is still http, then prove the component surfaces it instead
        // of reloading into an unchanged role.
        const orig = window.devRoleCookieString;
        window.devRoleCookieString = (role) => orig(role, 'https:');
        try {
            const t = window.devToolbar();
            t.currentRole = 'admin';
            t.switchRole('guest');

            expect(document.cookie).not.toContain('dev_role_override=guest');
            expect(t.error).toContain('refused');
            expect(location.reload).not.toHaveBeenCalled();
        } finally {
            window.devRoleCookieString = orig;
        }
    });
});

describe('init', () => {
    it('shows the toolbar only when the API reports dev_mode', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true,
            json: async () => ({ dev_mode: true, role: 'guest', email: 'guest@localhost' }),
        })));
        const t = window.devToolbar();
        await t.init();
        expect(t.visible).toBe(true);
        expect(t.currentRole).toBe('guest');
        expect(t.userEmail).toBe('guest@localhost');
    });

    it('stays hidden when dev_mode is false (the Cloudflare path)', async () => {
        vi.stubGlobal('fetch', vi.fn(async () => ({
            ok: true,
            json: async () => ({ dev_mode: false, role: 'admin' }),
        })));
        const t = window.devToolbar();
        await t.init();
        expect(t.visible).toBe(false);
    });
});
