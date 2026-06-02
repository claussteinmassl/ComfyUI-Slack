"""Unit tests for utils/comfy_trigger.py (graph injection + prompt submission)."""

import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from utils import comfy_trigger, config


def _req(prompt="hello", channel="C1", thread_ts="123.45", user="U9",
         input_kind=None, input_path=None):
    return SimpleNamespace(
        prompt=prompt, channel=channel, thread_ts=thread_ts, user=user,
        input_kind=input_kind, input_path=input_path,
    )


# --------------------------------------------------------------------------- #
# inject — prompt field selection
# --------------------------------------------------------------------------- #
def test_inject_prompt_into_cliptextencode(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: True)
    graph = {"1": {"class_type": "CLIPTextEncode", "_meta": {"title": "SLACK_PROMPT"},
                   "inputs": {"text": "old"}}}
    out = comfy_trigger.inject(graph, _req(prompt="a cat"), [])
    assert out["1"]["inputs"]["text"] == "a cat"


def test_inject_prompt_into_primitive_value(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: True)
    graph = {"1": {"class_type": "PrimitiveNode", "_meta": {"title": "SLACK_PROMPT"},
                   "inputs": {"value": "old"}}}
    out = comfy_trigger.inject(graph, _req(prompt="x"), [])
    assert out["1"]["inputs"]["value"] == "x"


def test_inject_prompt_fallback_to_first_string_input(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: True)
    graph = {"1": {"class_type": "WeirdNode", "_meta": {"title": "SLACK_PROMPT"},
                   "inputs": {"seed": 5, "caption": "old"}}}
    out = comfy_trigger.inject(graph, _req(prompt="x"), [])
    assert out["1"]["inputs"]["caption"] == "x"
    assert out["1"]["inputs"]["seed"] == 5


def test_inject_prompt_fallback_to_text_when_no_string_input(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: True)
    graph = {"1": {"class_type": "WeirdNode", "_meta": {"title": "SLACK_PROMPT"},
                   "inputs": {"seed": 5}}}
    out = comfy_trigger.inject(graph, _req(prompt="x"), [])
    assert out["1"]["inputs"]["text"] == "x"


# --------------------------------------------------------------------------- #
# inject — image / video slots
# --------------------------------------------------------------------------- #
def test_inject_image_slots_by_index(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: False)
    graph = {
        "1": {"_meta": {"title": "SLACK_INPUT_IMAGE"}, "inputs": {}},
        "2": {"_meta": {"title": "SLACK_INPUT_IMAGE_2"}, "inputs": {}},
    }
    out = comfy_trigger.inject(graph, _req(input_kind="image"), ["first.png", "second.png"])
    assert out["1"]["inputs"]["image"] == "first.png"
    assert out["2"]["inputs"]["image"] == "second.png"


def test_inject_image_slot_ignored_when_not_image(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: False)
    graph = {"1": {"_meta": {"title": "SLACK_INPUT_IMAGE"}, "inputs": {}}}
    out = comfy_trigger.inject(graph, _req(input_kind="video"), ["a.png"])
    assert "image" not in out["1"]["inputs"]


def test_inject_image_slot_out_of_range_skipped(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: False)
    graph = {"2": {"_meta": {"title": "SLACK_INPUT_IMAGE_2"}, "inputs": {}}}
    out = comfy_trigger.inject(graph, _req(input_kind="image"), ["only-one.png"])
    assert "image" not in out["2"]["inputs"]  # index 1 has no image


def test_inject_video_slot(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: False)
    graph = {"1": {"_meta": {"title": "SLACK_INPUT_VIDEO"}, "inputs": {}}}
    out = comfy_trigger.inject(graph, _req(input_kind="video", input_path="clip.mp4"), [])
    assert out["1"]["inputs"]["video"] == "clip.mp4"


# --------------------------------------------------------------------------- #
# inject — SLACK_OUTPUT + isolation
# --------------------------------------------------------------------------- #
def test_inject_output_sets_user_when_notify_on(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: True)
    graph = {"1": {"_meta": {"title": "SLACK_OUTPUT"}, "inputs": {}}}
    out = comfy_trigger.inject(graph, _req(channel="C1", thread_ts="9.9", user="U7"), [])
    assert out["1"]["inputs"]["channel"] == "C1"
    assert out["1"]["inputs"]["thread_ts"] == "9.9"
    assert out["1"]["inputs"]["user_id"] == "U7"


def test_inject_output_omits_user_when_notify_off(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: False)
    graph = {"1": {"_meta": {"title": "SLACK_OUTPUT"}, "inputs": {}}}
    out = comfy_trigger.inject(graph, _req(user="U7"), [])
    assert "user_id" not in out["1"]["inputs"]


def test_inject_does_not_mutate_original(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: True)
    graph = {"1": {"class_type": "CLIPTextEncode", "_meta": {"title": "SLACK_PROMPT"},
                   "inputs": {"text": "ORIGINAL"}}}
    comfy_trigger.inject(graph, _req(prompt="changed"), [])
    assert graph["1"]["inputs"]["text"] == "ORIGINAL"


# --------------------------------------------------------------------------- #
# submit_prompt
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


@pytest.fixture
def _stub_comfy(monkeypatch):
    monkeypatch.setattr(config, "comfy_base_url", lambda: "http://test:8188")
    monkeypatch.setattr(config, "comfy_api_key", lambda: None)


def test_submit_prompt_success_returns_id(monkeypatch, _stub_comfy):
    captured = {}

    def fake_urlopen(request, timeout=15):
        captured["data"] = request.data
        return _FakeResp(json.dumps({"prompt_id": "pid-123"}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert comfy_trigger.submit_prompt({"1": {}}) == "pid-123"
    body = json.loads(captured["data"])
    assert body["prompt"] == {"1": {}}
    assert "extra_data" not in body  # no api key configured


def test_submit_prompt_includes_api_key(monkeypatch, _stub_comfy):
    monkeypatch.setattr(config, "comfy_api_key", lambda: "secret-key")
    captured = {}

    def fake_urlopen(request, timeout=15):
        captured["data"] = request.data
        return _FakeResp(json.dumps({"prompt_id": "p"}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    comfy_trigger.submit_prompt({"1": {}})
    body = json.loads(captured["data"])
    assert body["extra_data"]["api_key_comfy_org"] == "secret-key"


def test_submit_prompt_http_error_includes_detail(monkeypatch, _stub_comfy):
    def fake_urlopen(request, timeout=15):
        raise urllib.error.HTTPError(
            "http://test:8188/prompt", 400, "Bad Request", {},
            io.BytesIO(json.dumps({"error": "node blew up"}).encode()),
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="node blew up"):
        comfy_trigger.submit_prompt({"1": {}})


def test_submit_prompt_url_error(monkeypatch, _stub_comfy):
    def fake_urlopen(request, timeout=15):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Could not reach ComfyUI"):
        comfy_trigger.submit_prompt({"1": {}})


def test_submit_prompt_missing_id(monkeypatch, _stub_comfy):
    def fake_urlopen(request, timeout=15):
        return _FakeResp(json.dumps({"no_id": True}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="no prompt_id"):
        comfy_trigger.submit_prompt({"1": {}})


# --------------------------------------------------------------------------- #
# run — wiring
# --------------------------------------------------------------------------- #
def test_run_injects_then_submits(monkeypatch):
    seen = {}

    def fake_submit(graph):
        seen["graph"] = graph
        return "pid"

    monkeypatch.setattr(comfy_trigger, "inject",
                        lambda graph, req, images: {"injected": graph})
    monkeypatch.setattr(comfy_trigger, "submit_prompt", fake_submit)
    workflow = SimpleNamespace(graph={"orig": 1})
    assert comfy_trigger.run(workflow, _req(), ["a"]) == "pid"
    assert seen["graph"] == {"injected": {"orig": 1}}
