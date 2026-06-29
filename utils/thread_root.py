"""Thread-root bookkeeping for the Slack Thread Start node.

A workflow that wants several Slack outputs in one thread needs a single root
message whose ``ts`` is fed (as ``thread_ts``) into every send node. The root is
created with ``chat_postMessage`` — that reliably returns the message ``ts``,
unlike a file upload — and, in *reuse* mode, remembered in-process so repeated
queues of the same workflow keep appending to the same thread instead of opening
a new one each time.

The cache lives only for the current ComfyUI session: after a restart (or when
the cache key changes — e.g. a different channel/header) a fresh thread is
started. The "new thread each run" mode bypasses the cache entirely.

The thread reference handed to the send nodes is not a bare ``ts`` but a
``"<channel_id>@<ts>"`` pair: the thread already fixes the destination channel,
so the send node recovers it from the reference and can ignore its own
``channel`` field. A bare ``ts`` (e.g. injected by the Slack listener, which
also injects its own ``channel``) is still accepted — see ``split_thread_ref``.
"""

from .slack_client import post_message_to_slack
from .slack_resolve import resolve_destination
from .markdown_to_slack import markdown_to_mrkdwn

# Slack rejects an empty message body, so an empty header falls back to this.
_FALLBACK_HEADER = "🧵"

# Separator between the channel id and the ts in a thread reference. Neither a
# Slack channel id ([CGDZ][A-Z0-9]+) nor a ts (digits + a dot) ever contains it.
_THREAD_REF_SEP = "@"

# key -> thread reference, for reuse mode. Process-local; cleared on restart.
_thread_roots: dict[str, str] = {}


def encode_thread_ref(channel_id: str, ts: str) -> str:
    """Pack a resolved channel id and a message ts into one thread reference."""
    return f"{channel_id}{_THREAD_REF_SEP}{ts}"


def split_thread_ref(thread_ref: str) -> "tuple[str | None, str]":
    """Split a thread reference into ``(channel, ts)``.

    A reference produced by ``encode_thread_ref`` (``"<channel_id>@<ts>"``)
    yields its embedded channel, so a send node posts into the thread without
    needing its own ``channel`` field. A bare ts (no separator) yields
    ``(None, ts)`` — the caller keeps using its own channel, as the listener path
    requires.
    """
    if _THREAD_REF_SEP in thread_ref:
        channel, _, ts = thread_ref.partition(_THREAD_REF_SEP)
        return channel or None, ts
    return None, thread_ref


def resolve_thread_root(client, channel: str, header: str, reuse: bool, key: str) -> str:
    """Return the thread reference of the root, posting it if necessary.

    *header* is translated from Markdown to Slack mrkdwn. The returned value is a
    ``"<channel_id>@<ts>"`` reference (see ``encode_thread_ref``) so the channel
    travels with the thread. When *reuse* is true the root for *key* is created
    once and reused on later calls; otherwise a new root is posted every call.
    """
    text = markdown_to_mrkdwn(header) if header.strip() else _FALLBACK_HEADER
    # Resolve the destination up front so the channel id can travel with the
    # thread reference. post_message_to_slack re-resolves, but an id passes
    # through with no further API call.
    channel_id = resolve_destination(client, channel)

    if not reuse:
        ts = post_message_to_slack(client, channel_id, text)
        return encode_thread_ref(channel_id, ts)

    ref = _thread_roots.get(key)
    if ref is None:
        ts = post_message_to_slack(client, channel_id, text)
        ref = encode_thread_ref(channel_id, ts)
        _thread_roots[key] = ref
    return ref
