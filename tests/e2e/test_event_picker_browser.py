"""
E2E browser test for the create-event bottle picker on the management page.

Regression coverage for the July 2026 "_index" bug: after adding one bottle,
every search result showed "✓ Added" and was disabled (on a phone: "I could
only add one bottle"), because the picker compared a field that doesn't exist
on search results. Only a real browser executing the Alpine bindings catches
that class of bug — API tests never run the JS, and tests/ui only greps the
rendered HTML.

The picker logic itself lives in static/js/management/event-create.js and has
fast unit coverage in tests/js/event-create.test.js; this test proves the
template bindings + module + backend work together.
"""

import pytest
import requests
from playwright.sync_api import expect, sync_playwright

pytestmark = pytest.mark.e2e


class TestEventBottlePicker:
    """Create event → search bottles → add several → create, in a real browser."""

    def test_picker_supports_adding_multiple_bottles(self, web_server):
        """The full picker flow, anchored on the regression assertions.

        test_db seeds two whiskies matching "Bourbon": Weller (Original Wheated
        Bourbon) and Buffalo Trace (Kentucky Straight Bourbon).
        """
        with sync_playwright() as p:
            browser = p.firefox.launch(headless=True)
            page = browser.new_page()
            console_logs = []
            page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))

            page.goto(f"{web_server}/management")

            # Enter create-event mode: mode card → empty-state Create Event.
            # (test_db has no events, so the empty state always shows.)
            page.click("button:has-text('Manage Events')")
            page.click("button:has-text('Create Event'):visible")
            expect(page.locator("h2:has-text('Create Tasting Event')")).to_be_visible()

            # Event details
            page.fill("input[placeholder*='Bourbon Night']", "E2E Picker Event")
            page.fill("input[placeholder='Enter your name']", "E2E Host")

            # Search for bottles (debounced 300ms)
            page.fill("input[placeholder*='Search for bottles']", "Bourbon")
            weller = page.locator("button:has-text('Weller')")
            buffalo = page.locator("button:has-text('Buffalo Trace')")
            expect(weller).to_be_visible(timeout=5000)
            expect(buffalo).to_be_visible()

            # Add the first bottle
            weller.click()
            expect(page.locator("h4:has-text('Selected Bottles (1)')")).to_be_visible()
            expect(weller).to_be_disabled()
            expect(weller.locator("div:has-text('✓ Added')")).to_be_visible()

            # THE REGRESSION: the other result must still be addable. With the
            # _index bug, Buffalo Trace was disabled and marked "✓ Added" here.
            expect(buffalo).to_be_enabled()
            expect(buffalo.locator("div:has-text('✓ Added')")).to_be_hidden()

            # Add the second bottle
            buffalo.click()
            expect(page.locator("h4:has-text('Selected Bottles (2)')")).to_be_visible()
            expect(buffalo).to_be_disabled()

            # Remove frees the bottle for re-adding
            page.locator("button:has-text('Remove')").first.click()
            expect(page.locator("h4:has-text('Selected Bottles (1)')")).to_be_visible()
            expect(weller).to_be_enabled()
            weller.click()
            expect(page.locator("h4:has-text('Selected Bottles (2)')")).to_be_visible()

            # Create the event end-to-end
            page.click("button:has-text('Create Event'):visible")
            success = page.locator("text=Event Created Successfully")
            try:
                expect(success).to_be_visible(timeout=10000)
            except Exception:
                print(f"Console logs: {console_logs[-10:]}")
                raise

            # Verify against the backend: the event exists with both bottles.
            events = requests.get(f"{web_server}/api/v1/events", timeout=10).json()
            created = next(e for e in events if e["name"] == "E2E Picker Event")
            names = {b["bottle_name"] for b in created["bottles"]}
            assert len(created["bottles"]) == 2
            assert any("Buffalo Trace" in n for n in names)
            assert any("Weller" in n for n in names)

            browser.close()
