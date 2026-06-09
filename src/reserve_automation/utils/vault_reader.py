#CLAUDE_REQ: Vault structure MUST match Obsidian vault layout in the-reserve/Cellar/
#CLAUDE_REQ: Wine bottles: Cellar/1_Wines/{BottleName}/{BottleName}.md with fileClass: Wine
#CLAUDE_REQ: Whiskey bottles: Cellar/1_Whiskeys/{BottleName}/{BottleName}.md with fileClass: Whiskey
#CLAUDE_REQ: Bottle file naming: folder name MUST match bottle filename (e.g., "Producer - Name - Year" folder contains "Producer - Name - Year.md")
#CLAUDE_REQ: Tasting files in same folder as bottle: Tasting-YYYY-MM-DD-TasterName.md
#CLAUDE_REQ: Ingredients: Cellar/2_Ingredients/{Name}/{Name}.md with fileClass: Ingredient
#CLAUDE_REQ: Ingredient fields MUST match FileClass (8_FileClass/Ingredient.md) and model (core/ingredient.py)
#CLAUDE_REQ: Cocktail tastings: Cellar/3_Cocktails/{CocktailName}/Tasting-YYYY-MM-DD-TasterName.md with fileClass: "Cocktail Tasting"
#CLAUDE_REQ: Cocktail tasting fields MUST match FileClass (8_FileClass/Cocktail Tasting.md) and model (core/cocktail_tasting.py)
"""Utility for reading bottle metadata from Obsidian vault."""

import re
from pathlib import Path
from typing import Optional

from loguru import logger

from ..core.bottle_registry import BottleRegistry
from ..core.cocktail import CocktailRecipe, RecipeIngredient
from ..core.cocktail_tasting import CocktailTastingIngredient, CocktailTastingNote
from ..core.ingredient import Ingredient, build_ingredient_tree
from ..core.models import BottleMetadata


class VaultReader:
    """Read bottle metadata from Obsidian vault markdown files."""

    def __init__(self, vault_path: Path, registry: Optional[BottleRegistry] = None):
        """
        Initialize vault reader.

        Args:
            vault_path: Path to Obsidian vault
            registry: Optional BottleRegistry to register bottles with for ID mapping
        """
        self.vault_path = Path(vault_path)
        self.registry = registry

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
            raw_variety = metadata.get("Variety")
            bottle_data["variety"] = [raw_variety] if isinstance(raw_variety, str) and raw_variety.strip() else None
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

        # Register with bottle registry and get opaque ID
        # Note: Must use "is not None" because BottleRegistry has __len__ which
        # makes empty registries falsy in boolean context
        if self.registry is not None:
            bottle_id = self.registry.register(vault_path)
            bottle_data["id"] = bottle_id
        else:
            # Generate ID even without registry (for deterministic IDs)
            bottle_data["id"] = BottleRegistry.generate_id(vault_path)

        return BottleMetadata(**bottle_data)

    # ========================================================================
    # INGREDIENT READING
    # ========================================================================

    def read_all_ingredients(self, as_tree: bool = False) -> list[Ingredient]:
        """
        Read all ingredients from the vault 2_Ingredients/ directory.

        Args:
            as_tree: If True, return tree roots with children populated.
                     If False, return flat list.

        Returns:
            List of Ingredient objects (tree roots or flat list).
        """
        ingredients_dir = self.vault_path / "2_Ingredients"
        if not ingredients_dir.exists():
            logger.info("No 2_Ingredients directory found in vault")
            return []

        ingredients = []
        for item_dir in ingredients_dir.iterdir():
            if not item_dir.is_dir():
                continue

            # Look for the ingredient file (folder name matches filename)
            item_file = item_dir / f"{item_dir.name}.md"
            if not item_file.exists():
                logger.warning(f"Ingredient file not found: {item_file}")
                continue

            try:
                ingredient = self._parse_ingredient_file(item_file, item_dir)
                if ingredient:
                    ingredients.append(ingredient)
            except Exception as e:
                logger.error(f"Failed to parse ingredient {item_file}: {e}")

        logger.info(f"Read {len(ingredients)} ingredients from vault")

        if as_tree:
            return build_ingredient_tree(ingredients)
        return ingredients

    def read_ingredient(self, file_path: Path) -> Optional[Ingredient]:
        """
        Read a single ingredient from a file path.

        Args:
            file_path: Absolute or relative path to ingredient markdown file.

        Returns:
            Ingredient or None if parsing fails.
        """
        if not file_path.is_absolute():
            file_path = self.vault_path / file_path

        if not file_path.exists():
            logger.error(f"Ingredient file not found: {file_path}")
            return None

        return self._parse_ingredient_file(file_path, file_path.parent)

    def _parse_ingredient_file(
        self, file_path: Path, item_dir: Path
    ) -> Optional[Ingredient]:
        """
        Parse ingredient metadata from a markdown file.

        Args:
            file_path: Path to ingredient markdown file.
            item_dir: Path to ingredient directory.

        Returns:
            Ingredient or None if parsing fails.
        """
        try:
            content = file_path.read_text(encoding="utf-8")

            # Extract frontmatter
            match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL | re.MULTILINE)
            if not match:
                logger.warning(f"No frontmatter found in {file_path}")
                return None

            frontmatter_text = match.group(1)

            # Parse YAML-like frontmatter (same simple parser as bottles)
            metadata = {}
            for line in frontmatter_text.split('\n'):
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip()
                    value = value.strip()

                    if value in ['', '""', "''", '--', 'None']:
                        value = None
                    elif value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]

                    metadata[key] = value

            return self._metadata_to_ingredient(metadata, item_dir)

        except Exception as e:
            logger.error(f"Error parsing ingredient {file_path}: {e}")
            return None

    def _metadata_to_ingredient(
        self, metadata: dict, item_dir: Path
    ) -> Ingredient:
        """
        Convert vault metadata dict to Ingredient.

        Args:
            metadata: Parsed frontmatter dict.
            item_dir: Path to ingredient directory.

        Returns:
            Ingredient instance.
        """
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

        def parse_bool(value):
            if value is None:
                return None
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ('true', '1', 'yes')
            return None

        vault_path = str(item_dir.relative_to(self.vault_path))

        # Generate opaque ID
        if self.registry is not None:
            ingredient_id = self.registry.register(vault_path)
        else:
            ingredient_id = BottleRegistry.generate_id(vault_path)

        ingredient = Ingredient(
            name=metadata.get("IngredientName") or item_dir.name,
            parent=metadata.get("Parent"),
            cost=parse_float(metadata.get("Cost")),
            volume_ml=parse_int(metadata.get("VolumeMl")),
            abv=parse_float(metadata.get("ABV")),
            notes=metadata.get("Notes"),
            label_image=metadata.get("Label"),
            id=ingredient_id,
            vault_path=vault_path,
        )
        ingredient.compute_is_product()
        return ingredient

    # ========================================================================
    # COCKTAIL READING
    # ========================================================================

    def read_all_cocktails(self) -> list[CocktailRecipe]:
        """
        Read all cocktails from the vault 3_Cocktails/ directory.

        Uses pyyaml for proper YAML parsing (ingredients/instructions are arrays).

        Returns:
            List of CocktailRecipe objects.
        """
        cocktails_dir = self.vault_path / "3_Cocktails"
        if not cocktails_dir.exists():
            logger.info("No 3_Cocktails directory found in vault")
            return []

        cocktails = []
        for item_dir in cocktails_dir.iterdir():
            if not item_dir.is_dir():
                continue

            item_file = item_dir / f"{item_dir.name}.md"
            if not item_file.exists():
                logger.warning(f"Cocktail file not found: {item_file}")
                continue

            try:
                cocktail = self._parse_cocktail_file(item_file, item_dir)
                if cocktail:
                    cocktails.append(cocktail)
            except Exception as e:
                logger.error(f"Failed to parse cocktail {item_file}: {e}")

        logger.info(f"Read {len(cocktails)} cocktails from vault")
        return cocktails

    def read_cocktail(self, file_path: Path) -> Optional[CocktailRecipe]:
        """Read a single cocktail from a file path."""
        if not file_path.is_absolute():
            file_path = self.vault_path / file_path

        if not file_path.exists():
            logger.error(f"Cocktail file not found: {file_path}")
            return None

        return self._parse_cocktail_file(file_path, file_path.parent)

    def _parse_cocktail_file(
        self, file_path: Path, item_dir: Path
    ) -> Optional[CocktailRecipe]:
        """Parse cocktail from a markdown file using pyyaml for YAML arrays."""
        import yaml

        try:
            content = file_path.read_text(encoding="utf-8")

            match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL | re.MULTILINE)
            if not match:
                logger.warning(f"No frontmatter found in {file_path}")
                return None

            frontmatter_text = match.group(1)

            # Use pyyaml for proper parsing of YAML arrays
            metadata = yaml.safe_load(frontmatter_text) or {}

            return self._metadata_to_cocktail(metadata, item_dir)

        except Exception as e:
            logger.error(f"Error parsing cocktail {file_path}: {e}")
            return None

    def _metadata_to_cocktail(
        self, metadata: dict, item_dir: Path
    ) -> CocktailRecipe:
        """Convert vault metadata dict to CocktailRecipe."""
        vault_path = str(item_dir.relative_to(self.vault_path))

        # Generate opaque ID
        if self.registry is not None:
            cocktail_id = self.registry.register(vault_path)
        else:
            cocktail_id = BottleRegistry.generate_id(vault_path)

        # Parse ingredients array
        raw_ingredients = metadata.get("Ingredients") or []
        ingredients = []
        for item in raw_ingredients:
            if isinstance(item, dict):
                ingredients.append(RecipeIngredient(
                    ingredient=item.get("ingredient", ""),
                    amount=item.get("amount"),
                    unit=item.get("unit"),
                    notes=item.get("notes"),
                    optional=item.get("optional", False),
                ))

        # Parse instructions array
        raw_instructions = metadata.get("Instructions") or []
        instructions = [str(s) for s in raw_instructions if s]

        # Parse serving size
        serving_size = 1
        raw_serving = metadata.get("ServingSize")
        if raw_serving:
            try:
                serving_size = int(raw_serving)
            except (ValueError, TypeError):
                pass

        return CocktailRecipe(
            name=metadata.get("CocktailName") or item_dir.name,
            description=metadata.get("Description"),
            ingredients=ingredients,
            instructions=instructions,
            garnish=metadata.get("Garnish"),
            glassware=metadata.get("Glassware"),
            method=metadata.get("Method"),
            style=metadata.get("Style"),
            serving_size=serving_size,
            stars=metadata.get("Stars"),
            photo=metadata.get("Photo"),
            id=cocktail_id,
            vault_path=vault_path,
        )

    # ========================================================================
    # COCKTAIL TASTING READING
    # ========================================================================

    def read_cocktail_tastings(self, cocktail_name: str) -> list[CocktailTastingNote]:
        """
        Read all tasting notes for a specific cocktail.

        Tastings live in the cocktail folder: 3_Cocktails/{CocktailName}/Tasting-*.md

        Args:
            cocktail_name: Name of the cocktail (folder name).

        Returns:
            List of CocktailTastingNote objects.
        """

        cocktail_dir = self.vault_path / "3_Cocktails" / cocktail_name
        if not cocktail_dir.exists():
            logger.info(f"Cocktail directory not found: {cocktail_dir}")
            return []

        tastings = []
        for md_file in cocktail_dir.glob("Tasting-*.md"):
            try:
                tasting = self._parse_cocktail_tasting_file(md_file, cocktail_name)
                if tasting:
                    tastings.append(tasting)
            except Exception as e:
                logger.error(f"Failed to parse cocktail tasting {md_file}: {e}")

        logger.info(f"Read {len(tastings)} tastings for cocktail {cocktail_name}")
        return tastings

    def _parse_cocktail_tasting_file(
        self, file_path: Path, cocktail_name: str
    ) -> Optional[CocktailTastingNote]:
        """Parse a cocktail tasting note from a markdown file."""
        import yaml

        try:
            content = file_path.read_text(encoding="utf-8")

            match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL | re.MULTILINE)
            if not match:
                logger.warning(f"No frontmatter found in {file_path}")
                return None

            frontmatter_text = match.group(1)
            metadata = yaml.safe_load(frontmatter_text) or {}

            # Only parse files with correct fileClass
            file_class = metadata.get("fileClass")
            if file_class != "Cocktail Tasting":
                return None

            return self._metadata_to_cocktail_tasting(metadata, file_path, cocktail_name)

        except Exception as e:
            logger.error(f"Error parsing cocktail tasting {file_path}: {e}")
            return None

    def _metadata_to_cocktail_tasting(
        self, metadata: dict, file_path: Path, cocktail_name: str
    ) -> CocktailTastingNote:
        """Convert vault metadata dict to CocktailTastingNote."""

        # Generate opaque ID from the tasting file path
        tasting_vault_path = str(file_path.relative_to(self.vault_path))
        if self.registry is not None:
            tasting_id = self.registry.register(tasting_vault_path)
        else:
            tasting_id = BottleRegistry.generate_id(tasting_vault_path)

        # Parse bottles used (YAML array)
        raw_bottles = metadata.get("BottlesUsed") or []
        bottles_used = []
        for item in raw_bottles:
            if isinstance(item, dict):
                bottles_used.append(CocktailTastingIngredient(
                    recipe_ingredient=item.get("recipe_ingredient", ""),
                    actual_product=item.get("actual_product", ""),
                ))

        # Parse score
        score = None
        raw_score = metadata.get("Score")
        if raw_score is not None and raw_score != "":
            try:
                score = float(raw_score)
            except (ValueError, TypeError):
                pass

        return CocktailTastingNote(
            recipe_name=cocktail_name,
            taster_name=metadata.get("TasterName") or "",
            tasting_date=str(metadata.get("Date") or ""),
            bottles_used=bottles_used,
            score=score,
            notes=metadata.get("Notes"),
            bartender=metadata.get("Bartender"),
            id=tasting_id,
            vault_path=tasting_vault_path,
        )
