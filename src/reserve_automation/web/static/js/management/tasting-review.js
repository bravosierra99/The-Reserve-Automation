/**
 * Tasting Review Module
 *
 * Provides state and methods for the tasting review panel in management.html.
 * Supports wine, whiskey, and cocktail tastings.
 *
 * To add a new tasting type, add an entry to TASTING_TYPES below
 * and ensure the backend's get_all_tastings() handles the new type.
 *
 * Usage:
 *   const tastingReview = window.tastingReviewModule ? window.tastingReviewModule() : {};
 *   const tastingReviewState = tastingReview.initState ? tastingReview.initState() : {};
 *   // In managementApp return:
 *   ...tastingReviewState  // (state section)
 *   ...tastingReview       // (methods section)
 */

// Type registry — add new tasting types here.
// The HTML type-tab bar and expanded-row detail panel are both driven by this object.
const TASTING_TYPES = {
    wine: {
        label: 'Wine',
        icon: '\u{1F377}',
        scoreLabel: '/100',
        maxScore: 100,
        extraColumns: [
            { key: 'aws_score', label: 'AWS /20' }
        ],
        components: [
            { key: 'appearance', label: 'Appearance', max: 3 },
            { key: 'aroma',      label: 'Aroma',      max: 6 },
            { key: 'taste',      label: 'Taste',       max: 6 },
            { key: 'aftertaste', label: 'Aftertaste',  max: 3 },
            { key: 'overall',    label: 'Overall',     max: 2 },
        ],
        noteSections: ['appearance', 'aroma', 'taste', 'aftertaste', 'overall'],
        typeFilters: [
            { key: 'variety',        label: 'Variety',  searchable: true },
            { key: 'country_region', label: 'Region',   searchable: true },
            { key: 'wine_type',      label: 'Type',     searchable: false },
            { key: 'style',          label: 'Style',    searchable: true },
        ],
        cardFields: [
            { key: 'producer',        label: 'Producer' },
            { key: 'wine_type',       label: 'Type' },
            { key: 'variety',         label: 'Variety' },
            { key: 'vineyard',        label: 'Vineyard' },
            { key: 'country_region',  label: 'Region' },
            { key: 'style',           label: 'Style' },
            { key: 'vintage',         label: 'Vintage' },
            { key: 'abv',             label: 'ABV' },
            { key: 'price',           label: 'Price' },
            { key: 'purchase_source', label: 'Purchased At' },
        ],
    },
    whiskey: {
        label: 'Whiskey',
        icon: '\u{1F943}',
        scoreLabel: '/10',
        maxScore: 10,
        extraColumns: [
            { key: 'days_from_crack', label: 'Days Open' },
            { key: 'fill_level',      label: 'Fill %'    }
        ],
        components: [
            { key: 'nose',    label: 'Nose',    max: 3 },
            { key: 'palate',  label: 'Palate',  max: 3 },
            { key: 'finish',  label: 'Finish',  max: 3 },
            { key: 'overall', label: 'Overall', max: 1 },
        ],
        noteSections: ['nose', 'palate', 'finish', 'overall'],
        typeFilters: [
            { key: 'whiskey_type',   label: 'Type',    searchable: false },
            { key: 'region_state',   label: 'Region',  searchable: true },
            { key: 'barrel_type',    label: 'Barrel',  searchable: true },
        ],
        cardFields: [
            { key: 'producer',       label: 'Distiller' },
            { key: 'whiskey_type',   label: 'Type' },
            { key: 'region_state',   label: 'Region' },
            { key: 'proof',          label: 'Proof' },
            { key: 'age_statement',  label: 'Age' },
            { key: 'mash_bill',      label: 'Mash Bill' },
            { key: 'barrel_type',    label: 'Barrel' },
        ],
    },
    cocktail: {
        label: 'Cocktail',
        icon: '\u{1F378}',
        scoreLabel: '/10',
        maxScore: 10,
        extraColumns: [
            { key: 'bartender', label: 'Bartender' }
        ],
        components: [
            { key: 'score', label: 'Score', max: 10 },
        ],
        noteSections: ['notes'],
        typeFilters: [],
        cardFields: [
            { key: 'bartender', label: 'Bartender' },
        ],
    }
};

window.tastingReviewModule = function() {
    return {
        initState() {
            return {
                trLoading: false,
                trError: null,
                trAllTastings: [],
                trTasters: [],

                trFilterType: 'all',
                trFilterTaster: '',
                trFilterSearch: '',
                trFilterMinScore: '',
                trFilterMaxScore: '',
                trFilterDateFrom: '',
                trFilterDateTo: '',
                trShowHidden: false,

                trSortColumn: 'date',
                trSortDir: 'desc',

                trExpandedKey: null,

                trTypeFilters: {},
                trTypeFilterSearch: {},
                trFilterOptionsData: {},

                // Edit state
                trEditingId: null,   // composite "kind:id" of the tasting being edited
                trEditData: {},      // working copy of scores/notes for the edit form
            };
        },

        async loadTastings() {
            this.trLoading = true;
            this.trError = null;
            try {
                const resp = await fetch('/api/v1/management/tastings');
                if (!resp.ok) throw new Error(`Server error ${resp.status}`);
                const data = await resp.json();
                this.trAllTastings = data.tastings || [];
                this.trTasters = data.tasters || [];
                this.trFilterOptionsData = data.filter_options || {};
            } catch (e) {
                this.trError = e.message;
            } finally {
                this.trLoading = false;
            }
        },

        // Returns the list of type-tab options for the filter bar (driven by TASTING_TYPES).
        trAvailableTypes() {
            return Object.entries(TASTING_TYPES).map(([key, cfg]) => ({
                key,
                label: cfg.label,
                icon: cfg.icon,
            }));
        },

        trSort(column) {
            if (this.trSortColumn === column) {
                this.trSortDir = this.trSortDir === 'asc' ? 'desc' : 'asc';
            } else {
                this.trSortColumn = column;
                this.trSortDir = column === 'date' ? 'desc' : 'asc';
            }
        },

        trSortIcon(column) {
            if (this.trSortColumn !== column) return '\u2195';
            return this.trSortDir === 'asc' ? '\u2191' : '\u2193';
        },

        trRowKey(t) {
            return `${t.tasting_kind || 'bottle'}:${t.id}`;
        },

        trToggleRow(t) {
            const key = this.trRowKey(t);
            if (this.trExpandedKey === key) {
                this.trExpandedKey = null;
            } else {
                this.trEditingId = null;  // close any open edit form
                this.trExpandedKey = key;
            }
        },

        trIsExpanded(t) {
            return this.trExpandedKey === this.trRowKey(t);
        },

        trTypeConfig(type) {
            return TASTING_TYPES[type] || null;
        },

        trTypeIcon(type) {
            return TASTING_TYPES[type]?.icon || '?';
        },

        // Format a number for display: round to 1 decimal, drop trailing .0
        trFmt(n) {
            if (n === null || n === undefined) return '\u2014';
            const rounded = Math.round(n * 10) / 10;
            return Number.isInteger(rounded) ? rounded.toString() : rounded.toFixed(1);
        },

        trFormatScore(t) {
            if (t.total_score === null || t.total_score === undefined) return '\u2014';
            const cfg = TASTING_TYPES[t.type];
            const label = cfg ? cfg.scoreLabel : `/${t.max_score}`;
            return `${this.trFmt(t.total_score)}${label}`;
        },

        trFormatDate(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr + 'T00:00:00');
            return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
        },

        trScoreBarPct(t) {
            if (t.total_score === null || t.total_score === undefined || !t.max_score) return 0;
            return Math.min(100, Math.round((t.total_score / t.max_score) * 100));
        },

        trScoreBarColor(t) {
            if (t.total_score === null || t.total_score === undefined || !t.max_score) return 'bg-gray-300';
            const pct = t.total_score / t.max_score;
            if (pct >= 0.90) return 'bg-green-500';
            if (pct >= 0.75) return 'bg-blue-500';
            if (pct >= 0.60) return 'bg-yellow-500';
            return 'bg-red-400';
        },

        trResetFilters() {
            this.trFilterType = 'all';
            this.trFilterTaster = '';
            this.trFilterSearch = '';
            this.trFilterMinScore = '';
            this.trFilterMaxScore = '';
            this.trFilterDateFrom = '';
            this.trFilterDateTo = '';
            this.trTypeFilters = {};
            this.trTypeFilterSearch = {};
            this.trExpandedKey = null;
        },

        trOnTypeChange() {
            this.trTypeFilters = {};
            this.trTypeFilterSearch = {};
            this.trExpandedKey = null;
        },

        trHasActiveFilters() {
            return this.trFilterType !== 'all' ||
                this.trFilterTaster ||
                this.trFilterSearch ||
                this.trFilterMinScore !== '' ||
                this.trFilterMaxScore !== '' ||
                this.trFilterDateFrom ||
                this.trFilterDateTo ||
                Object.values(this.trTypeFilters).some(v => v) ||
                Object.values(this.trTypeFilterSearch).some(v => v);
        },

        // ── Actions ──────────────────────────────────────────────────────────

        async trDeleteTasting(t, event) {
            event.stopPropagation();
            if (!confirm(`Delete this tasting by ${t.taster} on ${t.date}? This cannot be undone.`)) return;
            try {
                const resp = await fetch(`/api/v1/management/tastings/${t.tasting_kind}/${t.id}`, { method: 'DELETE' });
                if (!resp.ok) throw new Error(`Server error ${resp.status}`);
                this.trAllTastings = this.trAllTastings.filter(x => !(x.id === t.id && x.tasting_kind === t.tasting_kind));
                if (this.trExpandedKey === this.trRowKey(t)) this.trExpandedKey = null;
            } catch (e) {
                alert('Failed to delete: ' + e.message);
            }
        },

        async trToggleHidden(t, event) {
            event.stopPropagation();
            try {
                const resp = await fetch(`/api/v1/management/tastings/${t.tasting_kind}/${t.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ hidden: !t.hidden }),
                });
                if (!resp.ok) throw new Error(`Server error ${resp.status}`);
                // Update in-place so the row re-renders immediately
                const idx = this.trAllTastings.findIndex(x => x.id === t.id && x.tasting_kind === t.tasting_kind);
                if (idx !== -1) this.trAllTastings[idx].hidden = !t.hidden;
            } catch (e) {
                alert('Failed to update: ' + e.message);
            }
        },

        trStartEdit(t, event) {
            event.stopPropagation();
            this.trEditingId = this.trRowKey(t);
            // Deep-copy the mutable fields into the edit buffer
            this.trEditData = {
                taster_name: t.taster,
                tasting_date: t.date,
                // Scores (flat copy)
                ...Object.fromEntries(Object.entries(t.scores).map(([k, v]) => [k, v ?? ''])),
                // Notes
                nose_notes: Array.isArray(t.notes?.nose) ? t.notes.nose.join(', ') : (t.notes?.nose || ''),
                palate_notes: Array.isArray(t.notes?.palate) ? t.notes.palate.join(', ') : (t.notes?.palate || ''),
                finish_notes: Array.isArray(t.notes?.finish) ? t.notes.finish.join(', ') : (t.notes?.finish || ''),
                overall_notes: t.notes?.overall || '',
                appearance_notes: Array.isArray(t.notes?.appearance) ? t.notes.appearance.join(', ') : (t.notes?.appearance || ''),
                notes: t.notes?.notes || '',
                bartender: t.bartender || '',
                days_from_crack: t.days_from_crack ?? '',
                fill_level: t.fill_level ?? '',
            };
        },

        trIsEditing(t) {
            return this.trEditingId === this.trRowKey(t);
        },

        trCancelEdit(event) {
            if (event) event.stopPropagation();
            this.trEditingId = null;
            this.trEditData = {};
        },

        async trSaveEdit(t, event) {
            if (event) event.stopPropagation();
            const d = this.trEditData;
            // Build payload — only send fields relevant to this tasting type
            const payload = { taster_name: d.taster_name, tasting_date: d.tasting_date };
            if (t.type === 'whiskey') {
                Object.assign(payload, {
                    whiskey_nose: parseFloat(d.nose) || null,
                    whiskey_palate: parseFloat(d.palate) || null,
                    whiskey_finish: parseFloat(d.finish) || null,
                    whiskey_overall: parseFloat(d.overall) || null,
                    nose_notes: d.nose_notes, palate_notes: d.palate_notes,
                    finish_notes: d.finish_notes, overall_notes: d.overall_notes,
                    days_from_crack: d.days_from_crack !== '' ? parseInt(d.days_from_crack) : null,
                    fill_level: d.fill_level !== '' ? parseInt(d.fill_level) : null,
                });
            } else if (t.type === 'wine') {
                Object.assign(payload, {
                    wine_appearance: parseFloat(d.appearance) || null,
                    wine_aroma: parseFloat(d.aroma) || null,
                    wine_taste: parseFloat(d.taste) || null,
                    wine_aftertaste: parseFloat(d.aftertaste) || null,
                    wine_overall: parseFloat(d.overall) || null,
                    appearance_notes: d.appearance_notes, nose_notes: d.palate_notes,
                    palate_notes: d.taste_notes, finish_notes: d.finish_notes,
                    overall_notes: d.overall_notes,
                });
            } else if (t.type === 'cocktail') {
                Object.assign(payload, {
                    score: parseFloat(d.score) || null,
                    notes: d.notes,
                    bartender: d.bartender,
                });
            }
            try {
                const resp = await fetch(`/api/v1/management/tastings/${t.tasting_kind}/${t.id}`, {
                    method: 'PATCH',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (!resp.ok) throw new Error(`Server error ${resp.status}`);
                // Reload to get fresh computed scores
                this.trEditingId = null;
                await this.loadTastings();
            } catch (e) {
                alert('Failed to save: ' + e.message);
            }
        },

        // Returns the type-specific filter definitions for the currently selected type
        trActiveTypeFilters() {
            if (this.trFilterType === 'all') return [];
            const cfg = TASTING_TYPES[this.trFilterType];
            return cfg?.typeFilters || [];
        },

        // Returns the dropdown options for a given type-specific filter key
        trFilterOptions(key) {
            return this.trFilterOptionsData[key] || [];
        },

        // Returns the card info fields for a given tasting type
        trCardFields(type) {
            const cfg = TASTING_TYPES[type];
            return cfg?.cardFields || [];
        },

        trFormatNoteSection(notes, key) {
            if (!notes) return '';
            const val = notes[key];
            if (!val) return '';
            if (Array.isArray(val)) return val.join(', ') || '';
            return val || '';
        },

        trExtraColumns() {
            if (this.trFilterType === 'all') return [];
            const cfg = TASTING_TYPES[this.trFilterType];
            return cfg ? cfg.extraColumns : [];
        },

        trFormatExtra(t, key) {
            const val = t[key];
            if (val === null || val === undefined || val === '') return '\u2014';
            if (key === 'fill_level') return `${val}%`;
            if (typeof val === 'number') return this.trFmt(val);
            return val;
        },
    };
};
