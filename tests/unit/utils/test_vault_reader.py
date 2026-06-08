"""Tests for VaultReader utility.

Tests reading bottle metadata from Obsidian vault markdown files.
"""


import pytest

from reserve_automation.utils.vault_reader import VaultReader

# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def temp_vault(tmp_path):
    """Create temporary vault with test bottles."""
    vault = tmp_path / "vault"
    vault.mkdir()

    # Create wine bottles
    wines_dir = vault / "1_Wines"
    wines_dir.mkdir()

    # Wine 1: Complete metadata
    wine1_dir = wines_dir / "Caymus - Cabernet Sauvignon - 2019"
    wine1_dir.mkdir()
    (wine1_dir / "Caymus - Cabernet Sauvignon - 2019.md").write_text("""---
fileClass: Wine
Winemaker: Caymus
WineName: Cabernet Sauvignon
Vintage: 2019
Type: Red wine
Country-Region: USA - Napa Valley
Variety: Cabernet Sauvignon
Price: 85.00
ABV: 14.5
Inventory: 1
Buy: 0
---

# Tasting Notes
Excellent wine.
""")

    # Wine 2: Minimal metadata
    wine2_dir = wines_dir / "Simple Wine"
    wine2_dir.mkdir()
    (wine2_dir / "Simple Wine.md").write_text("""---
fileClass: Wine
Winemaker: Producer
WineName: Simple
Inventory: 0
Buy: 0
---
""")

    # Create whiskey bottles
    whiskeys_dir = vault / "1_Whiskeys"
    whiskeys_dir.mkdir()

    # Whiskey 1: Complete metadata
    whiskey1_dir = whiskeys_dir / "Buffalo Trace - George T Stagg - 2022"
    whiskey1_dir.mkdir()
    (whiskey1_dir / "Buffalo Trace - George T Stagg - 2022.md").write_text("""---
fileClass: Whiskey
Distiller: Buffalo Trace
WhiskeyName: George T Stagg
Year: 2022
Type: Bourbon
Proof: 130.4
ABV: 65.2
MashBill: High rye
BarrelType: Charred oak
Price: 125.00
Inventory: 1
Buy: 0
---

# Tasting Notes
Outstanding bourbon.
""")

    return vault


@pytest.fixture
def vault_reader(temp_vault):
    """Create VaultReader instance."""
    return VaultReader(temp_vault)


# ============================================================================
# Reading Bottles Tests
# ============================================================================

class TestReadingBottles:
    """Test reading bottles from vault."""

    def test_read_all_bottles(self, vault_reader):
        """read_all_bottles should return all bottles."""
        bottles = vault_reader.read_all_bottles()

        # Should have 3 bottles total (2 wine + 1 whiskey)
        assert len(bottles) >= 3

    def test_read_wine_bottles_only(self, vault_reader):
        """Filtering by beverage_type='wine' should return only wines."""
        bottles = vault_reader.read_all_bottles(beverage_type="wine")

        assert len(bottles) >= 2
        assert all(b.type == "wine" for b in bottles)

    def test_read_whiskey_bottles_only(self, vault_reader):
        """Filtering by beverage_type='whiskey' should return only whiskeys."""
        bottles = vault_reader.read_all_bottles(beverage_type="whiskey")

        assert len(bottles) >= 1
        assert all(b.type == "whiskey" for b in bottles)

    def test_bottles_have_vault_path(self, vault_reader):
        """All bottles should have vault_path set."""
        bottles = vault_reader.read_all_bottles()

        for bottle in bottles:
            assert bottle.vault_path is not None
            assert "/" in bottle.vault_path  # Should be "1_Wines/..." or "1_Whiskeys/..."


# ============================================================================
# Wine Parsing Tests
# ============================================================================

class TestWineParsing:
    """Test parsing wine bottle metadata."""

    def test_parse_wine_basic_fields(self, vault_reader):
        """Wine should have Winemaker, WineName, Vintage."""
        bottles = vault_reader.read_all_bottles(beverage_type="wine")
        caymus = [b for b in bottles if b.producer == "Caymus"][0]

        assert caymus.producer == "Caymus"
        assert caymus.name == "Cabernet Sauvignon"
        assert caymus.year == 2019
        assert caymus.type == "wine"

    def test_parse_wine_country_region(self, vault_reader):
        """Wine should parse Country-Region field."""
        bottles = vault_reader.read_all_bottles(beverage_type="wine")
        caymus = [b for b in bottles if b.producer == "Caymus"][0]

        assert caymus.country == "USA"
        assert caymus.region == "Napa Valley"

    def test_parse_wine_price(self, vault_reader):
        """Wine should parse Price field."""
        bottles = vault_reader.read_all_bottles(beverage_type="wine")
        caymus = [b for b in bottles if b.producer == "Caymus"][0]

        assert caymus.price == 85.00

    def test_parse_wine_variety(self, vault_reader):
        """Wine should parse Variety field."""
        bottles = vault_reader.read_all_bottles(beverage_type="wine")
        caymus = [b for b in bottles if b.producer == "Caymus"][0]

        assert caymus.variety == ["Cabernet Sauvignon"]

    def test_parse_wine_abv(self, vault_reader):
        """Wine should parse ABV field."""
        bottles = vault_reader.read_all_bottles(beverage_type="wine")
        caymus = [b for b in bottles if b.producer == "Caymus"][0]

        assert caymus.abv == 14.5


# ============================================================================
# Whiskey Parsing Tests
# ============================================================================

class TestWhiskeyParsing:
    """Test parsing whiskey bottle metadata."""

    def test_parse_whiskey_basic_fields(self, vault_reader):
        """Whiskey should have Distiller, WhiskeyName, Year."""
        bottles = vault_reader.read_all_bottles(beverage_type="whiskey")
        stagg = bottles[0]

        assert stagg.producer == "Buffalo Trace"
        assert stagg.name == "George T Stagg"
        assert stagg.year == 2022
        assert stagg.type == "whiskey"

    def test_parse_whiskey_proof(self, vault_reader):
        """Whiskey should parse Proof field."""
        bottles = vault_reader.read_all_bottles(beverage_type="whiskey")
        stagg = bottles[0]

        assert stagg.proof == 130.4

    def test_parse_whiskey_abv(self, vault_reader):
        """Whiskey should parse ABV field."""
        bottles = vault_reader.read_all_bottles(beverage_type="whiskey")
        stagg = bottles[0]

        assert stagg.abv == 65.2

    def test_parse_whiskey_mash_bill(self, vault_reader):
        """Whiskey should parse MashBill field."""
        bottles = vault_reader.read_all_bottles(beverage_type="whiskey")
        stagg = bottles[0]

        assert stagg.mash_bill == "High rye"

    def test_parse_whiskey_barrel_type(self, vault_reader):
        """Whiskey should parse BarrelType field."""
        bottles = vault_reader.read_all_bottles(beverage_type="whiskey")
        stagg = bottles[0]

        assert stagg.barrel_type == "Charred oak"


# ============================================================================
# Frontmatter Parsing Tests
# ============================================================================

class TestFrontmatterParsing:
    """Test frontmatter extraction and parsing."""

    def test_parse_file_with_frontmatter(self, temp_vault):
        """Should extract frontmatter from markdown."""
        # The bottles created in fixture have frontmatter
        reader = VaultReader(temp_vault)
        bottles = reader.read_all_bottles()

        # If we found bottles, frontmatter was parsed successfully
        assert len(bottles) > 0

    def test_skip_file_without_frontmatter(self, temp_vault):
        """Files without frontmatter should be skipped."""
        # Create bottle file without frontmatter
        wines_dir = temp_vault / "1_Wines"
        bad_dir = wines_dir / "BadBottle"
        bad_dir.mkdir()
        (bad_dir / "BadBottle.md").write_text("Just markdown, no frontmatter")

        reader = VaultReader(temp_vault)
        bottles = reader.read_all_bottles(beverage_type="wine")

        # BadBottle should not be in results
        bad_bottles = [b for b in bottles if b.name == "BadBottle"]
        assert len(bad_bottles) == 0

    def test_parse_empty_values(self, temp_vault):
        """Empty field values should be handled gracefully."""
        wines_dir = temp_vault / "1_Wines"
        empty_dir = wines_dir / "EmptyFields"
        empty_dir.mkdir()
        (empty_dir / "EmptyFields.md").write_text("""---
fileClass: Wine
Winemaker: Producer
WineName: Wine
Price:
Variety: ""
Inventory: 0
Buy: 0
---
""")

        reader = VaultReader(temp_vault)
        bottles = reader.read_all_bottles(beverage_type="wine")

        empty_bottle = [b for b in bottles if b.name == "Wine"][0]

        # Empty fields should be None
        assert empty_bottle.price is None
        assert empty_bottle.variety is None


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_bottle_file(self, temp_vault):
        """Folder without bottle file should be skipped."""
        # Create empty folder
        wines_dir = temp_vault / "1_Wines"
        empty_dir = wines_dir / "EmptyFolder"
        empty_dir.mkdir()

        reader = VaultReader(temp_vault)
        reader.read_all_bottles(beverage_type="wine")

        # Should not crash, just skip the empty folder
        assert True  # If we got here, it didn't crash

    def test_nonexistent_wine_directory(self, tmp_path):
        """Vault without 1_Wines should handle gracefully."""
        vault = tmp_path / "empty_vault"
        vault.mkdir()

        reader = VaultReader(vault)
        bottles = reader.read_all_bottles(beverage_type="wine")

        # Should return empty list, not crash
        assert bottles == []

    def test_invalid_price_value(self, temp_vault):
        """Invalid price should be handled gracefully."""
        wines_dir = temp_vault / "1_Wines"
        bad_price_dir = wines_dir / "BadPrice"
        bad_price_dir.mkdir()
        (bad_price_dir / "BadPrice.md").write_text("""---
fileClass: Wine
Winemaker: Producer
WineName: Wine
Price: invalid
---
""")

        reader = VaultReader(temp_vault)
        bottles = reader.read_all_bottles(beverage_type="wine")

        bad_bottle = [b for b in bottles if b.name == "Wine"]
        if bad_bottle:
            # Invalid price should be parsed as None
            assert bad_bottle[0].price is None

    def test_invalid_year_value(self, temp_vault):
        """Invalid year should be handled gracefully."""
        wines_dir = temp_vault / "1_Wines"
        nv_dir = wines_dir / "NonVintage"
        nv_dir.mkdir()
        (nv_dir / "NonVintage.md").write_text("""---
fileClass: Wine
Winemaker: Producer
WineName: Sparkling
Vintage: NV
---
""")

        reader = VaultReader(temp_vault)
        bottles = reader.read_all_bottles(beverage_type="wine")

        nv_bottle = [b for b in bottles if b.name == "Sparkling"]
        if nv_bottle:
            # NV should be parsed as None
            assert nv_bottle[0].year is None


# ============================================================================
# Vault Path Tests
# ============================================================================

class TestVaultPaths:
    """Test vault_path field generation."""

    def test_vault_path_format_wine(self, vault_reader):
        """Wine vault_path should be '1_Wines/FolderName'."""
        bottles = vault_reader.read_all_bottles(beverage_type="wine")
        caymus = [b for b in bottles if b.producer == "Caymus"][0]

        assert caymus.vault_path.startswith("1_Wines/")
        assert "Caymus" in caymus.vault_path

    def test_vault_path_format_whiskey(self, vault_reader):
        """Whiskey vault_path should be '1_Whiskeys/FolderName'."""
        bottles = vault_reader.read_all_bottles(beverage_type="whiskey")
        stagg = bottles[0]

        assert stagg.vault_path.startswith("1_Whiskeys/")
        assert "Buffalo Trace" in stagg.vault_path
