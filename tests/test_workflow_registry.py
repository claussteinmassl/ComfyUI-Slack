"""Unit tests for utils/workflow_registry.py (manifest/template loading)."""

import json

import pytest

from utils import workflow_registry as wr


# --------------------------------------------------------------------------- #
# _node_titles
# --------------------------------------------------------------------------- #
def test_node_titles_extracts_and_skips():
    graph = {
        "1": {"_meta": {"title": "SLACK_OUTPUT"}},
        "2": {"_meta": {"title": "SLACK_PROMPT"}},
        "3": {"_meta": {}},          # no title
        "4": {"class_type": "X"},     # no _meta
        "5": "not-a-dict",
    }
    assert wr._node_titles(graph) == {"SLACK_OUTPUT", "SLACK_PROMPT"}


# --------------------------------------------------------------------------- #
# _image_input_count
# --------------------------------------------------------------------------- #
def test_image_input_count_none():
    assert wr._image_input_count({"SLACK_OUTPUT", "SLACK_PROMPT"}) == 0


def test_image_input_count_bare_is_one():
    assert wr._image_input_count({"SLACK_INPUT_IMAGE"}) == 1


def test_image_input_count_contiguous():
    assert wr._image_input_count({"SLACK_INPUT_IMAGE", "SLACK_INPUT_IMAGE_2"}) == 2
    assert wr._image_input_count(
        {"SLACK_INPUT_IMAGE_1", "SLACK_INPUT_IMAGE_2", "SLACK_INPUT_IMAGE_3"}
    ) == 3


def test_image_input_count_non_contiguous_raises():
    with pytest.raises(ValueError, match="contiguous"):
        wr._image_input_count({"SLACK_INPUT_IMAGE_2"})  # missing slot 1


# --------------------------------------------------------------------------- #
# load — helpers to scaffold a workflow dir
# --------------------------------------------------------------------------- #
def _graph(*titles):
    return {str(i): {"_meta": {"title": t}} for i, t in enumerate(titles)}


def _write(dir_path, manifest, templates):
    (dir_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for fname, graph in templates.items():
        (dir_path / fname).write_text(json.dumps(graph), encoding="utf-8")


def test_load_valid_entry(tmp_path):
    _write(
        tmp_path,
        {"workflows": [{
            "name": "up",
            "template": "up.json",
            "modality": "image",
            "keywords": ["Upscale", "ENLARGE"],
        }]},
        {"up.json": _graph("SLACK_OUTPUT", "SLACK_INPUT_IMAGE", "SLACK_INPUT_IMAGE_2")},
    )
    reg = wr.load(str(tmp_path))
    assert set(reg) == {"up"}
    w = reg["up"]
    assert w.label == "up"                  # defaulted from name
    assert w.description == ""              # defaulted
    assert w.keywords == ["upscale", "enlarge"]  # lower-cased
    assert w.image_inputs == 2
    assert w.modality == "image"


def test_load_missing_required_marker_skipped(tmp_path):
    _write(
        tmp_path,
        {"workflows": [{"name": "bad", "template": "bad.json", "modality": "text"}]},
        {"bad.json": _graph("SLACK_PROMPT")},  # no SLACK_OUTPUT
    )
    assert wr.load(str(tmp_path)) == {}


def test_load_invalid_modality_skipped(tmp_path):
    _write(
        tmp_path,
        {"workflows": [{"name": "bad", "template": "bad.json", "modality": "audio"}]},
        {"bad.json": _graph("SLACK_OUTPUT")},
    )
    assert wr.load(str(tmp_path)) == {}


def test_load_non_contiguous_slots_skipped(tmp_path):
    _write(
        tmp_path,
        {"workflows": [{"name": "bad", "template": "bad.json", "modality": "image"}]},
        {"bad.json": _graph("SLACK_OUTPUT", "SLACK_INPUT_IMAGE_2")},
    )
    assert wr.load(str(tmp_path)) == {}


def test_load_entry_missing_field_skipped_but_others_survive(tmp_path):
    _write(
        tmp_path,
        {"workflows": [
            {"template": "x.json", "modality": "text"},          # missing name
            {"name": "ok", "template": "ok.json", "modality": "text"},
        ]},
        {"x.json": _graph("SLACK_OUTPUT"), "ok.json": _graph("SLACK_OUTPUT")},
    )
    reg = wr.load(str(tmp_path))
    assert set(reg) == {"ok"}


def test_load_missing_manifest_returns_empty(tmp_path):
    assert wr.load(str(tmp_path)) == {}


def test_load_malformed_manifest_returns_empty(tmp_path):
    (tmp_path / "manifest.json").write_text("{ not json", encoding="utf-8")
    assert wr.load(str(tmp_path)) == {}


def test_load_manifest_without_workflows_list_returns_empty(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"foo": "bar"}), encoding="utf-8")
    assert wr.load(str(tmp_path)) == {}


def test_load_bare_list_manifest(tmp_path):
    # manifest may be a bare list rather than {"workflows": [...]}.
    _write(
        tmp_path,
        [{"name": "ok", "template": "ok.json", "modality": "text"}],
        {"ok.json": _graph("SLACK_OUTPUT")},
    )
    assert set(wr.load(str(tmp_path))) == {"ok"}


# --------------------------------------------------------------------------- #
# query helpers
# --------------------------------------------------------------------------- #
def _wf(name, modality):
    return wr.Workflow(
        name=name, label=name, description="", modality=modality,
        keywords=[], template_path="", graph={}, image_inputs=0,
    )


def test_list_all_get_for_modality():
    reg = {
        "img": _wf("img", "image"),
        "txt": _wf("txt", "text"),
        "flex": _wf("flex", "any"),
    }
    assert {w.name for w in wr.list_all(reg)} == {"img", "txt", "flex"}
    assert wr.get(reg, "img").name == "img"
    assert wr.get(reg, "missing") is None
    # 'any' is always included alongside the exact-modality match.
    assert {w.name for w in wr.for_modality(reg, "image")} == {"img", "flex"}
    assert {w.name for w in wr.for_modality(reg, "video")} == {"flex"}
