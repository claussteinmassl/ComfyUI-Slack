"""Guarded, once-only startup of the Socket Mode listener thread.

Designed so it can NEVER crash ComfyUI's custom-node loading: the listener is
opt-in (SLACK_LISTENER_ENABLED), missing config only logs a warning, and the
whole body is wrapped so any exception is swallowed.
"""

import threading

from . import config

_started = False
_thread: threading.Thread | None = None
_lock = threading.Lock()


def maybe_start_listener() -> None:
    global _started, _thread

    if not config.listener_enabled():
        return  # opt-in: send-only users are unaffected

    with _lock:
        if _started or (_thread is not None and _thread.is_alive()):
            return  # guard against double-start on re-import / reload

        if not config.app_token() or not config.bot_token():
            print("[ComfyUI-Slack] Listener enabled but SLACK_APP_TOKEN and/or "
                  "SLACK_BOT_TOKEN is missing; not starting.")
            return
        if not config.workflow_dir():
            print("[ComfyUI-Slack] Listener enabled but SLACK_WORKFLOW_DIR is not "
                  "set; not starting.")
            return

        try:
            from . import socket_listener

            t = threading.Thread(
                target=socket_listener.run_forever,
                name="slack-comfy-listener",
                daemon=True,
            )
            t.start()
            _thread = t
            _started = True
            print("[ComfyUI-Slack] Socket Mode listener started.")
        except Exception as e:  # noqa: BLE001 - must not break ComfyUI load
            print(f"[ComfyUI-Slack] Failed to start listener: {e}")
