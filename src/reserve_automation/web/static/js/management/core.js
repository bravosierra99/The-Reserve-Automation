/**
 * Core Management Module - Shared utilities, toast, mode selection
 * Part of the management.html refactor
 */

export function coreModule() {
    return {
        // Toast notification system
        toasts: [],
        toastIdCounter: 0,

        showToast(message, type = 'success', duration = 2000) {
            const id = ++this.toastIdCounter;
            const toast = { id, message, type };
            this.toasts.push(toast);

            // Auto-dismiss after duration
            setTimeout(() => {
                this.toasts = this.toasts.filter(t => t.id !== id);
            }, duration);
        },

        // Mode selection
        mode: null,

        selectMode(m) {
            this.mode = m;
            if (m === 'manage-events') {
                this.loadManagedEvents();
            } else if (m === 'review-labels') {
                this.loadLabelsForReview();
            }
        },

        /**
         * Poll a task status endpoint until completion or timeout.
         *
         * @param {string} taskId - The task ID to poll
         * @param {function} onUpdate - Callback called on each poll with status object
         * @param {number} maxAttempts - Maximum number of polling attempts (default: 60)
         * @param {number} interval - Polling interval in milliseconds (default: 2000)
         * @returns {Promise<object>} - Resolves with final task result or rejects on timeout/error
         */
        async pollTaskStatus(taskId, onUpdate = null, maxAttempts = 60, interval = 2000) {
            let attempts = 0;

            while (attempts < maxAttempts) {
                try {
                    const response = await fetch(`/api/v1/management/tasks/${taskId}/status`);

                    if (!response.ok) {
                        if (response.status === 404) {
                            throw new Error('Task not found');
                        }
                        throw new Error(`Failed to get task status: ${response.statusText}`);
                    }

                    const result = await response.json();

                    // Call update callback if provided
                    if (onUpdate) {
                        onUpdate(result);
                    }

                    // Check if task is complete
                    if (result.status === 'complete') {
                        return result;
                    }

                    // Check if task failed
                    if (result.status === 'failed') {
                        throw new Error(result.error || 'Task failed');
                    }

                    // Wait before next poll
                    await new Promise(resolve => setTimeout(resolve, interval));
                    attempts++;

                } catch (error) {
                    // On network error, retry a few times
                    if (attempts < 3) {
                        console.warn('Polling error, retrying...', error);
                        await new Promise(resolve => setTimeout(resolve, interval));
                        attempts++;
                        continue;
                    }
                    throw error;
                }
            }

            // Timeout
            throw new Error('Task polling timed out');
        },
    };
}
