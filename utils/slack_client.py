import os
import re

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .slack_resolve import resolve_destination

_CHANNEL_ID_RE = re.compile(r'^[CGDZ][A-Z0-9]{8,}$')


def get_client() -> WebClient:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise EnvironmentError(
            "SLACK_BOT_TOKEN environment variable is not set. "
            "Set it to your Slack bot token (xoxb-...) before running ComfyUI."
        )
    return WebClient(token=token)


def _resolve_and_validate(client: WebClient, channel: str) -> str:
    # Accept a channel or a user. resolve_destination passes IDs through
    # untouched (no API call), turns "#general" into a C… id, and turns a user
    # ("@alice" / U…) into the D… id of a DM. The returned id always matches
    # _CHANNEL_ID_RE below.
    channel = resolve_destination(client, channel)
    if not _CHANNEL_ID_RE.match(channel):  # defense-in-depth; resolve_destination already guarantees this
        raise ValueError(
            f"'{channel}' is not a valid Slack channel or user ID. "
            "Enter a channel (#general), a user (@alice), or a raw ID."
        )
    return channel


def upload_file_to_slack(
    client: WebClient,
    channel: str,
    file_path: str,
    filename: str,
    title: str = "",
    message: str = "",
    thread_ts: str | None = None,
) -> None:
    channel = _resolve_and_validate(client, channel)
    try:
        client.files_upload_v2(
            channel=channel,
            file=file_path,
            filename=filename,
            title=title or filename,
            initial_comment=message or None,
            thread_ts=thread_ts or None,
        )
    except SlackApiError as e:
        raise RuntimeError(f"Slack upload failed: {e.response['error']}") from e


def post_message_to_slack(
    client: WebClient,
    channel: str,
    text: str,
    thread_ts: str | None = None,
) -> str:
    """Post a message and return its ``ts`` (the timestamp that identifies the
    message — usable as a ``thread_ts`` to reply under it)."""
    channel = _resolve_and_validate(client, channel)
    try:
        resp = client.chat_postMessage(
            channel=channel,
            text=text,
            mrkdwn=True,
            thread_ts=thread_ts or None,
        )
    except SlackApiError as e:
        raise RuntimeError(f"Slack message failed: {e.response['error']}") from e
    return resp["ts"]
