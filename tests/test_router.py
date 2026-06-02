"""Unit tests for utils/router.py (deterministic workflow routing)."""

from types import SimpleNamespace

import pytest

from utils import config, router
from utils.workflow_registry import Workflow


def _wf(name, modality="image", keywords=(), image_inputs=1, label=None):
    return Workflow(
        name=name,
        label=label or name,
        description="",
        modality=modality,
        keywords=[k.lower() for k in keywords],
        template_path=f"{name}.json",
        graph={},
        image_inputs=image_inputs,
    )


def _req(prompt="", input_kind=None, input_paths=(), override=None):
    return SimpleNamespace(
        prompt=prompt,
        input_kind=input_kind,
        input_paths=list(input_paths),
        override=override,
    )


def _registry(*workflows):
    return {w.name: w for w in workflows}


# --------------------------------------------------------------------------- #
# modality_of
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("kind,expected", [
    ("image", "image"),
    ("video", "video"),
    (None, "text"),
    ("something-else", "text"),
])
def test_modality_of(kind, expected):
    assert router.modality_of(kind) == expected


# --------------------------------------------------------------------------- #
# strip_override
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,name,rest", [
    ("[txt2img] a cat", "txt2img", "a cat"),
    ("  [up-scale]   hello  ", "up-scale", "hello"),
    ("no override here", None, "no override here"),
    ("  spaced  ", None, "spaced"),
    ("[only]", "only", ""),
    ("[bad name] x", None, "[bad name] x"),  # spaces inside brackets don't match
])
def test_strip_override(text, name, rest):
    assert router.strip_override(text) == (name, rest)


# --------------------------------------------------------------------------- #
# select
# --------------------------------------------------------------------------- #
def test_select_override_resolves():
    reg = _registry(_wf("img", modality="image"))
    res = router.select(_req(override="img", input_kind="image"), reg)
    assert isinstance(res, router.Resolved) and res.template.name == "img"


def test_select_unknown_override_rejected():
    reg = _registry(_wf("img"))
    res = router.select(_req(override="nope", input_kind="image"), reg)
    assert isinstance(res, router.Rejected) and "Unknown workflow" in res.reason


def test_select_override_modality_mismatch_rejected():
    reg = _registry(_wf("vid", modality="video"))
    res = router.select(_req(override="vid", input_kind="image"), reg)
    assert isinstance(res, router.Rejected) and "needs a video input" in res.reason


def test_select_override_any_modality_matches():
    reg = _registry(_wf("flex", modality="any"))
    res = router.select(_req(override="flex", input_kind="image"), reg)
    assert isinstance(res, router.Resolved)


def test_select_no_candidates_rejected():
    reg = _registry(_wf("img", modality="image"))
    res = router.select(_req(input_kind="video"), reg)
    assert isinstance(res, router.Rejected) and "No workflow accepts a video" in res.reason


def test_select_single_candidate_resolves():
    reg = _registry(_wf("only", modality="image"))
    res = router.select(_req(input_kind="image"), reg)
    assert isinstance(res, router.Resolved) and res.template.name == "only"


def test_select_keyword_narrows_to_one():
    reg = _registry(
        _wf("upscale", modality="image", keywords=["upscale", "enlarge"]),
        _wf("restyle", modality="image", keywords=["style"]),
    )
    res = router.select(_req(prompt="please UPSCALE this", input_kind="image"), reg)
    assert isinstance(res, router.Resolved) and res.template.name == "upscale"


def test_select_ambiguous_needs_choice():
    reg = _registry(
        _wf("a", modality="image", keywords=["alpha"]),
        _wf("b", modality="image", keywords=["beta"]),
    )
    res = router.select(_req(prompt="something unrelated", input_kind="image"), reg)
    assert isinstance(res, router.NeedsChoice) and len(res.candidates) == 2


# --------------------------------------------------------------------------- #
# plan_run
# --------------------------------------------------------------------------- #
def test_plan_run_non_image_runs_once_empty():
    res = router.plan_run(_wf("txt", image_inputs=0), _req(input_kind="text"))
    assert isinstance(res, router.RunOnce) and res.images == []


def test_plan_run_image_workflow_zero_inputs_rejected():
    res = router.plan_run(
        _wf("txt", image_inputs=0),
        _req(input_kind="image", input_paths=["a.png"]),
    )
    assert isinstance(res, router.Rejected) and "doesn't take image inputs" in res.reason


def test_plan_run_exact_match_runs_once():
    res = router.plan_run(
        _wf("img", image_inputs=2),
        _req(input_kind="image", input_paths=["a.png", "b.png"]),
    )
    assert isinstance(res, router.RunOnce) and res.images == ["a.png", "b.png"]


def test_plan_run_too_few_rejected():
    res = router.plan_run(
        _wf("img", image_inputs=3),
        _req(input_kind="image", input_paths=["a.png"]),
    )
    assert isinstance(res, router.Rejected) and "needs 3" in res.reason


def test_plan_run_multiple_confirms_fanout(monkeypatch):
    monkeypatch.setattr(config, "max_fanout", lambda: 25)
    res = router.plan_run(
        _wf("img", image_inputs=2),
        _req(input_kind="image", input_paths=["a", "b", "c", "d"]),
    )
    assert isinstance(res, router.ConfirmFanOut)
    assert res.n == 2 and res.m == 4
    assert res.batches == [["a", "b"], ["c", "d"]]


def test_plan_run_over_cap_rejected(monkeypatch):
    monkeypatch.setattr(config, "max_fanout", lambda: 1)
    res = router.plan_run(
        _wf("img", image_inputs=1),
        _req(input_kind="image", input_paths=["a", "b", "c"]),
    )
    assert isinstance(res, router.Rejected) and "over the" in res.reason


def test_plan_run_non_multiple_rejected():
    res = router.plan_run(
        _wf("img", image_inputs=2),
        _req(input_kind="image", input_paths=["a", "b", "c"]),
    )
    assert isinstance(res, router.Rejected) and "isn't a multiple" in res.reason
