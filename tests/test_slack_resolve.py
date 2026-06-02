"""Unit tests for utils/slack_resolve.py (mocked WebClient, no live Slack).

slack_resolve.py is loaded directly by file path so the test never imports the
``utils`` package or the repo-root ``__init__.py`` (the ComfyUI entry point,
which does relative imports that only work inside a running ComfyUI).
"""

import importlib.util
import os

import pytest
from slack_sdk.errors import SlackApiError

_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "utils", "slack_resolve.py")
_spec = importlib.util.spec_from_file_location("slack_resolve_under_test", _PATH)
slack_resolve = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(slack_resolve)

AmbiguousNameError = slack_resolve.AmbiguousNameError
resolve_allowed_channels = slack_resolve.resolve_allowed_channels
resolve_allowed_users = slack_resolve.resolve_allowed_users
resolve_channel = slack_resolve.resolve_channel
resolve_user = slack_resolve.resolve_user
resolve_destination = slack_resolve.resolve_destination


class FakeClient:
    """Records call counts and serves canned, cursor-paginated responses."""

    def __init__(self, channels_pages=None, users_pages=None, raise_on=None):
        self.channels_pages = channels_pages or []
        self.users_pages = users_pages or []
        self.raise_on = raise_on or set()
        self.calls = {"conversations_list": 0, "users_list": 0, "conversations_open": 0}

    def _page(self, pages, cursor):
        idx = 0 if cursor in (None, "") else int(cursor)
        return pages[idx]

    def conversations_list(self, cursor=None, **kwargs):
        if "conversations_list" in self.raise_on:
            raise SlackApiError("missing_scope", {"error": "missing_scope"})
        self.calls["conversations_list"] += 1
        return self._page(self.channels_pages, cursor)

    def users_list(self, cursor=None, **kwargs):
        if "users_list" in self.raise_on:
            raise SlackApiError("missing_scope", {"error": "missing_scope"})
        self.calls["users_list"] += 1
        return self._page(self.users_pages, cursor)

    def conversations_open(self, users=None, **kwargs):
        if "conversations_open" in self.raise_on:
            raise SlackApiError("missing_scope", {"error": "missing_scope"})
        self.calls["conversations_open"] += 1
        # Slack returns a stable D… id per user; fake one shaped like a real id.
        return {"channel": {"id": _dm(users)}}


def _dm(uid):
    """Deterministic DM channel id for a user id, shaped like a real Slack D… id."""
    return "D" + uid + "00000"


# Two channel pages so pagination is exercised; "random" is archived.
CHANNELS = [
    {
        "channels": [
            {"id": "C001", "name": "general"},
            {"id": "C002", "name": "random", "is_archived": True},
        ],
        "response_metadata": {"next_cursor": "1"},
    },
    {
        "channels": [{"id": "C003", "name": "Design"}],
        "response_metadata": {"next_cursor": ""},
    },
]

USERS = [
    {
        "members": [
            {"id": "U001", "name": "alice",
             "profile": {"display_name": "Alice", "real_name": "Alice Anderson"}},
            {"id": "U002", "name": "bob",
             "profile": {"display_name": "Bobby", "real_name": "Bob Builder"}},
            {"id": "U003", "name": "bob2",
             "profile": {"display_name": "Bobby", "real_name": "Bob Other"}},
            {"id": "U004", "name": "ghost", "deleted": True, "profile": {}},
        ],
        "response_metadata": {"next_cursor": ""},
    },
]


@pytest.fixture(autouse=True)
def _reset_caches():
    """Each test starts with empty module caches."""
    slack_resolve._channel_cache = None
    slack_resolve._channel_built_at = 0.0
    slack_resolve._user_cache = None
    slack_resolve._user_built_at = 0.0
    slack_resolve._dm_cache = {}
    yield


# --------------------------------------------------------------------------- #
# _norm
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("#general", "general"),
    ("  @Alice ", "alice"),
    ("Design", "design"),
    ("##weird", "weird"),
])
def test_norm(raw, expected):
    assert slack_resolve._norm(raw) == expected


# --------------------------------------------------------------------------- #
# ID pass-through — no API call
# --------------------------------------------------------------------------- #
def test_channel_id_passthrough_makes_no_api_call():
    client = FakeClient(channels_pages=CHANNELS)
    assert resolve_channel(client, "C0123ABCD") == "C0123ABCD"
    assert client.calls["conversations_list"] == 0


def test_user_id_passthrough_makes_no_api_call():
    client = FakeClient(users_pages=USERS)
    assert resolve_user(client, "U0123ABCD") == "U0123ABCD"
    assert client.calls["users_list"] == 0


# --------------------------------------------------------------------------- #
# Channel name resolution
# --------------------------------------------------------------------------- #
def test_resolve_channel_by_name_with_hash_and_case():
    client = FakeClient(channels_pages=CHANNELS)
    assert resolve_channel(client, "#general") == "C001"
    # second page, case-insensitive
    assert resolve_channel(client, "design") == "C003"


def test_resolve_channel_caches_after_first_build():
    client = FakeClient(channels_pages=CHANNELS)
    resolve_channel(client, "general")
    resolve_channel(client, "design")
    assert client.calls["conversations_list"] == 2  # one full paginated build (2 pages), then cached


def test_archived_channel_not_resolvable_by_name():
    client = FakeClient(channels_pages=CHANNELS)
    with pytest.raises(ValueError):
        resolve_channel(client, "random")


def test_resolve_channel_not_found_raises():
    client = FakeClient(channels_pages=CHANNELS)
    with pytest.raises(ValueError):
        resolve_channel(client, "nope")


def test_resolve_channel_empty_raises():
    client = FakeClient(channels_pages=CHANNELS)
    with pytest.raises(ValueError):
        resolve_channel(client, "   ")


# --------------------------------------------------------------------------- #
# User name resolution
# --------------------------------------------------------------------------- #
def test_resolve_user_by_handle_display_real():
    client = FakeClient(users_pages=USERS)
    assert resolve_user(client, "@alice") == "U001"
    assert resolve_user(client, "Alice Anderson") == "U001"  # real name
    assert resolve_user(client, "bob") == "U002"             # handle


def test_resolve_user_ambiguous_display_name():
    client = FakeClient(users_pages=USERS)
    with pytest.raises(AmbiguousNameError) as exc:
        resolve_user(client, "Bobby")  # shared display name on U002 + U003
    assert "U002" in str(exc.value) and "U003" in str(exc.value)


def test_resolve_user_deactivated_not_resolvable():
    client = FakeClient(users_pages=USERS)
    with pytest.raises(ValueError):
        resolve_user(client, "ghost")


def test_resolve_user_not_found_raises():
    client = FakeClient(users_pages=USERS)
    with pytest.raises(ValueError):
        resolve_user(client, "nobody")


# --------------------------------------------------------------------------- #
# Allow-list helpers — never raise
# --------------------------------------------------------------------------- #
def test_resolve_allowed_channels_mixed_names_and_ids():
    client = FakeClient(channels_pages=CHANNELS)
    out = resolve_allowed_channels(client, {"#general", "C999ZZZ99", "nope"})
    assert out == {"C001", "C999ZZZ99"}  # name resolved, raw ID kept, miss skipped


def test_resolve_allowed_users_skips_ambiguous_and_missing():
    client = FakeClient(users_pages=USERS)
    out = resolve_allowed_users(client, {"alice", "Bobby", "U777XXX77", "ghost"})
    assert out == {"U001", "U777XXX77"}  # ambiguous + deactivated skipped, ID kept


def test_resolve_allowed_degrades_on_missing_scope():
    client = FakeClient(users_pages=USERS, raise_on={"users_list"})
    out = resolve_allowed_users(client, {"alice", "U777XXX77"})
    assert out == {"U777XXX77"}  # API failed → name skipped, ID survives, no raise


def test_resolve_allowed_empty_set():
    client = FakeClient()
    assert resolve_allowed_channels(client, set()) == set()
    assert resolve_allowed_users(client, set()) == set()


# --------------------------------------------------------------------------- #
# Rebuild-on-miss throttling
# --------------------------------------------------------------------------- #
def test_miss_triggers_throttled_rebuild(monkeypatch):
    client = FakeClient(channels_pages=CHANNELS)
    # First miss builds once; immediate retry must NOT rebuild (interval not elapsed).
    with pytest.raises(ValueError):
        resolve_channel(client, "nope")
    builds_after_first = client.calls["conversations_list"]
    with pytest.raises(ValueError):
        resolve_channel(client, "nope")
    assert client.calls["conversations_list"] == builds_after_first  # throttled

    # Force the interval to elapse → a miss rebuilds again.
    monkeypatch.setattr(slack_resolve, "_REBUILD_INTERVAL", -1.0)
    with pytest.raises(ValueError):
        resolve_channel(client, "nope")
    assert client.calls["conversations_list"] > builds_after_first


# --------------------------------------------------------------------------- #
# resolve_destination — channel vs user (DM)
# --------------------------------------------------------------------------- #
def test_destination_explicit_channel_no_dm():
    client = FakeClient(channels_pages=CHANNELS, users_pages=USERS)
    assert resolve_destination(client, "#general") == "C001"
    assert resolve_destination(client, "C0123ABCD") == "C0123ABCD"
    assert client.calls["conversations_open"] == 0  # never opened a DM


def test_destination_explicit_user_opens_dm():
    client = FakeClient(channels_pages=CHANNELS, users_pages=USERS)
    assert resolve_destination(client, "@alice") == _dm("U001")   # name → uid → DM
    assert resolve_destination(client, "U777XXX77") == _dm("U777XXX77")  # raw id → DM
    assert client.calls["conversations_open"] == 2


def test_destination_bare_name_prefers_channel():
    client = FakeClient(channels_pages=CHANNELS, users_pages=USERS)
    # "design" is a channel and not a user → resolves as the channel, no DM.
    assert resolve_destination(client, "design") == "C003"
    assert client.calls["conversations_open"] == 0


def test_destination_bare_name_falls_back_to_user_dm():
    client = FakeClient(channels_pages=CHANNELS, users_pages=USERS)
    # "alice" is not a channel → falls back to the user DM.
    assert resolve_destination(client, "alice") == _dm("U001")


def test_destination_bare_ambiguous_user_propagates():
    client = FakeClient(channels_pages=CHANNELS, users_pages=USERS)
    with pytest.raises(AmbiguousNameError):
        resolve_destination(client, "Bobby")  # not a channel; matches 2 users


def test_destination_not_found_raises():
    client = FakeClient(channels_pages=CHANNELS, users_pages=USERS)
    with pytest.raises(ValueError):
        resolve_destination(client, "ghost")  # archived/none + deactivated user


def test_destination_empty_raises():
    client = FakeClient(channels_pages=CHANNELS, users_pages=USERS)
    with pytest.raises(ValueError):
        resolve_destination(client, "   ")


def test_dm_cache_avoids_second_open():
    client = FakeClient(channels_pages=CHANNELS, users_pages=USERS)
    resolve_destination(client, "@alice")
    resolve_destination(client, "@alice")
    assert client.calls["conversations_open"] == 1  # second call served from cache


def test_dm_missing_scope_raises_clear_error():
    client = FakeClient(users_pages=USERS, raise_on={"conversations_open"})
    with pytest.raises(ValueError, match="im:write"):
        resolve_destination(client, "U777XXX77")
