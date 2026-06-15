from ..utils.slack_client import get_client
from ..utils.thread_root import resolve_thread_root


class SlackThreadStart:
    """Posts a root message to Slack and outputs its ``thread_ts``.

    Wire the ``thread_ts`` output into the ``thread_ts`` input of any Send-to-Slack
    node to make all of them reply in the same thread. The connection also forces
    those send nodes to run after this one, so the root always exists first.

    Two modes:
      * "New thread each run"   — a fresh root (and thread) on every execution.
      * "Reuse existing thread" — the same root is kept across re-runs of the
        workflow (within the ComfyUI session), so new results append to the
        ongoing thread.
    """

    CATEGORY = "Slack"
    OUTPUT_NODE = False
    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("thread_ts",)
    FUNCTION = "start"

    MODES = ["New thread each run", "Reuse existing thread"]
    _DEFAULT_HEADER = "🧵 ComfyUI"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "channel": ("STRING", {"default": "", "tooltip": "Channel or user: #general, @alice, or a raw ID. A user (@name or U…) starts the thread in a direct message. Names resolve automatically; the bot must be a member of private channels."}),
                "mode": (cls.MODES, {"tooltip": "'New thread each run' posts a fresh root every execution. 'Reuse existing thread' keeps the same thread across re-runs (within this ComfyUI session) so new results append to it."}),
            },
            "optional": {
                "header": ("STRING", {"default": cls._DEFAULT_HEADER, "multiline": True, "tooltip": "Text of the root message that opens the thread. Standard Markdown is translated to Slack formatting."}),
            },
            "hidden": {"unique_id": "UNIQUE_ID"},
        }

    @classmethod
    def IS_CHANGED(cls, channel, mode, header=_DEFAULT_HEADER, unique_id=None):
        # "New thread each run" -> NaN is never equal to itself, so ComfyUI
        # re-executes the node on every queue and posts a fresh root. "Reuse"
        # returns a stable key, so the node is cached and its ts is reused.
        if mode == "New thread each run":
            return float("nan")
        return f"{unique_id}|{channel}|{header}"

    def start(self, channel, mode, header=_DEFAULT_HEADER, unique_id=None):
        reuse = mode != "New thread each run"
        key = f"{unique_id}|{channel}|{header}"
        ts = resolve_thread_root(get_client(), channel, header, reuse, key)
        return (ts,)
