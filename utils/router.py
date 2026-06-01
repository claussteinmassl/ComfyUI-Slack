"""Deterministic workflow routing. No LLM -- pure rules.

Given a parsed Slack request and the workflow registry, decide which template
to run, or that the user must disambiguate, or that the request is rejected.
"""

import re
from dataclasses import dataclass

from . import config, workflow_registry
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


@dataclass
class RunOnce:
    workflow: Workflow
    images: list[str]          # the N images for the single run ([] for text/video)


@dataclass
class ConfirmFanOut:
    workflow: Workflow
    batches: list[list[str]]   # k batches of N images each
    n: int
    m: int


PlanResult = RunOnce | ConfirmFanOut | Rejected


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


def plan_run(workflow, req) -> PlanResult:
    """Decide how to execute *workflow* given the images on *req*.

    Compares M (images sent) to N (``workflow.image_inputs``):
      M == N        -> RunOnce
      M <  N        -> Rejected (needs more)
      M == k*N, k>1 -> ConfirmFanOut (ask Continue/Cancel), unless k exceeds cap
      otherwise     -> Rejected (not a multiple)
    Video/text requests (input_kind != "image") always RunOnce.
    """
    if req.input_kind != "image":
        return RunOnce(workflow, [])

    n = workflow.image_inputs
    images = list(req.input_paths)
    m = len(images)

    if n == 0:
        return Rejected(
            f"*{workflow.label}* doesn't take image inputs, but you attached "
            f"{m} image(s). Remove the attachment(s) or pick an image workflow."
        )
    if m == n:
        return RunOnce(workflow, images)
    if m < n:
        return Rejected(
            f"*{workflow.label}* needs {n} image(s); you sent {m}. "
            f"Attach {n - m} more and try again."
        )
    if m % n == 0:                       # k > 1
        k = m // n
        cap = config.max_fanout()
        if k > cap:
            return Rejected(
                f"That would run *{workflow.label}* {k} times, over the "
                f"{cap}-run limit (SLACK_MAX_FANOUT). Send fewer images."
            )
        batches = [images[i:i + n] for i in range(0, m, n)]
        return ConfirmFanOut(workflow, batches, n=n, m=m)
    return Rejected(
        f"*{workflow.label}* takes {n} image(s) per run. You sent {m}, which "
        f"isn't a multiple of {n}. Send {n}, or a multiple of {n}, image(s)."
    )
