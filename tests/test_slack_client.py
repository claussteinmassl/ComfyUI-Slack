"""Unit tests for utils/slack_client.py (client + upload/post wrappers)."""

import pytest
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from utils import slack_client


# --------------------------------------------------------------------------- #
# get_client
# --------------------------------------------------------------------------- #
def test_get_client_with_token(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-abc")
    client = slack_client.get_client()
    assert isinstance(client, WebClient)
    assert client.token == "xoxb-abc"


def test_get_client_without_token_raises(monkeypatch):
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    with pytest.raises(EnvironmentError, match="SLACK_BOT_TOKEN"):
        slack_client.get_client()


# --------------------------------------------------------------------------- #
# _resolve_and_validate
# --------------------------------------------------------------------------- #
def test_resolve_and_validate_passes_valid_id(monkeypatch):
    monkeypatch.setattr(slack_client, "resolve_destination", lambda c, ch: "C012345678")
    assert slack_client._resolve_and_validate(None, "#general") == "C012345678"


def test_resolve_and_validate_rejects_bad_id(monkeypatch):
    monkeypatch.setattr(slack_client, "resolve_destination", lambda c, ch: "not-an-id")
    with pytest.raises(ValueError, match="not a valid Slack channel or user ID"):
        slack_client._resolve_and_validate(None, "garbage")


# --------------------------------------------------------------------------- #
# upload_file_to_slack / post_message_to_slack
# --------------------------------------------------------------------------- #
class _FakeClient:
    def __init__(self, raise_exc=None):
        self.raise_exc = raise_exc
        self.upload_kwargs = None
        self.post_kwargs = None

    def files_upload_v2(self, **kwargs):
        self.upload_kwargs = kwargs
        if self.raise_exc:
            raise self.raise_exc

    def chat_postMessage(self, **kwargs):
        self.post_kwargs = kwargs
        if self.raise_exc:
            raise self.raise_exc


@pytest.fixture(autouse=True)
def _stub_resolve(monkeypatch):
    # resolve_destination is exercised in test_slack_resolve; here we pin it to a
    # valid id so these wrappers can be tested in isolation.
    monkeypatch.setattr(slack_client, "resolve_destination", lambda c, ch: "C012345678")


def test_upload_file_passes_args():
    client = _FakeClient()
    slack_client.upload_file_to_slack(
        client, "#general", "/tmp/x.png", "x.png",
        title="", message="hi", thread_ts="9.9",
    )
    kw = client.upload_kwargs
    assert kw["channel"] == "C012345678"
    assert kw["file"] == "/tmp/x.png"
    assert kw["filename"] == "x.png"
    assert kw["title"] == "x.png"            # falls back to filename
    assert kw["initial_comment"] == "hi"
    assert kw["thread_ts"] == "9.9"


def test_upload_file_blank_message_becomes_none():
    client = _FakeClient()
    slack_client.upload_file_to_slack(client, "#g", "/tmp/x", "x", message="", thread_ts="")
    assert client.upload_kwargs["initial_comment"] is None
    assert client.upload_kwargs["thread_ts"] is None


def test_upload_file_api_error_becomes_runtime_error():
    client = _FakeClient(raise_exc=SlackApiError("boom", {"error": "channel_not_found"}))
    with pytest.raises(RuntimeError, match="channel_not_found"):
        slack_client.upload_file_to_slack(client, "#g", "/tmp/x", "x")


def test_post_message_passes_args():
    client = _FakeClient()
    slack_client.post_message_to_slack(client, "#general", "hello", thread_ts="9.9")
    kw = client.post_kwargs
    assert kw["channel"] == "C012345678"
    assert kw["text"] == "hello"
    assert kw["mrkdwn"] is True
    assert kw["thread_ts"] == "9.9"


def test_post_message_api_error_becomes_runtime_error():
    client = _FakeClient(raise_exc=SlackApiError("boom", {"error": "not_in_channel"}))
    with pytest.raises(RuntimeError, match="not_in_channel"):
        slack_client.post_message_to_slack(client, "#g", "hi")
