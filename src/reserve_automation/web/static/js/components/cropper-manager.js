/**
 * Cropper Manager - Reusable Cropper.js lifecycle management
 *
 * Handles initialization, configuration, and cleanup of Cropper.js instances.
 * Used by both upload workflow (temp labels) and management workflow (vault labels).
 */

window.cropperManager = {
    /**
     * Default Cropper.js configuration
     */
    defaultConfig: {
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
    },

    /**
     * Initialize Cropper.js on an image element
     *
     * @param {HTMLImageElement} imageElement - The image element to crop
     * @param {Object} config - Optional Cropper.js configuration overrides
     * @param {Function} onError - Error callback
     * @returns {Promise<Cropper>} - Promise that resolves with Cropper instance
     */
    async initializeCropper(imageElement, config = {}, onError = null) {
        if (!imageElement) {
            throw new Error('Image element is required');
        }

        if (typeof Cropper === 'undefined') {
            throw new Error('Cropper.js library not loaded');
        }

        // Merge custom config with defaults
        const cropperConfig = { ...this.defaultConfig, ...config };

        return new Promise((resolve, reject) => {
            const initCropper = () => {
                try {
                    const cropperInstance = new Cropper(imageElement, cropperConfig);
                    resolve(cropperInstance);
                } catch (error) {
                    console.error('Failed to initialize Cropper:', error);
                    if (onError) onError(error);
                    reject(error);
                }
            };

            // If image is already loaded, init immediately
            if (imageElement.complete && imageElement.naturalHeight !== 0) {
                initCropper();
            } else {
                // Otherwise wait for load event
                imageElement.onload = initCropper;
                imageElement.onerror = () => {
                    const error = new Error('Failed to load image for cropping');
                    console.error(error);
                    if (onError) onError(error);
                    reject(error);
                };
            }
        });
    },

    /**
     * Get crop data from Cropper instance
     * Returns rounded pixel coordinates ready for backend processing
     *
     * @param {Cropper} cropperInstance - Active Cropper instance
     * @returns {Object} - Crop coordinates { x, y, width, height }
     */
    getCropData(cropperInstance) {
        if (!cropperInstance) {
            throw new Error('Cropper instance is required');
        }

        // Get crop box data with rounded pixels
        const cropData = cropperInstance.getData(true);

        return {
            x: Math.round(cropData.x),
            y: Math.round(cropData.y),
            width: Math.round(cropData.width),
            height: Math.round(cropData.height)
        };
    },

    /**
     * Destroy Cropper instance and clean up
     *
     * @param {Cropper} cropperInstance - Cropper instance to destroy
     */
    destroyCropper(cropperInstance) {
        if (cropperInstance) {
            try {
                cropperInstance.destroy();
            } catch (error) {
                console.error('Error destroying Cropper:', error);
            }
        }
    },

    /**
     * Send crop coordinates to backend for processing
     *
     * @param {string} endpoint - API endpoint URL
     * @param {Object} data - Request data (must include x, y, width, height)
     * @returns {Promise<Response>} - Fetch response
     */
    async sendCropRequest(endpoint, data) {
        const response = await fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`Crop request failed: ${response.status} ${errorText}`);
        }

        return response;
    },

    /**
     * Complete manual crop workflow:
     * 1. Get crop data from Cropper instance
     * 2. Send to backend
     * 3. Destroy Cropper instance
     * 4. Call success/error callbacks
     *
     * @param {Cropper} cropperInstance - Active Cropper instance
     * @param {string} endpoint - Backend API endpoint
     * @param {Object} additionalData - Additional data to send with crop coordinates
     * @param {Function} onSuccess - Success callback
     * @param {Function} onError - Error callback
     */
    async completeCrop(cropperInstance, endpoint, additionalData = {}, onSuccess = null, onError = null) {
        try {
            // Get crop coordinates
            const cropData = this.getCropData(cropperInstance);

            // Send to backend
            const response = await this.sendCropRequest(endpoint, {
                ...additionalData,
                ...cropData
            });

            // Parse response if JSON
            let result = null;
            const contentType = response.headers.get('content-type');
            if (contentType && contentType.includes('application/json')) {
                result = await response.json();
            }

            // Cleanup
            this.destroyCropper(cropperInstance);

            // Success callback
            if (onSuccess) {
                onSuccess(result);
            }

            return result;
        } catch (error) {
            console.error('Crop failed:', error);

            // Cleanup even on error
            this.destroyCropper(cropperInstance);

            // Error callback
            if (onError) {
                onError(error);
            }

            throw error;
        }
    }
};
