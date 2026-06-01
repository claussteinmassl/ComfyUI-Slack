"""Slack payload parsing, authenticated file download, and message helpers."""

import json
import os
import re
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass, field
from threading import Lock
from uuid import uuid4

from slack_sdk.errors import SlackApiError

from . import config
from . import router

_MENTION_RE = re.compile(r"<@[A-Z0-9]+>")
_UNSAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


@dataclass
class TriggerRequest:
    prompt: str
    channel: str
    thread_ts: str
    user: str
    override: str | None = None
    input_paths: list[str] = field(default_factory=list)  # filenames in input dir
    input_kind: str | None = None   # "image" | "video" | None
    file_ids: list[str] = field(default_factory=list)  # Slack file IDs, aligned with input_paths

    @property
    def input_path(self) -> str | None:
        """First input path -- back-compat shim for single-input/video sites."""
        return self.input_paths[0] if self.input_paths else None


def parse_app_mention(event: dict, bot_user_id: str | None) -> TriggerRequest:
    """Build a TriggerRequest from an app_mention event payload."""
    raw_text = event.get("text", "")
    # Drop every <@USER> token (the bot mention, plus any others).
    text = _MENTION_RE.sub("", raw_text).strip()
    override, prompt = router.strip_override(text)

    channel = event.get("channel", "")
    # Reply in the existing thread if present, else start one on the mention.
    thread_ts = event.get("thread_ts") or event.get("ts", "")

    return TriggerRequest(
        prompt=prompt,
        channel=channel,
        thread_ts=thread_ts,
        user=event.get("user", ""),
        override=override,
    )


def _sanitize(name: str) -> str:
    name = os.path.basename(name or "file")
    name = _UNSAFE_RE.sub("_", name)
    return name or "file"


def download_slack_file(file_obj: dict, dest_dir: str) -> tuple[str, str]:
    """Download a Slack file into *dest_dir*.

    Returns (filename, kind) where kind is "image" or "video". Raises
    RuntimeError on unsupported type or oversize file.
    """
    mimetype = file_obj.get("mimetype", "")
    if mimetype.startswith("image/"):
        kind = "image"
    elif mimetype.startswith("video/"):
        kind = "video"
    else:
        raise RuntimeError(
            f"Unsupported attachment type '{mimetype or 'unknown'}'. "
            "Attach an image or a video."
        )

    size = file_obj.get("size") or 0
    limit = config.max_input_mb() * 1024 * 1024
    if size and size > limit:
        raise RuntimeError(
            f"Attachment is {size // (1024 * 1024)} MB, over the "
            f"{config.max_input_mb()} MB limit (SLACK_MAX_INPUT_MB)."
        )

    url = file_obj.get("url_private_download") or file_obj.get("url_private")
    if not url:
        raise RuntimeError("Slack file has no downloadable URL.")

    filename = f"slack_{file_obj.get('id', 'file')}_{_sanitize(file_obj.get('name', ''))}"
    dest = os.path.join(dest_dir, filename)

    # Idempotent: the filename is deterministic, so if this machine already
    # fetched the file (e.g. at mention time) skip the re-download. This is what
    # lets a button click be handled by *any* machine -- it materializes the
    # input locally on demand, but never twice.
    if os.path.exists(dest):
        return filename, kind

    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {config.bot_token()}"}
    )
    with urllib.request.urlopen(request, timeout=30) as resp:
        downloaded = 0
        with open(dest, "wb") as out:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                downloaded += len(chunk)
                if downloaded > limit:
                    out.close()
                    os.unlink(dest)
                    raise RuntimeError(
                        f"Attachment exceeds the {config.max_input_mb()} MB limit."
                    )
                out.write(chunk)

    return filename, kind


def download_slack_files(files: list[dict], dest_dir: str) -> tuple[list[str], str, list[str]]:
    """Download every attachment in *files* into *dest_dir*.

    Returns (paths, kind, ids) where *ids* are the Slack file IDs aligned with
    *paths*. All-images -> (N paths, "image", N ids); exactly one video and
    nothing else -> (1 path, "video", 1 id). Raises RuntimeError on a mixed set,
    on multiple videos, or (via download_slack_file) on an unsupported type.
    """
    images, image_ids, videos, video_ids = [], [], [], []
    for f in files:
        name, kind = download_slack_file(f, dest_dir)
        if kind == "image":
            images.append(name)
            image_ids.append(f.get("id", ""))
        else:
            videos.append(name)
            video_ids.append(f.get("id", ""))

    if videos and images:
        raise RuntimeError("Attach images *or* a single video, not both.")
    if len(videos) > 1:
        raise RuntimeError("Only one video can be processed per request.")
    if videos:
        return videos, "video", video_ids
    return images, "image", image_ids


def download_files_by_id(client, file_ids: list[str],
                         dest_dir: str) -> tuple[list[str], str, list[str]]:
    """Resolve Slack *file_ids* via files.info and download them into *dest_dir*.

    Used on the button-click path so whichever machine handles the click can
    re-materialize the input files locally (their on-disk filenames are
    deterministic, so already-present files are skipped). Returns the same
    (paths, kind, ids) tuple as :func:`download_slack_files`.
    """
    file_objs = []
    for fid in file_ids:
        obj = client.files_info(file=fid).get("file")
        if not obj:
            raise RuntimeError(f"Slack file '{fid}' is no longer available.")
        file_objs.append(obj)
    return download_slack_files(file_objs, dest_dir)


def mention_prefix(user_id: str) -> str:
    """Return '<@user> ' when user notifications are enabled, else ''."""
    if user_id and config.notify_user():
        return f"<@{user_id}> "
    return ""


def post_text(client, channel: str, text: str, thread_ts: str | None) -> None:
    """Post a threaded status/error reply. Best-effort; swallows API errors."""
    try:
        client.chat_postMessage(
            channel=channel, text=text, thread_ts=thread_ts or None
        )
    except SlackApiError as e:
        print(f"[ComfyUI-Slack] chat_postMessage failed: {e}")


# --------------------------------------------------------------------------- #
# Stateless button payloads
#
# Everything a click needs to reconstruct the request travels INSIDE the Slack
# button ``value`` (the request context under key "s", plus small action fields
# like the chosen workflow name). No server-side state -> any machine connected
# to the same Slack app can handle the click, even one that never posted the
# buttons. Input files are re-materialized on the handling machine from the
# Slack file IDs carried in the state (see download_files_by_id).
# --------------------------------------------------------------------------- #
_VALUE_LIMIT = 1900            # Slack caps button ``value`` at 2000 chars.
_OVERFLOW_MAX = 64
_overflow: "OrderedDict[str, TriggerRequest]" = OrderedDict()
_overflow_lock = Lock()


def _stash_overflow(req: TriggerRequest) -> str:
    """Fallback for the rare oversized state: keep it in-process, ref it by id.

    Only hit when the inline state would exceed the button-value limit (a very
    long prompt). Degrades to single-machine behaviour for that one message --
    a click landing on another machine won't find the ref and reports expiry.
    """
    pid = uuid4().hex[:12]
    with _overflow_lock:
        _overflow[pid] = req
        while len(_overflow) > _OVERFLOW_MAX:
            _overflow.popitem(last=False)
    return pid


def _pop_overflow(pid: str):
    with _overflow_lock:
        return _overflow.pop(pid, None)


def _req_state(req: TriggerRequest) -> dict:
    return {
        "p": req.prompt,
        "c": req.channel,
        "t": req.thread_ts,
        "u": req.user,
        "o": req.override,
        "k": req.input_kind,
        "f": list(req.file_ids),
    }


def _button_value(req: TriggerRequest, **action) -> str:
    """Encode *req* + *action* into a button ``value`` string.

    Inlines the full request state when it fits; otherwise stashes the state
    in-process and references it by id (the "r" key).
    """
    body = dict(action)
    body["s"] = _req_state(req)
    encoded = json.dumps(body, separators=(",", ":"))
    if len(encoded) <= _VALUE_LIMIT:
        return encoded
    body = dict(action)
    body["r"] = _stash_overflow(req)
    return json.dumps(body, separators=(",", ":"))


def decode_button_value(value: str) -> tuple[TriggerRequest | None, dict]:
    """Decode a button ``value`` into (request_or_None, action_fields).

    Returns ``(None, action)`` when the request can't be reconstructed (an
    overflow ref that this machine doesn't hold) so the caller can report expiry.
    """
    obj = json.loads(value or "{}")
    action = {k: v for k, v in obj.items() if k not in ("s", "r")}
    if "s" in obj:
        s = obj["s"]
        req = TriggerRequest(
            prompt=s.get("p", ""),
            channel=s.get("c", ""),
            thread_ts=s.get("t", ""),
            user=s.get("u", ""),
            override=s.get("o"),
            input_kind=s.get("k"),
            file_ids=list(s.get("f") or []),
        )
        return req, action
    if "r" in obj:
        return _pop_overflow(obj["r"]), action
    return None, action


def _choice_blocks(text: str, req: TriggerRequest, candidates) -> list[dict]:
    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": w.label[:75]},
            "value": _button_value(req, name=w.name),
            "action_id": f"slack_comfy_choose_{w.name}",
        }
        for w in candidates
    ]
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "elements": buttons},
    ]


def post_choice_buttons(client, channel: str, thread_ts: str | None,
                        req: TriggerRequest, candidates) -> None:
    """Post a Block Kit message with one button per candidate workflow."""
    text = "Which workflow should I run?"
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts or None,
        text=text,
        blocks=_choice_blocks(text, req, candidates),
    )


def _confirm_blocks(text: str, req: TriggerRequest, workflow_name: str) -> list[dict]:
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "elements": [
            {"type": "button", "style": "primary",
             "text": {"type": "plain_text", "text": "Continue"},
             "value": _button_value(req, kind="confirm", n=workflow_name),
             "action_id": "slack_comfy_confirm"},
            {"type": "button",
             "text": {"type": "plain_text", "text": "Cancel"},
             "value": _button_value(req, kind="cancel", n=workflow_name),
             "action_id": "slack_comfy_cancel"},
        ]},
    ]


def post_confirm_buttons(client, channel: str, thread_ts: str | None,
                         req: TriggerRequest, text: str, workflow_name: str) -> None:
    """Post a Continue/Cancel confirmation prompt."""
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts or None,
        text=text,
        blocks=_confirm_blocks(text, req, workflow_name),
    )
