"""Unit tests for utils/markdown_to_slack.py (Markdown -> Slack mrkdwn).

Loaded by file path so the test never imports the ``utils`` package or the
repo-root ``__init__.py`` (the ComfyUI entry point, whose relative imports only
work inside a running ComfyUI).
"""

import importlib.util
import os

import pytest

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils", "markdown_to_slack.py")
_spec = importlib.util.spec_from_file_location("markdown_to_slack_under_test", _PATH)
markdown_to_slack = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(markdown_to_slack)

markdown_to_mrkdwn = markdown_to_slack.markdown_to_mrkdwn


@pytest.mark.parametrize("src, want", [
    ("**bold**", "*bold*"),
    ("__bold__", "*bold*"),
    ("*italic*", "_italic_"),
    ("_italic_", "_italic_"),
    ("~~strike~~", "~strike~"),
    ("[text](https://example.com)", "<https://example.com|text>"),
    ("![alt](https://img.png)", "<https://img.png|alt>"),
    ("# Heading", "*Heading*"),
    ("### Sub head ###", "*Sub head*"),
    ("**bold _and italic_**", "*bold _and italic_*"),
    ("- a\n- b", "• a\n• b"),
    ("* a\n+ b", "• a\n• b"),
])
def test_basic_conversions(src, want):
    assert markdown_to_mrkdwn(src) == want


def test_indented_bullet_keeps_indentation():
    assert markdown_to_mrkdwn("  - nested") == "  • nested"


def test_inline_code_is_preserved_verbatim():
    # Markup inside a code span must not be converted.
    assert markdown_to_mrkdwn("use `**not bold**` here") == "use `**not bold**` here"


def test_fenced_block_is_preserved_verbatim():
    src = "a\n```\n**raw** _x_\n```\nb **bold**"
    assert markdown_to_mrkdwn(src) == "a\n```\n**raw** _x_\n```\nb *bold*"


def test_empty_string_passthrough():
    assert markdown_to_mrkdwn("") == ""


def test_plain_text_unchanged():
    assert markdown_to_mrkdwn("just a normal sentence.") == "just a normal sentence."
