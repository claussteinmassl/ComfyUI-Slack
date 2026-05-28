"""Slack payload parsing, authenticated file download, and message helpers."""

import json
import os
import re
import urllib.request
from dataclasses import dataclass

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
    input_path: str | None = None   # filename inside the ComfyUI input dir
    input_kind: str | None = None   # "image" | "video" | None


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


def post_text(client, channel: str, text: str, thread_ts: str | None) -> None:
    """Post a threaded status/error reply. Best-effort; swallows API errors."""
    try:
        client.chat_postMessage(
            channel=channel, text=text, thread_ts=thread_ts or None
        )
    except SlackApiError as e:
        print(f"[ComfyUI-Slack] chat_postMessage failed: {e}")


def _choice_blocks(text: str, pid: str, candidates) -> list[dict]:
    buttons = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": w.label[:75]},
            "value": json.dumps({"pid": pid, "name": w.name}),
            "action_id": f"slack_comfy_choose_{w.name}",
        }
        for w in candidates
    ]
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "actions", "elements": buttons},
    ]


def post_choice_buttons(client, channel: str, thread_ts: str | None,
                        pid: str, candidates) -> None:
    """Post a Block Kit message with one button per candidate workflow."""
    text = "Which workflow should I run?"
    client.chat_postMessage(
        channel=channel,
        thread_ts=thread_ts or None,
        text=text,
        blocks=_choice_blocks(text, pid, candidates),
    )
