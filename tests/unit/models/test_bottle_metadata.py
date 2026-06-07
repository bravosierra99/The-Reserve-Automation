"""BottleMetadata Tests - Field Coherence and Conversion.

These tests verify BottleMetadata field mappings and conversions work correctly
across all integration points:
1. Obsidian FileClass definitions
2. Templates
3. Generator context
4. Vault reader parsing
5. Field name mapping (web/routes/management.py)

CRITICAL: The #CLAUDE_REQ chain requires all of these to stay synchronized.
"""


import pytest

from reserve_automation.core.models import BeverageType, BottleMetadata

# ============================================================================
# Test Basic BottleMetadata Creation
# ============================================================================

class TestBottleMetadataCreation:
    """Test creating BottleMetadata with various field combinations."""

    def test_create_minimal_wine_bottle(self):
        """Test creating wine with only required fields."""
        wine = BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            type=BeverageType.WINE,
            source="test"
        )

        assert wine.producer == "Caymus"
        assert wine.name == "Cabernet Sauvignon"
        assert wine.type == "wine"

    def test_create_minimal_whiskey_bottle(self):
        """Test creating whiskey with only required fields."""
        whiskey = BottleMetadata(
            producer="Buffalo Trace",
            name="Bourbon",
            type=BeverageType.WHISKEY,
            source="test"
        )

        assert whiskey.producer == "Buffalo Trace"
        assert whiskey.name == "Bourbon"
        assert whiskey.type == "whiskey"

    def test_create_wine_with_all_fields(self):
        """Test creating wine with all possible fields."""
        wine = BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            type=BeverageType.WINE,
            year=2019,
            beverage_type="Red wine",
            country="USA",
            region="Napa Valley",
            variety="Cabernet Sauvignon",
            vineyard="Special Selection",
            abv=14.5,
            price=85.00,
            purchase_source="Wine Shop",
            inventory=2,
            source="test"
        )

        assert wine.year == 2019
        assert wine.country == "USA"
        assert wine.region == "Napa Valley"
        assert wine.variety == ["Cabernet Sauvignon"]
        assert wine.price == 85.00
        assert wine.inventory == 2

    def test_create_whiskey_with_all_fields(self):
        """Test creating whiskey with all whiskey-specific fields."""
        whiskey = BottleMetadata(
            producer="Buffalo Trace",
            name="George T. Stagg",
            type=BeverageType.WHISKEY,
            year=2022,
            beverage_type="Bourbon",
            age_statement=15,
            proof=130.4,
            mash_bill="High rye bourbon",
            barrel_type="Charred oak",
            abv=65.2,
            price=125.00,
            purchase_source="Liquor Store",
            inventory=1,
            source="test"
        )

        assert whiskey.age_statement == 15
        assert whiskey.proof == 130.4
        assert whiskey.mash_bill == "High rye bourbon"
        assert whiskey.barrel_type == "Charred oak"


# ============================================================================
# Test Field Validation
# ============================================================================

class TestFieldValidation:
    """Test Pydantic validation rules."""

    def test_year_range_validation(self):
        """Year should be between 1800 and 2030."""
        # Valid years
        BottleMetadata(producer="Test", name="Wine", type="wine", year=1800, source="test")
        BottleMetadata(producer="Test", name="Wine", type="wine", year=2030, source="test")

        # Invalid years should raise
        with pytest.raises(Exception):
            BottleMetadata(producer="Test", name="Wine", type="wine", year=2031, source="test")

        with pytest.raises(Exception):
            BottleMetadata(producer="Test", name="Wine", type="wine", year=1799, source="test")

    def test_proof_range_validation(self):
        """Proof should be 0-200."""
        BottleMetadata(producer="Test", name="Whiskey", type="whiskey", proof=0, source="test")
        BottleMetadata(producer="Test", name="Whiskey", type="whiskey", proof=200, source="test")

        with pytest.raises(Exception):
            BottleMetadata(producer="Test", name="Whiskey", type="whiskey", proof=201, source="test")

    def test_abv_range_validation(self):
        """ABV should be 0-100."""
        BottleMetadata(producer="Test", name="Wine", type="wine", abv=0, source="test")
        BottleMetadata(producer="Test", name="Wine", type="wine", abv=100, source="test")

        with pytest.raises(Exception):
            BottleMetadata(producer="Test", name="Wine", type="wine", abv=101, source="test")

    def test_age_statement_validation(self):
        """Age statement should be 0-100."""
        BottleMetadata(producer="Test", name="Whiskey", type="whiskey", age_statement=0, source="test")
        BottleMetadata(producer="Test", name="Whiskey", type="whiskey", age_statement=100, source="test")

        with pytest.raises(Exception):
            BottleMetadata(producer="Test", name="Whiskey", type="whiskey", age_statement=101, source="test")

    def test_inventory_validation(self):
        """Inventory should be >= 0."""
        BottleMetadata(producer="Test", name="Wine", type="wine", inventory=0, source="test")
        BottleMetadata(producer="Test", name="Wine", type="wine", inventory=100, source="test")

        with pytest.raises(Exception):
            BottleMetadata(producer="Test", name="Wine", type="wine", inventory=-1, source="test")

    def test_confidence_range_validation(self):
        """Confidence should be 0-1."""
        BottleMetadata(producer="Test", name="Wine", type="wine", confidence=0.0, source="test")
        BottleMetadata(producer="Test", name="Wine", type="wine", confidence=1.0, source="test")

        with pytest.raises(Exception):
            BottleMetadata(producer="Test", name="Wine", type="wine", confidence=1.1, source="test")


# ============================================================================
# Test Obsidian Dict Conversion
# ============================================================================

class TestObsidianDictConversion:
    """Test to_obsidian_dict() method for FileClass compatibility."""

    def test_wine_to_obsidian_dict_basic_fields(self):
        """Wine should use Winemaker and Vintage."""
        wine = BottleMetadata(
            producer="Caymus",
            name="Cabernet Sauvignon",
            type="wine",
            year=2019,
            source="test"
        )

        obsidian_dict = wine.to_obsidian_dict()

        assert obsidian_dict["Winemaker"] == "Caymus"
        assert obsidian_dict["Vintage"] == 2019
        assert "Distiller" not in obsidian_dict
        assert "Year" not in obsidian_dict

    def test_whiskey_to_obsidian_dict_basic_fields(self):
        """Whiskey should use Distiller and Year."""
        whiskey = BottleMetadata(
            producer="Buffalo Trace",
            name="Bourbon",
            type="whiskey",
            year=2022,
            source="test"
        )

        obsidian_dict = whiskey.to_obsidian_dict()

        assert obsidian_dict["Distiller"] == "Buffalo Trace"
        assert obsidian_dict["Year"] == 2022
        assert "Winemaker" not in obsidian_dict
        assert "Vintage" not in obsidian_dict

    def test_to_obsidian_dict_includes_purchase_source(self):
        """PurchaseSource should be in Obsidian dict."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            purchase_source="Wine Shop",
            source="test"
        )

        obsidian_dict = bottle.to_obsidian_dict()

        assert obsidian_dict["PurchaseSource"] == "Wine Shop"

    def test_to_obsidian_dict_includes_inventory(self):
        """Inventory should always be in Obsidian dict (defaults to 0)."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            source="test"
        )

        obsidian_dict = bottle.to_obsidian_dict()

        assert "Inventory" in obsidian_dict
        assert obsidian_dict["Inventory"] == 0

    def test_to_obsidian_dict_with_inventory(self):
        """Inventory value should be preserved."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            inventory=5,
            source="test"
        )

        obsidian_dict = bottle.to_obsidian_dict()

        assert obsidian_dict["Inventory"] == 5

    def test_to_obsidian_dict_excludes_none_fields(self):
        """None fields should not appear in Obsidian dict."""
        bottle = BottleMetadata(
            producer="Test",
            name="Wine",
            type="wine",
            country=None,
            region=None,
            abv=None,
            source="test"
        )

        obsidian_dict = bottle.to_obsidian_dict()

        assert "Country" not in obsidian_dict
        assert "Region" not in obsidian_dict
        assert "Abv" not in obsidian_dict


# ============================================================================
# Test Field Name Conventions
# ============================================================================

class TestFieldNameConventions:
    """Test field naming consistency across models."""

    def test_bottle_metadata_core_fields_exist(self):
        """Ensure all core bottle fields exist."""
        required_fields = {
            "producer", "name", "type", "year", "beverage_type",
            "country", "region", "abv", "price", "purchase_source", "inventory"
        }

        bottle_fields = set(BottleMetadata.model_fields.keys())

        for field in required_fields:
            assert field in bottle_fields, f"BottleMetadata missing field: {field}"

    def test_wine_specific_fields_exist(self):
        """Ensure wine-specific fields exist."""
        wine_fields = {"variety", "vineyard"}

        bottle_fields = set(BottleMetadata.model_fields.keys())

        for field in wine_fields:
            assert field in bottle_fields, f"BottleMetadata missing wine field: {field}"

    def test_whiskey_specific_fields_exist(self):
        """Ensure whiskey-specific fields exist."""
        whiskey_fields = {"age_statement", "proof", "mash_bill", "barrel_type"}

        bottle_fields = set(BottleMetadata.model_fields.keys())

        for field in whiskey_fields:
            assert field in bottle_fields, f"BottleMetadata missing whiskey field: {field}"
