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
    };
}
