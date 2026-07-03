/**
 * Unit tests for the shared tasting form mixin
 * (src/reserve_automation/web/static/js/components/tasting-form-mixin.js).
 *
 * The mixin is spread into a host component that owns a `tasting` object;
 * these tests build a minimal host the same way real components do.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/tasting-form-mixin.js';

function freshHost(extra = {}) {
    return {
        ...window.tastingFormMixin(),
        tasting: {
            nose_notes: [],
            palate_notes: [],
            finish_notes: [],
            appearance_notes: [],
        },
        ...extra,
    };
}

let host;

beforeEach(() => {
    host = freshHost();
});

describe('whiskey note management', () => {
    it('addNoseNote pushes the trimmed input and clears the field', () => {
        host.noseNotesInput = '  caramel  ';
        host.addNoseNote();
        expect(host.tasting.nose_notes).toEqual(['caramel']);
        expect(host.noseNotesInput).toBe('');
    });

    it('ignores blank input', () => {
        host.noseNotesInput = '   ';
        host.addNoseNote();
        expect(host.tasting.nose_notes).toEqual([]);
    });

    it('removeNoseNote removes by index', () => {
        host.tasting.nose_notes = ['caramel', 'oak', 'vanilla'];
        host.removeNoseNote(1);
        expect(host.tasting.nose_notes).toEqual(['caramel', 'vanilla']);
    });

    it('add/remove palate and finish notes work the same way', () => {
        host.palateNotesInput = 'cherry';
        host.addPalateNote();
        host.finishNotesInput = 'long';
        host.addFinishNote();
        expect(host.tasting.palate_notes).toEqual(['cherry']);
        expect(host.tasting.finish_notes).toEqual(['long']);
        host.removePalateNote(0);
        host.removeFinishNote(0);
        expect(host.tasting.palate_notes).toEqual([]);
        expect(host.tasting.finish_notes).toEqual([]);
    });
});

describe('wine note aliases map onto the shared arrays', () => {
    // Wine inputs write into the same underlying arrays the backend stores:
    // aroma → nose_notes, taste → palate_notes, aftertaste → finish_notes.
    it('addAromaNote writes to nose_notes', () => {
        host.aromaNotesInput = 'blackberry';
        host.addAromaNote();
        expect(host.tasting.nose_notes).toEqual(['blackberry']);
    });

    it('addTasteNote writes to palate_notes', () => {
        host.tasteNotesInput = 'tannic';
        host.addTasteNote();
        expect(host.tasting.palate_notes).toEqual(['tannic']);
    });

    it('addAftertasteNote writes to finish_notes', () => {
        host.aftertasteNotesInput = 'smooth';
        host.addAftertasteNote();
        expect(host.tasting.finish_notes).toEqual(['smooth']);
    });

    it('addAppearanceNote writes to appearance_notes', () => {
        host.appearanceNotesInput = 'ruby';
        host.addAppearanceNote();
        expect(host.tasting.appearance_notes).toEqual(['ruby']);
    });
});

describe('ensureNoteArrays', () => {
    it('creates missing note arrays on the tasting object', () => {
        host.tasting = {};
        host.ensureNoteArrays();
        expect(host.tasting.nose_notes).toEqual([]);
        expect(host.tasting.palate_notes).toEqual([]);
        expect(host.tasting.finish_notes).toEqual([]);
        expect(host.tasting.appearance_notes).toEqual([]);
    });

    it('add* functions self-heal a tasting missing its arrays', () => {
        host.tasting = {};
        host.noseNotesInput = 'oak';
        host.addNoseNote();
        expect(host.tasting.nose_notes).toEqual(['oak']);
    });
});

describe('onTastingChange hook', () => {
    it('is called after adding and removing a note when defined', () => {
        const onChange = vi.fn();
        host = freshHost({ onTastingChange: onChange });
        host.noseNotesInput = 'oak';
        host.addNoseNote();
        host.removeNoseNote(0);
        expect(onChange).toHaveBeenCalledTimes(2);
    });

    it('is not called when the input was blank', () => {
        const onChange = vi.fn();
        host = freshHost({ onTastingChange: onChange });
        host.noseNotesInput = '';
        host.addNoseNote();
        expect(onChange).not.toHaveBeenCalled();
    });
});

describe('clearNoteInputs', () => {
    it('clears every input field but leaves saved notes alone', () => {
        host.noseNotesInput = 'a';
        host.palateNotesInput = 'b';
        host.finishNotesInput = 'c';
        host.appearanceNotesInput = 'd';
        host.aromaNotesInput = 'e';
        host.tasteNotesInput = 'f';
        host.aftertasteNotesInput = 'g';
        host.tasting.nose_notes = ['kept'];

        host.clearNoteInputs();

        expect(host.noseNotesInput).toBe('');
        expect(host.palateNotesInput).toBe('');
        expect(host.finishNotesInput).toBe('');
        expect(host.appearanceNotesInput).toBe('');
        expect(host.aromaNotesInput).toBe('');
        expect(host.tasteNotesInput).toBe('');
        expect(host.aftertasteNotesInput).toBe('');
        expect(host.tasting.nose_notes).toEqual(['kept']);
    });
});
