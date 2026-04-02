"""One-time import script to migrate data from Obsidian vault to SQLite database.

Usage:
    uv run python -m reserve_automation.scripts.import_vault --vault-path /path/to/vault/Cellar
    uv run python -m reserve_automation.scripts.import_vault --vault-path /path/to/vault/Cellar --dry-run
"""

import re
import shutil
import sys
from datetime import date
from pathlib import Path

import click
import yaml
from loguru import logger
from sqlalchemy.orm import sessionmaker

from reserve_automation.core.bottle_registry import BottleRegistry
from reserve_automation.core.models import BottleMetadata
from reserve_automation.core.tasting_note import TastingNote
from reserve_automation.db.engine import init_db
from reserve_automation.db.models.bottle import BottleModel, TastingNoteModel
from reserve_automation.db.models.cocktail import (
    CocktailModel,
    CocktailInstructionModel,
    RecipeIngredientModel,
)
from reserve_automation.db.models.cocktail_tasting import (
    CocktailTastingModel,
    CocktailTastingIngredientModel,
)
from reserve_automation.db.models.ingredient import IngredientModel
from reserve_automation.utils.vault_reader import VaultReader


@click.command()
@click.option("--vault-path", required=True, type=click.Path(exists=True), help="Path to vault Cellar directory")
@click.option("--database-url", default="sqlite:///data/reserve.db", help="SQLAlchemy database URL")
@click.option("--media-dir", default="data/media", help="Directory for media files (images)")
@click.option("--dry-run", is_flag=True, help="Preview import without writing")
def main(vault_path: str, database_url: str, media_dir: str, dry_run: bool):
    """Import data from Obsidian vault into SQLite database."""
    vault = Path(vault_path)
    media = Path(media_dir)

    logger.info(f"Importing from vault: {vault}")
    logger.info(f"Database: {database_url}")
    logger.info(f"Media dir: {media}")
    if dry_run:
        logger.info("DRY RUN - no data will be written")

    # Initialize database
    engine = init_db(database_url)
    Session = sessionmaker(bind=engine)
    db = Session()

    # Initialize vault reader
    registry = BottleRegistry()
    reader = VaultReader(vault, registry=registry)

    stats = {
        "bottles": 0,
        "tastings": 0,
        "ingredients": 0,
        "cocktails": 0,
        "cocktail_tastings": 0,
        "images_copied": 0,
        "errors": [],
    }

    try:
        # Phase 1: Import bottles
        _import_bottles(db, reader, vault, media, stats, dry_run)

        # Phase 2: Import tasting notes (needs bottle IDs from phase 1)
        _import_tastings(db, vault, stats, dry_run)

        # Phase 3: Import ingredients (two-pass for parent resolution)
        _import_ingredients(db, reader, vault, media, stats, dry_run)

        # Phase 4: Import cocktails
        _import_cocktails(db, reader, stats, dry_run)

        # Phase 5: Import cocktail tastings
        _import_cocktail_tastings(db, reader, vault, stats, dry_run)

        if not dry_run:
            db.commit()

        # Report
        logger.info("=" * 60)
        logger.info("IMPORT COMPLETE")
        logger.info(f"  Bottles:           {stats['bottles']}")
        logger.info(f"  Tasting notes:     {stats['tastings']}")
        logger.info(f"  Ingredients:       {stats['ingredients']}")
        logger.info(f"  Cocktails:         {stats['cocktails']}")
        logger.info(f"  Cocktail tastings: {stats['cocktail_tastings']}")
        logger.info(f"  Images copied:     {stats['images_copied']}")
        if stats["errors"]:
            logger.warning(f"  Errors:            {len(stats['errors'])}")
            for err in stats["errors"]:
                logger.warning(f"    - {err}")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"Import failed: {e}")
        db.rollback()
        raise
    finally:
        db.close()


def _import_bottles(db, reader: VaultReader, vault: Path, media: Path, stats: dict, dry_run: bool):
    """Import all bottles from the vault."""
    logger.info("Phase 1: Importing bottles...")

    bottles = reader.read_all_bottles()
    logger.info(f"  Found {len(bottles)} bottles in vault")

    for bottle in bottles:
        try:
            if dry_run:
                logger.info(f"  [DRY] Would import: {bottle.producer} - {bottle.name}")
                stats["bottles"] += 1
                continue

            db_bottle = BottleModel(
                producer=bottle.producer,
                name=bottle.name,
                type=bottle.type if isinstance(bottle.type, str) else bottle.type.value,
                year=bottle.year,
                beverage_type=bottle.beverage_type,
                country=bottle.country,
                region=bottle.region,
                variety=bottle.variety,
                vineyard=bottle.vineyard,
                style=bottle.style,
                age_statement=bottle.age_statement,
                proof=bottle.proof,
                mash_bill=bottle.mash_bill,
                barrel_type=bottle.barrel_type,
                batch_number=bottle.batch_number,
                bottle_number=bottle.bottle_number,
                bottle_opened_date=bottle.bottle_opened_date,
                abv=bottle.abv,
                price=bottle.price,
                purchase_source=bottle.purchase_source,
                purchase_link=bottle.purchase_link,
                inventory=bottle.inventory or 0,
                buy=bottle.buy or 0,
                stars=bottle.stars,
                value_for_money=bottle.value_for_money,
                points=bottle.points,
                confidence=bottle.confidence,
                source=bottle.source or "vault",
                enriched=bottle.enriched,
                notes=bottle.notes,
            )
            db.add(db_bottle)
            db.flush()  # Get the ID

            # Store vault_path -> db_id mapping for tasting import
            if bottle.vault_path:
                db_bottle._vault_path = bottle.vault_path

            # Copy label image (skip non-image files like PDFs)
            if bottle.vault_path:
                label_path = vault / bottle.vault_path / "labels" / "label.jpg"
                if label_path.exists():
                    try:
                        from PIL import Image
                        Image.open(label_path).verify()
                        dest_dir = media / "bottles" / str(db_bottle.id)
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        dest = dest_dir / "label.jpg"
                        shutil.copy2(label_path, dest)
                        db_bottle.label_image_path = f"bottles/{db_bottle.id}/label.jpg"
                        stats["images_copied"] += 1
                    except Exception:
                        logger.warning(f"  Skipping non-image label: {label_path}")
                        stats["errors"].append(f"Non-image label skipped: {label_path}")

            stats["bottles"] += 1

        except Exception as e:
            stats["errors"].append(f"Bottle {bottle.producer} - {bottle.name}: {e}")
            logger.error(f"  Error importing bottle: {e}")


def _import_tastings(db, vault: Path, stats: dict, dry_run: bool):
    """Import tasting notes for all bottles."""
    logger.info("Phase 2: Importing tasting notes...")

    # Build a lookup from (producer.lower(), name.lower()) -> BottleModel
    # so we can match vault directories to DB bottles without relying on
    # the ephemeral _vault_path attribute (which is lost on fresh DB queries).
    bottles = db.query(BottleModel).all()
    bottle_lookup: dict[tuple[str, str], BottleModel] = {}
    for b in bottles:
        key = (b.producer.lower().strip(), b.name.lower().strip())
        bottle_lookup[key] = b

    # Scan all bottle directories across beverage-type subdirs
    bottle_dirs = []
    for bev_dir in vault.iterdir():
        if not bev_dir.is_dir() or bev_dir.name.startswith("_") or bev_dir.name.startswith("0_"):
            continue
        for bottle_dir in bev_dir.iterdir():
            if bottle_dir.is_dir():
                bottle_dirs.append(bottle_dir)

    for bottle_dir in bottle_dirs:
        tasting_files = list(bottle_dir.glob("Tasting-*.md"))
        if not tasting_files:
            continue

        # Try to match this directory to a DB bottle.
        # Directory names are "Producer - Name" or "Producer - Name - Year".
        dir_name = bottle_dir.name
        matched_bottle = None

        if " - " in dir_name:
            parts = dir_name.split(" - ", 1)
            producer_raw = parts[0].strip()
            name_raw = parts[1].strip()

            # Attempt 1: full name as-is
            key = (producer_raw.lower(), name_raw.lower())
            matched_bottle = bottle_lookup.get(key)

            # Attempt 2: strip trailing 4-digit year from name (e.g. "Stagg Jr - 2024" → "Stagg Jr")
            if matched_bottle is None and re.search(r' - \d{4}$', name_raw):
                name_no_year = re.sub(r' - \d{4}$', '', name_raw).strip()
                key2 = (producer_raw.lower(), name_no_year.lower())
                matched_bottle = bottle_lookup.get(key2)

            # Attempt 3: treat last " - " segment as year, re-split to get full name
            if matched_bottle is None:
                all_parts = dir_name.split(" - ")
                if len(all_parts) >= 3 and re.match(r'^\d{4}$', all_parts[-1].strip()):
                    producer2 = all_parts[0].strip()
                    name2 = " - ".join(all_parts[1:-1]).strip()
                    key3 = (producer2.lower(), name2.lower())
                    matched_bottle = bottle_lookup.get(key3)

        # Fallback: match against _vault_path if set (first-run case)
        if matched_bottle is None:
            rel = str(bottle_dir.relative_to(vault))
            for b in bottles:
                if getattr(b, "_vault_path", None) == rel:
                    matched_bottle = b
                    break

        if matched_bottle is None:
            logger.debug(f"  No DB match for vault dir: {bottle_dir.name}")
            continue

        bev_type = matched_bottle.type

        for tasting_file in tasting_files:
            try:
                tasting_data = _parse_tasting_file(tasting_file, bev_type)
                if tasting_data is None:
                    continue

                if dry_run:
                    logger.info(f"  [DRY] Would import tasting: {tasting_file.name}")
                    stats["tastings"] += 1
                    continue

                db_tasting = TastingNoteModel(
                    bottle_id=matched_bottle.id,
                    bottle_name=f"{matched_bottle.producer} - {matched_bottle.name}",
                    **tasting_data,
                )
                db.add(db_tasting)
                stats["tastings"] += 1

            except Exception as e:
                stats["errors"].append(f"Tasting {tasting_file.name}: {e}")
                logger.error(f"  Error importing tasting {tasting_file.name}: {e}")


def _parse_tasting_file(file_path: Path, beverage_type: str) -> dict | None:
    """Parse a tasting note file into a dict of TastingNoteModel fields."""
    content = file_path.read_text(encoding="utf-8")
    match = re.search(r'^---\n(.*?)\n---', content, re.DOTALL | re.MULTILINE)
    if not match:
        return None

    frontmatter = match.group(1)
    metadata = {}
    for line in frontmatter.split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            if value in ['', '""', "''", '--', 'None']:
                value = None
            elif value.startswith('"') and value.endswith('"'):
                value = value[1:-1]
            metadata[key] = value

    # Check fileClass
    file_class = metadata.get("fileClass", "")
    if file_class not in ["Wine Tasting", "Tasting"]:
        return None

    def pf(v):
        if v:
            try:
                return float(v)
            except (ValueError, TypeError):
                return None
        return None

    def pi(v):
        if v:
            try:
                return int(v)
            except (ValueError, TypeError):
                return None
        return None

    # Parse tasting date from filename: Tasting-YYYY-MM-DD-TasterName.md
    tasting_date = None
    taster_name = "Unknown"
    fname = file_path.stem  # e.g., "Tasting-2025-01-15-Ben"
    date_match = re.match(r'Tasting-(\d{4}-\d{2}-\d{2})-(.+)', fname)
    if date_match:
        try:
            tasting_date = date.fromisoformat(date_match.group(1))
        except ValueError:
            pass
        taster_name = date_match.group(2)

    # Also check metadata for override
    if metadata.get("TasterName"):
        taster_name = metadata["TasterName"]
    if metadata.get("Date"):
        try:
            tasting_date = date.fromisoformat(str(metadata["Date"]))
        except (ValueError, TypeError):
            pass

    if tasting_date is None:
        tasting_date = date.today()

    result = {
        "taster_name": taster_name,
        "tasting_date": tasting_date,
        "beverage_type": beverage_type,
        "confidence": 1.0,
    }

    if beverage_type == "wine":
        result.update({
            "wine_appearance": pf(metadata.get("Appearance")),
            "wine_aroma": pf(metadata.get("Aroma")),
            "wine_taste": pf(metadata.get("Taste")),
            "wine_aftertaste": pf(metadata.get("Aftertaste")),
            "wine_overall": pf(metadata.get("Overall")),
        })
    else:
        result.update({
            "whiskey_nose": pf(metadata.get("Nose")),
            "whiskey_palate": pf(metadata.get("Palate")),
            "whiskey_finish": pf(metadata.get("Finish")),
            "whiskey_overall": pf(metadata.get("Overall")),
        })

    result["days_from_crack"] = pi(metadata.get("DaysFromCrack"))
    result["fill_level"] = pi(metadata.get("FillLevel"))
    result["place"] = metadata.get("Place")
    result["theme"] = metadata.get("Theme")
    result["price"] = metadata.get("Price")
    result["color"] = metadata.get("Color")

    # Parse note sections from body content (after frontmatter)
    # Notes are stored as bullet lists in markdown sections
    body = content.split("---", 2)[-1] if content.count("---") >= 2 else ""
    result["nose_notes"] = _extract_notes_section(body, "Nose") or _extract_notes_section(body, "Aroma")
    result["palate_notes"] = _extract_notes_section(body, "Palate") or _extract_notes_section(body, "Taste")
    result["finish_notes"] = _extract_notes_section(body, "Finish") or _extract_notes_section(body, "Aftertaste")
    result["appearance_notes"] = _extract_notes_section(body, "Appearance")
    result["overall_notes"] = metadata.get("OverallNotes")

    return result


def _extract_notes_section(body: str, section_name: str) -> list[str] | None:
    """Extract bullet-point notes from a markdown section."""
    pattern = rf'##\s*{re.escape(section_name)}\s*\n(.*?)(?=\n##|\Z)'
    match = re.search(pattern, body, re.DOTALL)
    if not match:
        return None

    notes = []
    for line in match.group(1).strip().split('\n'):
        line = line.strip()
        if line.startswith('- '):
            notes.append(line[2:].strip())
        elif line.startswith('* '):
            notes.append(line[2:].strip())

    return notes if notes else None


def _import_ingredients(db, reader: VaultReader, vault: Path, media: Path, stats: dict, dry_run: bool):
    """Import ingredients with two-pass parent resolution."""
    logger.info("Phase 3: Importing ingredients...")

    ingredients = reader.read_all_ingredients(as_tree=False)
    logger.info(f"  Found {len(ingredients)} ingredients in vault")

    if dry_run:
        for ing in ingredients:
            logger.info(f"  [DRY] Would import: {ing.name} (parent: {ing.parent})")
            stats["ingredients"] += 1
        return

    # Pass 1: Insert all ingredients without parent_id
    name_to_id = {}
    for ing in ingredients:
        try:
            db_ing = IngredientModel(
                name=ing.name,
                parent_id=None,  # Set in pass 2
                cost=ing.cost,
                volume_ml=ing.volume_ml,
                abv=ing.abv,
                notes=ing.notes,
            )
            db.add(db_ing)
            db.flush()
            name_to_id[ing.name] = db_ing.id

            # Copy label image if exists
            if ing.vault_path:
                label_path = vault / ing.vault_path / "labels" / "label.jpg"
                if label_path.exists():
                    dest_dir = media / "ingredients" / str(db_ing.id)
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    dest = dest_dir / "label.jpg"
                    shutil.copy2(label_path, dest)
                    db_ing.label_image_path = f"ingredients/{db_ing.id}/label.jpg"
                    stats["images_copied"] += 1

            stats["ingredients"] += 1
        except Exception as e:
            stats["errors"].append(f"Ingredient {ing.name}: {e}")
            logger.error(f"  Error importing ingredient {ing.name}: {e}")

    # Pass 2: Set parent_id references
    for ing in ingredients:
        if ing.parent and ing.parent in name_to_id and ing.name in name_to_id:
            db_ing = db.get(IngredientModel, name_to_id[ing.name])
            if db_ing:
                db_ing.parent_id = name_to_id[ing.parent]

    logger.info(f"  Imported {stats['ingredients']} ingredients with parent links")


def _import_cocktails(db, reader: VaultReader, stats: dict, dry_run: bool):
    """Import cocktail recipes."""
    logger.info("Phase 4: Importing cocktails...")

    cocktails = reader.read_all_cocktails()
    logger.info(f"  Found {len(cocktails)} cocktails in vault")

    # First pass: create all cocktails (no parent resolution yet)
    name_to_id = {}
    for cocktail in cocktails:
        try:
            if dry_run:
                logger.info(f"  [DRY] Would import: {cocktail.name}")
                stats["cocktails"] += 1
                continue

            db_cocktail = CocktailModel(
                name=cocktail.name,
                description=cocktail.description,
                garnish=cocktail.garnish,
                glassware=cocktail.glassware,
                method=cocktail.method,
                style=cocktail.style,
                serving_size=cocktail.serving_size,
                stars=cocktail.stars,
                photo_path=cocktail.photo,
            )
            db.add(db_cocktail)
            db.flush()
            name_to_id[cocktail.name] = db_cocktail.id

            # Add ingredients
            for i, ing in enumerate(cocktail.ingredients):
                db_ing = RecipeIngredientModel(
                    cocktail_id=db_cocktail.id,
                    ingredient_name=ing.ingredient,
                    amount=ing.amount,
                    unit=ing.unit,
                    notes=ing.notes,
                    optional=ing.optional,
                    sort_order=i,
                )
                db.add(db_ing)

            # Add instructions
            for i, instruction in enumerate(cocktail.instructions):
                db_inst = CocktailInstructionModel(
                    cocktail_id=db_cocktail.id,
                    step_number=i + 1,
                    instruction=instruction,
                )
                db.add(db_inst)

            stats["cocktails"] += 1

        except Exception as e:
            stats["errors"].append(f"Cocktail {cocktail.name}: {e}")
            logger.error(f"  Error importing cocktail {cocktail.name}: {e}")

    # Second pass: resolve parent_cocktail references
    if not dry_run:
        for cocktail in cocktails:
            if cocktail.parent_cocktail and cocktail.parent_cocktail in name_to_id:
                if cocktail.name in name_to_id:
                    db_cocktail = db.get(CocktailModel, name_to_id[cocktail.name])
                    if db_cocktail:
                        db_cocktail.parent_cocktail_id = name_to_id[cocktail.parent_cocktail]


def _import_cocktail_tastings(db, reader: VaultReader, vault: Path, stats: dict, dry_run: bool):
    """Import cocktail tasting notes."""
    logger.info("Phase 5: Importing cocktail tastings...")

    # Get all cocktails we just imported
    cocktails = db.query(CocktailModel).all()
    cocktail_name_to_id = {c.name: c.id for c in cocktails}

    for cocktail in cocktails:
        tastings = reader.read_cocktail_tastings(cocktail.name)
        for tasting in tastings:
            try:
                if dry_run:
                    logger.info(f"  [DRY] Would import tasting for {cocktail.name} by {tasting.taster_name}")
                    stats["cocktail_tastings"] += 1
                    continue

                tasting_date = tasting.tasting_date
                if isinstance(tasting_date, str):
                    try:
                        tasting_date = date.fromisoformat(tasting_date)
                    except ValueError:
                        tasting_date = date.today()

                db_tasting = CocktailTastingModel(
                    cocktail_id=cocktail.id,
                    recipe_name=cocktail.name,
                    taster_name=tasting.taster_name,
                    tasting_date=tasting_date,
                    score=tasting.score,
                    notes=tasting.notes,
                    bartender=tasting.bartender,
                )
                db.add(db_tasting)
                db.flush()

                for bu in tasting.bottles_used:
                    db_bu = CocktailTastingIngredientModel(
                        cocktail_tasting_id=db_tasting.id,
                        recipe_ingredient=bu.recipe_ingredient,
                        actual_product=bu.actual_product,
                    )
                    db.add(db_bu)

                stats["cocktail_tastings"] += 1

            except Exception as e:
                stats["errors"].append(f"Cocktail tasting for {cocktail.name}: {e}")
                logger.error(f"  Error importing cocktail tasting: {e}")


if __name__ == "__main__":
    main()
