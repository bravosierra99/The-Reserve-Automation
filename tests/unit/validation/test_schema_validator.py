"""Unit tests for validation/schema_validator.py.

Exercises FileClass parsing and the schema cross-checks against an isolated
tmp vault + tmp project tree — never the real Obsidian vault.
"""

from pathlib import Path

import pytest

from reserve_automation.validation.schema_validator import (
    FieldDefinition,
    FileClassParser,
    SchemaValidator,
)

# A Tasting FileClass with four 0..10 whiskey score fields plus a text field.
TASTING_FILECLASS = """---
fields:
  - name: Nose
    type: Number
    id: nose
    options:
      min: 0
      max: 10
      step: 0.5
      formula: "sum / n"
  - name: Palate
    type: Number
    id: palate
    options:
      min: 0
      max: 10
  - name: Finish
    type: Number
    id: finish
    options:
      min: 0
      max: 10
  - name: Overall
    type: Number
    id: overall
    options:
      min: 0
      max: 10
  - name: Notes
    type: Input
    id: notes
---
Body text, ignored by the parser.
"""

MODEL_OK = """from pydantic import BaseModel, Field


class TastingNote(BaseModel):
    whiskey_nose: float = Field(ge=0, le=10)
    whiskey_palate: float = Field(ge=0, le=10)
    whiskey_finish: float = Field(ge=0, le=10)
    whiskey_overall: float = Field(ge=0, le=10)
"""

TEMPLATE_OK = "Nose Palate Finish Overall Notes — all field names present.\n"

FORM_OK = """
<input x-model="tasting.whiskey_nose" max="10">
<input x-model="tasting.whiskey_palate" max="10">
<input x-model="tasting.whiskey_finish" max="10">
<input x-model="tasting.whiskey_overall" max="10">
"""


def _write_fileclass(vault: Path, content: str, name: str = "Tasting") -> None:
    d = vault / "8_FileClass"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(content)


# --------------------------------------------------------------------------- #
# FileClassParser
# --------------------------------------------------------------------------- #
class TestFileClassParser:
    def test_parses_fields_and_options(self, tmp_path):
        _write_fileclass(tmp_path, TASTING_FILECLASS)
        fields = FileClassParser(tmp_path).parse_fileclass("Tasting")

        assert [f.name for f in fields] == ["Nose", "Palate", "Finish", "Overall", "Notes"]
        by_name = {f.name: f for f in fields}

        nose = by_name["Nose"]
        assert isinstance(nose, FieldDefinition)
        assert nose.type == "Number" and nose.id == "nose"
        assert nose.min_value == 0 and nose.max_value == 10
        assert nose.step == 0.5 and nose.formula == "sum / n"

        # A field with no options leaves the numeric attributes as None.
        notes = by_name["Notes"]
        assert notes.type == "Input"
        assert notes.min_value is None and notes.max_value is None and notes.step is None

    def test_missing_fileclass_raises(self, tmp_path):
        (tmp_path / "8_FileClass").mkdir()
        with pytest.raises(FileNotFoundError, match="FileClass not found"):
            FileClassParser(tmp_path).parse_fileclass("DoesNotExist")

    def test_no_frontmatter_raises(self, tmp_path):
        _write_fileclass(tmp_path, "no frontmatter here\njust text\n")
        with pytest.raises(ValueError, match="No frontmatter"):
            FileClassParser(tmp_path).parse_fileclass("Tasting")

    def test_no_fields_returns_empty_list(self, tmp_path):
        _write_fileclass(tmp_path, "---\ntitle: Tasting\n---\nbody\n")
        assert FileClassParser(tmp_path).parse_fileclass("Tasting") == []


# --------------------------------------------------------------------------- #
# SchemaValidator
# --------------------------------------------------------------------------- #
@pytest.fixture
def project_env(tmp_path):
    """Build an isolated vault + project tree that all match the FileClass.

    Returns (vault_path, project_root). Individual tests overwrite a single
    file to create a mismatch.
    """
    vault = tmp_path / "vault"
    root = tmp_path / "project"
    _write_fileclass(vault, TASTING_FILECLASS)

    core = root / "src" / "reserve_automation" / "core"
    core.mkdir(parents=True)
    (core / "tasting_note.py").write_text(MODEL_OK)

    (root / "templates").mkdir(parents=True)
    (root / "templates" / "tasting_whiskey.md.jinja").write_text(TEMPLATE_OK)

    webt = root / "src" / "reserve_automation" / "web" / "templates"
    webt.mkdir(parents=True)
    (webt / "review.html").write_text(FORM_OK)

    return vault, root


class TestSchemaValidator:
    def test_tasting_model_matches_has_no_issues(self, project_env):
        vault, root = project_env
        assert SchemaValidator(vault, root).validate_tasting_model() == []

    def test_tasting_model_max_mismatch_reported(self, project_env):
        vault, root = project_env
        # FileClass says max=5 for the score fields, Python model says le=10.
        _write_fileclass(vault, TASTING_FILECLASS.replace("max: 10", "max: 5"))
        issues = SchemaValidator(vault, root).validate_tasting_model()
        assert any("max value mismatch" in i for i in issues)
        assert any("whiskey_nose" in i for i in issues)

    def test_tasting_model_missing_field_reported(self, project_env):
        vault, root = project_env
        (root / "src" / "reserve_automation" / "core" / "tasting_note.py").write_text(
            "class TastingNote:\n    pass\n"
        )
        issues = SchemaValidator(vault, root).validate_tasting_model()
        assert any("Missing field in Python model" in i for i in issues)

    def test_jinja_template_missing_returns_not_found(self, project_env):
        vault, root = project_env
        issues = SchemaValidator(vault, root).validate_jinja_template("no_such_template")
        assert len(issues) == 1 and "Template not found" in issues[0]

    def test_jinja_template_present_all_fields_ok(self, project_env):
        vault, root = project_env
        assert SchemaValidator(vault, root).validate_jinja_template("tasting_whiskey.md") == []

    def test_web_form_matching_max_ok(self, project_env):
        vault, root = project_env
        assert SchemaValidator(vault, root).validate_web_form() == []

    def test_tasting_model_min_mismatch_reported(self, project_env):
        vault, root = project_env
        # FileClass min becomes 1 while the Python model keeps ge=0.
        _write_fileclass(vault, TASTING_FILECLASS.replace("min: 0", "min: 1"))
        issues = SchemaValidator(vault, root).validate_tasting_model()
        assert any("min value mismatch" in i for i in issues)

    def test_jinja_template_missing_field_reported(self, project_env):
        vault, root = project_env
        # Template omits the "Nose" field name.
        (root / "templates" / "tasting_whiskey.md.jinja").write_text(
            "Palate Finish Overall Notes\n"
        )
        issues = SchemaValidator(vault, root).validate_jinja_template("tasting_whiskey.md")
        assert any("missing field: Nose" in i for i in issues)

    def test_web_form_missing_field_reported(self, project_env):
        vault, root = project_env
        webform = root / "src" / "reserve_automation" / "web" / "templates" / "review.html"
        webform.write_text('<input x-model="tasting.whiskey_palate" max="10">\n')
        issues = SchemaValidator(vault, root).validate_web_form()
        assert any("Web form missing field: whiskey_nose" in i for i in issues)

    def test_validate_all_returns_three_components(self, project_env):
        vault, root = project_env
        results = SchemaValidator(vault, root).validate_all()
        assert set(results) == {"python_model", "jinja_template", "web_form"}
        assert all(v == [] for v in results.values())
