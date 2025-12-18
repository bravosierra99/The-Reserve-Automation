"""Obsidian markdown file generator.

CRITICAL TEMPLATE REQUIREMENTS (see CLAUDE.md for full details):
- Templates MUST start with '---' on line 1 (Obsidian frontmatter delimiter)
- DO NOT add #CLAUDE_REQ comments to templates - they'll appear in generated files
- Label images MUST use Obsidian embed syntax: ![[labels/label.jpg]]
- fileClass values MUST match exactly what DataviewJS queries expect
- Field names MUST match Obsidian fileClass definitions
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, TemplateNotFound

from ..core.exceptions import GenerationError
from ..core.models import BottleMetadata
from ..utils.logging import logger


class ObsidianFile:
    """Generated Obsidian markdown file."""

    def __init__(self, file_path: Path, content: str, bottle: BottleMetadata):
        """
        Initialize Obsidian file.

        Args:
            file_path: Path where file will be written
            content: Markdown content
            bottle: Source bottle metadata
        """
        self.file_path = file_path
        self.content = content
        self.bottle = bottle


class ObsidianGenerator:
    """
    Generate Obsidian markdown files from bottle metadata.

    Creates structured markdown files compatible with the Obsidian vault
    format, including frontmatter, dataview queries, and proper folder
    organization.
    """

    def __init__(self, vault_path: Path, template_dir: Path):
        """
        Initialize Obsidian generator.

        Args:
            vault_path: Path to Obsidian vault
            template_dir: Path to Jinja2 templates directory

        Raises:
            GenerationError: If paths don't exist or templates can't be loaded
        """
        self.vault_path = Path(vault_path)
        self.template_dir = Path(template_dir)

        # Validate paths
        if not self.vault_path.exists():
            raise GenerationError(f"Vault path does not exist: {self.vault_path}")

        if not self.template_dir.exists():
            raise GenerationError(f"Template directory does not exist: {self.template_dir}")

        # Initialize Jinja2 environment
        try:
            self.env = Environment(
                loader=FileSystemLoader(str(self.template_dir)),
                keep_trailing_newline=True,
            )
        except Exception as e:
            raise GenerationError(f"Failed to initialize Jinja2 environment: {e}") from e

        logger.debug(f"ObsidianGenerator initialized with vault: {self.vault_path}")

    def generate_bottle_file(self, bottle: BottleMetadata) -> ObsidianFile:
        """
        Generate markdown file for a bottle.

        Args:
            bottle: Bottle metadata to generate file for

        Returns:
            ObsidianFile with path and content

        Raises:
            GenerationError: If file generation fails
        """
        try:
            # Determine subdirectory based on type
            subdir_map = {
                "wine": "1_Wines",
                "whiskey": "1_Whiskeys",
                "vodka": "1_Spirits",
                "gin": "1_Spirits",
                "rum": "1_Spirits",
                "tequila": "1_Spirits",
                "brandy": "1_Spirits",
                "other": "1_Spirits",
            }
            subdir = subdir_map.get(bottle.type, "1_Spirits")

            # Generate filename
            filename = self._generate_filename(bottle)

            # Construct full path (bottles are in subdirectories)
            # Format: vault_path/1_Wines/Producer - Name - Year/Producer - Name - Year.md
            folder_path = self.vault_path / subdir / filename
            file_path = folder_path / f"{filename}.md"

            # Render template
            content = self._render_template(bottle)

            logger.info(f"Generated file for {bottle.producer} - {bottle.name}")

            return ObsidianFile(
                file_path=file_path,
                content=content,
                bottle=bottle,
            )

        except Exception as e:
            logger.error(f"Failed to generate file for {bottle.producer} - {bottle.name}: {e}")
            raise GenerationError(f"Failed to generate bottle file: {e}") from e

    def _generate_filename(self, bottle: BottleMetadata) -> str:
        """
        Generate Obsidian-safe filename.

        Format: Producer - Name - Year
        For NV (non-vintage) wines, omits year.

        Args:
            bottle: Bottle metadata

        Returns:
            Sanitized filename without extension
        """
        parts = [bottle.producer, bottle.name]

        if bottle.year:
            parts.append(str(bottle.year))

        filename = " - ".join(parts)
        return self._sanitize_filename(filename)

    def _sanitize_filename(self, name: str) -> str:
        """
        Remove/replace invalid filename characters.

        Makes filename safe for Obsidian and cross-platform filesystems.

        Args:
            name: Raw filename

        Returns:
            Sanitized filename
        """
        # Remove invalid characters: < > : " / \ | ? *
        name = re.sub(r'[<>:"/\\|?*]', '', name)

        # Collapse multiple spaces
        name = re.sub(r'\s+', ' ', name)

        # Remove leading/trailing whitespace
        return name.strip()

    def _render_template(self, bottle: BottleMetadata) -> str:
        """
        Render Jinja2 template for bottle.

        Args:
            bottle: Bottle metadata

        Returns:
            Rendered markdown content

        Raises:
            GenerationError: If template rendering fails
        """
        try:
            # Choose template based on bottle type
            # Wine uses wine template, everything else uses whiskey/spirits template
            if bottle.type == "wine":
                template_name = "wine.md.j2"
            else:
                # All spirits (whiskey, vodka, gin, rum, etc.) use the whiskey template
                # TODO: Consider creating spirit-specific templates if needed
                template_name = "whiskey.md.j2"

            # Load template
            try:
                template = self.env.get_template(template_name)
            except TemplateNotFound:
                raise GenerationError(f"Template not found: {template_name}")

            # Prepare template context
            context = self._prepare_context(bottle)

            # Render
            content = template.render(**context)

            return content

        except Exception as e:
            raise GenerationError(f"Template rendering failed: {e}") from e

    def _prepare_context(self, bottle: BottleMetadata) -> dict:
        """
        Prepare Jinja2 template context from bottle metadata.

        Args:
            bottle: Bottle metadata

        Returns:
            Dictionary of template variables
        """
        # Full bottle name for frontmatter
        name_parts = [bottle.producer, bottle.name]
        if bottle.year:
            name_parts.append(str(bottle.year))
        full_name = " - ".join(name_parts)

        # Wine-specific or whiskey-specific name
        if bottle.type == "wine":
            wine_name = bottle.name
            whiskey_name = None
        else:
            wine_name = None
            whiskey_name = bottle.name

        context = {
            # Common fields
            "name": full_name,
            "producer": bottle.producer,
            "wine_name": wine_name,
            "whiskey_name": whiskey_name,
            "year": bottle.year,
            "beverage_type": bottle.beverage_type,
            "country": bottle.country,
            "region": bottle.region,
            "price": bottle.price,
            "notes": bottle.notes,
            # Purchase and inventory
            "purchase_source": bottle.purchase_source,
            "inventory": bottle.inventory,
            # Wine-specific
            "variety": bottle.variety,
            "vineyard": bottle.vineyard,
            # Whiskey-specific
            "age_statement": bottle.age_statement,
            "proof": bottle.proof,
            "mash_bill": bottle.mash_bill,
            "barrel_type": bottle.barrel_type,
        }

        return context

    def write_file(self, obsidian_file: ObsidianFile, dry_run: bool = False) -> None:
        """
        Write Obsidian file to vault.

        Creates parent directories if needed.

        Args:
            obsidian_file: File to write
            dry_run: If True, don't actually write file

        Raises:
            GenerationError: If file writing fails
        """
        try:
            if dry_run:
                logger.info(f"[DRY RUN] Would create: {obsidian_file.file_path}")
                return

            # Create parent directory
            obsidian_file.file_path.parent.mkdir(parents=True, exist_ok=True)

            # Write file
            obsidian_file.file_path.write_text(obsidian_file.content, encoding="utf-8")

            logger.info(f"Created file: {obsidian_file.file_path}")

        except Exception as e:
            logger.error(f"Failed to write file {obsidian_file.file_path}: {e}")
            raise GenerationError(f"Failed to write file: {e}") from e

    def generate_batch(
        self, bottles: list[BottleMetadata], dry_run: bool = False
    ) -> list[ObsidianFile]:
        """
        Generate files for multiple bottles.

        Args:
            bottles: List of bottles to generate files for
            dry_run: If True, don't actually write files

        Returns:
            List of generated ObsidianFile objects

        Raises:
            GenerationError: If batch generation fails
        """
        generated = []
        errors = []

        for bottle in bottles:
            try:
                obsidian_file = self.generate_bottle_file(bottle)
                self.write_file(obsidian_file, dry_run=dry_run)
                generated.append(obsidian_file)

            except Exception as e:
                error_msg = f"{bottle.producer} - {bottle.name}: {e}"
                errors.append(error_msg)
                logger.warning(f"Skipping bottle due to error: {error_msg}")

        # Log summary
        logger.info(
            f"Generated {len(generated)} files "
            f"({len(errors)} errors)"
        )

        if errors:
            logger.warning(f"Errors during generation:\n" + "\n".join(f"  - {e}" for e in errors))

        return generated
