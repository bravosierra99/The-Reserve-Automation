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

                trSortColumn: 'date',
                trSortDir: 'desc',

                trExpandedKey: null,

                trTypeFilters: {},
                trTypeFilterSearch: {},
                trFilterOptionsData: {},
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

        trToggleRow(t) {
            const key = `${t.bottle_name}|${t.date}|${t.taster}`;
            this.trExpandedKey = this.trExpandedKey === key ? null : key;
        },

        trIsExpanded(t) {
            return this.trExpandedKey === `${t.bottle_name}|${t.date}|${t.taster}`;
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
