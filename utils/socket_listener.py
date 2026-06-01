"""Slack Socket Mode listener: receives @mentions and button clicks, routes
them to ComfyUI workflows, and posts results back in-thread.

Runs entirely on a background daemon thread. The WebSocket callback only ACKs
and dispatches; all real work happens on a small worker pool so the 3-second
Slack ACK window is never missed.
"""

import time
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from threading import Event

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

_web_client: WebClient | None = None
_bot_user_id: str | None = None
_registry: dict = {}


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
# Core: plan a resolved workflow against the request, then run or confirm
# --------------------------------------------------------------------------- #
def _replace_buttons(channel: str, message_ts: str | None, text: str) -> None:
    """Swap a button message's blocks for a plain status line. Cosmetic only."""
    if not message_ts:
        return
    try:
        _web_client.chat_update(channel=channel, ts=message_ts, text=text, blocks=[])
    except Exception:  # noqa: BLE001 - cosmetic only
        pass


def _fan_out(workflow, req, batches, channel: str, thread_ts: str | None) -> None:
    """Queue one ComfyUI run per batch, then post a single summary reply."""
    ids = [comfy_trigger.run(workflow, req, batch) for batch in batches]
    slack_messages.post_text(
        _web_client, channel,
        f"Queued :white_check_mark: {len(ids)} run(s) of *{workflow.label}* — "
        "results will post here as each finishes.",
        thread_ts,
    )


def _dispatch_plan(workflow, req, channel: str, message_ts: str | None,
                   thread_ts: str | None) -> None:
    """Plan *workflow* against *req* (M-vs-N), then run, fan out, or confirm.

    Shared by the direct mention path and the post-disambiguation button path.
    *message_ts* is the button message to update (None from a fresh mention).
    """
    plan = router.plan_run(workflow, req)

    if isinstance(plan, router.Rejected):
        _replace_buttons(channel, message_ts, f"Can't run *{workflow.label}* as sent.")
        slack_messages.post_text(_web_client, channel, plan.reason, thread_ts)
    elif isinstance(plan, router.RunOnce):
        _replace_buttons(channel, message_ts, f"Running *{workflow.label}*…")
        prompt_id = comfy_trigger.run(workflow, req, plan.images)
        slack_messages.post_text(
            _web_client, channel,
            f"Queued :white_check_mark: *{workflow.label}* (id `{prompt_id}`) — "
            "the result will post here shortly.",
            thread_ts,
        )
    elif isinstance(plan, router.ConfirmFanOut):
        # Clear any stale choice buttons; ask the confirm question in a fresh message.
        # The request travels inside the button value (stateless); the batches are
        # re-derived from it on click, so nothing is stashed server-side.
        _replace_buttons(channel, message_ts,
                         f"One more question about *{workflow.label}*…")
        slack_messages.post_confirm_buttons(
            _web_client, channel, thread_ts, req,
            f"*{workflow.label}* takes {plan.n} image(s) per run, and you sent "
            f"{plan.m}. I can run it {plan.m // plan.n} times "
            f"({plan.n} image(s) each). Continue?",
            workflow.name,
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
            paths, kind, ids = slack_messages.download_slack_files(files, _input_dir())
            req.input_paths, req.input_kind, req.file_ids = paths, kind, ids

        route = router.select(req, _registry)
        if isinstance(route, Rejected):
            slack_messages.post_text(_web_client, req.channel, route.reason, req.thread_ts)
        elif isinstance(route, NeedsChoice):
            slack_messages.post_choice_buttons(
                _web_client, req.channel, req.thread_ts, req, route.candidates
            )
        elif isinstance(route, Resolved):
            _dispatch_plan(route.template, req, req.channel, None, req.thread_ts)
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
        # The request is reconstructed entirely from the button value (stateless),
        # so any connected machine can handle this click.
        req, action = slack_messages.decode_button_value(actions[0].get("value", "{}"))
        if req is None:
            slack_messages.post_text(
                _web_client, channel,
                "That choice expired — please @mention me again.", thread_ts,
            )
            return

        # Cancel needs no inputs — handle it before touching Slack/files.
        if action.get("kind") == "cancel":
            _handle_confirm(req, action.get("n"), "cancel",
                            channel, message_ts, thread_ts)
            return

        # Re-materialize input files on THIS machine (the click may have landed on
        # a machine that never downloaded them). download_files_by_id is idempotent.
        if req.file_ids:
            paths, kind, ids = slack_messages.download_files_by_id(
                _web_client, req.file_ids, _input_dir()
            )
            req.input_paths, req.input_kind, req.file_ids = paths, kind, ids

        # Continue on a fan-out confirmation.
        if action.get("kind") == "confirm":
            _handle_confirm(req, action.get("n"), "confirm",
                            channel, message_ts, thread_ts)
            return

        # Otherwise this is a workflow-choice click.
        name = action.get("name")
        workflow = workflow_registry.get(_registry, name)
        if workflow is None:
            slack_messages.post_text(
                _web_client, channel, f"Workflow '{name}' is no longer available.",
                req.thread_ts,
            )
            return

        # Plan first: a chosen workflow may still need a fan-out confirmation,
        # so let _dispatch_plan decide whether to run or ask (it updates the
        # button message itself).
        _dispatch_plan(workflow, req, channel, message_ts, req.thread_ts)
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        prefix = slack_messages.mention_prefix(payload.get("user", {}).get("id", ""))
        slack_messages.post_text(
            _web_client, channel, f"{prefix}:warning: Failed: {e}", thread_ts
        )


def _handle_confirm(req, workflow_name: str | None, kind: str, channel: str,
                    message_ts: str | None, thread_ts: str | None) -> None:
    """Act on a Continue/Cancel click for a fan-out confirmation.

    *req* is the reconstructed request; batches are re-derived deterministically
    via router.plan_run (they were never stored server-side).
    """
    workflow = workflow_registry.get(_registry, workflow_name) if workflow_name else None
    label = workflow.label if workflow else (workflow_name or "workflow")

    if kind == "cancel":
        _replace_buttons(channel, message_ts, f"Cancelled *{label}*.")
        return

    if workflow is None:
        _replace_buttons(channel, message_ts,
                         f"Workflow '{workflow_name}' is no longer available.")
        return

    plan = router.plan_run(workflow, req)
    if isinstance(plan, router.ConfirmFanOut):
        _replace_buttons(channel, message_ts, f"Running *{label}*…")
        _fan_out(workflow, req, plan.batches, channel, thread_ts)
    elif isinstance(plan, router.RunOnce):
        _replace_buttons(channel, message_ts, f"Running *{label}*…")
        prompt_id = comfy_trigger.run(workflow, req, plan.images)
        slack_messages.post_text(
            _web_client, channel,
            f"Queued :white_check_mark: *{label}* (id `{prompt_id}`) — "
            "the result will post here shortly.",
            thread_ts,
        )
    else:  # Rejected — images no longer line up (shouldn't normally happen)
        _replace_buttons(channel, message_ts, f"Can't run *{label}* as sent.")
        slack_messages.post_text(_web_client, channel, plan.reason, thread_ts)


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
