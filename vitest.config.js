import { defineConfig } from 'vitest/config';

// JS unit tests for the frontend modules in src/reserve_automation/web/static/js.
// jsdom provides `window` so the browser modules (which attach themselves as
// window globals, e.g. window.eventCreateModule) load unmodified.
export default defineConfig({
    test: {
        environment: 'jsdom',
        include: ['tests/js/**/*.test.js'],
        coverage: {
            provider: 'v8',
            // Coverage is scoped to the extracted frontend modules. Inline
            // template JS never shows up here — that's the point: anything
            // missing from this report is only testable via browser e2e.
            include: ['src/reserve_automation/web/static/js/**/*.js'],
            reporter: ['text', 'html'],
            reportsDirectory: './coverage-js',
        },
    },
});
