"""Validate that code matches Obsidian FileClass definitions.

This ensures the single source of truth (Obsidian FileClass) is reflected across:
- Python Pydantic models
- Jinja templates
- Web forms
- LLM extraction prompts
"""

import re
import yaml
from pathlib import Path
from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class FieldDefinition:
    """Parsed field from Obsidian FileClass."""
    name: str
    type: str
    id: str
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    formula: Optional[str] = None


class FileClassParser:
    """Parse Obsidian FileClass definitions."""

    def __init__(self, vault_path: Path):
        self.vault_path = Path(vault_path)
        self.fileclass_dir = vault_path / "8_FileClass"

    def parse_fileclass(self, name: str) -> list[FieldDefinition]:
        """
        Parse a FileClass definition file.

        Args:
            name: FileClass name (e.g., "Tasting", "Whiskey")

        Returns:
            List of field definitions
        """
        file_path = self.fileclass_dir / f"{name}.md"

        if not file_path.exists():
            raise FileNotFoundError(f"FileClass not found: {file_path}")

        with open(file_path, 'r') as f:
            content = f.read()

        # Extract YAML frontmatter
        match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
        if not match:
            raise ValueError(f"No frontmatter found in {file_path}")

        frontmatter = yaml.safe_load(match.group(1))

        # Parse fields
        fields = []
        for field_data in frontmatter.get('fields', []):
            field = FieldDefinition(
                name=field_data['name'],
                type=field_data['type'],
                id=field_data['id'],
            )

            # Parse options
            options = field_data.get('options', {})
            if 'min' in options:
                field.min_value = options['min']
            if 'max' in options:
                field.max_value = options['max']
            if 'step' in options:
                field.step = options['step']
            if 'formula' in options:
                field.formula = options['formula']

            fields.append(field)

        return fields


class SchemaValidator:
    """Validate code against FileClass schemas."""

    def __init__(self, vault_path: Path, project_root: Path):
        self.vault_path = Path(vault_path)
        self.project_root = Path(project_root)
        self.parser = FileClassParser(vault_path)

    def validate_tasting_model(self) -> list[str]:
        """Validate TastingNote model matches FileClass definition."""
        issues = []

        # Parse FileClass
        fields = self.parser.parse_fileclass("Tasting")
        field_map = {f.name: f for f in fields}

        # Check Python model
        model_path = self.project_root / "src" / "reserve_automation" / "core" / "tasting_note.py"
        with open(model_path, 'r') as f:
            model_code = f.read()

        # Check whiskey score fields
        for field_name in ['Nose', 'Palate', 'Finish', 'Overall']:
            if field_name not in field_map:
                continue

            field_def = field_map[field_name]
            python_field_name = f"whiskey_{field_name.lower()}"

            # Check field exists
            if python_field_name not in model_code:
                issues.append(f"Missing field in Python model: {python_field_name}")
                continue

            # Extract field definition from code
            pattern = rf'{python_field_name}:.*?ge=(\d+(?:\.\d+)?),\s*le=(\d+(?:\.\d+)?)'
            match = re.search(pattern, model_code)

            if match:
                ge_value = float(match.group(1))
                le_value = float(match.group(2))

                if ge_value != field_def.min_value:
                    issues.append(
                        f"Field {python_field_name}: min value mismatch. "
                        f"FileClass={field_def.min_value}, Python={ge_value}"
                    )

                if le_value != field_def.max_value:
                    issues.append(
                        f"Field {python_field_name}: max value mismatch. "
                        f"FileClass={field_def.max_value}, Python={le_value}"
                    )

        return issues

    def validate_jinja_template(self, template_name: str) -> list[str]:
        """Validate Jinja template uses correct field names."""
        issues = []

        # Parse FileClass
        fields = self.parser.parse_fileclass("Tasting")
        field_map = {f.name: f for f in fields}

        # Check template
        template_path = self.project_root / "templates" / f"{template_name}.jinja"
        if not template_path.exists():
            return [f"Template not found: {template_path}"]

        with open(template_path, 'r') as f:
            template_code = f.read()

        # Check frontmatter references correct field names
        for field_name in field_map.keys():
            if field_name not in template_code:
                issues.append(f"Template missing field: {field_name}")

        return issues

    def validate_web_form(self) -> list[str]:
        """Validate web form has correct fields."""
        issues = []

        # Parse FileClass
        fields = self.parser.parse_fileclass("Tasting")
        field_map = {f.name: f for f in fields}

        # Check review.html
        form_path = self.project_root / "src" / "reserve_automation" / "web" / "templates" / "review.html"
        with open(form_path, 'r') as f:
            form_code = f.read()

        # Check whiskey score fields
        for field_name in ['Nose', 'Palate', 'Finish', 'Overall']:
            if field_name not in field_map:
                continue

            field_def = field_map[field_name]
            python_field_name = f"whiskey_{field_name.lower()}"

            # Check field exists in form
            if python_field_name not in form_code:
                issues.append(f"Web form missing field: {python_field_name}")
                continue

            # Check max attribute
            pattern = rf'x-model="tasting\.{python_field_name}"[^>]*max="(\d+(?:\.\d+)?)"'
            match = re.search(pattern, form_code)

            if match:
                max_value = float(match.group(1))
                if max_value != field_def.max_value:
                    issues.append(
                        f"Web form field {python_field_name}: max mismatch. "
                        f"FileClass={field_def.max_value}, HTML={max_value}"
                    )

        return issues

    def validate_all(self) -> dict[str, list[str]]:
        """Run all validations."""
        return {
            "python_model": self.validate_tasting_model(),
            "jinja_template": self.validate_jinja_template("tasting_whiskey.md"),
            "web_form": self.validate_web_form(),
        }

    def print_report(self):
        """Print validation report."""
        results = self.validate_all()

        has_issues = any(issues for issues in results.values())

        if not has_issues:
            print("✅ All validations passed! Code matches FileClass definitions.")
            return True

        print("❌ Schema validation failed:\n")

        for component, issues in results.items():
            if issues:
                print(f"{component}:")
                for issue in issues:
                    print(f"  - {issue}")
                print()

        return False


def main():
    """CLI entry point for validation."""
    import sys
    from reserve_automation.core.config import Config

    config = Config.load()
    project_root = Path(__file__).parent.parent.parent.parent

    validator = SchemaValidator(
        vault_path=config.vault_path,
        project_root=project_root
    )

    success = validator.print_report()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
