/**
 * Ingredients page root component (window.ingredientsApp).
 *
 * Extracted from templates/ingredients.html (July 2026) so the logic gets
 * vitest unit coverage (tests/js/ingredients-page.test.js). Attached as a
 * WHOLE factory (the established pattern for page root components — see
 * management/management-app.js): the returned object is handed to Alpine
 * intact, never spread.
 *
 * Owns the ingredient tree UI: tree load + flat-name walk (parent
 * autocomplete), search (including the #search= hash deep-link from cocktail
 * ingredient links), the imperative renderNode() tree renderer with
 * expand/collapse toggles, the view/add/edit modals, and create/update/delete
 * against the ingredients API. The tree is important collection
 * infrastructure: cocktail recipe ingredients are free text matched by NAME,
 * so renames/deletes here can orphan recipes (the backend blocks deletes of
 * referenced ingredients with a 409).
 */

// #CLAUDE_REQ: State keys, method names, and $refs used here (tree, treeVersion,
//              loading, searchQuery, searchMode, searchResults, showViewForm,
//              showAddForm, showEditForm, saving, formError, allIngredientNames,
//              viewData, formData, init/loadTree/doSearch/renderNode/
//              viewIngredient/viewIngredientByName/editIngredient/editFromView/
//              resetForm/openAddForm/closeModal/saveIngredient/deleteIngredient/
//              expandAll/collapseAll/handleAutocomplete, $refs.nameInput) MUST
//              match the Alpine bindings in templates/ingredients.html
//              (x-data="ingredientsApp()"). Rename in both places or the page
//              silently loses functionality.
// #CLAUDE_REQ: Endpoints and payload/response shapes must match
//              web/routes/ingredients.py:
//              GET  /api/v1/ingredients          (tree of nested dicts)
//              GET  /api/v1/ingredients/search?q= (tree-shaped matches)
//              GET  /api/v1/ingredients/{id}     (dict with ancestors/children)
//              POST /api/v1/ingredients          (name, parent, cost, volume_ml, abv, notes)
//              PUT  /api/v1/ingredients/{id}     (same payload)
//              DELETE /api/v1/ingredients/{id}   (409 if children or recipe refs)

window.ingredientsApp = function() {
    return {
        tree: [],
        treeVersion: 0,
        loading: true,
        searchQuery: '',
        searchMode: false,
        searchResults: [],
        showViewForm: false,
        showAddForm: false,
        showEditForm: false,
        saving: false,
        formError: '',
        editId: null,
        addParent: null,
        allIngredientNames: [],
        viewData: {},
        formData: {
            name: '',
            parent: '',
            cost: null,
            volume_ml: null,
            abv: null,
            notes: ''
        },

        async init() {
            await this.loadTree();
            // Check for hash parameter (e.g., #search=Vodka from cocktail ingredient link)
            const hash = window.location.hash;
            if (hash && hash.startsWith('#search=')) {
                const searchTerm = decodeURIComponent(hash.substring(8));
                this.searchQuery = searchTerm;
                await this.doSearch();
                // If only one result, auto-open it
                if (this.searchResults.length === 1) {
                    this.viewIngredient(this.searchResults[0]);
                }
                // Clear the hash
                window.history.replaceState(null, '', window.location.pathname);
            }
        },

        async loadTree() {
            try {
                this.loading = true;
                const response = await fetch('/api/v1/ingredients');
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.tree = await response.json();
                this.treeVersion++; // Force re-render

                // Build flat name list for parent suggestions
                const names = [];
                const walk = (nodes) => {
                    for (const n of nodes) {
                        names.push(n.name);
                        if (n.children) walk(n.children);
                    }
                };
                walk(this.tree);
                this.allIngredientNames = names;
            } catch (error) {
                console.error('Failed to load ingredients:', error);
            } finally {
                this.loading = false;
                // Expand tree after DOM renders (happens on every tree load)
                this.$nextTick(() => {
                    setTimeout(() => this.expandAll(), 50);
                });
            }
        },

        async doSearch() {
            if (!this.searchQuery.trim()) {
                this.searchMode = false;
                this.searchResults = [];
                return;
            }
            this.searchMode = true;
            try {
                const response = await fetch(`/api/v1/ingredients/search?q=${encodeURIComponent(this.searchQuery)}`);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                this.searchResults = await response.json();
                // Auto-expand search results after DOM renders
                this.$nextTick(() => {
                    setTimeout(() => this.expandAll(), 50);
                });
            } catch (error) {
                console.error('Search failed:', error);
            }
        },

        renderNode(node, el, depth) {
            el.innerHTML = '';
            const container = document.createElement('div');

            // Node row
            const row = document.createElement('div');
            row.className = 'p-3 hover:bg-gray-50 flex items-center justify-between border-b border-gray-100 cursor-pointer';
            row.style.paddingLeft = (16 + depth * 24) + 'px';
            row.addEventListener('click', (e) => {
                // Don't trigger if clicking on action buttons
                if (e.target.closest('button')) return;
                this.viewIngredient(node);
            });

            const left = document.createElement('div');
            left.className = 'flex items-center gap-2';

            // Expand/collapse toggle
            if (node.children && node.children.length > 0) {
                const toggle = document.createElement('button');
                toggle.className = 'text-gray-400 hover:text-gray-600 w-5 text-center';
                toggle.textContent = '▶';
                toggle.dataset.expanded = 'false';
                const childContainer = document.createElement('div');
                childContainer.style.display = 'none';
                toggle.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const expanded = toggle.dataset.expanded === 'true';
                    toggle.dataset.expanded = expanded ? 'false' : 'true';
                    toggle.textContent = expanded ? '▶' : '▼';
                    childContainer.style.display = expanded ? 'none' : 'block';
                });
                left.appendChild(toggle);

                // Children
                for (const child of node.children) {
                    const childEl = document.createElement('div');
                    this.renderNode(child, childEl, depth + 1);
                    childContainer.appendChild(childEl);
                }
                container.appendChild(childContainer);
            } else {
                const spacer = document.createElement('span');
                spacer.className = 'w-5 inline-block';
                spacer.textContent = '·';
                left.appendChild(spacer);
            }

            // Icon
            const icon = document.createElement('span');
            icon.textContent = node.is_product ? '🏷️' : '📁';
            left.appendChild(icon);

            // Name
            const name = document.createElement('span');
            name.className = 'font-medium text-gray-800';
            name.textContent = node.name;
            left.appendChild(name);

            // Cost badge
            if (node.cost) {
                const cost = document.createElement('span');
                cost.className = 'text-green-700 text-sm font-medium';
                cost.textContent = `$${node.cost}`;
                left.appendChild(cost);
            }

            row.appendChild(left);

            // Action buttons
            const actions = document.createElement('div');
            actions.className = 'flex gap-2';

            const addChild = document.createElement('button');
            addChild.className = 'text-green-600 hover:text-green-800 text-sm px-2 py-1';
            addChild.textContent = '+ Child';
            addChild.addEventListener('click', (e) => {
                e.stopPropagation();
                this.openAddForm(node.name);
            });
            actions.appendChild(addChild);

            const editBtn = document.createElement('button');
            editBtn.className = 'text-blue-600 hover:text-blue-800 text-sm px-2 py-1';
            editBtn.textContent = 'Edit';
            editBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                this.editIngredient(node);
            });
            actions.appendChild(editBtn);

            row.appendChild(actions);

            // Insert row at the beginning (before child container)
            container.insertBefore(row, container.firstChild);
            el.appendChild(container);
        },

        viewIngredient(ing) {
            this.viewData = { ...ing };
            this.showViewForm = true;
        },

        async viewIngredientByName(name) {
            // Search for ingredient and show focused tree view with it as root
            try {
                // Set search to the ingredient name - this will show it + children
                this.searchQuery = name;
                await this.doSearch();

                // Find exact match in search results
                const match = this.searchResults.find(r => r.name === name);
                if (match) {
                    // Fetch full details to ensure we have all fields
                    const detailResponse = await fetch(`/api/v1/ingredients/${match.id}`);
                    if (detailResponse.ok) {
                        const details = await detailResponse.json();
                        // Open the ingredient detail modal
                        this.viewIngredient(details);
                    } else {
                        // Fallback to match data
                        this.viewIngredient(match);
                    }
                }
            } catch (error) {
                console.error('Failed to load ingredient:', error);
            }
        },

        editIngredient(ing) {
            this.editId = ing.id;
            this.formData = {
                name: ing.name || '',
                parent: ing.parent || '',
                cost: ing.cost || null,
                volume_ml: ing.volume_ml || null,
                abv: ing.abv || null,
                notes: ing.notes || ''
            };
            this.formError = '';
            this.showEditForm = true;
            // Focus name input after modal is visible
            this.$nextTick(() => {
                if (this.$refs.nameInput) {
                    this.$refs.nameInput.focus();
                }
            });
        },

        editFromView() {
            const ing = this.viewData;
            this.showViewForm = false;
            this.editIngredient(ing);
        },

        resetForm() {
            this.formData = {
                name: '',
                parent: '',
                cost: null,
                volume_ml: null,
                abv: null,
                notes: ''
            };
            this.formError = '';
            this.editId = null;
        },

        openAddForm(parent) {
            this.addParent = parent;
            this.resetForm();
            if (parent) {
                this.formData.parent = parent;
            }
            this.showAddForm = true;
            // Focus name input after modal is visible
            this.$nextTick(() => {
                if (this.$refs.nameInput) {
                    this.$refs.nameInput.focus();
                }
            });
        },

        closeModal() {
            this.showAddForm = false;
            this.showEditForm = false;
            this.resetForm();
        },

        async saveIngredient() {
            if (!this.formData.name.trim()) {
                this.formError = 'Name is required';
                return;
            }

            this.saving = true;
            this.formError = '';

            try {
                // Clean up empty strings to null
                const payload = { ...this.formData };
                if (!payload.parent) payload.parent = null;
                if (!payload.cost) payload.cost = null;
                if (!payload.volume_ml) payload.volume_ml = null;
                if (!payload.abv) payload.abv = null;
                if (!payload.notes) payload.notes = null;

                let response;
                if (this.showEditForm && this.editId) {
                    response = await fetch(`/api/v1/ingredients/${this.editId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                } else {
                    response = await fetch('/api/v1/ingredients', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(payload)
                    });
                }

                if (!response.ok) {
                    const error = await response.json();
                    this.formError = error.detail || 'Failed to save';
                    return;
                }

                this.closeModal();
                await this.loadTree();
                // If in search mode, re-run the search to update results
                if (this.searchMode && this.searchQuery) {
                    await this.doSearch();
                }
            } catch (error) {
                this.formError = error.message;
            } finally {
                this.saving = false;
            }
        },

        async deleteIngredient() {
            if (!this.editId) return;
            if (!confirm('Delete this ingredient? This cannot be undone.')) return;

            try {
                const response = await fetch(`/api/v1/ingredients/${this.editId}`, { method: 'DELETE' });
                if (!response.ok) {
                    const error = await response.json();
                    this.formError = error.detail || 'Failed to delete';
                    return;
                }
                this.closeModal();
                await this.loadTree();
                // If in search mode, re-run the search to update results
                if (this.searchMode && this.searchQuery) {
                    await this.doSearch();
                }
            } catch (error) {
                this.formError = error.message;
            }
        },

        expandAll() {
            // Find all toggle buttons and expand them
            const toggles = document.querySelectorAll('button[data-expanded]');
            toggles.forEach(toggle => {
                if (toggle.dataset.expanded === 'false') {
                    toggle.click();
                }
            });
        },

        collapseAll() {
            // Find all toggle buttons and collapse them
            const toggles = document.querySelectorAll('button[data-expanded]');
            toggles.forEach(toggle => {
                if (toggle.dataset.expanded === 'true') {
                    toggle.click();
                }
            });
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
