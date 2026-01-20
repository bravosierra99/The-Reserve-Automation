/**
 * Shared Tasting Form Mixin
 *
 * This mixin provides the note management functions and computed score properties
 * for the tasting scores form component. Include this in your Alpine component
 * using the spread operator: { ...tastingFormMixin(), ...yourOtherData }
 *
 * Requirements:
 * - Your component must have a `tasting` object with score/notes fields
 * - Your component must have an `isWine` property (boolean)
 * - Optionally implement `onTastingChange()` for auto-save behavior
 */

function tastingFormMixin() {
    return {
        // Note input fields (for tag-style entry)
        noseNotesInput: '',
        palateNotesInput: '',
        finishNotesInput: '',
        appearanceNotesInput: '',  // Wine
        aromaNotesInput: '',       // Wine (maps to nose_notes)
        tasteNotesInput: '',       // Wine (maps to palate_notes)
        aftertasteNotesInput: '',  // Wine (maps to finish_notes)

        // Computed scores - these are getters that calculate from tasting data
        get computedWineScore() {
            const t = this.tasting || {};
            return (t.wine_appearance || 0) +
                   (t.wine_aroma || 0) +
                   (t.wine_taste || 0) +
                   (t.wine_aftertaste || 0) +
                   (t.wine_overall || 0);
        },

        get computed100ptScore() {
            return 50 + (this.computedWineScore / 20) * 50;
        },

        get computedWhiskeyScore() {
            const t = this.tasting || {};
            return (t.whiskey_nose || 0) +
                   (t.whiskey_palate || 0) +
                   (t.whiskey_finish || 0) +
                   (t.whiskey_overall || 0);
        },

        // Ensure tasting object has required note arrays
        ensureNoteArrays() {
            if (!this.tasting) return;
            if (!this.tasting.nose_notes) this.tasting.nose_notes = [];
            if (!this.tasting.palate_notes) this.tasting.palate_notes = [];
            if (!this.tasting.finish_notes) this.tasting.finish_notes = [];
            if (!this.tasting.appearance_notes) this.tasting.appearance_notes = [];
        },

        // Whiskey note management
        addNoseNote() {
            this.ensureNoteArrays();
            if (this.noseNotesInput.trim()) {
                this.tasting.nose_notes.push(this.noseNotesInput.trim());
                this.noseNotesInput = '';
                if (typeof this.onTastingChange === 'function') this.onTastingChange();
            }
        },

        removeNoseNote(index) {
            this.ensureNoteArrays();
            this.tasting.nose_notes.splice(index, 1);
            if (typeof this.onTastingChange === 'function') this.onTastingChange();
        },

        addPalateNote() {
            this.ensureNoteArrays();
            if (this.palateNotesInput.trim()) {
                this.tasting.palate_notes.push(this.palateNotesInput.trim());
                this.palateNotesInput = '';
                if (typeof this.onTastingChange === 'function') this.onTastingChange();
            }
        },

        removePalateNote(index) {
            this.ensureNoteArrays();
            this.tasting.palate_notes.splice(index, 1);
            if (typeof this.onTastingChange === 'function') this.onTastingChange();
        },

        addFinishNote() {
            this.ensureNoteArrays();
            if (this.finishNotesInput.trim()) {
                this.tasting.finish_notes.push(this.finishNotesInput.trim());
                this.finishNotesInput = '';
                if (typeof this.onTastingChange === 'function') this.onTastingChange();
            }
        },

        removeFinishNote(index) {
            this.ensureNoteArrays();
            this.tasting.finish_notes.splice(index, 1);
            if (typeof this.onTastingChange === 'function') this.onTastingChange();
        },

        // Wine note management
        addAppearanceNote() {
            this.ensureNoteArrays();
            if (this.appearanceNotesInput.trim()) {
                this.tasting.appearance_notes.push(this.appearanceNotesInput.trim());
                this.appearanceNotesInput = '';
                if (typeof this.onTastingChange === 'function') this.onTastingChange();
            }
        },

        removeAppearanceNote(index) {
            this.ensureNoteArrays();
            this.tasting.appearance_notes.splice(index, 1);
            if (typeof this.onTastingChange === 'function') this.onTastingChange();
        },

        addAromaNote() {
            this.ensureNoteArrays();
            if (this.aromaNotesInput.trim()) {
                this.tasting.nose_notes.push(this.aromaNotesInput.trim());
                this.aromaNotesInput = '';
                if (typeof this.onTastingChange === 'function') this.onTastingChange();
            }
        },

        removeAromaNote(index) {
            this.ensureNoteArrays();
            this.tasting.nose_notes.splice(index, 1);
            if (typeof this.onTastingChange === 'function') this.onTastingChange();
        },

        addTasteNote() {
            this.ensureNoteArrays();
            if (this.tasteNotesInput.trim()) {
                this.tasting.palate_notes.push(this.tasteNotesInput.trim());
                this.tasteNotesInput = '';
                if (typeof this.onTastingChange === 'function') this.onTastingChange();
            }
        },

        removeTasteNote(index) {
            this.ensureNoteArrays();
            this.tasting.palate_notes.splice(index, 1);
            if (typeof this.onTastingChange === 'function') this.onTastingChange();
        },

        addAftertasteNote() {
            this.ensureNoteArrays();
            if (this.aftertasteNotesInput.trim()) {
                this.tasting.finish_notes.push(this.aftertasteNotesInput.trim());
                this.aftertasteNotesInput = '';
                if (typeof this.onTastingChange === 'function') this.onTastingChange();
            }
        },

        removeAftertasteNote(index) {
            this.ensureNoteArrays();
            this.tasting.finish_notes.splice(index, 1);
            if (typeof this.onTastingChange === 'function') this.onTastingChange();
        },

        // Clear all note inputs (useful when switching tastings)
        clearNoteInputs() {
            this.noseNotesInput = '';
            this.palateNotesInput = '';
            this.finishNotesInput = '';
            this.appearanceNotesInput = '';
            this.aromaNotesInput = '';
            this.tasteNotesInput = '';
            this.aftertasteNotesInput = '';
        }
    };
}
