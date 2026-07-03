import { defineConfig } from 'vitest/config';

// JS unit tests for the frontend modules in src/reserve_automation/web/static/js.
// jsdom provides `window` so the browser modules (which attach themselves as
// window globals, e.g. window.eventCreateModule) load unmodified.
export default defineConfig({
    test: {
        environment: 'jsdom',
        include: ['tests/js/**/*.test.js'],
    },
});
