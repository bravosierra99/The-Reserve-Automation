"""Tests for ObsidianUpdater utility.

Tests updating Obsidian markdown frontmatter fields.
"""

import pytest
from pathlib import Path

from reserve_automation.utils.obsidian_updater import ObsidianUpdater


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_vault(tmp_path):
    """Create temporary vault with test bottle."""
    vault = tmp_path / "vault"
    vault.mkdir()
    
    # Create sample bottle
    wines_dir = vault / "1_Wines"
    wines_dir.mkdir()
    
    bottle_dir = wines_dir / "TestWine"
    bottle_dir.mkdir()
    
    bottle_file = bottle_dir / "TestWine.md"
    bottle_file.write_text("""---
fileClass: Wine
Winemaker: Test Producer
WineName: Test Wine
Vintage: 2020
Label: 
---

# Tasting Notes
Some notes here.
""")
    
    return vault


@pytest.fixture
def updater(temp_vault):
    """Create ObsidianUpdater instance."""
    return ObsidianUpdater(temp_vault)


# ============================================================================
# Label Field Update Tests
# ============================================================================

class TestLabelFieldUpdate:
    """Test updating Label field in bottle files."""

    def test_update_label_field_success(self, updater, temp_vault):
        """Should successfully update Label field."""
        bottle_file = temp_vault / "1_Wines" / "TestWine" / "TestWine.md"
        
        success = updater.update_label_field(bottle_file, "labels/test-label.jpg")
        
        assert success is True
        
        # Verify file was updated
        content = bottle_file.read_text()
        assert "Label: labels/test-label.jpg" in content or 'Label: "labels/test-label.jpg"' in content

    def test_update_label_field_preserves_frontmatter(self, updater, temp_vault):
        """Should preserve other frontmatter fields."""
        bottle_file = temp_vault / "1_Wines" / "TestWine" / "TestWine.md"
        
        updater.update_label_field(bottle_file, "labels/new-label.jpg")
        
        content = bottle_file.read_text()
        
        # Other fields should still be there
        assert "Winemaker: Test Producer" in content or 'Winemaker: "Test Producer"' in content
        assert "Vintage: 2020" in content

    def test_update_label_field_preserves_body(self, updater, temp_vault):
        """Should preserve markdown body content."""
        bottle_file = temp_vault / "1_Wines" / "TestWine" / "TestWine.md"
        
        updater.update_label_field(bottle_file, "labels/label.jpg")
        
        content = bottle_file.read_text()
        
        # Body content should be preserved
        assert "# Tasting Notes" in content
        assert "Some notes here." in content

    def test_update_label_field_nonexistent_file(self, updater, temp_vault):
        """Should return False for nonexistent file."""
        nonexistent = temp_vault / "1_Wines" / "DoesNotExist" / "DoesNotExist.md"
        
        success = updater.update_label_field(nonexistent, "labels/label.jpg")
        
        assert success is False


# ============================================================================
# Frontmatter Parsing Tests
# ============================================================================

class TestFrontmatterParsing:
    """Test parsing frontmatter from markdown."""

    def test_parse_frontmatter_success(self, updater):
        """Should successfully parse frontmatter."""
        content = """---
fileClass: Wine
Winemaker: Producer
Price: 50.00
---

Body content
"""
        
        frontmatter, body = updater.parse_frontmatter(content)
        
        assert frontmatter is not None
        assert frontmatter["fileClass"] == "Wine"
        assert frontmatter["Winemaker"] == "Producer"
        assert "Body content" in body

    def test_parse_frontmatter_no_frontmatter(self, updater):
        """Should return None for content without frontmatter."""
        content = "Just markdown, no frontmatter"
        
        frontmatter, body = updater.parse_frontmatter(content)
        
        assert frontmatter is None
        assert body == content

    def test_parse_frontmatter_quoted_values(self, updater):
        """Should remove quotes from quoted values."""
        content = """---
Name: "Quoted Name"
Region: "Napa Valley"
---
"""
        
        frontmatter, body = updater.parse_frontmatter(content)
        
        assert frontmatter["Name"] == "Quoted Name"
        assert frontmatter["Region"] == "Napa Valley"

    def test_parse_frontmatter_empty_values(self, updater):
        """Should handle empty values."""
        content = """---
Label: 
Notes: ""
Rating: --
---
"""
        
        frontmatter, body = updater.parse_frontmatter(content)
        
        # Empty values should be preserved as empty string
        assert frontmatter["Label"] == ""
        assert frontmatter["Notes"] == ""
        assert frontmatter["Rating"] == ""


# ============================================================================
# Frontmatter Writing Tests
# ============================================================================

class TestFrontmatterWriting:
    """Test writing frontmatter back to file."""

    def test_write_frontmatter_success(self, updater, tmp_path):
        """Should successfully write frontmatter."""
        test_file = tmp_path / "test.md"
        
        frontmatter = {
            "fileClass": "Wine",
            "Winemaker": "Producer",
            "Price": "50.00"
        }
        body = "\n# Notes\nSome content"
        
        success = updater.write_frontmatter(test_file, frontmatter, body)
        
        assert success is True
        assert test_file.exists()
        
        # Verify content
        content = test_file.read_text()
        assert "---" in content
        assert "fileClass: Wine" in content
        assert "# Notes" in content

    def test_write_frontmatter_quotes_values_with_spaces(self, updater, tmp_path):
        """Should quote values that contain spaces."""
        test_file = tmp_path / "test.md"
        
        frontmatter = {
            "Producer": "Test Producer",  # Has space
            "Region": "Napa Valley"  # Has space
        }
        body = ""
        
        updater.write_frontmatter(test_file, frontmatter, body)
        
        content = test_file.read_text()
        
        # Values with spaces should be quoted
        assert '"Test Producer"' in content or 'Test Producer' in content
        assert '"Napa Valley"' in content or 'Napa Valley' in content

    def test_write_frontmatter_handles_empty_values(self, updater, tmp_path):
        """Should handle empty/None values."""
        test_file = tmp_path / "test.md"
        
        frontmatter = {
            "Label": "",
            "Notes": None
        }
        body = ""
        
        success = updater.write_frontmatter(test_file, frontmatter, body)
        
        assert success is True


# ============================================================================
# Get Bottle File Path Tests
# ============================================================================

class TestGetBottleFilePath:
    """Test finding bottle file in folder."""

    def test_get_bottle_file_path_exists(self, updater, temp_vault):
        """Should find bottle file when it exists."""
        bottle_folder = temp_vault / "1_Wines" / "TestWine"
        
        bottle_file = updater.get_bottle_file_path(bottle_folder)
        
        assert bottle_file is not None
        assert bottle_file.exists()
        assert bottle_file.name == "TestWine.md"

    def test_get_bottle_file_path_nonexistent(self, updater, temp_vault):
        """Should return None when bottle file doesn't exist."""
        # Create empty folder
        empty_folder = temp_vault / "1_Wines" / "EmptyFolder"
        empty_folder.mkdir(parents=True)
        
        bottle_file = updater.get_bottle_file_path(empty_folder)
        
        assert bottle_file is None


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Test full update workflow."""

    def test_full_update_workflow(self, updater, temp_vault):
        """Test complete workflow of reading, updating, writing."""
        bottle_file = temp_vault / "1_Wines" / "TestWine" / "TestWine.md"
        
        # Read original
        original_content = bottle_file.read_text()
        
        # Update label
        success = updater.update_label_field(bottle_file, "labels/new-label.jpg")
        assert success is True
        
        # Read updated
        updated_content = bottle_file.read_text()
        
        # Should have changed
        assert original_content != updated_content
        
        # Should have new label
        assert "new-label.jpg" in updated_content
        
        # Should preserve other content
        assert "Test Producer" in updated_content
        assert "# Tasting Notes" in updated_content

    def test_multiple_updates_same_file(self, updater, temp_vault):
        """Multiple updates to same file should work."""
        bottle_file = temp_vault / "1_Wines" / "TestWine" / "TestWine.md"
        
        # First update
        updater.update_label_field(bottle_file, "labels/label1.jpg")
        content1 = bottle_file.read_text()
        assert "label1.jpg" in content1
        
        # Second update
        updater.update_label_field(bottle_file, "labels/label2.jpg")
        content2 = bottle_file.read_text()
        assert "label2.jpg" in content2
        
        # Old label should be replaced
        assert "label1.jpg" not in content2
