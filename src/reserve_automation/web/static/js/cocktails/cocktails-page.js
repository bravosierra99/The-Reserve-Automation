/**
 * Cocktail list page component (window.cocktailsApp).
 *
 * Extracted from templates/cocktails.html (July 2026) so the logic gets
 * vitest unit coverage (tests/js/cocktails-page.test.js). Attached as a WHOLE
 * factory — it defines a live getter (filteredCocktails) that a spread/
 * initState split would invoke once and freeze into a static value, so the
 * object must be returned intact.
 *
 * Covers: cocktail list loading + search, method/min-score client filters,
 * the create-recipe modal, the quick-add-ingredient modal, the LLM
 * recipe-search modal, and the datalist Tab/Enter autocomplete helper.
 *
 * Depends on the global formatApiError() helper defined in base.html.
 */

// #CLAUDE_REQ: State/method/getter names here MUST match the Alpine bindings
//              in templates/cocktails.html (x-data="cocktailsApp()"). Rename
//              in both places or the page silently loses functionality.
// #CLAUDE_REQ: Endpoints must match web/routes/cocktails.py and
//              web/routes/ingredients.py:
//              GET /api/v1/cocktails[?q=], POST /api/v1/cocktails,
//              POST /api/v1/cocktails/search-recipe,
//              GET /api/v1/ingredients?flat=true, POST /api/v1/ingredients.

window.cocktailsApp = function cocktailsApp() {
    return {
        cocktails: [],
        loading: true,
        searchQuery: '',
        filterMethod: '',
        filterMinScore: '',
        showCreateForm: false,
        saving: false,
        formError: '',
        ingredientNames: [],
        cocktailNames: [],
        showNewIngredientForm: false,
        savingNewIngredient: false,
        newIngredientError: '',
        newIngredientSuccess: '',
        newIngredientData: { name: '', parent: '' },
        showRecipeSearch: false,
        recipeSearchQuery: '',
        recipeSearching: false,
        recipeSearchError: '',
        recipeSearchSuccess: '',

        get filteredCocktails() {
            let list = this.cocktails;
            if (this.filterMethod) {
                list = list.filter(c => c.method === this.filterMethod);
            }
            if (this.filterMinScore !== '' && this.filterMinScore !== null) {
                const min = parseFloat(this.filterMinScore);
                list = list.filter(c => c.avg_score !== null && c.avg_score !== undefined && c.avg_score >= min);
            }
            return list;
        },
        newCocktail: {
            name: '', description: '', parent_cocktail: '', method: '', style: '', glassware: '', garnish: '',
            ingredients: [{ingredient: '', amount: null, unit: 'oz', notes: '', optional: false}],
            instructions: [''],
        },

        async init() {
            await this.loadCocktails();
            await this.loadIngredientNames();
        },

        async loadCocktails() {
            try {
                this.loading = true;
                const url = this.searchQuery ? `/api/v1/cocktails?q=${encodeURIComponent(this.searchQuery)}` : '/api/v1/cocktails';
                const response = await fetch(url);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.cocktails = await response.json();
                // Update cocktail names for parent selection
                this.cocktailNames = this.cocktails.map(c => c.name);
            } catch (e) {
                console.error('Failed to load cocktails:', e);
            } finally {
                this.loading = false;
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

        async saveCocktail() {
            if (!this.newCocktail.name.trim()) { this.formError = 'Name is required'; return; }
            this.saving = true;
            this.formError = '';
            try {
                const payload = {
                    ...this.newCocktail,
                    ingredients: this.newCocktail.ingredients.filter(i => i.ingredient.trim()),
                    instructions: this.newCocktail.instructions.filter(s => s.trim()),
                    method: this.newCocktail.method || null,
                    style: this.newCocktail.style || null,
                    glassware: this.newCocktail.glassware || null,
                    garnish: this.newCocktail.garnish || null,
                    description: this.newCocktail.description || null,
                    parent_cocktail: this.newCocktail.parent_cocktail || null,
                };
                const response = await fetch('/api/v1/cocktails', {
                    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    const error = await response.json();
                    this.formError = formatApiError(error.detail, 'Failed to save');
                    return;
                }
                this.showCreateForm = false;
                this.newCocktail = {
                    name: '', description: '', parent_cocktail: '', method: '', style: '', glassware: '', garnish: '',
                    ingredients: [{ingredient: '', amount: null, unit: 'oz', notes: '', optional: false}],
                    instructions: [''],
                };
                await this.loadCocktails();
            } catch (e) {
                this.formError = e.message;
            } finally {
                this.saving = false;
            }
        },

        async saveNewIngredient() {
            if (!this.newIngredientData.name.trim()) {
                this.newIngredientError = 'Name is required';
                return;
            }
            this.savingNewIngredient = true;
            this.newIngredientError = '';
            this.newIngredientSuccess = '';
            try {
                const payload = {
                    name: this.newIngredientData.name.trim(),
                    parent: this.newIngredientData.parent.trim() || null,
                };
                const response = await fetch('/api/v1/ingredients', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                if (!response.ok) {
                    const error = await response.json();
                    this.newIngredientError = formatApiError(error.detail, 'Failed to save ingredient');
                    return;
                }
                const created = await response.json();
                this.newIngredientSuccess = `Created "${created.name}"!`;

                // Reload ingredient names
                await this.loadIngredientNames();

                // Add to the last ingredient row if it's empty, or create new row
                const lastIng = this.newCocktail.ingredients[this.newCocktail.ingredients.length - 1];
                if (lastIng && !lastIng.ingredient) {
                    lastIng.ingredient = created.name;
                } else {
                    this.newCocktail.ingredients.push({
                        ingredient: created.name,
                        amount: null,
                        unit: 'oz',
                        notes: '',
                        optional: false
                    });
                }

                // Close form after brief delay
                setTimeout(() => {
                    this.showNewIngredientForm = false;
                    this.newIngredientData = { name: '', parent: '' };
                    this.newIngredientSuccess = '';
                }, 1000);
            } catch (e) {
                this.newIngredientError = e.message;
            } finally {
                this.savingNewIngredient = false;
            }
        },

        async searchRecipe() {
            if (!this.recipeSearchQuery.trim()) {
                this.recipeSearchError = 'Please enter a cocktail name';
                return;
            }
            this.recipeSearching = true;
            this.recipeSearchError = '';
            this.recipeSearchSuccess = '';
            try {
                const response = await fetch('/api/v1/cocktails/search-recipe', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({query: this.recipeSearchQuery})
                });
                if (!response.ok) {
                    const error = await response.json();
                    this.recipeSearchError = formatApiError(error.detail, 'Failed to find recipe');
                    return;
                }
                const recipe = await response.json();

                // Populate the form with the found recipe
                this.newCocktail = {
                    name: recipe.name || this.recipeSearchQuery,
                    description: recipe.description || '',
                    parent_cocktail: recipe.parent_cocktail || '',
                    method: recipe.method || '',
                    style: recipe.style || '',
                    glassware: recipe.glassware || '',
                    garnish: recipe.garnish || '',
                    ingredients: recipe.ingredients || [{ingredient: '', amount: null, unit: 'oz', notes: '', optional: false}],
                    instructions: recipe.instructions || [''],
                };

                this.recipeSearchSuccess = `Recipe loaded! Review and edit before saving.`;
                setTimeout(() => {
                    this.showRecipeSearch = false;
                    this.recipeSearchQuery = '';
                    this.recipeSearchSuccess = '';
                }, 1500);
            } catch (e) {
                this.recipeSearchError = e.message;
            } finally {
                this.recipeSearching = false;
            }
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
