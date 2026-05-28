"""Deterministic workflow routing. No LLM -- pure rules.

Given a parsed Slack request and the workflow registry, decide which template
to run, or that the user must disambiguate, or that the request is rejected.
"""

import re
from dataclasses import dataclass

from . import workflow_registry
from .workflow_registry import Workflow

_OVERRIDE_RE = re.compile(r"^\s*\[([A-Za-z0-9_-]+)\]\s*")


@dataclass
class Resolved:
    template: Workflow


@dataclass
class NeedsChoice:
    candidates: list[Workflow]


@dataclass
class Rejected:
    reason: str


RouteResult = Resolved | NeedsChoice | Rejected


def modality_of(input_kind: str | None) -> str:
    """Map a downloaded-file kind to a workflow modality."""
    if input_kind == "image":
        return "image"
    if input_kind == "video":
        return "video"
    return "text"


def strip_override(text: str) -> tuple[str | None, str]:
    """Split a leading ``[name]`` override token off *text*.

    Returns (override_name_or_None, remaining_prompt).
    """
    match = _OVERRIDE_RE.match(text)
    if match:
        return match.group(1), text[match.end():].strip()
    return None, text.strip()


def _options_list(registry) -> str:
    lines = []
    for w in workflow_registry.list_all(registry):
        desc = f" — {w.description}" if w.description else ""
        lines.append(f"• `[{w.name}]` ({w.modality}){desc}")
    return "\n".join(lines) if lines else "(no workflows configured)"


def select(req, registry) -> RouteResult:
    """Pick a workflow for *req* against *registry*.

    *req* must expose ``.prompt`` and ``.input_kind`` attributes; ``.prompt`` is
    expected to already have any leading override token stripped by the caller
    (see :func:`strip_override`).
    """
    modality = modality_of(req.input_kind)

    # 1. Explicit [name] override always wins (already stripped into req.override).
    override = getattr(req, "override", None)
    if override:
        workflow = workflow_registry.get(registry, override)
        if workflow is None:
            return Rejected(
                f"Unknown workflow `[{override}]`. Available workflows:\n"
                + _options_list(registry)
            )
        if workflow.modality not in (modality, "any"):
            need = workflow.modality
            return Rejected(
                f"Workflow `[{override}]` needs a {need} input, but you sent a "
                f"{modality} request. Attach a {need} and try again."
            )
        return Resolved(workflow)

    # 2. Candidates by modality.
    candidates = workflow_registry.for_modality(registry, modality)
    if not candidates:
        return Rejected(
            f"No workflow accepts a {modality} input. Available workflows:\n"
            + _options_list(registry)
        )
    if len(candidates) == 1:
        return Resolved(candidates[0])

    # 3. Keyword narrowing within the candidate set.
    text = (req.prompt or "").lower()
    keyword_hits = [
        w for w in candidates
        if any(kw in text for kw in w.keywords)
    ]
    if len(keyword_hits) == 1:
        return Resolved(keyword_hits[0])

    # 4. Still ambiguous -> ask via buttons.
    return NeedsChoice(candidates)
