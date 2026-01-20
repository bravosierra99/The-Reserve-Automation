#CLAUDE_REQ: Vault structure MUST match Obsidian vault layout in the-reserve/Cellar/
#CLAUDE_REQ: Wine bottles: Cellar/1_Wines/{BottleName}/{BottleName}.md with fileClass: Wine
#CLAUDE_REQ: Whiskey bottles: Cellar/1_Whiskeys/{BottleName}/{BottleName}.md with fileClass: Whiskey
#CLAUDE_REQ: Bottle file naming: folder name MUST match bottle filename (e.g., "Producer - Name - Year" folder contains "Producer - Name - Year.md")
#CLAUDE_REQ: Tasting files in same folder as bottle: Tasting-YYYY-MM-DD-TasterName.md
"""Utility for reading bottle metadata from Obsidian vault."""

import re
from pathlib import Path
from typing import Optional

from loguru import logger

from ..core.models import BottleMetadata


class VaultReader:
    """Read bottle metadata from Obsidian vault markdown files."""

    def __init__(self, vault_path: Path):
        """
        Initialize vault reader.

        Args:
            vault_path: Path to Obsidian vault
        """
        self.vault_path = Path(vault_path)

    def read_all_bottles(
        self, beverage_type: Optional[str] = None
    ) -> list[BottleMetadata]:
        """
        Read all bottles from vault.

        Args:
            beverage_type: Optional filter ("wine" or "whiskey")

        Returns:
            List of bottle metadata
        """
        bottles = []

        # Read wines
        if not beverage_type or beverage_type == "wine":
            wine_dir = self.vault_path / "1_Wines"
            if wine_dir.exists():
                bottles.extend(self._read_bottles_from_dir(wine_dir, "wine"))

        # Read whiskeys
        if not beverage_type or beverage_type == "whiskey":
            whiskey_dir = self.vault_path / "1_Whiskeys"
            if whiskey_dir.exists():
                bottles.extend(self._read_bottles_from_dir(whiskey_dir, "whiskey"))

        logger.info(f"Read {len(bottles)} bottles from vault")
        return bottles

    def read_bottle(self, file_path: Path) -> Optional[BottleMetadata]:
        """
        Read a single bottle from a file path.

        Args:
            file_path: Absolute or relative path to bottle markdown file

        Returns:
            BottleMetadata or None if parsing fails
        """
        # Ensure absolute path
        if not file_path.is_absolute():
            file_path = self.vault_path / file_path

        # Determine bottle type from path
        bottle_type = None
        try:
            relative_path = file_path.relative_to(self.vault_path)
            first_part = str(relative_path).split('/')[0]
            if first_part == "1_Wines":
                bottle_type = "wine"
            elif first_part == "1_Whiskeys":
                bottle_type = "whiskey"
            else:
                logger.error(f"Cannot determine bottle type from path: {file_path}")
                return None
        except ValueError:
            logger.error(f"File path is not within vault: {file_path}")
            return None

        # Get bottle directory
        bottle_dir = file_path.parent

        return self._parse_bottle_file(file_path, bottle_type, bottle_dir)

    def _read_bottles_from_dir(self, directory: Path, bottle_type: str) -> list[BottleMetadata]:
        """
        Read bottles from a directory.

        Args:
            directory: Directory containing bottle folders
            bottle_type: "wine" or "whiskey"

        Returns:
            List of bottle metadata
        """
        bottles = []

        for bottle_dir in directory.iterdir():
            if not bottle_dir.is_dir():
                continue

            # Look for the bottle file
            bottle_file = bottle_dir / f"{bottle_dir.name}.md"
            if not bottle_file.exists():
                logger.warning(f"Bottle file not found: {bottle_file}")
                continue

            try:
                bottle = self._parse_bottle_file(bottle_file, bottle_type, bottle_dir)
                if bottle:
                    bottles.append(bottle)
            except Exception as e:
                logger.error(f"Failed to parse {bottle_file}: {e}")

        return bottles

    def _parse_bottle_file(self, file_path: Path, bottle_type: str, bottle_dir: Path) -> Optional[BottleMetadata]:
        """
        Parse bottle metadata from markdown file.

        Args:
            file_path: Path to bottle markdown file
            bottle_type: "wine" or "whiskey"
            bottle_dir: Path to bottle directory

        Returns:
            BottleMetadata or None if parsing fails
        """
        try:
            content = file_path.read_text(encoding="utf-8")

            # Extract frontmatter
            match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL | re.MULTILINE)
            if not match:
                logger.warning(f"No frontmatter found in {file_path}")
                return None

            frontmatter_text = match.group(1)

            # Parse YAML-like frontmatter
            metadata = {}
            for line in frontmatter_text.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()

                    # Clean up values
                    if value in ['', '""', "''", '--', 'None']:
                        value = None
                    elif value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]

                    metadata[key] = value

            # Convert to BottleMetadata
            return self._metadata_to_bottle(metadata, bottle_type, file_path.stem, bottle_dir)

        except Exception as e:
            logger.error(f"Error parsing {file_path}: {e}")
            return None

    def _metadata_to_bottle(
        self, metadata: dict, bottle_type: str, filename: str, bottle_dir: Path
    ) -> BottleMetadata:
        """
        Convert vault metadata dict to BottleMetadata.

        Args:
            metadata: Parsed frontmatter dict
            bottle_type: "wine" or "whiskey"
            filename: Filename (used to extract producer/name/year)
            bottle_dir: Path to bottle directory

        Returns:
            BottleMetadata instance
        """
        # Parse Country-Region field (combined in vault, separate in BottleMetadata)
        country = None
        region = None
        country_region = metadata.get("Country-Region")
        if country_region and country_region != "":
            # Split on " - " if present
            if " - " in country_region:
                parts = country_region.split(" - ", 1)
                country = parts[0].strip()
                region = parts[1].strip()
            else:
                # Assume it's just country or just region
                # Try to determine which based on common patterns
                if country_region in ["Italy", "France", "Spain", "United States", "USA"]:
                    country = country_region
                else:
                    region = country_region

        # Get producer and wine/whiskey name from metadata or filename
        producer = metadata.get("Winemaker") or metadata.get("Distiller")
        name = metadata.get("WineName") or metadata.get("WhiskeyName")

        # Parse year (wines use "Vintage", whiskeys use "Year")
        vintage_str = metadata.get("Vintage") or metadata.get("Year")
        year = None
        if vintage_str and vintage_str not in ["", "NV"]:
            try:
                year = int(vintage_str)
            except (ValueError, TypeError):
                pass

        # Parse price
        price_str = metadata.get("Price")
        price = None
        if price_str and price_str != "":
            try:
                price = float(price_str)
            except (ValueError, TypeError):
                pass

        # Calculate vault path (relative to vault root)
        # e.g., "1_Whiskeys/Rare character - American light whiskey - 2025"
        vault_path = str(bottle_dir.relative_to(self.vault_path))

        # Parse numeric fields
        def parse_float(value):
            if value:
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return None
            return None

        def parse_int(value):
            if value:
                try:
                    return int(value)
                except (ValueError, TypeError):
                    return None
            return None

        # Build BottleMetadata
        bottle_data = {
            "producer": producer or "Unknown",
            "name": name or filename,
            "type": bottle_type,
            "year": year,
            "beverage_type": metadata.get("Type"),
            "country": country,
            "region": region,
            "price": price,
            "source": "vault",
            "vault_path": vault_path,
            # Common fields
            "purchase_source": metadata.get("PurchaseSource"),
            "purchase_link": metadata.get("PurchaseLink"),
            "inventory": parse_int(metadata.get("Inventory")),
            "buy": parse_int(metadata.get("Buy")),
            "stars": metadata.get("Stars"),
            "value_for_money": parse_float(metadata.get("ValueForMoney")),
            "points": metadata.get("Points"),
        }

        # Wine-specific fields
        if bottle_type == "wine":
            bottle_data["variety"] = metadata.get("Variety")
            bottle_data["vineyard"] = metadata.get("Vineyard")
            bottle_data["style"] = metadata.get("Style")
            bottle_data["abv"] = parse_float(metadata.get("ABV"))

        # Whiskey-specific fields
        elif bottle_type == "whiskey":
            # Parse age statement - extract first number from strings like "6+ years", "15", "NAS"
            age_str = metadata.get("AgeStatement")
            age_statement = None
            if age_str and age_str not in ["NAS", "N/A"]:
                try:
                    # Try to parse as int directly
                    age_statement = int(age_str)
                except ValueError:
                    # Extract first number from strings like "6+ years"
                    import re
                    match = re.search(r'\d+', age_str)
                    if match:
                        age_statement = int(match.group())

            bottle_data["age_statement"] = age_statement
            bottle_data["mash_bill"] = metadata.get("MashBill")
            bottle_data["barrel_type"] = metadata.get("BarrelType")
            bottle_data["batch_number"] = metadata.get("BatchNumber")
            bottle_data["bottle_number"] = metadata.get("BottleNumber")
            bottle_data["bottle_opened_date"] = metadata.get("BottleOpenedDate")
            bottle_data["proof"] = parse_float(metadata.get("Proof"))
            bottle_data["abv"] = parse_float(metadata.get("ABV"))

        return BottleMetadata(**bottle_data)
