"""Tests for the wine/whiskey extraction prompt ``Unknown`` placeholder rule.

When the LLM cannot determine a REQUIRED field (producer, name, type) but
there IS bottle-related text on the page, it must emit ``Unknown`` rather
than returning an empty array. This rule is enforced via prompt copy in
``src/reserve_automation/llm/prompts/extraction.py`` and is the only thing
keeping unparseable-but-present bottles from being silently dropped.

Both the wine prompt (``beverage_type="wine"``) and the whiskey prompt
(``beverage_type="whiskey"``) carry this rule.
"""

import re

import pytest

from reserve_automation.llm.prompts.extraction import build_extraction_prompt


SAMPLE_TEXT_WINE = "2019 Caymus Cabernet Sauvignon Napa Valley $85"
SAMPLE_TEXT_WHISKEY = "Buffalo Trace Bourbon 90 Proof Kentucky $25"


# ---------------------------------------------------------------------------
# Wine prompt
# ---------------------------------------------------------------------------


class TestWinePromptUnknownPlaceholder:
    """The wine prompt must instruct the LLM to use ``Unknown`` instead of dropping bottles."""

    @pytest.fixture
    def prompt(self):
        return build_extraction_prompt(SAMPLE_TEXT_WINE, beverage_type="wine")

    def test_mentions_unknown_placeholder(self, prompt):
        # Match the actual wording — Unicode em-dash, "Unknown" placeholder
        assert '"Unknown" as a placeholder' in prompt

    def test_forbids_empty_array_when_wine_text_present(self, prompt):
        # Two requirements packed into one bullet — verify both halves
        assert "NEVER return an empty array" in prompt
        assert "wine-related text" in prompt

    def test_required_fields_are_named(self, prompt):
        # "REQUIRED FIELDS (producer, name, type)" — the full triple
        assert re.search(r"REQUIRED FIELDS\s*\(producer,\s*name,\s*type\)", prompt)

    def test_rule_is_in_a_single_logical_bullet(self, prompt):
        """The placeholder rule and the no-empty-array rule must live together
        so the LLM can't satisfy one without considering the other."""
        # Find the line containing "Unknown" placeholder
        for line in prompt.splitlines():
            if '"Unknown" as a placeholder' in line:
                # That same line must also forbid the empty array
                assert "NEVER return an empty array" in line, (
                    "Placeholder rule and empty-array rule must be in the same bullet"
                )
                return
        pytest.fail('No bullet found containing \'"Unknown" as a placeholder\'')

    def test_includes_input_text(self, prompt):
        assert SAMPLE_TEXT_WINE in prompt


# ---------------------------------------------------------------------------
# Whiskey prompt
# ---------------------------------------------------------------------------


class TestWhiskeyPromptUnknownPlaceholder:
    """Same rule, whiskey prompt."""

    @pytest.fixture
    def prompt(self):
        return build_extraction_prompt(SAMPLE_TEXT_WHISKEY, beverage_type="whiskey")

    def test_mentions_unknown_placeholder(self, prompt):
        assert '"Unknown" as a placeholder' in prompt

    def test_forbids_empty_array_when_whiskey_text_present(self, prompt):
        assert "NEVER return an empty array" in prompt
        assert "whiskey-related text" in prompt

    def test_required_fields_are_named(self, prompt):
        assert re.search(r"REQUIRED FIELDS\s*\(producer,\s*name,\s*type\)", prompt)

    def test_rule_is_in_a_single_logical_bullet(self, prompt):
        for line in prompt.splitlines():
            if '"Unknown" as a placeholder' in line:
                assert "NEVER return an empty array" in line
                return
        pytest.fail('No bullet found containing \'"Unknown" as a placeholder\'')

    def test_includes_input_text(self, prompt):
        assert SAMPLE_TEXT_WHISKEY in prompt


# ---------------------------------------------------------------------------
# Auto prompt — has its own (stricter) rule and should NOT use the placeholder
# ---------------------------------------------------------------------------


class TestAutoPromptDoesNotUsePlaceholderRule:
    """The auto-mode prompt uses a different rule — it skips the bottle entirely.

    We pin this so a future refactor that unifies the rules has to make a
    deliberate decision rather than silently changing semantics.
    """

    def test_auto_prompt_says_skip_rather_than_unknown(self):
        prompt = build_extraction_prompt(
            "mixed text", beverage_type="auto"
        )
        # Auto branch tells the LLM to skip the bottle entirely
        assert "skip that bottle entirely" in prompt
        # And does NOT include the wine/whiskey "Unknown" placeholder rule
        assert '"Unknown" as a placeholder' not in prompt


# ---------------------------------------------------------------------------
# Cross-cutting: required field list is consistent across prompts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("beverage_type", ["wine", "whiskey"])
def test_required_field_triple_consistent(beverage_type):
    """Both prompts must list the same required-field triple in the same order."""
    prompt = build_extraction_prompt("sample", beverage_type=beverage_type)
    assert "(producer, name, type)" in prompt
