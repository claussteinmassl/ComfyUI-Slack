"""Slack Socket Mode listener: receives @mentions and button clicks, routes
them to ComfyUI workflows, and posts results back in-thread.

Runs entirely on a background daemon thread. The WebSocket callback only ACKs
and dispatches; all real work happens on a small worker pool so the 3-second
Slack ACK window is never missed.
"""

import json
import time
import traceback
from collections import OrderedDict, deque
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from uuid import uuid4

from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from . import comfy_trigger, config, router, slack_messages, workflow_registry
from .router import NeedsChoice, Rejected, Resolved

try:
    import folder_paths
except Exception:  # pragma: no cover - only available inside ComfyUI
    folder_paths = None

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="slack-comfy")
_recent_event_ids: deque = deque(maxlen=256)

_PENDING_MAX = 64
_pending: "OrderedDict[str, slack_messages.TriggerRequest]" = OrderedDict()
_pending_lock = Lock()

_web_client: WebClient | None = None
_bot_user_id: str | None = None
_registry: dict = {}


# --------------------------------------------------------------------------- #
# Pending (button) store
# --------------------------------------------------------------------------- #
def _stash_pending(req) -> str:
    pid = uuid4().hex[:12]
    with _pending_lock:
        _pending[pid] = req
        while len(_pending) > _PENDING_MAX:
            _pending.popitem(last=False)
    return pid


def _pop_pending(pid: str):
    with _pending_lock:
        return _pending.pop(pid, None)


# --------------------------------------------------------------------------- #
# Authorization
# --------------------------------------------------------------------------- #
def _authorized(req) -> bool:
    users, channels = config.allowed_users(), config.allowed_channels()
    if not users and not channels:
        return False  # default-deny
    return req.user in users or req.channel in channels


def _input_dir() -> str:
    if folder_paths is not None:
        return folder_paths.get_input_directory()
    return "."


# --------------------------------------------------------------------------- #
# Core: run a resolved workflow and acknowledge in-thread
# --------------------------------------------------------------------------- #
def _run_workflow(workflow, req) -> None:
    prompt_id = comfy_trigger.run(workflow, req)
    slack_messages.post_text(
        _web_client, req.channel,
        f"Queued :white_check_mark: *{workflow.label}* (id `{prompt_id}`) — "
        "the result will post here shortly.",
        req.thread_ts,
    )


# --------------------------------------------------------------------------- #
# Handlers (run on the worker pool)
# --------------------------------------------------------------------------- #
def _handle_mention(event: dict) -> None:
    channel = event.get("channel", "")
    thread_ts = event.get("thread_ts") or event.get("ts", "")
    try:
        req = slack_messages.parse_app_mention(event, _bot_user_id)

        if not _authorized(req):
            slack_messages.post_text(
                _web_client, req.channel,
                "You're not authorized to trigger workflows here. Ask the admin "
                "to add your user or this channel to SLACK_ALLOWED_USERS / "
                "SLACK_ALLOWED_CHANNELS.",
                req.thread_ts,
            )
            return

        if req.prompt.lower() in ("help", "") and not event.get("files"):
            _post_help(req)
            return

        files = event.get("files") or []
        if files:
            name, kind = slack_messages.download_slack_file(files[0], _input_dir())
            req.input_path, req.input_kind = name, kind

        route = router.select(req, _registry)
        if isinstance(route, Rejected):
            slack_messages.post_text(_web_client, req.channel, route.reason, req.thread_ts)
        elif isinstance(route, NeedsChoice):
            pid = _stash_pending(req)
            slack_messages.post_choice_buttons(
                _web_client, req.channel, req.thread_ts, pid, route.candidates
            )
        elif isinstance(route, Resolved):
            _run_workflow(route.template, req)
    except Exception as e:  # noqa: BLE001 - never let the worker die silently
        traceback.print_exc()
        prefix = slack_messages.mention_prefix(event.get("user", ""))
        slack_messages.post_text(
            _web_client, channel, f"{prefix}:warning: Failed: {e}", thread_ts
        )


def _handle_button(payload: dict) -> None:
    actions = payload.get("actions") or []
    if not actions:
        return
    container = payload.get("container", {})
    channel = payload.get("channel", {}).get("id", "")
    message_ts = container.get("message_ts")
    thread_ts = payload.get("message", {}).get("thread_ts") or message_ts

    try:
        value = json.loads(actions[0].get("value", "{}"))
        pid, name = value.get("pid"), value.get("name")

        req = _pop_pending(pid) if pid else None
        if req is None:
            slack_messages.post_text(
                _web_client, channel,
                "That choice expired — please @mention me again.", thread_ts,
            )
            return

        workflow = workflow_registry.get(_registry, name)
        if workflow is None:
            slack_messages.post_text(
                _web_client, channel, f"Workflow '{name}' is no longer available.",
                req.thread_ts,
            )
            return

        # Replace the buttons with a running notice.
        try:
            _web_client.chat_update(
                channel=channel, ts=message_ts,
                text=f"Running *{workflow.label}*…", blocks=[],
            )
        except Exception:  # noqa: BLE001 - cosmetic only
            pass

        _run_workflow(workflow, req)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        prefix = slack_messages.mention_prefix(payload.get("user", {}).get("id", ""))
        slack_messages.post_text(
            _web_client, channel, f"{prefix}:warning: Failed: {e}", thread_ts
        )


def _post_help(req) -> None:
    lines = ["*Available workflows:*"]
    for w in workflow_registry.list_all(_registry):
        desc = f" — {w.description}" if w.description else ""
        lines.append(f"• `[{w.name}]` ({w.modality}){desc}")
    lines.append("\nMention me with a prompt, optionally attach an image/video, "
                 "or prefix with `[name]` to pick a specific workflow.")
    slack_messages.post_text(_web_client, req.channel, "\n".join(lines), req.thread_ts)


# --------------------------------------------------------------------------- #
# WebSocket dispatch (runs on the SDK's WS thread — must stay fast)
# --------------------------------------------------------------------------- #
def _on_request(client: SocketModeClient, req: SocketModeRequest) -> None:
    # ACK first, always, within Slack's 3s window.
    client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))

    if req.type == "events_api":
        event = req.payload.get("event", {})
        if event.get("type") != "app_mention":
            return
        if event.get("user") and event.get("user") == _bot_user_id:
            return  # ignore our own posts
        eid = req.payload.get("event_id")
        if eid in _recent_event_ids:
            return  # dedupe Slack redeliveries
        _recent_event_ids.append(eid)
        _executor.submit(_handle_mention, event)

    elif req.type == "interactive" and req.payload.get("type") == "block_actions":
        _executor.submit(_handle_button, req.payload)


def build_client() -> SocketModeClient:
    global _web_client, _bot_user_id
    _web_client = WebClient(token=config.bot_token())
    try:
        _bot_user_id = _web_client.auth_test().get("user_id")
    except Exception as e:  # noqa: BLE001
        print(f"[ComfyUI-Slack] auth_test failed (self-loop guard disabled): {e}")
    sm = SocketModeClient(app_token=config.app_token(), web_client=_web_client)
    sm.socket_mode_request_listeners.append(_on_request)
    return sm


def run_forever() -> None:
    """Thread target: load the registry, connect, and stay up forever."""
    global _registry
    _registry = workflow_registry.load(config.workflow_dir())
    if not _registry:
        print("[ComfyUI-Slack] No usable workflows; listener will idle. "
              "Check SLACK_WORKFLOW_DIR / manifest.json.")

    while True:
        try:
            client = build_client()
            client.connect()
            print("[ComfyUI-Slack] Socket Mode listener connected.")
            Event().wait()  # block; the SDK runs its own background threads
        except Exception as e:  # noqa: BLE001 - never let the thread die
            print(f"[ComfyUI-Slack] listener error, reconnecting in 5s: {e}")
            time.sleep(5)
