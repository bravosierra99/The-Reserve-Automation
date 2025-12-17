"""Generate tasting markdown files in the vault."""

import logging
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..core.tasting_note import TastingNote
from ..utils.bottle_matcher import BottleMatch

logger = logging.getLogger(__name__)


class TastingGenerator:
    """Generate tasting markdown files from TastingNote objects."""

    def __init__(self, vault_path: Path, templates_path: Path):
        self.vault_path = Path(vault_path)
        self.templates_path = Path(templates_path)

        # Set up Jinja2 environment
        self.jinja_env = Environment(
            loader=FileSystemLoader(self.templates_path),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def generate_tasting_file(
        self,
        tasting: TastingNote,
        bottle_match: BottleMatch,
        dry_run: bool = False,
    ) -> Path:
        """
        Generate a tasting markdown file for a matched bottle.

        Args:
            tasting: TastingNote to generate file for
            bottle_match: Matched bottle from vault
            dry_run: If True, don't write file (just return path)

        Returns:
            Path to generated tasting file
        """
        # Get template based on beverage type
        if tasting.beverage_type == "wine":
            template = self.jinja_env.get_template("tasting_wine.md.jinja")
        else:
            template = self.jinja_env.get_template("tasting_whiskey.md.jinja")

        # Prepare template context
        context = self._prepare_context(tasting, bottle_match)

        # Render template
        content = template.render(**context)

        # Determine output path
        output_path = self._get_tasting_file_path(tasting, bottle_match)

        if dry_run:
            logger.info(f"[DRY RUN] Would create: {output_path}")
            return output_path

        # Write file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")

        logger.info(f"Created tasting file: {output_path}")
        return output_path

    def _prepare_context(self, tasting: TastingNote, bottle_match: BottleMatch) -> dict:
        """Prepare Jinja2 template context from tasting note."""
        # Use the matched bottle's folder name for LinkedBottle field
        bottle_name = bottle_match.folder_path.name

        context = {
            "tasting_date": tasting.tasting_date.isoformat(),
            "taster_name": tasting.taster_name,
            "bottle_name": bottle_name,
            "nose_notes": tasting.nose_notes or [],
            "palate_notes": tasting.palate_notes or [],
            "finish_notes": tasting.finish_notes or [],
            "overall_notes": tasting.overall_notes,
        }

        # Add type-specific fields
        if tasting.beverage_type == "wine":
            # Calculate AWS Score (sum of all component scores, max 20 points)
            # Appearance: /3, Aroma: /6, Taste: /6, Aftertaste: /3, Overall: /2
            aws_score = (
                (tasting.wine_appearance or 0) +
                (tasting.wine_aroma or 0) +
                (tasting.wine_taste or 0) +
                (tasting.wine_aftertaste or 0) +
                (tasting.wine_overall or 0)
            )

            # Calculate 100-point scale: 50 + (AWS_Score / 20) * 50
            # This maps 0-20 AWS scale to 50-100 point scale
            scale_100pt = round(50 + (aws_score / 20) * 50, 1)

            context.update({
                "wine_appearance": tasting.wine_appearance,
                "wine_aroma": tasting.wine_aroma,
                "wine_taste": tasting.wine_taste,
                "wine_aftertaste": tasting.wine_aftertaste,
                "wine_overall": tasting.wine_overall,
                "aws_score": aws_score,
                "scale_100pt": scale_100pt,
                "appearance_notes": [],  # User adds freeform notes in Obsidian
            })
        else:  # whiskey
            context.update({
                "whiskey_nose": tasting.whiskey_nose,
                "whiskey_palate": tasting.whiskey_palate,
                "whiskey_finish": tasting.whiskey_finish,
                "whiskey_overall": tasting.whiskey_overall,
                "days_from_crack": tasting.days_from_crack,
                "fill_level": tasting.fill_level,
            })

        return context

    def _get_tasting_file_path(self, tasting: TastingNote, bottle_match: BottleMatch) -> Path:
        """
        Determine output path for tasting file.

        Format: {bottle_folder}/Tasting-{YYYY-MM-DD}-{TasterName}.md
        """
        filename = f"Tasting-{tasting.tasting_date.isoformat()}-{tasting.taster_name}.md"
        return bottle_match.folder_path / filename

    def generate_batch(
        self,
        tastings: list[tuple[TastingNote, BottleMatch]],
        dry_run: bool = False,
    ) -> list[Path]:
        """
        Generate tasting files for multiple tastings.

        Args:
            tastings: List of (TastingNote, BottleMatch) tuples
            dry_run: If True, don't write files

        Returns:
            List of paths to generated files
        """
        paths = []
        for tasting, bottle_match in tastings:
            try:
                path = self.generate_tasting_file(tasting, bottle_match, dry_run=dry_run)
                paths.append(path)
            except Exception as e:
                logger.error(f"Failed to generate tasting for {tasting.bottle_name}: {e}")
                continue

        logger.info(f"Generated {len(paths)} tasting files")
        return paths
