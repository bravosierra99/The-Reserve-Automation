/**
 * Event results page component (window.eventResultsApp).
 *
 * Extracted from templates/event_results.html (July 2026) so the ranking /
 * scoring logic gets vitest unit coverage (tests/js/event-results.test.js).
 * Attached as a WHOLE factory (not initState/spread) to match the repo's
 * extraction convention — the object must be returned intact so Alpine
 * receives exactly what the inline script used to build.
 *
 * The event id is passed by the template markup:
 *   x-data="eventResultsApp('{{ event_id }}')"
 * so no Jinja values live in this file.
 */

// #CLAUDE_REQ: State keys, method names, and modalData fields here MUST match
//              the Alpine bindings in templates/event_results.html
//              (x-data="eventResultsApp(...)"). Rename in both places or the
//              page silently loses functionality.
// #CLAUDE_REQ: Fetches GET /api/v1/events/{event_id} (web/routes/events.py).
//              Response shape: { name, beverage_type, status, bottles:
//              [{bottle_id, bottle_name, bottle_path, blind_number}],
//              participants: {id: {participant_id, participant_name,
//              tastings: [{bottle_id, tasting_data}]}} }. Tastings carry
//              bottle_id (the DB id, saved by /api/v1/manual-tasting/save);
//              legacy tastings may carry bottle_path instead — read via
//              tastingBottleKey(). Blind events pre-reveal are redacted
//              server-side (_redact_blind_bottles); results require status
//              'revealed' or 'closed'.
// #CLAUDE_REQ: Score formulas must match the wine AWS (out of 20) and whiskey
//              (out of 10) fields written by the manual tasting wizard
//              (static/js/tastings/manual-tasting.js): wine_appearance/aroma/
//              taste/aftertaste/overall, whiskey_nose/palate/finish/overall.

window.eventResultsApp = function eventResultsApp(eventId) {
    return {
        eventId: eventId,
        event: null,
        loading: true,
        error: null,
        overallRankings: [],
        participantRankings: [],
        showModal: false,
        modalData: {
            participantName: '',
            bottleName: '',
            formattedNotes: ''
        },

        async init() {
            await this.loadEventAndCalculateResults();
        },

        async loadEventAndCalculateResults() {
            try {
                const response = await fetch(`/api/v1/events/${this.eventId}`);
                if (!response.ok) {
                    if (response.status === 404) {
                        this.error = 'Event not found';
                    } else {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    this.loading = false;
                    return;
                }

                this.event = await response.json();

                // Check if event is revealed or closed
                if (this.event.status !== 'revealed' && this.event.status !== 'closed') {
                    this.error = 'Results are only available after the event has been revealed';
                    this.loading = false;
                    return;
                }

                // Calculate rankings
                this.calculateOverallRankings();
                this.calculateParticipantRankings();

                this.loading = false;
            } catch (error) {
                console.error('Failed to load event:', error);
                this.error = 'Failed to load event results';
                this.loading = false;
            }
        },

        // Tastings saved via /api/v1/manual-tasting/save carry bottle_id;
        // legacy event tastings carried bottle_path. Normalize to one string key.
        tastingBottleKey(tasting) {
            const key = tasting.bottle_id ?? tasting.bottle_path;
            return key == null ? '' : String(key);
        },

        findBottle(bottleKey) {
            const key = String(bottleKey);
            return this.event.bottles.find(
                b => String(b.bottle_id) === key || String(b.bottle_path) === key
            );
        },

        participantName(participant) {
            return participant.participant_name ?? participant.name ?? '';
        },

        calculateOverallRankings() {
            const bottleScores = {};

            // Collect all scores for each bottle
            for (const participantId in this.event.participants) {
                const participant = this.event.participants[participantId];

                for (const tasting of participant.tastings) {
                    const key = this.tastingBottleKey(tasting);
                    if (!bottleScores[key]) {
                        bottleScores[key] = {
                            bottle_path: key,
                            scores: [],
                            total: 0
                        };
                    }

                    const score = this.calculateTastingScore(tasting.tasting_data, this.event.beverage_type);
                    bottleScores[key].scores.push(score);
                    bottleScores[key].total += score;
                }
            }

            // Calculate averages and create rankings
            const rankings = [];
            for (const bottlePath in bottleScores) {
                const bottleData = bottleScores[bottlePath];
                const bottle = this.findBottle(bottlePath);

                rankings.push({
                    bottle_path: bottlePath,
                    bottle_name: bottle ? bottle.bottle_name : bottlePath,
                    avg_score: bottleData.total / bottleData.scores.length,
                    tasting_count: bottleData.scores.length
                });
            }

            // Sort by average score (highest first)
            rankings.sort((a, b) => b.avg_score - a.avg_score);

            this.overallRankings = rankings;
        },

        calculateParticipantRankings() {
            const rankings = [];

            for (const participantId in this.event.participants) {
                const participant = this.event.participants[participantId];

                const bottleRankings = [];
                for (const tasting of participant.tastings) {
                    const key = this.tastingBottleKey(tasting);
                    const bottle = this.findBottle(key);
                    const score = this.calculateTastingScore(tasting.tasting_data, this.event.beverage_type);

                    bottleRankings.push({
                        bottle_path: key,
                        bottle_name: bottle ? bottle.bottle_name : key,
                        score: score
                    });
                }

                // Sort by score (highest first)
                bottleRankings.sort((a, b) => b.score - a.score);

                rankings.push({
                    participant_id: participantId,
                    name: this.participantName(participant),
                    rankings: bottleRankings
                });
            }

            this.participantRankings = rankings;
        },

        calculateTastingScore(tastingData, beverageType) {
            if (!tastingData) return 0;

            // Unwrap if double-nested (bug fix migration)
            if (tastingData.tasting_data) {
                tastingData = tastingData.tasting_data;
            }

            if (beverageType === 'wine') {
                // Wine AWS: Appearance/3 + Aroma/6 + Taste/6 + Aftertaste/3 + Overall/2 = 20 total
                return (tastingData.wine_appearance || 0) +
                       (tastingData.wine_aroma || 0) +
                       (tastingData.wine_taste || 0) +
                       (tastingData.wine_aftertaste || 0) +
                       (tastingData.wine_overall || 0);
            } else {
                // Whiskey: Nose/3 + Palate/3 + Finish/3 + Overall/1 = 10 total
                return (tastingData.whiskey_nose || 0) +
                       (tastingData.whiskey_palate || 0) +
                       (tastingData.whiskey_finish || 0) +
                       (tastingData.whiskey_overall || 0);
            }
        },

        getTastingForBottle(participantId, bottlePath) {
            const participant = this.event.participants[participantId];
            if (!participant) return null;

            const key = String(bottlePath);
            return participant.tastings.find(t => this.tastingBottleKey(t) === key);
        },

        formatTastingNotes(tasting) {
            if (!tasting || !tasting.tasting_data) return '<p class="text-gray-500">No tasting data</p>';

            // Unwrap if double-nested (bug fix migration)
            let data = tasting.tasting_data;
            if (data.tasting_data) {
                data = data.tasting_data;
            }

            const beverageType = this.event.beverage_type;
            let html = '<div class="space-y-4">';

            if (beverageType === 'wine') {
                // Wine AWS scoring: Appearance/3, Aroma/6, Taste/6, Aftertaste/3, Overall/2 = 20 total
                // Appearance
                html += '<div class="border-b border-gray-200 pb-3">';
                html += '<div class="flex items-center justify-between mb-1">';
                html += '<span class="font-semibold text-gray-800">Appearance</span>';
                html += `<span class="text-blue-600 font-bold">${(data.wine_appearance ?? 0).toFixed(1)}/3</span>`;
                html += '</div>';
                if (data.appearance_notes && data.appearance_notes.length > 0) {
                    html += `<div class="text-sm text-gray-600">${data.appearance_notes.join(', ')}</div>`;
                }
                html += '</div>';

                // Aroma
                html += '<div class="border-b border-gray-200 pb-3">';
                html += '<div class="flex items-center justify-between mb-1">';
                html += '<span class="font-semibold text-gray-800">Aroma</span>';
                html += `<span class="text-blue-600 font-bold">${(data.wine_aroma ?? 0).toFixed(1)}/6</span>`;
                html += '</div>';
                // The wizard stores wine aroma notes under nose_notes
                const aromaNotes = data.aroma_notes?.length ? data.aroma_notes : data.nose_notes;
                if (aromaNotes && aromaNotes.length > 0) {
                    html += `<div class="text-sm text-gray-600">${this.formatNotesAsHashtags(aromaNotes)}</div>`;
                }
                html += '</div>';

                // Taste
                html += '<div class="border-b border-gray-200 pb-3">';
                html += '<div class="flex items-center justify-between mb-1">';
                html += '<span class="font-semibold text-gray-800">Taste</span>';
                html += `<span class="text-blue-600 font-bold">${(data.wine_taste ?? 0).toFixed(1)}/6</span>`;
                html += '</div>';
                // The wizard stores wine taste notes under palate_notes
                const tasteNotes = data.taste_notes?.length ? data.taste_notes : data.palate_notes;
                if (tasteNotes && tasteNotes.length > 0) {
                    html += `<div class="text-sm text-gray-600">${this.formatNotesAsHashtags(tasteNotes)}</div>`;
                }
                html += '</div>';

                // Aftertaste
                html += '<div class="border-b border-gray-200 pb-3">';
                html += '<div class="flex items-center justify-between mb-1">';
                html += '<span class="font-semibold text-gray-800">Aftertaste</span>';
                html += `<span class="text-blue-600 font-bold">${(data.wine_aftertaste ?? 0).toFixed(1)}/3</span>`;
                html += '</div>';
                // The wizard stores wine aftertaste notes under finish_notes
                const aftertasteNotes = data.aftertaste_notes?.length ? data.aftertaste_notes : data.finish_notes;
                if (aftertasteNotes && aftertasteNotes.length > 0) {
                    html += `<div class="text-sm text-gray-600">${this.formatNotesAsHashtags(aftertasteNotes)}</div>`;
                }
                html += '</div>';

                // Overall Impression
                html += '<div class="pb-3">';
                html += '<div class="flex items-center justify-between mb-1">';
                html += '<span class="font-semibold text-gray-800">Overall Impression</span>';
                html += `<span class="text-blue-600 font-bold">${(data.wine_overall ?? 0).toFixed(1)}/2</span>`;
                html += '</div>';
                const wineOverallNotes = data.overall_notes || data.notes;
                if (wineOverallNotes) {
                    html += `<div class="text-sm text-gray-600 italic">${this.escapeHtml(wineOverallNotes)}</div>`;
                }
                html += '</div>';

                // AWS Total Score
                const wineTotal = this.calculateTastingScore(data, beverageType);
                html += '<div class="pt-3 border-t border-gray-200">';
                html += `<div class="font-bold text-lg text-blue-600">AWS Score: ${wineTotal.toFixed(1)}/20</div>`;
                html += '</div>';

            } else {
                // Whiskey scoring: Nose/3, Palate/3, Finish/3, Overall/1 = 10 total
                // Nose
                html += '<div class="border-b border-gray-200 pb-3">';
                html += '<div class="flex items-center justify-between mb-1">';
                html += '<span class="font-semibold text-gray-800">Nose</span>';
                html += `<span class="text-blue-600 font-bold">${(data.whiskey_nose ?? 0).toFixed(1)}/3</span>`;
                html += '</div>';
                if (data.nose_notes && data.nose_notes.length > 0) {
                    html += `<div class="text-sm text-gray-600">${this.formatNotesAsHashtags(data.nose_notes)}</div>`;
                }
                html += '</div>';

                // Palate
                html += '<div class="border-b border-gray-200 pb-3">';
                html += '<div class="flex items-center justify-between mb-1">';
                html += '<span class="font-semibold text-gray-800">Palate</span>';
                html += `<span class="text-blue-600 font-bold">${(data.whiskey_palate ?? 0).toFixed(1)}/3</span>`;
                html += '</div>';
                if (data.palate_notes && data.palate_notes.length > 0) {
                    html += `<div class="text-sm text-gray-600">${this.formatNotesAsHashtags(data.palate_notes)}</div>`;
                }
                html += '</div>';

                // Finish
                html += '<div class="border-b border-gray-200 pb-3">';
                html += '<div class="flex items-center justify-between mb-1">';
                html += '<span class="font-semibold text-gray-800">Finish</span>';
                html += `<span class="text-blue-600 font-bold">${(data.whiskey_finish ?? 0).toFixed(1)}/3</span>`;
                html += '</div>';
                if (data.finish_notes && data.finish_notes.length > 0) {
                    html += `<div class="text-sm text-gray-600">${this.formatNotesAsHashtags(data.finish_notes)}</div>`;
                }
                html += '</div>';

                // Overall
                html += '<div class="pb-3">';
                html += '<div class="flex items-center justify-between mb-1">';
                html += '<span class="font-semibold text-gray-800">Overall</span>';
                html += `<span class="text-blue-600 font-bold">${(data.whiskey_overall ?? 0).toFixed(1)}/1</span>`;
                html += '</div>';
                const whiskeyOverallNotes = data.overall_notes || data.notes;
                if (whiskeyOverallNotes) {
                    html += `<div class="text-sm text-gray-600 italic">${this.escapeHtml(whiskeyOverallNotes)}</div>`;
                }
                html += '</div>';

                // Whiskey Total Score
                const whiskeyTotal = this.calculateTastingScore(data, beverageType);
                html += '<div class="pt-3 border-t border-gray-200">';
                html += `<div class="font-bold text-lg text-blue-600">Total: ${whiskeyTotal.toFixed(1)}/10</div>`;
                html += '</div>';
            }

            html += '</div>';
            return html;
        },

        formatNotesAsHashtags(notes) {
            if (!notes || !Array.isArray(notes) || notes.length === 0) return '';
            return notes.map(n => `#${n}`).join(' ');
        },

        escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        },

        openTastingModal(participantId, bottlePath) {
            const participant = this.event.participants[participantId];
            const tasting = this.getTastingForBottle(participantId, bottlePath);
            const bottle = this.findBottle(bottlePath);

            if (!participant || !tasting || !bottle) return;

            this.modalData = {
                participantName: this.participantName(participant),
                bottleName: bottle.bottle_name,
                formattedNotes: this.formatTastingNotes(tasting)
            };

            this.showModal = true;
        }
    };
};
