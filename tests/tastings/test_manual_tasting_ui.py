#!/usr/bin/env python3
"""
UI Tests for Manual Tasting Wizard

Tests that form fields have correct Alpine.js bindings for:
- Obsidian mode: fields editable
- Event mode: fields readonly/disabled

Uses FastAPI TestClient to test without requiring a running server.
"""

from pathlib import Path
from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

# The wizard component (window.manualTastingWizard) — extracted from the
# template so it gets vitest unit coverage (tests/js/manual-tasting.test.js).
_WIZARD_MODULE = (
    Path(__file__).parents[2]
    / "src/reserve_automation/web/static/js/tastings/manual-tasting.js"
)


@pytest.fixture
def client(tmp_path):
    """Create test client with app."""
    from reserve_automation.core.config import Config
    from reserve_automation.web import app as app_module

    # Create temp vault
    vault_path = tmp_path / "vault"
    vault_path.mkdir(parents=True, exist_ok=True)

    # Mock global config
    config = Config(paths={"vault": str(vault_path), "templates_dir": "templates"})
    app_module.core_config = config

    web_config = Mock()
    web_config.sessions.secret_key = "test-secret"
    web_config.sessions.max_age_hours = 24
    app_module.web_config = web_config

    # Create test client
    return TestClient(app_module.app)


def test_obsidian_mode_fields_editable(client):
    """Test that name and beverage type fields have editable bindings in Obsidian mode."""
    # Request manual tasting page without event parameters (Obsidian mode)
    response = client.get("/manual-tasting")
    assert response.status_code == 200

    soup = BeautifulSoup(response.text, 'html.parser')

    # Check taster name field
    name_input = soup.find('input', {'placeholder': 'Enter your name'})
    assert name_input is not None, "Taster name input not found"

    # Field should use :readonly="isEventMode" binding
    assert 'x-model="tasterName"' in str(name_input) or ':readonly="isEventMode"' in str(name_input), \
        "Taster name field should have Alpine.js binding"

    # Check beverage type radios
    wine_radio = soup.find('input', {'type': 'radio', 'value': 'wine'})
    whiskey_radio = soup.find('input', {'type': 'radio', 'value': 'whiskey'})

    assert wine_radio is not None, "Wine radio not found"
    assert whiskey_radio is not None, "Whiskey radio not found"

    # Both should have :disabled="isEventMode" binding
    assert ':disabled="isEventMode"' in str(wine_radio) or 'x-model="beverageType"' in str(wine_radio), \
        "Wine radio should have Alpine.js binding"
    assert ':disabled="isEventMode"' in str(whiskey_radio) or 'x-model="beverageType"' in str(whiskey_radio), \
        "Whiskey radio should have Alpine.js binding"

    # Check date field is always editable
    date_input = soup.find('input', {'type': 'date'})
    assert date_input is not None, "Date input not found"
    assert 'readonly' not in date_input.attrs, "Date field should not be readonly"


def test_event_mode_fields_readonly(client):
    """Test that field bindings correctly support readonly/disabled in Event mode."""
    response = client.get("/manual-tasting")
    assert response.status_code == 200

    soup = BeautifulSoup(response.text, 'html.parser')

    name_input = soup.find('input', {'placeholder': 'Enter your name'})
    assert name_input is not None, "Name input not found"
    assert ':readonly="isEventMode"' in str(name_input), \
        "Taster name should have :readonly='isEventMode' binding"

    wine_radio = soup.find('input', {'type': 'radio', 'value': 'wine'})
    assert wine_radio is not None, "Wine radio not found"
    assert ':disabled="isEventMode"' in str(wine_radio), \
        "Wine radio should have :disabled='isEventMode' binding"

    whiskey_radio = soup.find('input', {'type': 'radio', 'value': 'whiskey'})
    assert whiskey_radio is not None, "Whiskey radio not found"
    assert ':disabled="isEventMode"' in str(whiskey_radio), \
        "Whiskey radio should have :disabled='isEventMode' binding"


def test_isEventMode_computed_property(client):
    """Test that isEventMode computed property exists and the page loads it.

    The wizard logic lives in static/js/tastings/manual-tasting.js (extracted
    July 2026 for vitest coverage), so the property is asserted in the module
    file and the page is asserted to include that module.
    """
    response = client.get("/manual-tasting")
    assert response.status_code == 200

    content = response.text

    # The page must load the wizard module that defines the component
    assert "/static/js/tastings/manual-tasting.js" in content, \
        "manual-tasting page should load the wizard module"

    wizard_js = _WIZARD_MODULE.read_text(encoding="utf-8")
    assert "get isEventMode()" in wizard_js, \
        "isEventMode computed property not found in the wizard module"

    # Verify it's used in bindings
    assert ':readonly="isEventMode"' in content, \
        "isEventMode not used in readonly binding"
    assert ':disabled="isEventMode"' in content, \
        "isEventMode not used in disabled binding"


def test_wine_whiskey_tasting_notes_fields(client):
    """Test that wine and whiskey have correct tasting note fields."""
    response = client.get("/manual-tasting")
    assert response.status_code == 200

    content = response.text

    # Check wine-specific fields
    # Wine section should have conditional rendering (uses isWine computed property)
    assert 'x-show="isWine"' in content, \
        "Wine section should have conditional rendering via isWine"

    # Check for wine-specific field labels (Appearance, Aroma, Taste, Aftertaste)
    assert "Appearance" in content, "Should have Appearance field"
    assert "Aroma" in content, "Should have Aroma field"

    # Check for wine-specific input models
    assert 'x-model="appearanceNotesInput"' in content, \
        "Should have appearanceNotesInput model"
    assert 'x-model="aromaNotesInput"' in content, \
        "Should have aromaNotesInput model"
    assert 'x-model="tasteNotesInput"' in content, \
        "Should have tasteNotesInput model"
    assert 'x-model="aftertasteNotesInput"' in content, \
        "Should have aftertasteNotesInput model"

    # Check whiskey-specific fields
    # Whiskey section should have conditional rendering (uses !isWine)
    assert 'x-show="!isWine"' in content, \
        "Whiskey section should have conditional rendering via !isWine"

    # Check for whiskey-specific field labels (Nose, Palate, Finish)
    assert ">Nose<" in content, "Should have Nose field label"
    assert ">Palate<" in content, "Should have Palate field label"
    assert ">Finish<" in content, "Should have Finish field label"

    # Check for whiskey-specific input models
    assert 'x-model="noseNotesInput"' in content, \
        "Should have noseNotesInput model"
    assert 'x-model="palateNotesInput"' in content, \
        "Should have palateNotesInput model"
    assert 'x-model="finishNotesInput"' in content, \
        "Should have finishNotesInput model"

    # Verify tasting form mixin is loaded (contains the note functions)
    assert "tasting-form-mixin.js" in content, "Should load tasting-form-mixin.js"

    # Verify the wizard module (loaded by the page) converts input text to note arrays
    assert "parseNotes" in _WIZARD_MODULE.read_text(encoding="utf-8"), \
        "Wizard module should use parseNotes to convert text to arrays"
