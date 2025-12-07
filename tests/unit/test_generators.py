"""Unit tests for Obsidian file generators."""

import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from datetime import datetime

from reserve_automation.generators.obsidian import ObsidianGenerator, ObsidianFile
from reserve_automation.core.models import BottleMetadata
from reserve_automation.core.exceptions import GenerationError


class TestObsidianGenerator:
    """Tests for ObsidianGenerator class."""

    @pytest.fixture
    def temp_vault(self, tmp_path):
        """Create temporary vault directory."""
        vault = tmp_path / "test_vault"
        vault.mkdir()
        (vault / "Cellar").mkdir()
        (vault / "Cellar" / "1_Wines").mkdir()
        (vault / "Cellar" / "1_Whiskeys").mkdir()
        return vault

    @pytest.fixture
    def temp_templates(self, tmp_path):
        """Create temporary templates directory with basic templates."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()

        # Create a minimal wine template
        wine_template = templates_dir / "wine.md.j2"
        wine_template.write_text(
            "---\n"
            "fileClass: Wine\n"
            "Name: {{ name }}\n"
            "Winemaker: {{ producer }}\n"
            "WineName: {{ wine_name }}\n"
            "Vintage: {% if year %}\"{{ year }}\"{% endif %}\n"
            "Type: {% if beverage_type %}{{ beverage_type }}{% endif %}\n"
            "Variety: {% if variety %}{{ variety }}{% endif %}\n"
            "Country-Region: {% if country and region %}{{ country }} - {{ region }}{% elif region %}{{ region }}{% elif country %}{{ country }}{% endif %}\n"
            "---\n"
            "\n"
            "## Bottle Information\n"
        )

        # Create a minimal whiskey template
        whiskey_template = templates_dir / "whiskey.md.j2"
        whiskey_template.write_text(
            "---\n"
            "fileClass: Whiskey\n"
            "Name: {{ name }}\n"
            "Distiller: {{ producer }}\n"
            "WhiskeyName: {{ whiskey_name }}\n"
            "Year: {% if year %}\"{{ year }}\"{% endif %}\n"
            "Type: {% if beverage_type %}{{ beverage_type }}{% endif %}\n"
            "Proof: {% if proof %}{{ proof }}{% endif %}\n"
            "---\n"
            "\n"
            "## Bottle Information\n"
        )

        return templates_dir

    @pytest.fixture
    def sample_wine_bottle(self):
        """Create sample wine bottle metadata."""
        return BottleMetadata(
            producer="Test Winery",
            name="Cabernet Sauvignon",
            type="wine",
            year=2020,
            beverage_type="Red wine",
            variety="Cabernet Sauvignon",
            country="United States",
            region="Napa Valley",
            price=45.99,
            source="test",
        )

    @pytest.fixture
    def sample_whiskey_bottle(self):
        """Create sample whiskey bottle metadata."""
        return BottleMetadata(
            producer="Test Distillery",
            name="Single Barrel Bourbon",
            type="whiskey",
            year=2018,
            beverage_type="Bourbon",
            proof=120.0,
            age_statement=10,
            price=75.00,
            source="test",
        )

    def test_init_with_valid_paths(self, temp_vault, temp_templates):
        """Test generator initialization with valid paths."""
        generator = ObsidianGenerator(
            vault_path=temp_vault, template_dir=temp_templates
        )

        assert generator.vault_path == temp_vault
        assert generator.template_dir == temp_templates
        assert generator.env is not None

    def test_init_with_invalid_vault_path(self, temp_templates):
        """Test generator raises error with non-existent vault path."""
        invalid_vault = Path("/nonexistent/vault")

        with pytest.raises(GenerationError, match="Vault path does not exist"):
            ObsidianGenerator(vault_path=invalid_vault, template_dir=temp_templates)

    def test_init_with_invalid_template_dir(self, temp_vault):
        """Test generator raises error with non-existent template directory."""
        invalid_templates = Path("/nonexistent/templates")

        with pytest.raises(GenerationError, match="Template directory does not exist"):
            ObsidianGenerator(vault_path=temp_vault, template_dir=invalid_templates)

    def test_generate_filename_wine_with_year(self, temp_vault, temp_templates, sample_wine_bottle):
        """Test filename generation for wine bottle with year."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        filename = generator._generate_filename(sample_wine_bottle)

        assert filename == "Test Winery - Cabernet Sauvignon - 2020"

    def test_generate_filename_wine_without_year(self, temp_vault, temp_templates):
        """Test filename generation for wine bottle without year."""
        bottle = BottleMetadata(
            producer="Test Winery",
            name="Champagne Brut",
            type="wine",
            beverage_type="Champagne",
            source="test",
        )

        generator = ObsidianGenerator(temp_vault, temp_templates)
        filename = generator._generate_filename(bottle)

        assert filename == "Test Winery - Champagne Brut"

    def test_sanitize_filename(self, temp_vault, temp_templates):
        """Test filename sanitization removes invalid characters."""
        generator = ObsidianGenerator(temp_vault, temp_templates)

        # Test various invalid characters
        dirty_name = 'Test: Wine / Producer * "Special" <Edition>'
        clean_name = generator._sanitize_filename(dirty_name)

        assert clean_name == "Test Wine Producer Special Edition"
        assert all(c not in clean_name for c in '<>:"/\\|?*')

    def test_sanitize_filename_multiple_spaces(self, temp_vault, temp_templates):
        """Test filename sanitization collapses multiple spaces."""
        generator = ObsidianGenerator(temp_vault, temp_templates)

        dirty_name = "Test    Wine     2020"
        clean_name = generator._sanitize_filename(dirty_name)

        assert clean_name == "Test Wine 2020"

    def test_generate_bottle_file_wine(self, temp_vault, temp_templates, sample_wine_bottle):
        """Test generating markdown file for wine bottle."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        obsidian_file = generator.generate_bottle_file(sample_wine_bottle)

        assert isinstance(obsidian_file, ObsidianFile)
        assert obsidian_file.bottle == sample_wine_bottle
        assert "Test Winery" in str(obsidian_file.file_path)
        assert "Cabernet Sauvignon" in str(obsidian_file.file_path)
        assert "2020" in str(obsidian_file.file_path)
        assert obsidian_file.file_path.suffix == ".md"

    def test_generate_bottle_file_whiskey(self, temp_vault, temp_templates, sample_whiskey_bottle):
        """Test generating markdown file for whiskey bottle."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        obsidian_file = generator.generate_bottle_file(sample_whiskey_bottle)

        assert isinstance(obsidian_file, ObsidianFile)
        assert obsidian_file.bottle == sample_whiskey_bottle
        assert "Test Distillery" in str(obsidian_file.file_path)
        assert "Single Barrel Bourbon" in str(obsidian_file.file_path)
        assert "1_Whiskeys" in str(obsidian_file.file_path)

    def test_prepare_context_wine(self, temp_vault, temp_templates, sample_wine_bottle):
        """Test template context preparation for wine bottle."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        context = generator._prepare_context(sample_wine_bottle)

        assert context["name"] == "Test Winery - Cabernet Sauvignon - 2020"
        assert context["producer"] == "Test Winery"
        assert context["wine_name"] == "Cabernet Sauvignon"
        assert context["whiskey_name"] is None
        assert context["year"] == 2020
        assert context["beverage_type"] == "Red wine"
        assert context["variety"] == "Cabernet Sauvignon"
        assert context["country"] == "United States"
        assert context["region"] == "Napa Valley"
        assert context["price"] == 45.99

    def test_prepare_context_whiskey(self, temp_vault, temp_templates, sample_whiskey_bottle):
        """Test template context preparation for whiskey bottle."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        context = generator._prepare_context(sample_whiskey_bottle)

        assert context["name"] == "Test Distillery - Single Barrel Bourbon - 2018"
        assert context["producer"] == "Test Distillery"
        assert context["wine_name"] is None
        assert context["whiskey_name"] == "Single Barrel Bourbon"
        assert context["year"] == 2018
        assert context["beverage_type"] == "Bourbon"
        assert context["proof"] == 120.0
        assert context["age_statement"] == 10
        assert context["price"] == 75.00

    def test_render_template_wine(self, temp_vault, temp_templates, sample_wine_bottle):
        """Test template rendering for wine bottle."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        content = generator._render_template(sample_wine_bottle)

        assert "fileClass: Wine" in content
        assert "Test Winery" in content
        assert "Cabernet Sauvignon" in content
        assert "2020" in content
        assert "Red wine" in content

    def test_render_template_whiskey(self, temp_vault, temp_templates, sample_whiskey_bottle):
        """Test template rendering for whiskey bottle."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        content = generator._render_template(sample_whiskey_bottle)

        assert "fileClass: Whiskey" in content
        assert "Test Distillery" in content
        assert "Single Barrel Bourbon" in content
        assert "Bourbon" in content
        assert "120.0" in content

    def test_write_file_creates_directory(self, temp_vault, temp_templates, sample_wine_bottle):
        """Test that write_file creates parent directory if needed."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        obsidian_file = generator.generate_bottle_file(sample_wine_bottle)

        # Write the file
        generator.write_file(obsidian_file, dry_run=False)

        # Verify file was created
        assert obsidian_file.file_path.exists()
        assert obsidian_file.file_path.is_file()
        assert obsidian_file.file_path.parent.exists()

    def test_write_file_dry_run(self, temp_vault, temp_templates, sample_wine_bottle):
        """Test that dry_run mode doesn't write files."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        obsidian_file = generator.generate_bottle_file(sample_wine_bottle)

        # Write in dry-run mode
        generator.write_file(obsidian_file, dry_run=True)

        # Verify file was NOT created
        assert not obsidian_file.file_path.exists()

    def test_generate_batch_multiple_bottles(self, temp_vault, temp_templates, sample_wine_bottle, sample_whiskey_bottle):
        """Test batch generation of multiple bottles."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        bottles = [sample_wine_bottle, sample_whiskey_bottle]

        generated = generator.generate_batch(bottles, dry_run=True)

        assert len(generated) == 2
        assert all(isinstance(f, ObsidianFile) for f in generated)
        assert generated[0].bottle == sample_wine_bottle
        assert generated[1].bottle == sample_whiskey_bottle

    def test_generate_batch_with_error(self, temp_vault, temp_templates, sample_wine_bottle):
        """Test batch generation handles errors gracefully."""
        generator = ObsidianGenerator(temp_vault, temp_templates)

        # Create a bottle with invalid data that will fail rendering
        bad_bottle = Mock(spec=BottleMetadata)
        bad_bottle.type = "invalid_type"  # This will fail template selection
        bad_bottle.producer = "Bad Producer"
        bad_bottle.name = "Bad Bottle"

        bottles = [sample_wine_bottle, bad_bottle]

        # Should not raise exception, but log error
        generated = generator.generate_batch(bottles, dry_run=True)

        # Should have generated the good one, skipped the bad one
        assert len(generated) == 1
        assert generated[0].bottle == sample_wine_bottle

    def test_file_path_structure_wine(self, temp_vault, temp_templates, sample_wine_bottle):
        """Test that wine file paths follow correct structure."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        obsidian_file = generator.generate_bottle_file(sample_wine_bottle)

        path_parts = obsidian_file.file_path.parts
        assert "Cellar" in path_parts
        assert "1_Wines" in path_parts
        assert any("Test Winery" in part for part in path_parts)

    def test_file_path_structure_whiskey(self, temp_vault, temp_templates, sample_whiskey_bottle):
        """Test that whiskey file paths follow correct structure."""
        generator = ObsidianGenerator(temp_vault, temp_templates)
        obsidian_file = generator.generate_bottle_file(sample_whiskey_bottle)

        path_parts = obsidian_file.file_path.parts
        assert "Cellar" in path_parts
        assert "1_Whiskeys" in path_parts
        assert any("Test Distillery" in part for part in path_parts)
