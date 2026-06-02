"""Translate standard Markdown into Slack's ``mrkdwn`` flavor.

Slack messages use a reduced, idiosyncratic markup ("mrkdwn") that differs from
CommonMark: bold is ``*one asterisk*``, italic is ``_underscore_``,
strikethrough is ``~one tilde~``, links are ``<url|text>``, and there are no
headings. This module rewrites the common Markdown a user is likely to type in
the Send Text node into the equivalent mrkdwn so it renders as intended.

It is intentionally best-effort and regex-based — Slack already accepts backtick
code spans/blocks and ``>`` blockquotes verbatim, so those are preserved as-is.
"""

import re

# Placeholders for stashed code spans/blocks. The NUL-ish sentinels are very
# unlikely to occur in user text, so they survive the other substitutions.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")

_HEADING_RE = re.compile(r"^[ \t]*#{1,6}[ \t]+(.*?)[ \t]*#*[ \t]*$", re.MULTILINE)
_BOLD_RE = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1", re.DOTALL)
_ITALIC_STAR_RE = re.compile(r"(?<![\*\w])\*(?=\S)(.+?)(?<=\S)\*(?![\*\w])", re.DOTALL)
_ITALIC_USCORE_RE = re.compile(r"(?<![_\w])_(?=\S)(.+?)(?<=\S)_(?![_\w])", re.DOTALL)
_STRIKE_RE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.DOTALL)
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_BULLET_RE = re.compile(r"^([ \t]*)[-*+][ \t]+", re.MULTILINE)


def markdown_to_mrkdwn(text: str) -> str:
    """Return ``text`` with common Markdown rewritten to Slack mrkdwn."""
    if not text:
        return text

    # 1. Stash code so its contents are never transformed (and backtick syntax
    #    is already valid in Slack). Fenced blocks first, then inline spans.
    stash: list[str] = []

    def _stash(match: "re.Match[str]") -> str:
        stash.append(match.group(0))
        return f"\x00{len(stash) - 1}\x00"

    text = _FENCE_RE.sub(_stash, text)
    text = _INLINE_CODE_RE.sub(_stash, text)

    # 2-3. Headings and bold both become Slack bold (*one asterisk*). Emit a
    #      \x01 sentinel for the bold delimiters so the italic pass below can't
    #      mistake the single asterisks for italic; the sentinel is swapped back
    #      to "*" at the very end. Inner text is left intact so italic nested in
    #      a heading/bold span still converts.
    text = _HEADING_RE.sub("\x01\\1\x01", text)
    text = _BOLD_RE.sub("\x01\\2\x01", text)  # ** or __
    # 4. Italic (* or _) -> _.
    text = _ITALIC_STAR_RE.sub(r"_\1_", text)
    text = _ITALIC_USCORE_RE.sub(r"_\1_", text)
    # 5. Strikethrough ~~ -> ~.
    text = _STRIKE_RE.sub(r"~\1~", text)
    # 6. Images and links -> <url|text>.
    text = _IMAGE_RE.sub(lambda m: f"<{m.group(2)}|{m.group(1) or m.group(2)}>", text)
    text = _LINK_RE.sub(r"<\2|\1>", text)
    # 7. Unordered bullets -> Slack bullet glyph (keeps indentation).
    text = _BULLET_RE.sub(r"\1• ", text)

    # 8. Swap the bold/heading sentinels back to Slack's single asterisk.
    text = text.replace("\x01", "*")

    # 9. Restore stashed code verbatim.
    def _restore(match: "re.Match[str]") -> str:
        return stash[int(match.group(1))]

    text = re.sub(r"\x00(\d+)\x00", _restore, text)
    return text
