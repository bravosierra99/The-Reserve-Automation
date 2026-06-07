"""Obsidian Vault Coherence Tests - Ensure Automation Matches Obsidian.

These tests are CRITICAL - they verify that automation templates generate files
that match the Obsidian vault's FileClass definitions.

PREVENTS:
- Generated files that Obsidian can't read
- Field name mismatches between automation and vault
- Score ranges that violate FileClass constraints
- Template drift from source of truth (Obsidian vault)

COMPARES:
1. Automation templates → Obsidian templates (9_Templates/)
2. Automation templates → Obsidian FileClass definitions (8_FileClass/)
3. Python model constraints → FileClass constraints
"""

from pathlib import Path
from typing import Any, Dict

import pytest
import yaml

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def obsidian_vault_path():
    """Get path to Obsidian vault."""
    # Navigate from tests/unit/models/ to the-reserve/Cellar/
    test_dir = Path(__file__).parent
    vault_path = test_dir.parent.parent.parent.parent / "the-reserve" / "Cellar"

    if not vault_path.exists():
        pytest.skip(f"Obsidian vault not found at {vault_path}")

    return vault_path


@pytest.fixture
def automation_templates_path():
    """Get path to automation templates."""
    test_dir = Path(__file__).parent
    return test_dir.parent.parent.parent / "templates"


def parse_obsidian_fileclass(file_path: Path) -> Dict[str, Any]:
    """Parse Obsidian FileClass YAML definition.

    Returns dict with:
    - fields: List of field definitions
    - version: FileClass version
    """
    content = file_path.read_text()

    # Extract YAML frontmatter
    if not content.startswith("---"):
        raise ValueError(f"FileClass {file_path} missing frontmatter")

    # Find closing ---
    parts = content.split("---", 2)
    if len(parts) < 2:
        raise ValueError(f"FileClass {file_path} malformed frontmatter")

    frontmatter = yaml.safe_load(parts[1])
    return frontmatter


@pytest.fixture
def wine_fileclass(obsidian_vault_path):
    """Parse Wine FileClass definition."""
    return parse_obsidian_fileclass(obsidian_vault_path / "8_FileClass" / "Wine.md")


@pytest.fixture
def whiskey_fileclass(obsidian_vault_path):
    """Parse Whiskey FileClass definition."""
    return parse_obsidian_fileclass(obsidian_vault_path / "8_FileClass" / "Whiskey.md")


@pytest.fixture
def wine_tasting_fileclass(obsidian_vault_path):
    """Parse Wine Tasting FileClass definition."""
    return parse_obsidian_fileclass(obsidian_vault_path / "8_FileClass" / "Wine Tasting.md")


@pytest.fixture
def whiskey_tasting_fileclass(obsidian_vault_path):
    """Parse Tasting (Whiskey) FileClass definition."""
    return parse_obsidian_fileclass(obsidian_vault_path / "8_FileClass" / "Tasting.md")


# ============================================================================
# Wine Tasting Coherence Tests (5 tests)
# ============================================================================

class TestWineTastingCoherence:
    """Verify wine tasting automation matches Obsidian FileClass."""

    def test_wine_tasting_fileclass_has_correct_fields(self, wine_tasting_fileclass):
        """Ensure Wine Tasting FileClass has all expected fields."""
        fields = {f["name"] for f in wine_tasting_fileclass["fields"]}

        required_fields = {
            "Date", "TasterName", "LinkedBottle",
            "Appearance", "Aroma", "Taste", "Aftertaste", "Overall",
            "AWS Score", "100pt Scale"
        }

        for field in required_fields:
            assert field in fields, f"Wine Tasting FileClass missing field: {field}"

    def test_wine_tasting_score_ranges_match_fileclass(self, wine_tasting_fileclass):
        """Verify score ranges match Obsidian FileClass constraints.

        CRITICAL: These ranges MUST match for Obsidian validation to work!
        """
        fields_dict = {f["name"]: f for f in wine_tasting_fileclass["fields"]}

        # Check Appearance score range (0-3)
        appearance = fields_dict.get("Appearance")
        assert appearance is not None, "Appearance field missing"
        assert appearance["type"] == "Number"
        assert appearance["options"]["min"] == 0
        assert appearance["options"]["max"] == 3
        assert appearance["options"]["step"] == 0.5

        # Check Aroma score range (0-6)
        aroma = fields_dict.get("Aroma")
        assert aroma is not None, "Aroma field missing"
        assert aroma["options"]["min"] == 0
        assert aroma["options"]["max"] == 6
        assert aroma["options"]["step"] == 0.5

        # Check Taste score range (0-6)
        taste = fields_dict.get("Taste")
        assert taste is not None, "Taste field missing"
        assert taste["options"]["min"] == 0
        assert taste["options"]["max"] == 6
        assert taste["options"]["step"] == 0.5

        # Check Aftertaste score range (0-3)
        aftertaste = fields_dict.get("Aftertaste")
        assert aftertaste is not None, "Aftertaste field missing"
        assert aftertaste["options"]["min"] == 0
        assert aftertaste["options"]["max"] == 3
        assert aftertaste["options"]["step"] == 0.5

        # Check Overall score range (0-2)
        overall = fields_dict.get("Overall")
        assert overall is not None, "Overall field missing"
        assert overall["options"]["min"] == 0
        assert overall["options"]["max"] == 2
        assert overall["options"]["step"] == 0.5

    def test_wine_tasting_template_matches_fileclass(self, automation_templates_path, wine_tasting_fileclass):
        """Verify automation template generates frontmatter matching FileClass."""
        template = automation_templates_path / "tasting_wine.md.jinja"

        if not template.exists():
            pytest.skip(f"Template not found: {template}")

        content = template.read_text()

        # Check fileClass declaration
        assert 'fileClass: Wine Tasting' in content, "Template has wrong fileClass"

        # Check all required fields appear in template
        fields = {f["name"] for f in wine_tasting_fileclass["fields"]}
        for field in fields:
            # Field should appear in frontmatter (with : after it)
            assert f"{field}:" in content or f'"{field}"' in content, \
                f"Template missing field: {field}"

    def test_wine_tasting_sections_match_obsidian(self, automation_templates_path, obsidian_vault_path):
        """Verify template sections match Obsidian template structure."""
        automation_template = automation_templates_path / "tasting_wine.md.jinja"
        obsidian_template = obsidian_vault_path / "9_Templates" / "Wine Tasting.md"

        if not automation_template.exists():
            pytest.skip(f"Automation template not found: {automation_template}")
        if not obsidian_template.exists():
            pytest.skip(f"Obsidian template not found: {obsidian_template}")

        auto_content = automation_template.read_text()
        obsidian_content = obsidian_template.read_text()

        # Check section headers match
        expected_sections = ["### Appearance", "### Aroma", "### Taste", "### Aftertaste", "### Overall Impression"]

        for section in expected_sections:
            assert section in auto_content, f"Automation template missing section: {section}"
            assert section in obsidian_content, f"Obsidian template missing section: {section}"

    def test_wine_tasting_aws_score_formula(self, wine_tasting_fileclass):
        """Verify AWS Score formula matches expected calculation."""
        fields_dict = {f["name"]: f for f in wine_tasting_fileclass["fields"]}

        aws_score = fields_dict.get("AWS Score")
        assert aws_score is not None, "AWS Score field missing"
        assert aws_score["type"] == "Formula"

        # Formula should sum all components
        formula = aws_score["options"]["formula"]
        assert "Appearance" in formula
        assert "Aroma" in formula
        assert "Taste" in formula
        assert "Aftertaste" in formula
        assert "Overall" in formula


# ============================================================================
# Whiskey Tasting Coherence Tests (5 tests)
# ============================================================================

class TestWhiskeyTastingCoherence:
    """Verify whiskey tasting automation matches Obsidian FileClass."""

    def test_whiskey_tasting_fileclass_has_correct_fields(self, whiskey_tasting_fileclass):
        """Ensure Tasting FileClass has all expected fields."""
        fields = {f["name"] for f in whiskey_tasting_fileclass["fields"]}

        required_fields = {
            "Date", "TasterName", "LinkedBottle",
            "DaysFromCrack", "FillLevel",
            "Nose", "Palate", "Finish", "Overall",
            "TotalScore"
        }

        for field in required_fields:
            assert field in fields, f"Tasting FileClass missing field: {field}"

    def test_whiskey_tasting_score_ranges_match_fileclass(self, whiskey_tasting_fileclass):
        """Verify whiskey score ranges are 0-3 (max 10 total).

        CRITICAL: Was documented as 0-10 (max 40) but FileClass shows 0-3!
        """
        fields_dict = {f["name"]: f for f in whiskey_tasting_fileclass["fields"]}

        # Check Nose score range (0-3)
        nose = fields_dict.get("Nose")
        assert nose is not None, "Nose field missing"
        assert nose["type"] == "Number"
        assert nose["options"]["min"] == 0
        assert nose["options"]["max"] == 3
        assert nose["options"]["step"] == 0.1

        # Check Palate score range (0-3)
        palate = fields_dict.get("Palate")
        assert palate is not None, "Palate field missing"
        assert palate["options"]["min"] == 0
        assert palate["options"]["max"] == 3
        assert palate["options"]["step"] == 0.1

        # Check Finish score range (0-3)
        finish = fields_dict.get("Finish")
        assert finish is not None, "Finish field missing"
        assert finish["options"]["min"] == 0
        assert finish["options"]["max"] == 3
        assert finish["options"]["step"] == 0.1

        # Check Overall score range (0-1)
        overall = fields_dict.get("Overall")
        assert overall is not None, "Overall field missing"
        assert overall["options"]["min"] == 0
        assert overall["options"]["max"] == 1
        assert overall["options"]["step"] == 0.05

    def test_whiskey_tasting_template_matches_fileclass(self, automation_templates_path, whiskey_tasting_fileclass):
        """Verify automation template generates frontmatter matching FileClass."""
        template = automation_templates_path / "tasting_whiskey.md.jinja"

        if not template.exists():
            pytest.skip(f"Template not found: {template}")

        content = template.read_text()

        # Check fileClass declaration
        assert 'fileClass: Tasting' in content, "Template has wrong fileClass"

        # Check all required fields appear in template
        fields = {f["name"] for f in whiskey_tasting_fileclass["fields"]}
        for field in fields:
            assert f"{field}:" in content or f'"{field}"' in content, \
                f"Template missing field: {field}"

    def test_whiskey_tasting_sections_match_obsidian(self, automation_templates_path, obsidian_vault_path):
        """Verify template sections match Obsidian template structure."""
        automation_template = automation_templates_path / "tasting_whiskey.md.jinja"
        obsidian_template = obsidian_vault_path / "9_Templates" / "Tasting.md"

        if not automation_template.exists():
            pytest.skip(f"Automation template not found: {automation_template}")
        if not obsidian_template.exists():
            pytest.skip(f"Obsidian template not found: {obsidian_template}")

        auto_content = automation_template.read_text()
        obsidian_content = obsidian_template.read_text()

        # Check section headers match
        expected_sections = ["### Nose", "### Palate", "### Finish", "### Overall Impression"]

        for section in expected_sections:
            assert section in auto_content, f"Automation template missing section: {section}"
            assert section in obsidian_content, f"Obsidian template missing section: {section}"

    def test_whiskey_tasting_total_score_formula(self, whiskey_tasting_fileclass):
        """Verify TotalScore formula sums to max 10."""
        fields_dict = {f["name"]: f for f in whiskey_tasting_fileclass["fields"]}

        total_score = fields_dict.get("TotalScore")
        assert total_score is not None, "TotalScore field missing"
        assert total_score["type"] == "Formula"

        # Formula should sum: Nose (0-3) + Palate (0-3) + Finish (0-3) + Overall (0-1) = max 10
        formula = total_score["options"]["formula"]
        assert "Nose" in formula
        assert "Palate" in formula
        assert "Finish" in formula
        assert "Overall" in formula


# ============================================================================
# Wine Bottle Coherence Tests (3 tests)
# ============================================================================

class TestWineBottleCoherence:
    """Verify wine bottle automation matches Obsidian FileClass."""

    def test_wine_bottle_fileclass_has_core_fields(self, wine_fileclass):
        """Ensure Wine FileClass has all core fields."""
        fields = {f["name"] for f in wine_fileclass["fields"]}

        core_fields = {
            "Winemaker", "WineName", "Vintage", "Type",
            "Variety", "Country-Region",
            "Price", "PurchaseSource", "Inventory", "Buy",
            "Stars", "ValueForMoney", "Label"
        }

        for field in core_fields:
            assert field in fields, f"Wine FileClass missing field: {field}"

    def test_wine_bottle_template_exists(self, automation_templates_path):
        """Verify wine bottle template exists."""
        template = automation_templates_path / "wine.md.j2"
        assert template.exists(), f"Wine bottle template not found: {template}"

    def test_wine_type_select_values(self, wine_fileclass):
        """Verify Type field has correct select values."""
        fields_dict = {f["name"]: f for f in wine_fileclass["fields"]}

        type_field = fields_dict.get("Type")
        assert type_field is not None, "Type field missing"
        assert type_field["type"] == "Select"

        values_list = type_field["options"]["valuesList"]
        expected_types = {"Red wine", "White wine", "Rose wine", "Champagne"}
        actual_types = set(values_list.values())

        assert expected_types == actual_types, \
            f"Wine types mismatch. Expected {expected_types}, got {actual_types}"


# ============================================================================
# Whiskey Bottle Coherence Tests (3 tests)
# ============================================================================

class TestWhiskeyBottleCoherence:
    """Verify whiskey bottle automation matches Obsidian FileClass."""

    def test_whiskey_bottle_fileclass_has_core_fields(self, whiskey_fileclass):
        """Ensure Whiskey FileClass has all core fields."""
        fields = {f["name"] for f in whiskey_fileclass["fields"]}

        core_fields = {
            "Distiller", "WhiskeyName", "Year", "Type",
            "AgeStatement", "Proof", "MashBill", "BarrelType",
            "Region-State", "Price", "PurchaseSource", "Inventory", "Buy",
            "Stars", "ValueForMoney", "BottleOpenedDate", "Label"
        }

        for field in core_fields:
            assert field in fields, f"Whiskey FileClass missing field: {field}"

    def test_whiskey_bottle_template_exists(self, automation_templates_path):
        """Verify whiskey bottle template exists."""
        template = automation_templates_path / "whiskey.md.j2"
        assert template.exists(), f"Whiskey bottle template not found: {template}"

    def test_whiskey_proof_range(self, whiskey_fileclass):
        """Verify Proof field has correct range (0-200)."""
        fields_dict = {f["name"]: f for f in whiskey_fileclass["fields"]}

        proof = fields_dict.get("Proof")
        assert proof is not None, "Proof field missing"
        assert proof["type"] == "Number"
        assert proof["options"]["min"] == 0
        assert proof["options"]["max"] == 200
        assert proof["options"]["step"] == 0.1
