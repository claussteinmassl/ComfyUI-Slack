"""Unit tests for utils/thread_root.py (Slack Thread Start root bookkeeping)."""

import pytest

from utils import thread_root


class _FakeClient:
    """Records posts and hands out an incrementing ts so reuse vs. new is visible."""

    def __init__(self):
        self.posts = []
        self._n = 0

    def chat_postMessage(self, **kwargs):
        self._n += 1
        self.posts.append(kwargs)
        return {"ts": f"170000000{self._n}.000000"}


@pytest.fixture(autouse=True)
def _stub_resolve_and_clear(monkeypatch):
    # Both thread_root (to embed the channel in the ref) and post_message_to_slack
    # (internally) resolve the channel; pin both to a valid id and start each test
    # with an empty reuse cache.
    from utils import slack_client
    monkeypatch.setattr(slack_client, "resolve_destination", lambda c, ch: "C012345678")
    monkeypatch.setattr(thread_root, "resolve_destination", lambda c, ch: "C012345678")
    thread_root._thread_roots.clear()


def test_new_mode_posts_every_call():
    client = _FakeClient()
    ts1 = thread_root.resolve_thread_root(client, "#g", "hi", reuse=False, key="k")
    ts2 = thread_root.resolve_thread_root(client, "#g", "hi", reuse=False, key="k")
    assert ts1 != ts2                 # a fresh root each time
    assert len(client.posts) == 2


def test_ref_embeds_resolved_channel_and_ts():
    client = _FakeClient()
    ref = thread_root.resolve_thread_root(client, "#g", "hi", reuse=False, key="k")
    channel, ts = thread_root.split_thread_ref(ref)
    assert channel == "C012345678"      # resolved channel travels with the ref
    assert ts == "1700000001.000000"    # first post's ts, unwrapped from the ref


def test_split_thread_ref_passes_bare_ts_through():
    # A listener-injected bare ts has no channel — the send node keeps its own.
    assert thread_root.split_thread_ref("1700000001.000000") == (None, "1700000001.000000")
    assert thread_root.split_thread_ref("") == (None, "")



def test_reuse_mode_posts_once_per_key():
    client = _FakeClient()
    ts1 = thread_root.resolve_thread_root(client, "#g", "hi", reuse=True, key="k")
    ts2 = thread_root.resolve_thread_root(client, "#g", "hi", reuse=True, key="k")
    assert ts1 == ts2                 # same root reused
    assert len(client.posts) == 1


def test_reuse_mode_distinct_keys_get_distinct_roots():
    client = _FakeClient()
    ts1 = thread_root.resolve_thread_root(client, "#g", "hi", reuse=True, key="a")
    ts2 = thread_root.resolve_thread_root(client, "#g", "hi", reuse=True, key="b")
    assert ts1 != ts2
    assert len(client.posts) == 2


def test_header_translated_to_mrkdwn():
    client = _FakeClient()
    thread_root.resolve_thread_root(client, "#g", "**bold**", reuse=False, key="k")
    assert client.posts[0]["text"] == "*bold*"   # markdown -> Slack mrkdwn


def test_blank_header_falls_back_to_nonempty():
    client = _FakeClient()
    thread_root.resolve_thread_root(client, "#g", "   ", reuse=False, key="k")
    assert client.posts[0]["text"] == thread_root._FALLBACK_HEADER
