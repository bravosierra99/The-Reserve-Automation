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
                    if value in ['', '""', "''", '--']:
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
        }

        # Wine-specific fields
        if bottle_type == "wine":
            bottle_data["variety"] = metadata.get("Variety")
            bottle_data["vineyard"] = metadata.get("Vineyard")

            # Parse ABV for wine
            abv_str = metadata.get("ABV")
            if abv_str:
                try:
                    bottle_data["abv"] = float(abv_str)
                except (ValueError, TypeError):
                    pass

        # Whiskey-specific fields
        elif bottle_type == "whiskey":
            bottle_data["mash_bill"] = metadata.get("MashBill")
            bottle_data["barrel_type"] = metadata.get("BarrelType")

            # Try to parse proof
            proof_str = metadata.get("Proof")
            if proof_str:
                try:
                    bottle_data["proof"] = float(proof_str)
                except (ValueError, TypeError):
                    pass

            # Parse ABV for whiskey (in addition to proof)
            abv_str = metadata.get("ABV")
            if abv_str:
                try:
                    bottle_data["abv"] = float(abv_str)
                except (ValueError, TypeError):
                    pass

        return BottleMetadata(**bottle_data)
