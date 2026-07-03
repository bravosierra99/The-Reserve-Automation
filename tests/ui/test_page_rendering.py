"""Fast page-rendering tests using TestClient.

These verify that key pages return 200 and contain the Alpine.js root
elements and structural markers that the frontend depends on.  A failing
test here means a user would see a broken or blank page.

What these tests protect against:
- Template removed or renamed (route stops returning the right file)
- Alpine root component (`x-data`) moved or renamed (JS never initialises)
- Required DOM elements deleted from a template (page breaks silently)
- Auth misconfiguration that gates a page off unexpectedly

What they don't test (covered elsewhere):
- Live JS execution         → tests/e2e/
- API response shape        → tests/ui/test_collection_api.py
- Form submission outcomes  → tests/ui/test_manual_tasting.py
"""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Bottles collection page
# ---------------------------------------------------------------------------

class TestBottlesPage:
    def test_bottles_page_returns_200(self, ui_client):
        resp = ui_client.get("/bottles")
        assert resp.status_code == 200

    def test_bottles_page_has_alpine_root(self, ui_client):
        soup = BeautifulSoup(ui_client.get("/bottles").text, "html.parser")
        # Find the specific bottlesApp root — not the first x-data (which is authNav())
        root = soup.find(attrs={"x-data": lambda v: v and "bottlesApp" in v})
        assert root is not None, (
            "No element with x-data containing 'bottlesApp' found on /bottles; "
            "Alpine UI will not initialise"
        )

    def test_bottles_page_has_collection_api_reference(self, ui_client):
        content = ui_client.get("/bottles").text
        assert "/api/v1/bottles/collection" in content, (
            "Page must reference the collection API endpoint; "
            "removing it breaks the bottle grid entirely"
        )


# ---------------------------------------------------------------------------
# Manual tasting page
# ---------------------------------------------------------------------------

class TestManualTastingPage:
    def test_manual_tasting_page_returns_200(self, ui_client):
        resp = ui_client.get("/manual-tasting")
        assert resp.status_code == 200

    def test_manual_tasting_has_alpine_root(self, ui_client):
        soup = BeautifulSoup(ui_client.get("/manual-tasting").text, "html.parser")
        root = soup.find(attrs={"x-data": lambda v: v and "manualTastingWizard" in v})
        assert root is not None, (
            "No element with x-data containing 'manualTastingWizard' found; "
            "wizard will not initialise"
        )

    def test_taster_name_field_exists_with_correct_model(self, ui_client):
        soup = BeautifulSoup(ui_client.get("/manual-tasting").text, "html.parser")
        field = soup.find("input", attrs={"x-model": "tasterName"})
        assert field is not None, (
            "Taster name input with x-model='tasterName' not found; "
            "form cannot capture the taster's name"
        )

    def test_event_mode_readonly_bindings_present(self, ui_client):
        content = ui_client.get("/manual-tasting").text
        assert ':readonly="isEventMode"' in content, (
            "Taster name field must have :readonly='isEventMode' binding; "
            "event mode will allow editing locked fields"
        )
        assert ':disabled="isEventMode"' in content, (
            "Beverage type radios must have :disabled='isEventMode' binding"
        )

    def test_is_event_mode_computed_property_exists(self, ui_client):
        # The wizard logic lives in static/js/tastings/manual-tasting.js
        # (extracted July 2026); the page must load it and the module must
        # define the computed property. Its behavior is unit-tested in
        # tests/js/manual-tasting.test.js.
        content = ui_client.get("/manual-tasting").text
        assert "/static/js/tastings/manual-tasting.js" in content, (
            "manual-tasting page no longer loads the wizard module — "
            "the page would render but the Alpine component would be undefined"
        )
        wizard_js = (
            Path(__file__).parents[2]
            / "src/reserve_automation/web/static/js/tastings/manual-tasting.js"
        ).read_text(encoding="utf-8")
        assert "get isEventMode()" in wizard_js, (
            "isEventMode computed property missing — event mode detection broken"
        )

    def test_beverage_type_radios_present(self, ui_client):
        soup = BeautifulSoup(ui_client.get("/manual-tasting").text, "html.parser")
        wine_radio = soup.find("input", {"type": "radio", "value": "wine"})
        whiskey_radio = soup.find("input", {"type": "radio", "value": "whiskey"})
        assert wine_radio is not None, "Wine radio button missing"
        assert whiskey_radio is not None, "Whiskey radio button missing"

    def test_wine_section_has_conditional_show(self, ui_client):
        content = ui_client.get("/manual-tasting").text
        assert 'x-show="isWine"' in content, (
            "Wine tasting section must use x-show='isWine'; "
            "section will be permanently hidden or visible"
        )

    def test_whiskey_section_has_conditional_show(self, ui_client):
        content = ui_client.get("/manual-tasting").text
        assert 'x-show="!isWine"' in content, (
            "Whiskey tasting section must use x-show='!isWine'"
        )

    def test_wine_note_models_present(self, ui_client):
        content = ui_client.get("/manual-tasting").text
        required = [
            "appearanceNotesInput", "aromaNotesInput",
            "tasteNotesInput", "aftertasteNotesInput",
        ]
        for model in required:
            assert f'x-model="{model}"' in content, (
                f"Wine note model '{model}' missing — wine notes cannot be entered"
            )

    def test_whiskey_note_models_present(self, ui_client):
        content = ui_client.get("/manual-tasting").text
        required = ["noseNotesInput", "palateNotesInput", "finishNotesInput"]
        for model in required:
            assert f'x-model="{model}"' in content, (
                f"Whiskey note model '{model}' missing — whiskey notes cannot be entered"
            )

    def test_tasting_form_mixin_loaded(self, ui_client):
        content = ui_client.get("/manual-tasting").text
        assert "tasting-form-mixin.js" in content, (
            "tasting-form-mixin.js not referenced; parseNotes() and related "
            "helpers will be undefined, breaking note parsing on save"
        )


# ---------------------------------------------------------------------------
# Other key pages (smoke tests)
# ---------------------------------------------------------------------------

class TestOtherPages:
    @pytest.mark.parametrize("path", [
        "/bottles",
        "/manual-tasting",
    ])
    def test_page_has_base_html_structure(self, ui_client, path):
        soup = BeautifulSoup(ui_client.get(path).text, "html.parser")
        assert soup.find("html") is not None
        assert soup.find("body") is not None
        assert soup.find("head") is not None
