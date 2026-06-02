"""Unit tests for utils/slack_messages.py (parsing, button state, downloads)."""

import os

import pytest
from slack_sdk.errors import SlackApiError

from utils import config, slack_messages as sm
from utils.slack_messages import TriggerRequest


# --------------------------------------------------------------------------- #
# _sanitize
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("photo.png", "photo.png"),
    ("/some/dir/cat dog.jpg", "cat_dog.jpg"),
    ("../../etc/passwd", "passwd"),
    ("weird@name!.png", "weird_name_.png"),
    ("", "file"),
    (None, "file"),
])
def test_sanitize(raw, expected):
    assert sm._sanitize(raw) == expected


# --------------------------------------------------------------------------- #
# parse_app_mention
# --------------------------------------------------------------------------- #
def test_parse_app_mention_strips_mentions_and_override():
    event = {
        "text": "<@UBOT> [upscale] make it <@UOTHER> bigger",
        "channel": "C1",
        "ts": "111.1",
        "user": "U5",
    }
    req = sm.parse_app_mention(event, "UBOT")
    assert req.override == "upscale"
    assert req.prompt == "make it  bigger"
    assert req.channel == "C1"
    assert req.thread_ts == "111.1"  # falls back to ts
    assert req.user == "U5"


def test_parse_app_mention_prefers_thread_ts():
    event = {"text": "<@UBOT> hi", "channel": "C1", "ts": "1.0",
             "thread_ts": "9.9", "user": "U5"}
    req = sm.parse_app_mention(event, "UBOT")
    assert req.thread_ts == "9.9"
    assert req.prompt == "hi"
    assert req.override is None


# --------------------------------------------------------------------------- #
# mention_prefix
# --------------------------------------------------------------------------- #
def test_mention_prefix_on(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: True)
    assert sm.mention_prefix("U7") == "<@U7> "


def test_mention_prefix_off(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: False)
    assert sm.mention_prefix("U7") == ""


def test_mention_prefix_empty_user(monkeypatch):
    monkeypatch.setattr(config, "notify_user", lambda: True)
    assert sm.mention_prefix("") == ""


# --------------------------------------------------------------------------- #
# button value encode / decode round-trip
# --------------------------------------------------------------------------- #
def _req(prompt="do a thing"):
    return TriggerRequest(
        prompt=prompt, channel="C1", thread_ts="9.9", user="U5",
        override="up", input_kind="image", file_ids=["F1", "F2"],
    )


def test_button_value_inline_roundtrip():
    value = sm._button_value(_req(), name="upscale")
    req, action = sm.decode_button_value(value)
    assert action == {"name": "upscale"}
    assert req.prompt == "do a thing"
    assert req.channel == "C1"
    assert req.thread_ts == "9.9"
    assert req.user == "U5"
    assert req.override == "up"
    assert req.input_kind == "image"
    assert req.file_ids == ["F1", "F2"]


def test_button_value_overflow_stash_and_pop():
    big = "x" * 5000  # forces the inline state past the 1900-char limit
    value = sm._button_value(_req(prompt=big), kind="confirm", n="wf")
    # The encoded value carries a ref, not the inline state.
    assert '"r"' in value and '"s"' not in value
    req, action = sm.decode_button_value(value)
    assert action == {"kind": "confirm", "n": "wf"}
    assert req is not None and req.prompt == big
    # Popped on decode -> a second decode of the same ref yields None.
    req2, _ = sm.decode_button_value(value)
    assert req2 is None


def test_decode_unknown_ref_returns_none():
    req, action = sm.decode_button_value('{"r":"deadbeef","name":"x"}')
    assert req is None and action == {"name": "x"}


def test_decode_empty_value():
    req, action = sm.decode_button_value("")
    assert req is None and action == {}


# --------------------------------------------------------------------------- #
# download_slack_file
# --------------------------------------------------------------------------- #
class _FakeDownloadResp:
    """Context-managed HTTP response that yields *body* in 8 KB-ish chunks."""

    def __init__(self, body, chunk=8192):
        self._chunks = [body[i:i + chunk] for i in range(0, len(body), chunk)] or [b""]
        self._i = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, n=None):
        if self._i >= len(self._chunks):
            return b""
        c = self._chunks[self._i]
        self._i += 1
        return c


@pytest.fixture
def _dl_env(monkeypatch):
    monkeypatch.setattr(config, "bot_token", lambda: "xoxb-test")
    monkeypatch.setattr(config, "max_input_mb", lambda: 1)


def _img(**over):
    base = {"id": "F1", "name": "pic.png", "mimetype": "image/png",
            "size": 10, "url_private_download": "https://files/pic"}
    base.update(over)
    return base


def test_download_image(monkeypatch, tmp_path, _dl_env):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=30: _FakeDownloadResp(b"PNGDATA"))
    name, kind = sm.download_slack_file(_img(), str(tmp_path))
    assert kind == "image"
    assert name == "slack_F1_pic.png"
    assert (tmp_path / name).read_bytes() == b"PNGDATA"


def test_download_video_kind(monkeypatch, tmp_path, _dl_env):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=30: _FakeDownloadResp(b"MP4"))
    _, kind = sm.download_slack_file(
        _img(id="F2", name="clip.mp4", mimetype="video/mp4"), str(tmp_path))
    assert kind == "video"


def test_download_unsupported_type_raises(tmp_path, _dl_env):
    with pytest.raises(RuntimeError, match="Unsupported attachment"):
        sm.download_slack_file(_img(mimetype="application/pdf"), str(tmp_path))


def test_download_oversize_by_declared_size_raises(tmp_path, _dl_env):
    big = 2 * 1024 * 1024  # 2 MB, over the 1 MB limit
    with pytest.raises(RuntimeError, match="over the"):
        sm.download_slack_file(_img(size=big), str(tmp_path))


def test_download_no_url_raises(tmp_path, _dl_env):
    obj = _img()
    del obj["url_private_download"]
    with pytest.raises(RuntimeError, match="no downloadable URL"):
        sm.download_slack_file(obj, str(tmp_path))


def test_download_idempotent_skip(monkeypatch, tmp_path, _dl_env):
    # Pre-create the deterministic destination; download must skip the HTTP call.
    dest = tmp_path / "slack_F1_pic.png"
    dest.write_bytes(b"ALREADY")

    def boom(*a, **k):
        raise AssertionError("should not download when file already exists")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    name, kind = sm.download_slack_file(_img(), str(tmp_path))
    assert name == "slack_F1_pic.png" and kind == "image"
    assert dest.read_bytes() == b"ALREADY"


# --------------------------------------------------------------------------- #
# download_slack_files — homogeneity rules
# --------------------------------------------------------------------------- #
def test_download_files_all_images(monkeypatch, tmp_path, _dl_env):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=30: _FakeDownloadResp(b"D"))
    files = [_img(id="A", name="a.png"), _img(id="B", name="b.png")]
    paths, kind, ids = sm.download_slack_files(files, str(tmp_path))
    assert kind == "image"
    assert ids == ["A", "B"]
    assert paths == ["slack_A_a.png", "slack_B_b.png"]


def test_download_files_single_video(monkeypatch, tmp_path, _dl_env):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=30: _FakeDownloadResp(b"D"))
    files = [_img(id="V", name="v.mp4", mimetype="video/mp4")]
    paths, kind, ids = sm.download_slack_files(files, str(tmp_path))
    assert kind == "video" and ids == ["V"] and len(paths) == 1


def test_download_files_mixed_raises(monkeypatch, tmp_path, _dl_env):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=30: _FakeDownloadResp(b"D"))
    files = [_img(id="A", name="a.png"),
             _img(id="V", name="v.mp4", mimetype="video/mp4")]
    with pytest.raises(RuntimeError, match="images \\*or\\* a single video"):
        sm.download_slack_files(files, str(tmp_path))


def test_download_files_two_videos_raises(monkeypatch, tmp_path, _dl_env):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=30: _FakeDownloadResp(b"D"))
    files = [_img(id="V1", name="a.mp4", mimetype="video/mp4"),
             _img(id="V2", name="b.mp4", mimetype="video/mp4")]
    with pytest.raises(RuntimeError, match="[Oo]ne video"):
        sm.download_slack_files(files, str(tmp_path))


# --------------------------------------------------------------------------- #
# download_files_by_id
# --------------------------------------------------------------------------- #
class _FakeFilesClient:
    def __init__(self, objs):
        self._objs = objs

    def files_info(self, file):
        return {"file": self._objs.get(file)}


def test_download_files_by_id(monkeypatch, tmp_path, _dl_env):
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=30: _FakeDownloadResp(b"D"))
    client = _FakeFilesClient({"A": _img(id="A", name="a.png")})
    paths, kind, ids = sm.download_files_by_id(client, ["A"], str(tmp_path))
    assert kind == "image" and ids == ["A"] and paths == ["slack_A_a.png"]


def test_download_files_by_id_missing_raises(tmp_path, _dl_env):
    client = _FakeFilesClient({})  # files_info returns {"file": None}
    with pytest.raises(RuntimeError, match="no longer available"):
        sm.download_files_by_id(client, ["GONE"], str(tmp_path))


# --------------------------------------------------------------------------- #
# post_text — best effort
# --------------------------------------------------------------------------- #
class _RecordingClient:
    def __init__(self, raise_exc=None):
        self.raise_exc = raise_exc
        self.kwargs = None

    def chat_postMessage(self, **kwargs):
        self.kwargs = kwargs
        if self.raise_exc:
            raise self.raise_exc


def test_post_text_passes_thread_ts():
    client = _RecordingClient()
    sm.post_text(client, "C1", "hello", "9.9")
    assert client.kwargs == {"channel": "C1", "text": "hello", "thread_ts": "9.9"}


def test_post_text_coerces_blank_thread_to_none():
    client = _RecordingClient()
    sm.post_text(client, "C1", "hello", "")
    assert client.kwargs["thread_ts"] is None


def test_post_text_swallows_api_error():
    client = _RecordingClient(raise_exc=SlackApiError("boom", {"error": "rate_limited"}))
    # Must not raise.
    sm.post_text(client, "C1", "hello", None)
