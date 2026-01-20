/**
 * Label Review Module - Grid view, metadata editing, label operations, tasting summaries
 * Part of the management.html refactor
 *
 * Usage: Call window.labelReviewModule() to get an object with all label review methods.
 * Spread this into your Alpine.js data object.
 */

window.labelReviewModule = function() {
    return {
        // State initialization
        initState() {
            return {
                // Label review mode
                labelsLoading: false,
                labelBottles: [],
                selectedLabelBottle: null,
                labelSearchResults: [],
                selectedSearchImage: null,
                labelCropPreview: null,
                labelActionInProgress: false,
                labelDownloadedOriginal: null,
                labelDownloadedCropped: null,
                labelGridTimestamp: Date.now(),
                currentLabelTimestamp: Date.now(),  // Cache buster for current label display
                manualCropActive: false,
                manualCropImageSrc: null,
                cropperInstance: null,
                manualCropDownloadedActive: false,
                manualCropDownloadedSrc: null,
                cropperDownloadedInstance: null,
                manualUploadFile: null,
                manualUploadPreview: null,

                // Grid filters
                gridFilterType: 'all',  // 'all', 'wine', 'whiskey'
                gridSearchQuery: '',

                // Tasting summary
                tastingSummary: null,
                tastingSummaryLoading: false,

                // Grid metadata editing
                gridEditedFields: {},
                gridVerifying: false,
                gridSaving: false,
                gridSaveSuccess: false,
                gridSearchResult: null,
                gridApprovedChanges: {},
            };
        },

        // Computed property for filtered bottles
        getFilteredBottles(labelBottles, gridFilterType, gridSearchQuery) {
            let bottles = labelBottles;

            // Filter by type
            if (gridFilterType !== 'all') {
                bottles = bottles.filter(b => b.type === gridFilterType);
            }

            // Filter by search (producer, name, year)
            if (gridSearchQuery) {
                const query = gridSearchQuery.toLowerCase();
                bottles = bottles.filter(b =>
                    (b.producer || '').toLowerCase().includes(query) ||
                    (b.name || '').toLowerCase().includes(query) ||
                    (b.year || '').toString().includes(query)
                );
            }

            return bottles;
        },

        // Reset operations on CURRENT label (auto-crop, manual-crop)
        // Call this before starting a new operation on current label
        resetCurrentLabelOperations() {
            // Clear auto-crop preview
            this.labelCropPreview = null;

            // Clear manual crop state
            if (this.cropperInstance) {
                this.cropperInstance.destroy();
                this.cropperInstance = null;
            }
            this.manualCropActive = false;
            this.manualCropImageSrc = null;
        },

        // Reset downloaded/uploaded image operations
        // Call this when going back to current label operations
        resetDownloadedOperations() {
            this.labelDownloadedOriginal = null;
            this.labelDownloadedCropped = null;
            if (this.cropperDownloadedInstance) {
                this.cropperDownloadedInstance.destroy();
                this.cropperDownloadedInstance = null;
            }
            this.manualCropDownloadedActive = false;
            this.manualCropDownloadedSrc = null;
            this.manualUploadFile = null;
            this.manualUploadPreview = null;
            const fileInputs = document.querySelectorAll('input[type="file"]');
            fileInputs.forEach(input => input.value = '');
        },

        async loadLabelsForReview() {
            this.labelsLoading = true;
            try {
                // Load all bottles from vault
                const response = await fetch('/api/v1/management/bottles');
                const data = await response.json();

                // Each bottle already has vault_path from the backend
                // We need to construct the full path to the label image
                this.labelBottles = data.bottles;

                // Update timestamp to bust browser cache
                this.labelGridTimestamp = Date.now();

                console.log(`Loaded ${this.labelBottles.length} bottles for label review`);
            } catch (error) {
                console.error('Failed to load bottles:', error);
                alert('Failed to load bottles: ' + error.message);
            } finally {
                this.labelsLoading = false;
            }
        },

        selectLabelBottle(bottle) {
            this.selectedLabelBottle = bottle;
            this.labelSearchResults = [];
            this.selectedSearchImage = null;
            this.labelCropPreview = null;
            this.labelDownloadedOriginal = null;
            this.labelDownloadedCropped = null;

            // Initialize editable fields with current bottle data
            // Map backend fields to Obsidian fields
            const country = bottle.country || '';
            const region = bottle.region || '';
            const country_region = country && region ? `${country} - ${region}` : (country || region || '');
            const region_state = country_region; // Same mapping for whiskey

            this.gridEditedFields = {
                producer: bottle.producer || '',
                name: bottle.name || '',
                type: bottle.type || 'wine',
                beverage_type: bottle.beverage_type || '',
                year: bottle.year || null,
                variety: bottle.variety || '',
                vineyard: bottle.vineyard || '',
                age_statement: bottle.age_statement || '',
                proof: bottle.proof || null,
                mash_bill: bottle.mash_bill || '',
                barrel_type: bottle.barrel_type || '',
                batch_number: bottle.batch_number || '',
                bottle_number: bottle.bottle_number || '',
                abv: bottle.abv || '',
                style: bottle.style || '',
                price: bottle.price || '',
                inventory: bottle.inventory || 0,
                purchase_source: bottle.purchase_source || '',
                purchase_link: bottle.purchase_link || '',
                buy: bottle.buy || 0,
                value_for_money: bottle.value_for_money || null,
                points: bottle.points || '',
                stars: bottle.stars || '',
                bottle_opened_date: bottle.bottle_opened_date || '',
                country_region: country_region,
                region_state: region_state
            };

            // Reset metadata editing state
            this.gridSaveSuccess = false;
            this.gridSearchResult = null;
            this.gridApprovedChanges = {};

            // Load tasting summary
            this.loadTastingSummary();
        },

        async searchMetadata() {
            if (!this.selectedLabelBottle) return;

            this.gridVerifying = true;
            this.gridSaveSuccess = false;
            this.gridSearchResult = null;
            this.gridApprovedChanges = {};

            try {
                // Create a bottle object from current form values
                const currentBottle = {
                    ...this.selectedLabelBottle,
                    ...this.gridEditedFields
                };

                // Clean up empty strings to null for numeric fields
                const numericFields = ['year', 'age_statement', 'proof', 'abv', 'price', 'inventory', 'buy', 'value_for_money'];
                for (const field of numericFields) {
                    if (currentBottle[field] === '' || currentBottle[field] === null) {
                        currentBottle[field] = null;
                    }
                }

                const response = await fetch(`/api/v1/management/bottles/${this.selectedLabelBottle._index || 0}/verify`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bottle: currentBottle })
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.detail || 'Search failed');
                }

                const data = await response.json();
                this.gridSearchResult = data;

                // Initialize all changes as approved by default
                if (data.changes) {
                    for (const field in data.changes) {
                        this.gridApprovedChanges[field] = true;
                    }
                }
            } catch (error) {
                console.error('Search failed:', error);
                alert('Search failed: ' + error.message);
            } finally {
                this.gridVerifying = false;
            }
        },

        applySelectedChanges() {
            if (!this.gridSearchResult || !this.gridSearchResult.changes) return;

            // Apply approved changes to the editable form
            for (const field in this.gridSearchResult.changes) {
                if (this.gridApprovedChanges[field] && this.gridEditedFields.hasOwnProperty(field)) {
                    this.gridEditedFields[field] = this.gridSearchResult.changes[field].new;
                }
            }

            // Clear search result to hide comparison view
            this.gridSearchResult = null;
            this.gridApprovedChanges = {};
        },

        getFieldLabel(fieldKey) {
            const labels = {
                producer: 'Winemaker/Distiller',
                name: 'Wine/Whiskey Name',
                type: 'Category',
                beverage_type: 'Type',
                year: 'Vintage/Year',
                country: 'Country',
                region: 'Region',
                country_region: 'Country-Region',
                region_state: 'Region-State',
                variety: 'Variety',
                vineyard: 'Vineyard',
                style: 'Style',
                age_statement: 'Age Statement',
                proof: 'Proof',
                mash_bill: 'Mash Bill',
                barrel_type: 'Barrel Type',
                batch_number: 'Batch Number',
                bottle_number: 'Bottle Number',
                abv: 'ABV',
                price: 'Price',
                inventory: 'Inventory',
                purchase_source: 'Purchase Source',
                purchase_link: 'Purchase Link',
                buy: 'Buy',
                value_for_money: 'Value For Money',
                points: 'Points',
                stars: 'Stars',
                bottle_opened_date: 'Bottle Opened Date'
            };
            return labels[fieldKey] || fieldKey;
        },

        async saveGridMetadata() {
            if (!this.selectedLabelBottle) return;

            this.gridSaving = true;
            this.gridSaveSuccess = false;

            try {
                // Prepare updates - convert Obsidian fields back to model fields
                const updates = {};

                // Handle country_region / region_state splitting
                const isWine = this.selectedLabelBottle.type === 'wine';
                const combinedField = isWine ? 'country_region' : 'region_state';
                const combinedValue = this.gridEditedFields[combinedField];

                if (combinedValue) {
                    const parts = combinedValue.split(' - ').map(p => p.trim());
                    if (parts.length === 2) {
                        updates.country = parts[0];
                        updates.region = parts[1];
                    } else {
                        // If no separator, put everything in country
                        updates.country = combinedValue;
                        updates.region = '';
                    }
                }

                // Map other fields
                const fieldMappings = {
                    producer: 'producer',
                    name: 'name',
                    year: 'year',
                    beverage_type: 'beverage_type',
                    variety: 'variety',
                    vineyard: 'vineyard',
                    style: 'style',
                    age_statement: 'age_statement',
                    proof: 'proof',
                    mash_bill: 'mash_bill',
                    barrel_type: 'barrel_type',
                    batch_number: 'batch_number',
                    bottle_number: 'bottle_number',
                    abv: 'abv',
                    price: 'price',
                    inventory: 'inventory',
                    purchase_source: 'purchase_source',
                    purchase_link: 'purchase_link',
                    buy: 'buy',
                    value_for_money: 'value_for_money',
                    points: 'points',
                    stars: 'stars',
                    bottle_opened_date: 'bottle_opened_date'
                };

                for (const [formField, modelField] of Object.entries(fieldMappings)) {
                    const editedValue = this.gridEditedFields[formField];
                    const originalValue = this.selectedLabelBottle[modelField];

                    if (editedValue !== originalValue && editedValue !== undefined) {
                        if (editedValue === '' || editedValue === null) {
                            updates[modelField] = null;
                        } else {
                            updates[modelField] = editedValue;
                        }
                    }
                }

                if (Object.keys(updates).length === 0) {
                    alert('No changes to save');
                    this.gridSaving = false;
                    return;
                }

                console.log('Saving updates:', updates);

                const response = await fetch('/api/v1/management/bottles/update-fields', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: this.selectedLabelBottle,
                        updates: updates
                    })
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`Failed to save: ${errorText}`);
                }

                this.gridSaveSuccess = true;
                this.gridSearchResult = null;
                this.gridApprovedChanges = {};

                // Refresh the bottle data
                await this.loadLabelsForReview();

                // Find and update the selected bottle with fresh data
                const updatedBottle = this.labelBottles.find(b => b.vault_path === this.selectedLabelBottle.vault_path);
                if (updatedBottle) {
                    // Re-select to reinitialize form
                    this.selectLabelBottle(updatedBottle);
                }

                // Hide success message after 3 seconds
                setTimeout(() => {
                    this.gridSaveSuccess = false;
                }, 3000);
            } catch (error) {
                console.error('Save failed:', error);
                alert('Failed to save changes: ' + error.message);
            } finally {
                this.gridSaving = false;
            }
        },

        async loadTastingSummary() {
            if (!this.selectedLabelBottle) return;

            this.tastingSummaryLoading = true;
            try {
                const response = await fetch('/api/v1/management/bottles/tastings-summary', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ bottle: this.selectedLabelBottle })
                });

                if (!response.ok) throw new Error('Failed to load tasting summary');

                this.tastingSummary = await response.json();
            } catch (error) {
                console.error('Failed to load tasting summary:', error);
                this.tastingSummary = null;
            } finally {
                this.tastingSummaryLoading = false;
            }
        },

        async searchForLabelReplacement() {
            if (!this.selectedLabelBottle) return;

            // Reset current label operations (keep downloaded state for workflow continuity)
            this.resetCurrentLabelOperations();

            this.labelActionInProgress = true;
            try {
                // Use existing label search endpoint (from upload flow)
                const response = await fetch('/api/v1/bottles/search-labels', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(this.selectedLabelBottle)
                });

                const data = await response.json();
                this.labelSearchResults = data.images || [];
                console.log(`Found ${this.labelSearchResults.length} label candidates`);
            } catch (error) {
                console.error('Label search failed:', error);
                alert('Label search failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        async cropExistingLabel() {
            if (!this.selectedLabelBottle) return;

            // Reset conflicting operations first
            this.resetCurrentLabelOperations();
            this.resetDownloadedOperations();

            this.labelActionInProgress = true;
            try {
                // Call backend to crop current label using improved detection
                const response = await fetch('/api/v1/management/labels/crop-current', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: this.selectedLabelBottle
                    })
                });

                const data = await response.json();
                // Show preview of cropped version
                this.labelCropPreview = `/api/v1/labels/view?path=${encodeURIComponent(data.preview_path)}&t=${Date.now()}`;
            } catch (error) {
                console.error('Crop failed:', error);
                alert('Crop failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        async useSelectedSearchImage() {
            if (!this.selectedSearchImage || !this.selectedLabelBottle) return;

            this.labelActionInProgress = true;
            try {
                console.log('Download request - selected image:', this.selectedSearchImage);
                console.log('Download request - URL:', this.selectedSearchImage.url);

                // Download selected image (no cropping yet)
                const response = await fetch('/api/v1/management/labels/download-image', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: this.selectedLabelBottle,
                        image_url: this.selectedSearchImage.url
                    })
                });

                if (!response.ok) {
                    const errorText = await response.text();
                    console.error('Download failed:', errorText);
                    throw new Error('Failed to download image');
                }

                const data = await response.json();
                // Show downloaded original with aggressive cache busting
                const cacheBuster = `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                this.labelDownloadedOriginal = `/api/v1/labels/view?path=${encodeURIComponent(data.download_path)}&t=${cacheBuster}`;
                this.labelDownloadedCropped = null;
                // Clear search results since we now have downloaded image
                this.labelSearchResults = [];
                this.selectedSearchImage = null;
            } catch (error) {
                console.error('Failed to download image:', error);
                alert('Failed to download image: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        async cropDownloadedImage() {
            if (!this.selectedLabelBottle) return;

            // Clear any existing cropped preview first to force fresh load
            this.labelDownloadedCropped = null;

            this.labelActionInProgress = true;
            try {
                const response = await fetch('/api/v1/management/labels/crop-download', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: this.selectedLabelBottle
                    })
                });

                if (!response.ok) throw new Error('Failed to crop');

                const data = await response.json();

                // Use nextTick to ensure DOM clears before loading new image
                this.$nextTick(() => {
                    // Add random component to guarantee uniqueness and bust cache
                    const cacheBuster = `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                    this.labelDownloadedCropped = `/api/v1/labels/view?path=${encodeURIComponent(data.cropped_path)}&t=${cacheBuster}`;
                });
            } catch (error) {
                console.error('Failed to crop:', error);
                alert('Failed to crop: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        async useDownloadedLabel(useCropped) {
            if (!this.selectedLabelBottle) return;

            this.labelActionInProgress = true;
            try {
                const response = await fetch('/api/v1/management/labels/use-downloaded', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: this.selectedLabelBottle,
                        use_cropped: useCropped
                    })
                });

                if (!response.ok) throw new Error('Failed to replace label');

                // Update timestamp to force reload of current label
                this.currentLabelTimestamp = Date.now();

                this.showToast('Label replaced successfully!');
                // Go back to grid
                this.selectedLabelBottle = null;
                this.labelDownloadedOriginal = null;
                this.labelDownloadedCropped = null;
                // Reload bottles to show new label
                await this.loadLabelsForReview();
            } catch (error) {
                console.error('Failed to replace label:', error);
                alert('Failed to replace label: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        cancelDownload() {
            this.labelDownloadedOriginal = null;
            this.labelDownloadedCropped = null;
        },

        startManualCrop() {
            if (!this.selectedLabelBottle) return;

            // Reset ALL conflicting operations first
            this.resetCurrentLabelOperations();
            this.resetDownloadedOperations();

            // Set the image source from current label
            const labelPath = '/mnt/d/Users/ben/Documents/spirits/the-reserve/Cellar/' +
                              this.selectedLabelBottle.vault_path + '/labels/label.jpg';
            this.manualCropImageSrc = `/api/v1/labels/view?path=${encodeURIComponent(labelPath)}&t=${Date.now()}`;
            this.manualCropActive = true;

            // Initialize Cropper.js after image loads
            this.$nextTick(() => {
                const image = document.getElementById('manualCropImage');
                if (image && typeof Cropper !== 'undefined') {
                    // Wait for image to load before initializing Cropper
                    const initCropper = () => {
                        this.cropperInstance = new Cropper(image, {
                            viewMode: 1,
                            dragMode: 'crop',           // 'crop' mode = drag to adjust box, not move image
                            aspectRatio: NaN,           // Free aspect ratio
                            autoCropArea: 0.8,
                            restore: false,
                            guides: true,
                            center: true,
                            highlight: true,
                            movable: false,             // Prevent moving the underlying image
                            cropBoxMovable: true,       // Allow moving the crop box
                            cropBoxResizable: true,     // Allow resizing the crop box
                            toggleDragModeOnDblclick: false,
                        });
                    };

                    // If image is already loaded, init immediately
                    if (image.complete && image.naturalHeight !== 0) {
                        initCropper();
                    } else {
                        // Otherwise wait for load event
                        image.onload = initCropper;
                        image.onerror = () => {
                            console.error('Failed to load image for manual crop');
                            alert('Failed to load image. Please try again.');
                            this.cancelManualCrop();
                        };
                    }
                }
            });
        },

        async acceptManualCrop() {
            if (!this.cropperInstance || !this.selectedLabelBottle) return;

            this.labelActionInProgress = true;
            try {
                // Get crop box data
                const cropData = this.cropperInstance.getData(true); // true = rounded pixels

                // Send to backend for cropping
                const response = await fetch('/api/v1/management/labels/manual-crop', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: this.selectedLabelBottle,
                        x: Math.round(cropData.x),
                        y: Math.round(cropData.y),
                        width: Math.round(cropData.width),
                        height: Math.round(cropData.height)
                    })
                });

                if (!response.ok) throw new Error('Failed to crop');

                // Update timestamps to force reload of labels (detail view AND grid view)
                this.currentLabelTimestamp = Date.now();
                this.labelGridTimestamp = Date.now();

                this.showToast('Label cropped successfully!');

                // Cleanup
                this.cancelManualCrop();

                // Go back to grid
                this.selectedLabelBottle = null;

                // Reload bottles to show new label
                await this.loadLabelsForReview();
            } catch (error) {
                console.error('Manual crop failed:', error);
                alert('Manual crop failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        cancelManualCrop() {
            if (this.cropperInstance) {
                this.cropperInstance.destroy();
                this.cropperInstance = null;
            }
            this.manualCropActive = false;
            this.manualCropImageSrc = null;
        },

        // Manual crop for downloaded images
        startManualCropDownloaded() {
            if (!this.selectedLabelBottle || !this.labelDownloadedOriginal) return;

            // Clean up any existing cropper first
            if (this.cropperDownloadedInstance) {
                this.cropperDownloadedInstance.destroy();
                this.cropperDownloadedInstance = null;
            }

            // Set the image source from downloaded file
            const labelPath = '/mnt/d/Users/ben/Documents/spirits/the-reserve/Cellar/' +
                              this.selectedLabelBottle.vault_path + '/labels/label_download.jpg';
            this.manualCropDownloadedSrc = `/api/v1/labels/view?path=${encodeURIComponent(labelPath)}&t=${Date.now()}`;
            this.manualCropDownloadedActive = true;

            // Initialize Cropper.js after image loads
            this.$nextTick(() => {
                const image = document.getElementById('manualCropDownloadedImage');
                if (image && typeof Cropper !== 'undefined') {
                    // Wait for image to load before initializing Cropper
                    const initCropper = () => {
                        this.cropperDownloadedInstance = new Cropper(image, {
                            viewMode: 1,
                            dragMode: 'crop',           // 'crop' mode = drag to adjust box, not move image
                            aspectRatio: NaN,           // Free aspect ratio
                            autoCropArea: 0.8,
                            restore: false,
                            guides: true,
                            center: true,
                            highlight: true,
                            movable: false,             // Prevent moving the underlying image
                            cropBoxMovable: true,       // Allow moving the crop box
                            cropBoxResizable: true,     // Allow resizing the crop box
                            toggleDragModeOnDblclick: false,
                        });
                    };

                    // If image is already loaded, init immediately
                    if (image.complete && image.naturalHeight !== 0) {
                        initCropper();
                    } else {
                        // Otherwise wait for load event
                        image.onload = initCropper;
                        image.onerror = () => {
                            console.error('Failed to load downloaded image for manual crop');
                            alert('Failed to load image. Please try again.');
                            this.cancelManualCropDownloaded();
                        };
                    }
                }
            });
        },

        async acceptManualCropDownloaded() {
            if (!this.cropperDownloadedInstance || !this.selectedLabelBottle) return;

            this.labelActionInProgress = true;
            try {
                // Get crop box data
                const cropData = this.cropperDownloadedInstance.getData(true); // true = rounded pixels

                // Send to backend for cropping
                const response = await fetch('/api/v1/management/labels/manual-crop-downloaded', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: this.selectedLabelBottle,
                        x: Math.round(cropData.x),
                        y: Math.round(cropData.y),
                        width: Math.round(cropData.width),
                        height: Math.round(cropData.height)
                    })
                });

                if (!response.ok) throw new Error('Failed to crop downloaded image');

                // Cleanup cropper
                this.cancelManualCropDownloaded();

                // Force cache clear by nulling first, then setting with new timestamp
                this.labelDownloadedCropped = null;

                // Use nextTick to ensure DOM updates before setting new URL
                this.$nextTick(() => {
                    const croppedPath = '/mnt/d/Users/ben/Documents/spirits/the-reserve/Cellar/' +
                                        this.selectedLabelBottle.vault_path + '/labels/label_download_cropped.jpg';
                    // Add random component to guarantee uniqueness and bust cache
                    const cacheBuster = `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                    this.labelDownloadedCropped = `/api/v1/labels/view?path=${encodeURIComponent(croppedPath)}&t=${cacheBuster}`;
                });

                this.showToast('Downloaded image cropped successfully!');
            } catch (error) {
                console.error('Manual crop of downloaded failed:', error);
                alert('Manual crop failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        cancelManualCropDownloaded() {
            if (this.cropperDownloadedInstance) {
                this.cropperDownloadedInstance.destroy();
                this.cropperDownloadedInstance = null;
            }
            this.manualCropDownloadedActive = false;
            this.manualCropDownloadedSrc = null;
        },

        recropDownloaded() {
            // Clear the cropped version so user can try again
            this.labelDownloadedCropped = null;
            // Also destroy any active manual crop instance for downloaded
            if (this.cropperDownloadedInstance) {
                this.cropperDownloadedInstance.destroy();
                this.cropperDownloadedInstance = null;
            }
            this.manualCropDownloadedActive = false;
        },

        handleManualLabelUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            // Reset current label operations when uploading new image
            this.resetCurrentLabelOperations();

            this.manualUploadFile = file;

            // Show preview
            const reader = new FileReader();
            reader.onload = (e) => {
                this.manualUploadPreview = e.target.result;
            };
            reader.readAsDataURL(file);
        },

        async uploadManualLabelImage() {
            if (!this.manualUploadFile || !this.selectedLabelBottle) return;

            this.labelActionInProgress = true;
            try {
                // Create FormData to upload file
                const formData = new FormData();
                formData.append('file', this.manualUploadFile);
                formData.append('bottle', JSON.stringify(this.selectedLabelBottle));

                const response = await fetch('/api/v1/management/labels/upload-manual', {
                    method: 'POST',
                    body: formData
                });

                if (!response.ok) throw new Error('Failed to upload image');

                const result = await response.json();

                // Clear manual upload state
                this.cancelManualUpload();

                // Now show as downloaded image (reuse download workflow)
                const downloadPath = '/mnt/d/Users/ben/Documents/spirits/the-reserve/Cellar/' +
                                      this.selectedLabelBottle.vault_path + '/labels/label_download.jpg';
                const cacheBuster = `${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
                this.labelDownloadedOriginal = `/api/v1/labels/view?path=${encodeURIComponent(downloadPath)}&t=${cacheBuster}`;
                this.labelDownloadedCropped = null;

                this.showToast('Image uploaded! You can now crop it or use as-is.');
            } catch (error) {
                console.error('Manual upload failed:', error);
                alert('Upload failed: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },

        cancelManualUpload() {
            this.manualUploadFile = null;
            this.manualUploadPreview = null;
            // Reset file input
            const fileInputs = document.querySelectorAll('input[type="file"]');
            fileInputs.forEach(input => input.value = '');
        },

        async acceptLabelCrop() {
            if (!this.selectedLabelBottle) return;

            this.labelActionInProgress = true;
            try {
                // Accept the cropped version
                const response = await fetch('/api/v1/management/labels/accept-crop', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        bottle: this.selectedLabelBottle
                    })
                });

                if (!response.ok) throw new Error('Failed to accept crop');

                // Update timestamp to force reload of current label
                this.currentLabelTimestamp = Date.now();

                this.showToast('Cropped label accepted!');
                // Clear preview state
                this.labelCropPreview = null;
                // Go back to grid
                this.selectedLabelBottle = null;
                // Reload bottles
                await this.loadLabelsForReview();
            } catch (error) {
                console.error('Failed to accept crop:', error);
                alert('Failed to accept crop: ' + error.message);
            } finally {
                this.labelActionInProgress = false;
            }
        },
    };
};
