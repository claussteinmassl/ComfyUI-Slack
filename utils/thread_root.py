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
"""

from .slack_client import post_message_to_slack
from .markdown_to_slack import markdown_to_mrkdwn

# Slack rejects an empty message body, so an empty header falls back to this.
_FALLBACK_HEADER = "🧵"

# key -> root message ts, for reuse mode. Process-local; cleared on restart.
_thread_roots: dict[str, str] = {}


def resolve_thread_root(client, channel: str, header: str, reuse: bool, key: str) -> str:
    """Return the ``ts`` of the thread root, posting it if necessary.

    *header* is translated from Markdown to Slack mrkdwn. When *reuse* is true the
    root for *key* is created once and reused on later calls; otherwise a new root
    is posted every call.
    """
    text = markdown_to_mrkdwn(header) if header.strip() else _FALLBACK_HEADER

    if not reuse:
        return post_message_to_slack(client, channel, text)

    ts = _thread_roots.get(key)
    if ts is None:
        ts = post_message_to_slack(client, channel, text)
        _thread_roots[key] = ts
    return ts
