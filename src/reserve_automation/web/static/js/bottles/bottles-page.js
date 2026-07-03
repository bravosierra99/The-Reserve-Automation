/**
 * Bottle collection grid page component (window.bottlesApp).
 *
 * Extracted from templates/bottles.html (July 2026) so the filter / permission
 * / toast logic gets vitest unit coverage (tests/js/bottles-page.test.js).
 * Attached as a WHOLE factory — it defines a live getter (filteredBottles);
 * spreading the returned object elsewhere would invoke the getter once and
 * freeze it into a static value.
 *
 * Composes components/bottle-editor-modal.js (window.bottleEditorModal) at
 * call time (soft-guarded, but the page must load it BEFORE this file for the
 * edit modal to work).
 */

// #CLAUDE_REQ: State keys, method names, and the filteredBottles getter here
//              MUST match the Alpine bindings in templates/bottles.html
//              (x-data="bottlesApp()"). Rename in both places or the page
//              silently loses functionality.
// #CLAUDE_REQ: Endpoints must match the backend routes:
//              GET /api/v1/bottles/collection  (web/routes/bottles/collection.py)
//                  -> {bottles: [BottleMetadata.model_dump(mode='json')], count}
//              GET /api/v1/me                  (web/routes/health.py)
//                  -> {permissions: {bottles_edit, tastings_submit, ...}}
//              GET /api/v1/labels/thumbnail?id=&size=  (thumbnail images)
// #CLAUDE_REQ: navigateToCreateTasting writes sessionStorage 'preselect_bottle'
//              which static/js/tastings/manual-tasting.js reads on /manual-tasting.

window.bottlesApp = function bottlesApp() {
    // Initialize bottle editor modal
    const bottleEditor = window.bottleEditorModal ? window.bottleEditorModal() : {};

    return {
        // Grid state
        labelsLoading: false,
        labelBottles: [],
        selectedLabelBottle: null,
        gridFilterType: 'all',
        gridSearchQuery: '',
        gridFilterRegion: '',
        gridFilterBeverageType: '',
        gridFilterVariety: '',
        gridFilterStyle: '',
        gridFilterBarrelType: '',
        gridFilterInStockOnly: false,
        labelGridTimestamp: Date.now(),

        // Permission flags
        canEdit: false,
        canCreateTasting: false,

        // Bottle editor modal
        bottleEditor: bottleEditor,

        // Toast notifications
        toasts: [],
        toastIdCounter: 0,

        get filteredBottles() {
            let bottles = this.labelBottles;

            if (this.gridFilterType !== 'all') {
                bottles = bottles.filter(b => b.type === this.gridFilterType);
            }

            if (this.gridSearchQuery) {
                const query = this.gridSearchQuery.toLowerCase();
                bottles = bottles.filter(b =>
                    (b.producer || '').toLowerCase().includes(query) ||
                    (b.name || '').toLowerCase().includes(query) ||
                    (b.year || '').toString().includes(query) ||
                    (b.region || '').toLowerCase().includes(query) ||
                    (b.country || '').toLowerCase().includes(query) ||
                    (b.variety || []).join(', ').toLowerCase().includes(query) ||
                    (b.beverage_type || '').toLowerCase().includes(query) ||
                    (b.style || '').toLowerCase().includes(query)
                );
            }

            if (this.gridFilterRegion) {
                bottles = bottles.filter(b =>
                    (b.region || '') === this.gridFilterRegion ||
                    (b.country || '') === this.gridFilterRegion
                );
            }

            if (this.gridFilterBeverageType) {
                bottles = bottles.filter(b => (b.beverage_type || '') === this.gridFilterBeverageType);
            }

            if (this.gridFilterVariety) {
                const v = this.gridFilterVariety.toLowerCase();
                bottles = bottles.filter(b => (b.variety || []).some(va => va.toLowerCase().includes(v)));
            }

            if (this.gridFilterStyle) {
                bottles = bottles.filter(b => (b.style || '') === this.gridFilterStyle);
            }

            if (this.gridFilterBarrelType) {
                bottles = bottles.filter(b => (b.barrel_type || '') === this.gridFilterBarrelType);
            }

            if (this.gridFilterInStockOnly) {
                bottles = bottles.filter(b => (b.inventory || 0) > 0);
            }

            return bottles;
        },

        gridHasActiveFilters() {
            return this.gridFilterType !== 'all' ||
                this.gridSearchQuery ||
                this.gridFilterRegion ||
                this.gridFilterBeverageType ||
                this.gridFilterVariety ||
                this.gridFilterStyle ||
                this.gridFilterBarrelType ||
                this.gridFilterInStockOnly;
        },

        gridResetTypeFilters() {
            this.gridFilterRegion = '';
            this.gridFilterBeverageType = '';
            this.gridFilterVariety = '';
            this.gridFilterStyle = '';
            this.gridFilterBarrelType = '';
        },

        gridResetAllFilters() {
            this.gridFilterType = 'all';
            this.gridSearchQuery = '';
            this.gridResetTypeFilters();
            this.gridFilterInStockOnly = false;
        },

        // Returns unique region values for the current type filter
        gridAvailableRegions() {
            let bottles = this.gridFilterType !== 'all'
                ? this.labelBottles.filter(b => b.type === this.gridFilterType)
                : this.labelBottles;
            const seen = new Set();
            bottles.forEach(b => {
                if (b.region) seen.add(b.region);
                else if (b.country) seen.add(b.country);
            });
            return [...seen].sort();
        },

        gridAvailableBeverageTypes() {
            let bottles = this.gridFilterType !== 'all'
                ? this.labelBottles.filter(b => b.type === this.gridFilterType)
                : this.labelBottles;
            const seen = new Set();
            bottles.forEach(b => { if (b.beverage_type) seen.add(b.beverage_type); });
            return [...seen].sort();
        },

        gridAvailableVarieties() {
            let bottles = this.labelBottles.filter(b => b.type === 'wine');
            const seen = new Set();
            bottles.forEach(b => { (b.variety || []).forEach(va => { if (va) seen.add(va); }); });
            return [...seen].sort();
        },

        gridAvailableStyles() {
            let bottles = this.labelBottles.filter(b => b.type === 'wine');
            const seen = new Set();
            bottles.forEach(b => { if (b.style) seen.add(b.style); });
            return [...seen].sort();
        },

        gridAvailableBarrelTypes() {
            let bottles = this.labelBottles.filter(b => b.type === 'whiskey');
            const seen = new Set();
            bottles.forEach(b => { if (b.barrel_type) seen.add(b.barrel_type); });
            return [...seen].sort();
        },

        navigateToCreateTasting(bottle) {
            const preselect = {
                bottle_path: bottle.id,
                bottle_name: `${bottle.producer} - ${bottle.name}${bottle.year ? ' (' + bottle.year + ')' : ''}`,
                producer: bottle.producer,
                thumbnail_url: `/api/v1/labels/thumbnail?id=${encodeURIComponent(bottle.id)}&size=400`,
                beverage_type: bottle.type,
                confidence: 1.0
            };
            sessionStorage.setItem('preselect_bottle', JSON.stringify(preselect));
            window.location.href = '/manual-tasting';
        },

        async init() {
            // Check permissions
            try {
                const resp = await fetch('/api/v1/me');
                if (resp.ok) {
                    const me = await resp.json();
                    this.canEdit = me.permissions?.bottles_edit || false;
                    this.canCreateTasting = me.permissions?.tastings_submit || false;
                }
            } catch (e) { /* default: no edit */ }

            // Load bottles
            await this.loadBottles();
        },

        async loadBottles() {
            this.labelsLoading = true;
            try {
                const response = await fetch('/api/v1/bottles/collection');
                const data = await response.json();
                this.labelBottles = data.bottles;
                this.labelGridTimestamp = Date.now();
                console.log(`Loaded ${this.labelBottles.length} bottles for collection`);
            } catch (error) {
                console.error('Failed to load bottles:', error);
                this.showToast('Failed to load bottles: ' + error.message, 'error');
            } finally {
                this.labelsLoading = false;
            }
        },

        showToast(message, type = 'success') {
            const id = ++this.toastIdCounter;
            this.toasts.push({ id, message, type });
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, 3000);
        },
    };
};
