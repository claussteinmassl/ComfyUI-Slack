"""Resolve human-typed Slack channel and user names into IDs.

Users shouldn't have to dig up raw IDs like ``C0B6SUZMHC6`` / ``U0456DEF``. This
module accepts a name *or* an ID anywhere a human enters one (the send nodes'
``channel`` input and the ``SLACK_ALLOWED_*`` allow-lists) and returns the ID.

Raw IDs pass through untouched with no API call. Names are matched
case-insensitively, with a leading ``#``/``@`` stripped. Lookups are backed by
lazily-built, thread-safe, per-process caches (the listener resolves from a
worker pool), refreshed at most once per minute when a name misses.

This module owns its own ID regexes and imports nothing from the rest of the
package, so it can be imported one-way by ``slack_client`` and ``socket_listener``
without creating a cycle. The Slack ``WebClient`` is always passed in.
"""

import logging
import re
import time
from threading import Lock

from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)

# Channel IDs: C (public), G (private/group), D (DM), Z (shared). User IDs: U
# (normal), W (enterprise-grid). Aligned with slack_client._CHANNEL_ID_RE.
_CHANNEL_ID_RE = re.compile(r"^[CGDZ][A-Z0-9]{8,}$")
_USER_ID_RE = re.compile(r"^[UW][A-Z0-9]{8,}$")

# Minimum seconds between cache rebuilds triggered by a name miss, so unknown
# names can't trigger a rebuild storm while a freshly-created entity still
# resolves without a process restart.
_REBUILD_INTERVAL = 60.0

# name(lower) -> channel id. None means "never built"; {} means "built, empty".
_channel_cache: "dict[str, str] | None" = None
_channel_built_at: float = 0.0
_channel_lock = Lock()

# name(lower) -> [user ids]. A list so a name shared by several users is
# detectable as ambiguous.
_user_cache: "dict[str, list[str]] | None" = None
_user_built_at: float = 0.0
_user_lock = Lock()


class AmbiguousNameError(ValueError):
    """A user name matched more than one Slack user.

    Subclasses ValueError so callers that already catch ValueError keep working.
    """


def _norm(value: str) -> str:
    """Strip whitespace and a single leading ``#``/``@``, then lowercase."""
    return value.strip().lstrip("#@").strip().lower()


def _monotonic() -> float:
    return time.monotonic()


# --------------------------------------------------------------------------- #
# Cache builders (called holding the relevant lock)
# --------------------------------------------------------------------------- #
def _build_channel_cache(client) -> "dict[str, str]":
    cache: "dict[str, str]" = {}
    cursor = None
    while True:
        resp = client.conversations_list(
            types="public_channel,private_channel",
            exclude_archived=True,
            limit=200,
            cursor=cursor,
        )
        for ch in resp.get("channels", []):
            name = ch.get("name")
            cid = ch.get("id")
            if name and cid and not ch.get("is_archived"):
                cache[name.lower()] = cid
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return cache


def _build_user_cache(client) -> "dict[str, list[str]]":
    cache: "dict[str, list[str]]" = {}

    def add(key: "str | None", uid: str) -> None:
        if not key:
            return
        k = key.strip().lower()
        if not k:
            return
        ids = cache.setdefault(k, [])
        if uid not in ids:
            ids.append(uid)

    cursor = None
    while True:
        resp = client.users_list(limit=200, cursor=cursor)
        for member in resp.get("members", []):
            uid = member.get("id")
            if not uid or member.get("deleted"):
                continue
            profile = member.get("profile") or {}
            add(member.get("name"), uid)          # handle, e.g. "jdoe"
            add(profile.get("display_name"), uid)  # display name
            add(profile.get("real_name"), uid)     # real name
        cursor = (resp.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    return cache


# --------------------------------------------------------------------------- #
# Single-value resolution
# --------------------------------------------------------------------------- #
def resolve_channel(client, value: str) -> str:
    """Resolve a channel name or ID to a channel ID.

    Raises ValueError if *value* is empty or no channel matches the name.
    """
    raw = (value or "").strip().lstrip("#").strip()
    if not raw:
        raise ValueError("No Slack channel given.")
    if _CHANNEL_ID_RE.match(raw):
        return raw  # already an ID — no API call

    key = raw.lower()
    global _channel_cache, _channel_built_at
    with _channel_lock:
        if _channel_cache is None:
            _channel_cache = _build_channel_cache(client)
            _channel_built_at = _monotonic()
        hit = _channel_cache.get(key)
        if hit is None and (_monotonic() - _channel_built_at) >= _REBUILD_INTERVAL:
            _channel_cache = _build_channel_cache(client)
            _channel_built_at = _monotonic()
            hit = _channel_cache.get(key)
    if hit:
        return hit
    raise ValueError(
        f'Slack channel "{value}" not found. Check the spelling, or invite the '
        "bot to the channel (`/invite @YourBot`) — private channels resolve only "
        "when the bot is a member. You can also use the raw channel ID (C…)."
    )


def resolve_user(client, value: str) -> str:
    """Resolve a user handle / display name / real name or ID to a user ID.

    Raises AmbiguousNameError if the name matches several users, or ValueError if
    *value* is empty or no user matches.
    """
    raw = (value or "").strip().lstrip("@").strip()
    if not raw:
        raise ValueError("No Slack user given.")
    if _USER_ID_RE.match(raw):
        return raw  # already an ID — no API call

    key = raw.lower()
    global _user_cache, _user_built_at
    with _user_lock:
        if _user_cache is None:
            _user_cache = _build_user_cache(client)
            _user_built_at = _monotonic()
        hits = _user_cache.get(key)
        if not hits and (_monotonic() - _user_built_at) >= _REBUILD_INTERVAL:
            _user_cache = _build_user_cache(client)
            _user_built_at = _monotonic()
            hits = _user_cache.get(key)
    if hits and len(hits) == 1:
        return hits[0]
    if hits:
        raise AmbiguousNameError(
            f'Slack user "{value}" matches {len(hits)} users ({", ".join(hits)}). '
            "Use the exact @handle or the raw user ID (U…)."
        )
    raise ValueError(
        f'Slack user "{value}" not found. Check the spelling, or use the raw '
        "user ID (U…)."
    )


# --------------------------------------------------------------------------- #
# Allow-list resolution (never raises — used during authorization)
# --------------------------------------------------------------------------- #
def resolve_allowed_channels(client, raw: "set[str]") -> "set[str]":
    """Map a mixed name/ID allow-list to channel IDs.

    Entries that fail to resolve are skipped and logged; never raises, so a
    missing scope or a typo can't lock everyone out. Raw IDs always survive.
    """
    out: "set[str]" = set()
    for entry in raw:
        try:
            out.add(resolve_channel(client, entry))
        except SlackApiError as e:
            err = e.response.get("error", "") if getattr(e, "response", None) else ""
            logger.warning(
                "ComfyUI-Slack: could not resolve allowed channel %r (%s). "
                "Name entries need the channels:read/groups:read scopes; the bot "
                "must also be a member of private channels. Skipping.", entry, err,
            )
        except ValueError as e:
            logger.warning("ComfyUI-Slack: %s Skipping allowed channel %r.", e, entry)
    return out


def resolve_allowed_users(client, raw: "set[str]") -> "set[str]":
    """Map a mixed name/ID allow-list to user IDs.

    Entries that fail to resolve (not found, ambiguous, missing scope) are
    skipped and logged; never raises. Raw IDs always survive.
    """
    out: "set[str]" = set()
    for entry in raw:
        try:
            out.add(resolve_user(client, entry))
        except SlackApiError as e:
            err = e.response.get("error", "") if getattr(e, "response", None) else ""
            logger.warning(
                "ComfyUI-Slack: could not resolve allowed user %r (%s). Name "
                "entries need the users:read scope. Skipping.", entry, err,
            )
        except ValueError as e:  # includes AmbiguousNameError
            logger.warning("ComfyUI-Slack: %s Skipping allowed user %r.", e, entry)
    return out
