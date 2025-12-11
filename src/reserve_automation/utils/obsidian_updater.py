"""Update Obsidian markdown frontmatter fields."""

import logging
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class ObsidianUpdater:
    """Update Obsidian vault markdown files."""

    def __init__(self, vault_path: Path):
        """
        Initialize updater.

        Args:
            vault_path: Path to Obsidian vault root
        """
        self.vault_path = Path(vault_path)

    def update_label_field(
        self, md_file_path: Path, label_relative_path: str
    ) -> bool:
        """
        Update Label field in bottle markdown file.

        Args:
            md_file_path: Path to bottle markdown file
            label_relative_path: Relative path to label image (e.g., "labels/label.jpg")

        Returns:
            True if update succeeded, False otherwise
        """
        try:
            if not md_file_path.exists():
                logger.error(f"Markdown file not found: {md_file_path}")
                return False

            # Read file
            content = md_file_path.read_text(encoding="utf-8")

            # Parse frontmatter
            frontmatter, body = self.parse_frontmatter(content)

            if frontmatter is None:
                logger.error(f"No frontmatter found in {md_file_path}")
                return False

            # Update Label field
            frontmatter["Label"] = label_relative_path

            # Write back
            success = self.write_frontmatter(md_file_path, frontmatter, body)

            if success:
                logger.info(f"Updated Label field: {md_file_path.name}")

            return success

        except Exception as e:
            logger.error(f"Failed to update Label field in {md_file_path}: {e}")
            return False

    def parse_frontmatter(self, content: str) -> Tuple[Optional[Dict[str, str]], str]:
        """
        Parse YAML frontmatter from markdown content.

        Args:
            content: Full markdown file content

        Returns:
            Tuple of (frontmatter_dict, body_content)
            Returns (None, content) if no frontmatter found
        """
        try:
            # Match frontmatter block
            match = re.search(
                r"^---\n(.*?)\n---\n(.*)", content, re.DOTALL | re.MULTILINE
            )

            if not match:
                logger.warning("No frontmatter block found")
                return None, content

            frontmatter_text = match.group(1)
            body = match.group(2)

            # Parse YAML-like frontmatter
            frontmatter = {}
            for line in frontmatter_text.split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    key = key.strip()
                    value = value.strip()

                    # Preserve empty values
                    if value in ['""', "''", "--", ""]:
                        value = ""
                    elif value.startswith('"') and value.endswith('"'):
                        # Remove quotes
                        value = value[1:-1]

                    frontmatter[key] = value

            return frontmatter, body

        except Exception as e:
            logger.error(f"Frontmatter parsing error: {e}")
            return None, content

    def write_frontmatter(
        self, md_file_path: Path, frontmatter: Dict[str, str], body: str
    ) -> bool:
        """
        Write frontmatter and body back to markdown file.

        Args:
            md_file_path: Path to markdown file
            frontmatter: Frontmatter dictionary
            body: Body content

        Returns:
            True if write succeeded
        """
        try:
            # Build frontmatter block
            lines = ["---"]

            for key, value in frontmatter.items():
                # Format value
                if value == "" or value is None:
                    formatted_value = ""
                elif isinstance(value, str) and (" " in value or "-" in value):
                    # Quote values with spaces or dashes
                    formatted_value = f'"{value}"'
                else:
                    formatted_value = str(value)

                lines.append(f"{key}: {formatted_value}")

            lines.append("---")

            # Combine frontmatter and body
            content = "\n".join(lines) + "\n" + body

            # Write to file
            md_file_path.write_text(content, encoding="utf-8")

            return True

        except Exception as e:
            logger.error(f"Failed to write frontmatter to {md_file_path}: {e}")
            return False

    def get_bottle_file_path(self, bottle_folder: Path) -> Optional[Path]:
        """
        Get the main bottle markdown file in a bottle folder.

        Args:
            bottle_folder: Path to bottle folder

        Returns:
            Path to bottle.md file, or None if not found
        """
        # Expected pattern: FolderName/FolderName.md
        bottle_file = bottle_folder / f"{bottle_folder.name}.md"

        if bottle_file.exists():
            return bottle_file

        logger.warning(f"Bottle file not found: {bottle_file}")
        return None
