/**
 * Unit tests for the manual tasting wizard
 * (src/reserve_automation/web/static/js/tastings/manual-tasting.js).
 *
 * The factory returns the whole Alpine component (including live getters),
 * so tests call window.manualTastingWizard() directly — no initState spread.
 * The tasting-form-mixin must be imported first, exactly like the template's
 * script order.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import '../../src/reserve_automation/web/static/js/components/tasting-form-mixin.js';
import '../../src/reserve_automation/web/static/js/tastings/manual-tasting.js';

const BOTTLE_A = { bottle_path: 'whiskeys/weller', bottle_name: 'Weller', producer: 'Buffalo Trace', beverage_type: 'whiskey' };
const BOTTLE_B = { bottle_path: 'wines/caymus', bottle_name: 'Caymus Cab', producer: 'Caymus', beverage_type: 'wine' };

function freshWizard() {
    const w = window.manualTastingWizard();
    w.$refs = {};  // Alpine magic property used by clearCardFile
    return w;
}

let wizard;

beforeEach(() => {
    wizard = freshWizard();
    localStorage.clear();
    sessionStorage.clear();
    // jsdom cookies persist across tests within a file — clear ours
    document.cookie = 'participant_sessions=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
});

afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

describe('mixin merge', () => {
    it('includes the note-management methods from tastingFormMixin', () => {
        expect(typeof wizard.addNoseNote).toBe('function');
        expect(typeof wizard.clearNoteInputs).toBe('function');
        expect(wizard.noseNotesInput).toBe('');
    });

    it('keeps computed getters live (the reason this factory is not spread)', () => {
        wizard.tastingData.wine_appearance = 2;
        wizard.tastingData.wine_aroma = 5;
        expect(wizard.computedWineScore).toBe(7);
        wizard.tastingData.wine_taste = 4;
        expect(wizard.computedWineScore).toBe(11);  // updates, not frozen at spread time
    });
});

describe('computed scores', () => {
    it('computedWineScore sums the five wine components', () => {
        Object.assign(wizard.tastingData, {
            wine_appearance: 3, wine_aroma: 5, wine_taste: 5, wine_aftertaste: 2, wine_overall: 2,
        });
        expect(wizard.computedWineScore).toBe(17);
    });

    it('computed100ptScore maps the AWS 20-point scale to 50-100', () => {
        Object.assign(wizard.tastingData, {
            wine_appearance: 3, wine_aroma: 6, wine_taste: 6, wine_aftertaste: 3, wine_overall: 2,
        });
        expect(wizard.computedWineScore).toBe(20);
        expect(wizard.computed100ptScore).toBe(100);
    });

    it('computedWhiskeyScore sums the four whiskey components', () => {
        Object.assign(wizard.tastingData, {
            whiskey_nose: 2.5, whiskey_palate: 3, whiskey_finish: 2, whiskey_overall: 1,
        });
        expect(wizard.computedWhiskeyScore).toBe(8.5);
    });

    it('isWine follows beverageType', () => {
        expect(wizard.isWine).toBe(true);
        wizard.beverageType = 'whiskey';
        expect(wizard.isWine).toBe(false);
    });
});

describe('step navigation', () => {
    it('canProceed on taster_info requires name, date, and beverage type', () => {
        expect(wizard.canProceed).toBeFalsy();  // no name yet
        wizard.tasterName = 'Ben';
        expect(wizard.canProceed).toBeTruthy();
        wizard.tastingDate = '';
        expect(wizard.canProceed).toBeFalsy();
    });

    it('nextStep refuses to advance when canProceed is false', () => {
        wizard.nextStep();
        expect(wizard.currentStep).toBe('taster_info');
    });

    it('walks taster_info → bottle_selection → tasting_form', () => {
        wizard.tasterName = 'Ben';
        wizard.nextStep();
        expect(wizard.currentStep).toBe('bottle_selection');
        expect(wizard.currentStepNumber).toBe(2);

        wizard.nextStep();  // no bottle selected → blocked
        expect(wizard.currentStep).toBe('bottle_selection');

        wizard.selectedBottle = BOTTLE_A;
        wizard.nextStep();
        expect(wizard.currentStep).toBe('tasting_form');
        expect(wizard.currentStepNumber).toBe(3);
    });

    it('previousStep from the form clears the bottle and resets tasting data', () => {
        wizard.tasterName = 'Ben';
        wizard.selectedBottle = BOTTLE_A;
        wizard._currentStep = 'tasting_form';
        wizard.tastingData.whiskey_nose = 3;

        wizard.previousStep();

        expect(wizard.currentStep).toBe('bottle_selection');
        expect(wizard.selectedBottle).toBeNull();
        expect(wizard.tastingData.whiskey_nose).toBe(0);
    });

    it('previousStep from bottle_selection stays put in event mode (no taster_info step)', () => {
        wizard.participantSession = { event_id: 'evt1', participant_id: 'p1', participant_name: 'Ben' };
        wizard._currentStep = 'bottle_selection';
        wizard.previousStep();
        expect(wizard.currentStep).toBe('bottle_selection');
    });
});

describe('getParticipantSession (cookie parsing)', () => {
    it('returns the session for a joined event', () => {
        const sessions = { evt1: { participant_id: 'p1', participant_name: 'Ben' } };
        document.cookie = `participant_sessions=${encodeURIComponent(JSON.stringify(sessions))}`;

        const session = wizard.getParticipantSession('evt1');
        expect(session).toEqual({ event_id: 'evt1', participant_id: 'p1', participant_name: 'Ben' });
    });

    it('returns null for an event the user has not joined', () => {
        const sessions = { evt1: { participant_id: 'p1', participant_name: 'Ben' } };
        document.cookie = `participant_sessions=${encodeURIComponent(JSON.stringify(sessions))}`;
        expect(wizard.getParticipantSession('other-event')).toBeNull();
    });

    it('returns null (not a crash) on a corrupt cookie', () => {
        vi.spyOn(console, 'error').mockImplementation(() => {});
        document.cookie = 'participant_sessions=%7Bnot-json';
        expect(wizard.getParticipantSession('evt1')).toBeNull();
    });

    it('isEventMode is true only with a participant session carrying an event_id', () => {
        expect(wizard.isEventMode).toBe(false);
        wizard.participantSession = { event_id: 'evt1', participant_id: 'p1', participant_name: 'Ben' };
        expect(wizard.isEventMode).toBe(true);
    });
});

describe('bottle search', () => {
    it('debouncedSearch fires searchBottles once after 300ms', async () => {
        vi.useFakeTimers();
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ results: [] }) });
        vi.stubGlobal('fetch', fetchMock);
        wizard.searchQuery = 'weller';

        wizard.debouncedSearch();
        wizard.debouncedSearch();
        wizard.debouncedSearch();
        expect(fetchMock).not.toHaveBeenCalled();

        await vi.advanceTimersByTimeAsync(300);
        expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it('short queries clear results without fetching', async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);
        wizard.searchQuery = 'w';
        wizard.searchResults = [BOTTLE_A];

        await wizard.searchBottles();

        expect(wizard.searchResults).toEqual([]);
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('builds the search URL with encoded query and beverage type', async () => {
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ results: [BOTTLE_A] }) });
        vi.stubGlobal('fetch', fetchMock);
        wizard.searchQuery = 'wheated bourbon';
        wizard.beverageType = 'whiskey';

        await wizard.searchBottles();

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/v1/bottles/search?q=wheated%20bourbon&beverage_type=whiskey');
        expect(wizard.searchResults).toEqual([BOTTLE_A]);
        expect(wizard.searching).toBe(false);
    });

    it('appends event_id when in event mode', async () => {
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ results: [] }) });
        vi.stubGlobal('fetch', fetchMock);
        wizard.participantSession = { event_id: 'evt1', participant_id: 'p1', participant_name: 'Ben' };
        wizard.searchQuery = 'weller';
        wizard.beverageType = 'whiskey';

        await wizard.searchBottles();

        expect(fetchMock).toHaveBeenCalledWith(
            '/api/v1/bottles/search?q=weller&beverage_type=whiskey&event_id=evt1');
    });
});

describe('bottle selection', () => {
    it('selectBottle keeps tasting data when re-selecting the same bottle', () => {
        wizard.selectedBottle = BOTTLE_A;
        wizard.tastingData.whiskey_nose = 3;
        wizard.selectBottle({ ...BOTTLE_A });
        expect(wizard.tastingData.whiskey_nose).toBe(3);
    });

    it('selectBottle resets tasting data when switching to a DIFFERENT bottle', () => {
        // Guards against scores entered for bottle A being saved onto bottle B.
        wizard.selectedBottle = BOTTLE_A;
        wizard.tastingData.whiskey_nose = 3;
        wizard.noseNotesInput = 'caramel';

        wizard.selectBottle(BOTTLE_B);

        expect(wizard.tastingData.whiskey_nose).toBe(0);
        expect(wizard.noseNotesInput).toBe('');
        expect(wizard.selectedBottle).toEqual(BOTTLE_B);
    });

    it('selectBottle closes the modal and clears the query/results', () => {
        wizard.showSearchModal = true;
        wizard.searchQuery = 'well';
        wizard.searchResults = [BOTTLE_A];
        wizard.selectBottle(BOTTLE_A);
        expect(wizard.showSearchModal).toBe(false);
        expect(wizard.searchQuery).toBe('');
        expect(wizard.searchResults).toEqual([]);
    });

    it('selectBottleAndContinue advances to the tasting form', async () => {
        wizard.tasterName = 'Ben';
        wizard._currentStep = 'bottle_selection';
        await wizard.selectBottleAndContinue(BOTTLE_A);
        expect(wizard.currentStep).toBe('tasting_form');
        expect(wizard.selectedBottle).toEqual(BOTTLE_A);
    });
});

describe('event mode: tasted bottles', () => {
    function eventWizard() {
        const w = freshWizard();
        w.participantSession = { event_id: 'evt1', participant_id: 'p1', participant_name: 'Ben' };
        w.eventData = {
            participants: {
                p1: { tastings: [{ bottle_path: BOTTLE_A.bottle_path, tasting_data: { whiskey_nose: 2, nose_notes: ['oak'] } }] },
            },
        };
        return w;
    }

    it('hasBottleBeenTasted matches on bottle_path for the current participant', () => {
        const w = eventWizard();
        expect(w.hasBottleBeenTasted(BOTTLE_A)).toBe(true);
        expect(w.hasBottleBeenTasted(BOTTLE_B)).toBe(false);
    });

    it('hasBottleBeenTasted is false outside event mode', () => {
        expect(wizard.hasBottleBeenTasted(BOTTLE_A)).toBe(false);
    });

    it('editBottleTasting loads the existing data and jumps to the form', async () => {
        const w = eventWizard();
        await w.editBottleTasting(BOTTLE_A);
        expect(w.currentStep).toBe('tasting_form');
        expect(w.selectedBottle).toEqual(BOTTLE_A);
        expect(w.tastingData.whiskey_nose).toBe(2);
        expect(w.tastingData.nose_notes).toEqual(['oak']);
        // Merged defaults still present
        expect(w.tastingData.palate_notes).toEqual([]);
    });

    it('editBottleTasting unwraps double-nested tasting_data (legacy bug migration)', async () => {
        const w = eventWizard();
        w.eventData.participants.p1.tastings = [{
            bottle_path: BOTTLE_A.bottle_path,
            tasting_data: { tasting_data: { whiskey_nose: 1.5, nose_notes: null } },
        }];

        await w.editBottleTasting(BOTTLE_A);

        expect(w.tastingData.whiskey_nose).toBe(1.5);
        // null note arrays from old data are healed to []
        expect(w.tastingData.nose_notes).toEqual([]);
    });
});

describe('saveTasting', () => {
    function readyToSave(overrides = {}) {
        const w = freshWizard();
        Object.assign(w, {
            tasterName: 'Ben',
            tastingDate: '2026-07-03',
            beverageType: 'whiskey',
            selectedBottle: BOTTLE_A,
            _currentStep: 'tasting_form',
        }, overrides);
        return w;
    }

    // Successful saves redirect; stub location so jsdom doesn't attempt navigation.
    beforeEach(() => {
        vi.stubGlobal('location', { href: '' });
    });

    it('parses comma-separated whiskey note inputs into arrays and posts the payload', async () => {
        const w = readyToSave();
        w.noseNotesInput = 'caramel, oak,  vanilla ';
        w.palateNotesInput = 'cherry';
        w.finishNotesInput = '';
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ file_path: 'x.md' }) });
        vi.stubGlobal('fetch', fetchMock);
        vi.stubGlobal('alert', vi.fn());

        await w.saveTasting();

        const [url, opts] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/v1/manual-tasting/save');
        const body = JSON.parse(opts.body);
        expect(body.mode).toBe('obsidian');
        expect(body.beverage_type).toBe('whiskey');
        expect(body.taster_name).toBe('Ben');
        expect(body.selected_bottle_path).toBe(BOTTLE_A.bottle_path);
        expect(body.tasting_data.nose_notes).toEqual(['caramel', 'oak', 'vanilla']);
        expect(body.tasting_data.palate_notes).toEqual(['cherry']);
        expect(body.tasting_data.finish_notes).toEqual([]);
        expect(w.saving).toBe(false);
    });

    it('maps wine note inputs onto the backend arrays (aroma→nose, taste→palate, aftertaste→finish)', async () => {
        const w = readyToSave({ beverageType: 'wine', selectedBottle: BOTTLE_B });
        w.appearanceNotesInput = 'ruby';
        w.aromaNotesInput = 'blackberry, cassis';
        w.tasteNotesInput = 'tannic';
        w.aftertasteNotesInput = 'long';
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ file_path: 'x.md' }) });
        vi.stubGlobal('fetch', fetchMock);
        vi.stubGlobal('alert', vi.fn());

        await w.saveTasting();

        const body = JSON.parse(fetchMock.mock.calls[0][1].body);
        expect(body.tasting_data.appearance_notes).toEqual(['ruby']);
        expect(body.tasting_data.nose_notes).toEqual(['blackberry', 'cassis']);
        expect(body.tasting_data.palate_notes).toEqual(['tannic']);
        expect(body.tasting_data.finish_notes).toEqual(['long']);
    });

    it('includes event_id and participant_id in event mode', async () => {
        const w = readyToSave({
            participantSession: { event_id: 'evt1', participant_id: 'p1', participant_name: 'Ben' },
        });
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ event_id: 'evt1' }) });
        vi.stubGlobal('fetch', fetchMock);
        vi.stubGlobal('alert', vi.fn());

        await w.saveTasting();

        const body = JSON.parse(fetchMock.mock.calls[0][1].body);
        expect(body.mode).toBe('event');
        expect(body.event_id).toBe('evt1');
        expect(body.participant_id).toBe('p1');
    });

    it('caches taster preferences in localStorage after a successful save', async () => {
        const w = readyToSave();
        w.tastingData.place = 'Home';
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ file_path: 'x.md' }) }));
        vi.stubGlobal('alert', vi.fn());

        await w.saveTasting();

        expect(localStorage.getItem('tasting_taster_name')).toBe('Ben');
        expect(localStorage.getItem('tasting_beverage_type')).toBe('whiskey');
        expect(localStorage.getItem('tasting_place')).toBe('Home');
    });

    it('surfaces the server error detail and stops the spinner on failure', async () => {
        const w = readyToSave();
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
            ok: false, json: async () => ({ detail: 'DB exploded' }),
        }));
        const alertMock = vi.fn();
        vi.stubGlobal('alert', alertMock);

        await w.saveTasting();

        expect(alertMock).toHaveBeenCalledWith('Error: DB exploded');
        expect(w.saving).toBe(false);
        expect(localStorage.getItem('tasting_taster_name')).toBeNull();
    });
});

describe('upload tasting card', () => {
    it('uploadCardFile posts the file and records the extraction result', async () => {
        wizard.cardSelectedFile = new File(['x'], 'card.jpg', { type: 'image/jpeg' });
        wizard.uploadExpectedCount = 2;
        const fetchMock = vi.fn().mockResolvedValue({
            ok: true, json: async () => ({ extraction_id: 'ex1', tastings_count: 2 }),
        });
        vi.stubGlobal('fetch', fetchMock);

        await wizard.uploadCardFile();

        const [url, opts] = fetchMock.mock.calls[0];
        expect(url).toBe('/api/v1/tastings/upload-card');
        expect(opts.method).toBe('POST');
        expect(opts.body.get('expected_count')).toBe('2');
        expect(wizard.cardUploadComplete).toBe(true);
        expect(wizard.cardExtractionId).toBe('ex1');
        expect(wizard.cardTastingsCount).toBe(2);
        expect(wizard.cardUploading).toBe(false);
    });

    it('a failed upload sets the error state and clears the spinner', async () => {
        wizard.cardSelectedFile = new File(['x'], 'card.jpg', { type: 'image/jpeg' });
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }));

        await wizard.uploadCardFile();

        expect(wizard.cardError).toBe(true);
        expect(wizard.cardErrorMessage).toBe('Upload failed');
        expect(wizard.cardUploadComplete).toBe(false);
        expect(wizard.cardUploading).toBe(false);
    });

    it('does nothing without a selected file', async () => {
        const fetchMock = vi.fn();
        vi.stubGlobal('fetch', fetchMock);
        await wizard.uploadCardFile();
        expect(fetchMock).not.toHaveBeenCalled();
    });

    it('clearCardFile resets the upload state', () => {
        wizard.cardSelectedFile = new File(['x'], 'card.jpg', { type: 'image/jpeg' });
        wizard.cardPreviewUrl = 'blob:x';
        wizard.cardUploadComplete = true;
        wizard.cardTastingsCount = 3;

        wizard.clearCardFile();

        expect(wizard.cardSelectedFile).toBeNull();
        expect(wizard.cardPreviewUrl).toBeNull();
        expect(wizard.cardUploadComplete).toBe(false);
        expect(wizard.cardTastingsCount).toBe(0);
    });
});

describe('init', () => {
    it('restores cached preferences in standalone mode', async () => {
        localStorage.setItem('tasting_taster_name', 'Ben');
        localStorage.setItem('tasting_beverage_type', 'whiskey');
        localStorage.setItem('tasting_place', 'Home');
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));

        await wizard.init();

        expect(wizard.tasterName).toBe('Ben');
        expect(wizard.beverageType).toBe('whiskey');
        expect(wizard.tastingData.place).toBe('Home');
        expect(wizard.currentStep).toBe('taster_info');
    });

    it('applies a preselected bottle from sessionStorage (bottles page hand-off)', async () => {
        sessionStorage.setItem('preselect_bottle', JSON.stringify(BOTTLE_B));
        vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));

        await wizard.init();

        expect(wizard.selectedBottle).toEqual(BOTTLE_B);
        expect(wizard.beverageType).toBe('wine');
        expect(sessionStorage.getItem('preselect_bottle')).toBeNull();
    });

    it('loads autocomplete suggestions', async () => {
        const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ['Ben', 'Sarah'] });
        vi.stubGlobal('fetch', fetchMock);

        await wizard.init();

        expect(wizard.acTasterNames).toEqual(['Ben', 'Sarah']);
        expect(fetchMock).toHaveBeenCalledWith('/api/v1/autocomplete/tastings/taster_name');
    });

    describe('event mode', () => {
        const EVENT_DATA = {
            beverage_type: 'whiskey',
            is_blind: true,
            status: 'open',
            participants: {},
            bottles: [
                { bottle_path: 'b/two', bottle_name: 'Second Bottle', blind_number: 2 },
                { bottle_path: 'b/one', bottle_name: 'First Bottle', blind_number: 1 },
            ],
        };

        function joinEvent() {
            const sessions = { evt1: { participant_id: 'p1', participant_name: 'Ben' } };
            document.cookie = `participant_sessions=${encodeURIComponent(JSON.stringify(sessions))}`;
            window.history.pushState({}, '', '/tastings?event_mode=true&event_id=evt1');
        }

        afterEach(() => {
            window.history.pushState({}, '', '/');
        });

        it('locks the taster name, hides real names for open blind events, and sorts by blind number', async () => {
            joinEvent();
            vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => EVENT_DATA }));

            await wizard.init();

            expect(wizard.isEventMode).toBe(true);
            expect(wizard.tasterName).toBe('Ben');
            expect(wizard.beverageType).toBe('whiskey');
            expect(wizard.currentStep).toBe('bottle_selection');  // step 1 skipped
            expect(wizard.eventBottles.map(b => b.bottle_name)).toEqual(['Bottle #1', 'Bottle #2']);
        });

        it('shows real bottle names once the event is revealed', async () => {
            joinEvent();
            vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
                ok: true, json: async () => ({ ...EVENT_DATA, status: 'revealed' }),
            }));

            await wizard.init();

            expect(wizard.eventRevealed).toBe(true);
            expect(wizard.eventBottles.map(b => b.bottle_name)).toEqual(['First Bottle', 'Second Bottle']);
        });

        it('falls back to standalone mode when the participant cookie is missing', async () => {
            window.history.pushState({}, '', '/tastings?event_mode=true&event_id=evt1');
            vi.spyOn(console, 'error').mockImplementation(() => {});
            vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));

            await wizard.init();

            expect(wizard.isEventMode).toBe(false);
            expect(wizard.currentStep).toBe('taster_info');
        });
    });
});
