/**
 * Cocktail detail page component (window.cocktailDetailApp).
 *
 * Extracted from templates/cocktail_detail.html (July 2026) so the logic gets
 * vitest unit coverage (tests/js/cocktail-detail.test.js). Attached as a WHOLE
 * factory (no initState()/spread split) to match the other page components —
 * the returned object must reach Alpine intact.
 *
 * Covers: cocktail + tasting-history loading, the two-step "Rate This" wizard
 * (bottle/product selection with create-on-the-fly, then score/notes), the
 * edit-tasting modal, the edit-recipe modal, deletes, and the datalist
 * Tab/Enter autocomplete helper.
 *
 * Depends on the global formatApiError() helper defined in base.html.
 */

// #CLAUDE_REQ: State/method names here MUST match the Alpine bindings in
//              templates/cocktail_detail.html (x-data="cocktailDetailApp('{{ cocktail_id }}')",
//              x-init="loadCocktail()"). Rename in both places or the page
//              silently loses functionality.
// #CLAUDE_REQ: Endpoints must match web/routes/cocktails.py and
//              web/routes/ingredients.py:
//              GET/PUT/DELETE /api/v1/cocktails/{id},
//              GET/POST /api/v1/cocktails/{id}/tastings,
//              PATCH/DELETE /api/v1/cocktails/{id}/tastings/{tasting_id},
//              GET /api/v1/cocktails, GET /api/v1/ingredients/search?q=,
//              GET /api/v1/ingredients?flat=true,
//              GET /api/v1/ingredients/{id}/descendants,
//              POST /api/v1/ingredients.

window.cocktailDetailApp = function cocktailDetailApp(cocktailId) {
    return {
        cocktailId,
        cocktail: null,
        loading: true,
        tastings: [],
        avgScore: null,
        showTastingForm: false,
        tastingStep: 1,
        tastingSaving: false,
        tastingError: '',
        tastingData: {
            taster_name: '',
            score: 7,
            notes: '',
            bartender: '',
            bottles_used: [],
        },
        bottleSearchQueries: {},
        bottleResults: {},
        showEditTastingForm: false,
        editingTastingId: null,
        editTastingData: {},
        editTastingError: '',
        editBottleQueries: {},
        editBottleResults: {},
        showEditForm: false,
        editSaving: false,
        editError: '',
        ingredientNames: [],
        cocktailNames: [],
        editData: {
            name: '', description: '', parent_cocktail: '', method: '', style: '', glassware: '', garnish: '',
            ingredients: [],
            instructions: [],
        },

        async loadCocktail() {
            try {
                const response = await fetch(`/api/v1/cocktails/${this.cocktailId}`);
                if (response.ok) {
                    this.cocktail = await response.json();
                    await this.loadTastings();
                    // Load cocktail names for parent selection
                    const cocktailsResponse = await fetch('/api/v1/cocktails');
                    if (cocktailsResponse.ok) {
                        const allCocktails = await cocktailsResponse.json();
                        this.cocktailNames = allCocktails.map(c => c.name).filter(n => n !== this.cocktail.name);
                    }
                }
            } catch (e) {
                console.error('Failed to load cocktail:', e);
            } finally {
                this.loading = false;
            }
        },

        async loadTastings() {
            try {
                const response = await fetch(`/api/v1/cocktails/${this.cocktailId}/tastings`);
                if (response.ok) {
                    this.tastings = await response.json();
                    const scored = this.tastings.filter(t => t.score !== null);
                    if (scored.length > 0) {
                        this.avgScore = scored.reduce((sum, t) => sum + t.score, 0) / scored.length;
                    } else {
                        this.avgScore = null;
                    }
                }
            } catch (e) {
                console.error('Failed to load tastings:', e);
            }
        },

        async searchBottles(ingredientIndex, recipeIngredient) {
            const query = this.bottleSearchQueries[ingredientIndex] || '';
            try {
                // Search ingredients - smart filter by default shows descendants of recipe ingredient
                // But also allows full search if user types something different
                const response = await fetch(`/api/v1/ingredients/search?q=${encodeURIComponent(query || recipeIngredient)}`);
                if (response.ok) {
                    let results = await response.json();
                    // If no query, filter to descendants of the recipe ingredient (smart defaults)
                    // If query is provided, show all results (full flexibility)
                    if (!query) {
                        // Find the recipe ingredient node and its descendants
                        const allIngResponse = await fetch('/api/v1/ingredients?flat=true');
                        if (allIngResponse.ok) {
                            const allIng = await allIngResponse.json();
                            const recipeNode = allIng.find(i => i.name.toLowerCase() === recipeIngredient.toLowerCase());
                            if (recipeNode) {
                                // Get descendants
                                const descResponse = await fetch(`/api/v1/ingredients/${recipeNode.id}/descendants`);
                                if (descResponse.ok) {
                                    const descendants = await descResponse.json();
                                    results = [recipeNode, ...descendants];
                                }
                            }
                        }
                    }
                    // Prioritize products (items with cost/abv/etc)
                    results.sort((a, b) => {
                        if (a.is_product && !b.is_product) return -1;
                        if (!a.is_product && b.is_product) return 1;
                        return 0;
                    });
                    this.bottleResults[ingredientIndex] = results;
                }
            } catch (e) {
                console.error('Failed to search bottles:', e);
            }
        },

        selectBottle(ingredientIndex, bottle, recipeIngredient) {
            this.tastingData.bottles_used[ingredientIndex] = {
                recipe_ingredient: recipeIngredient,
                actual_product: bottle.name
            };
            this.bottleSearchQueries[ingredientIndex] = bottle.name;
            this.bottleResults[ingredientIndex] = [];
        },

        // Create a brand-new ingredient/product on the fly and select it for this
        // slot. Reuses the same POST /api/v1/ingredients endpoint as recipe
        // creation (single source of truth). Parents it under the recipe
        // ingredient when that category exists, otherwise creates it at root.
        async createAndSelectIngredient(ingredientIndex, recipeIngredient) {
            const name = (this.bottleSearchQueries[ingredientIndex] || '').trim();
            if (!name) return;
            this.tastingError = '';
            const post = (parent) => fetch('/api/v1/ingredients', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({name, parent}),
            });
            try {
                let response = await post(recipeIngredient || null);
                // If the recipe ingredient isn't a real ingredient record, the
                // backend rejects the parent — retry creating it at the root.
                if (response.status === 400 && recipeIngredient) {
                    response = await post(null);
                }
                // Already exists somewhere in the tree — just use it as-is.
                if (response.status === 409) {
                    this.selectBottle(ingredientIndex, {name}, recipeIngredient);
                    return;
                }
                if (!response.ok) {
                    const error = await response.json().catch(() => ({}));
                    this.tastingError = formatApiError(error.detail, 'Failed to create ingredient');
                    return;
                }
                const created = await response.json();
                this.selectBottle(ingredientIndex, created, recipeIngredient);
            } catch (e) {
                this.tastingError = e.message;
            }
        },

        closeTastingForm() {
            this.showTastingForm = false;
            this.tastingStep = 1;
            this.tastingData = {taster_name: '', score: 7, notes: '', bartender: '', bottles_used: []};
            this.bottleSearchQueries = {};
            this.bottleResults = {};
        },

        async saveTasting() {
            if (!this.tastingData.taster_name.trim()) {
                this.tastingError = 'Name is required';
                return;
            }
            this.tastingSaving = true;
            this.tastingError = '';
            try {
                // bottles_used is indexed by ingredient position and may be a sparse
                // array (holes -> null on JSON.stringify) when some ingredients are
                // left unselected. Drop holes/empties so we never send null entries.
                const bottlesUsed = (this.tastingData.bottles_used || [])
                    .filter(b => b && b.actual_product && b.actual_product.trim());
                const payload = {...this.tastingData, bottles_used: bottlesUsed};
                const response = await fetch(`/api/v1/cocktails/${this.cocktailId}/tastings`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    const error = await response.json();
                    this.tastingError = formatApiError(error.detail, 'Failed to save');
                    return;
                }
                this.closeTastingForm();
                await this.loadTastings();
            } catch (e) {
                this.tastingError = e.message;
            } finally {
                this.tastingSaving = false;
            }
        },

        async loadIngredientNames() {
            try {
                const response = await fetch('/api/v1/ingredients?flat=true');
                if (response.ok) {
                    const data = await response.json();
                    this.ingredientNames = data.map(i => i.name);
                }
            } catch (e) {}
        },

        openEditForm() {
            // Load ingredient names if not already loaded
            if (this.ingredientNames.length === 0) {
                this.loadIngredientNames();
            }
            // Populate edit form with current cocktail data
            this.editData = {
                name: this.cocktail.name,
                description: this.cocktail.description || '',
                parent_cocktail: this.cocktail.parent_cocktail || '',
                method: this.cocktail.method || '',
                style: this.cocktail.style || '',
                glassware: this.cocktail.glassware || '',
                garnish: this.cocktail.garnish || '',
                ingredients: JSON.parse(JSON.stringify(this.cocktail.ingredients || [])),
                instructions: JSON.parse(JSON.stringify(this.cocktail.instructions || [])),
            };
            // Ensure at least one ingredient and instruction row
            if (this.editData.ingredients.length === 0) {
                this.editData.ingredients.push({ingredient: '', amount: null, unit: 'oz', notes: '', optional: false});
            }
            if (this.editData.instructions.length === 0) {
                this.editData.instructions.push('');
            }
            this.showEditForm = true;
        },

        async saveEdit() {
            if (!this.editData.name.trim()) {
                this.editError = 'Name is required';
                return;
            }
            this.editSaving = true;
            this.editError = '';
            try {
                const payload = {
                    ...this.editData,
                    ingredients: this.editData.ingredients.filter(i => i.ingredient && i.ingredient.trim()),
                    instructions: this.editData.instructions.filter(s => s && s.trim()),
                    method: this.editData.method || null,
                    style: this.editData.style || null,
                    glassware: this.editData.glassware || null,
                    garnish: this.editData.garnish || null,
                    description: this.editData.description || null,
                    parent_cocktail: this.editData.parent_cocktail || null,
                };
                const response = await fetch(`/api/v1/cocktails/${this.cocktailId}`, {
                    method: 'PUT',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    const error = await response.json();
                    this.editError = formatApiError(error.detail, 'Failed to save');
                    return;
                }
                this.showEditForm = false;
                await this.loadCocktail(); // Reload to show updated data
            } catch (e) {
                this.editError = e.message;
            } finally {
                this.editSaving = false;
            }
        },

        async deleteCocktail() {
            if (!confirm('Delete this cocktail recipe? This cannot be undone.')) return;
            try {
                const response = await fetch(`/api/v1/cocktails/${this.cocktailId}`, {method: 'DELETE'});
                if (response.ok) window.location.href = '/cocktails';
            } catch (e) {
                alert('Failed to delete: ' + e.message);
            }
        },

        openEditTastingModal(t) {
            this.editingTastingId = t.id;
            this.editBottleQueries = {};
            this.editBottleResults = {};
            // Build bottles_used indexed by cocktail.ingredients position
            const buMap = {};
            (t.bottles_used || []).forEach(bu => { buMap[bu.recipe_ingredient] = bu.actual_product; });
            const bottles = (this.cocktail ? this.cocktail.ingredients : []).map((ing, idx) => {
                const actual = buMap[ing.ingredient] || '';
                this.editBottleQueries[idx] = actual;
                return { recipe_ingredient: ing.ingredient, actual_product: actual };
            });
            this.editTastingData = {
                taster_name: t.taster_name,
                tasting_date: t.tasting_date,
                score: t.score ?? 7,
                notes: t.notes || '',
                bartender: t.bartender || '',
                bottles_used: bottles,
            };
            this.editTastingError = '';
            this.showEditTastingForm = true;
        },

        async searchEditBottles(bidx, recipeIngredient) {
            const query = this.editBottleQueries[bidx] || '';
            try {
                const response = await fetch(`/api/v1/ingredients/search?q=${encodeURIComponent(query || recipeIngredient)}`);
                if (!response.ok) return;
                let results = await response.json();
                if (!query) {
                    const allResp = await fetch('/api/v1/ingredients?flat=true');
                    if (allResp.ok) {
                        const allIng = await allResp.json();
                        const node = allIng.find(i => i.name.toLowerCase() === recipeIngredient.toLowerCase());
                        if (node) {
                            const descResp = await fetch(`/api/v1/ingredients/${node.id}/descendants`);
                            if (descResp.ok) results = [node, ...(await descResp.json())];
                        }
                    }
                }
                results.sort((a, b) => (a.is_product && !b.is_product ? -1 : !a.is_product && b.is_product ? 1 : 0));
                this.editBottleResults[bidx] = results;
            } catch (e) {}
        },

        selectEditBottle(bidx, result, recipeIngredient) {
            this.editTastingData.bottles_used[bidx] = {
                recipe_ingredient: recipeIngredient,
                actual_product: result.name,
            };
            this.editBottleQueries[bidx] = result.name;
            this.editBottleResults[bidx] = [];
        },

        async saveEditTasting() {
            this.editTastingError = '';
            try {
                const bottlesUsed = (this.editTastingData.bottles_used || [])
                    .filter(b => b && b.actual_product && b.actual_product.trim());
                const response = await fetch(`/api/v1/cocktails/${this.cocktailId}/tastings/${this.editingTastingId}`, {
                    method: 'PATCH',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        taster_name: this.editTastingData.taster_name,
                        tasting_date: this.editTastingData.tasting_date,
                        score: this.editTastingData.score !== '' ? parseFloat(this.editTastingData.score) : null,
                        notes: this.editTastingData.notes,
                        bartender: this.editTastingData.bartender,
                        bottles_used: bottlesUsed,
                    }),
                });
                if (!response.ok) {
                    const error = await response.json().catch(() => ({}));
                    throw new Error(formatApiError(error.detail, `Server error ${response.status}`));
                }
                this.showEditTastingForm = false;
                await this.loadTastings();
            } catch (e) {
                this.editTastingError = 'Failed to save: ' + e.message;
            }
        },

        async deleteTasting(tastingId) {
            if (!confirm('Delete this tasting? This cannot be undone.')) return;
            try {
                const response = await fetch(`/api/v1/cocktails/${this.cocktailId}/tastings/${tastingId}`, {
                    method: 'DELETE'
                });
                if (response.ok) {
                    await this.loadTastings();
                } else {
                    alert('Failed to delete tasting');
                }
            } catch (e) {
                alert('Failed to delete: ' + e.message);
            }
        },

        async viewIngredient(ingredientName) {
            // Find ingredient by name, then navigate to ingredients page with pre-filled search and auto-open
            // Using a hash to trigger the ingredients page to auto-search and open
            window.location.href = `/ingredients#search=${encodeURIComponent(ingredientName)}`;
        },

        handleAutocomplete(event, options) {
            // Auto-complete with first matching option on Tab or Enter
            if (event.key !== 'Tab' && event.key !== 'Enter') return;

            const input = event.target.value.toLowerCase().trim();
            if (!input) return;

            // Find best match: prioritize starts-with, then contains
            let match = options.find(opt => opt.toLowerCase().startsWith(input));
            if (!match) {
                match = options.find(opt => opt.toLowerCase().includes(input));
            }

            if (match) {
                event.preventDefault();
                event.target.value = match;
                // Trigger input event to update x-model
                event.target.dispatchEvent(new Event('input'));
            }
        }
    };
};
