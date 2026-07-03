/**
 * Base-page components (loaded on EVERY page via templates/base.html).
 *
 * Extracted from base.html (July 2026) so the logic gets vitest unit
 * coverage (tests/js/base-page.test.js). Three window globals:
 *
 *   - window.authNav       — nav bar Alpine component (permission-gated links)
 *   - window.backupBanner  — admin-only backup staleness banner
 *   - window.formatApiError — shared helper turning FastAPI error `detail`
 *                             (string OR 422 list-of-objects) into readable
 *                             text; called bare from other page scripts, so it
 *                             must remain a window global.
 */

// #CLAUDE_REQ: authNav's `p` permission keys (bottles_view, tastings_submit,
//              upload_access, ingredients_view, cocktails_view, events_view,
//              management_access) must match the x-show bindings in
//              templates/base.html AND the permission names in config/auth.yaml
//              (served by /api/v1/me).
// #CLAUDE_REQ: backupBanner thresholds (30 min amber, 120 min red) must stay in
//              sync with the /api/v1/admin/backup-status contract in the routes.

window.backupBanner = function() {
    return {
        visible: false,
        dismissed: false,
        level: 'amber',
        message: '',
        async init() {
            try {
                const me = await fetch('/api/v1/me').then(r => r.json());
                if (!me.permissions?.management_access) return;
                const bs = await fetch('/api/v1/admin/backup-status').then(r => r.ok ? r.json() : null);
                if (!bs) return;
                if (bs.status === 'error') {
                    this.level = 'red';
                    this.message = `Backup error: ${bs.error || 'unknown error'}`;
                    this.visible = true;
                } else if (bs.status === 'unknown') {
                    this.level = 'amber';
                    this.message = 'Backup status unknown — status file missing';
                    this.visible = true;
                } else if (bs.age_minutes !== null && bs.age_minutes >= 120) {
                    this.level = 'red';
                    const hours = Math.round(bs.age_minutes / 60 * 10) / 10;
                    this.message = `Backup alert: backups have not run in ${hours} hour${hours !== 1 ? 's' : ''}`;
                    this.visible = true;
                } else if (bs.age_minutes !== null && bs.age_minutes >= 30) {
                    this.level = 'amber';
                    this.message = `Backup warning: last successful backup was ${bs.age_minutes} minutes ago`;
                    this.visible = true;
                }
            } catch (e) { /* silent — don't break the page */ }
        }
    };
};

window.authNav = function() {
    return {
        displayName: '',
        role: '',
        p: {},
        mobileOpen: false,
        async init() {
            try {
                const resp = await fetch('/api/v1/me');
                const data = await resp.json();
                this.displayName = data.display_name || '';
                this.role = data.role || '';
                this.p = data.permissions || {};
            } catch (e) {
                // Default: show all links if /me fails
                this.p = {
                    bottles_view: true, upload_access: true, tastings_submit: true,
                    ingredients_view: true, cocktails_view: true,
                    events_view: true, management_access: true,
                };
            }
        }
    };
};

// Shared helper: turn an API error `detail` into readable text.
// FastAPI 422 responses set `detail` to a list of error objects; assigning
// that straight into a string renders as "[object Object],[object Object]".
window.formatApiError = function(detail, fallback) {
    fallback = fallback || 'Request failed';
    if (detail === undefined || detail === null || detail === '') return fallback;
    if (typeof detail === 'string') return detail;
    const one = (e) => {
        if (e && typeof e === 'object') {
            const loc = Array.isArray(e.loc) ? e.loc.filter(p => p !== 'body').join('.') : '';
            const msg = e.msg || e.message || JSON.stringify(e);
            return loc ? `${loc}: ${msg}` : msg;
        }
        return String(e);
    };
    if (Array.isArray(detail)) {
        const msgs = detail.map(one).filter(Boolean);
        return msgs.length ? msgs.join('; ') : fallback;
    }
    return one(detail) || fallback;
};
