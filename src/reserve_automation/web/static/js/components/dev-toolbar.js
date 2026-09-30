/**
 * Dev-mode role-switcher toolbar (loaded on EVERY page via
 * templates/base.html -> components/dev_toolbar.html).
 *
 * Extracted from the template (Sept 2026) so the cookie logic gets vitest
 * coverage (tests/js/dev-toolbar.test.js). Two window globals:
 *
 *   - window.devToolbar         — the Alpine component
 *   - window.devRoleCookieString — pure builder, exported so the protocol
 *                                 branch is testable without relying on
 *                                 jsdom modelling cookie security rules.
 *
 * The toolbar only renders when /api/v1/me reports dev_mode:true, which the
 * middleware only returns for a request with NO Cloudflare JWT that also
 * comes from a configured toolbar_subnet — i.e. direct LAN access.
 */

// #CLAUDE_REQ: the role names here ('admin', 'family', 'guest') must match the
//              allow-list in web/auth/middleware.py::_get_dev_user and the role
//              keys in config/auth.yaml.

/**
 * Build the Set-Cookie string for the role override.
 *
 * `Secure` is applied ONLY over https. This is the bug fixed in Sept 2026:
 * the attribute was unconditional, so on plain-http LAN access
 * (http://192.168.x.x:8000 — the only way the toolbar is ever visible in the
 * first place) the browser silently discarded the cookie. The page reloaded,
 * the server saw no override, and the role never changed. No error anywhere.
 *
 * Dropping `Secure` off the http path gives up nothing: over https the request
 * carries a Cloudflare JWT, which forces real auth, so dev_mode is false and
 * this toolbar does not render at all. The cookie also cannot escalate
 * privilege — dev mode already defaults to admin, so every override it can set
 * is the same or weaker.
 */
window.devRoleCookieString = function(role, protocol) {
    const attrs = [
        `dev_role_override=${role}`,
        'path=/',
        `max-age=${7 * 24 * 3600}`,
        'samesite=strict',
    ];
    if (protocol === 'https:') {
        attrs.push('secure');
    }
    return attrs.join(';');
};

window.devToolbar = function() {
    return {
        visible: false,
        currentRole: '',
        userEmail: '',
        error: '',

        async init() {
            try {
                const resp = await fetch('/api/v1/me');
                const data = await resp.json();
                if (data.dev_mode) {
                    this.visible = true;
                    this.currentRole = data.role || 'admin';
                    this.userEmail = data.email || '';
                }
            } catch (e) {
                // Silently ignore - toolbar just won't show
            }
        },

        switchRole(role) {
            this.error = '';
            document.cookie = window.devRoleCookieString(role, window.location.protocol);
            // Don't reload on a cookie the browser refused to store: the page
            // would come back in the same role and look like a no-op, which is
            // exactly how the Secure bug hid for so long.
            if (document.cookie.indexOf(`dev_role_override=${role}`) === -1) {
                this.error = `Browser refused the role cookie — still ${this.currentRole}.`;
                return;
            }
            window.location.reload();
        },
    };
};
