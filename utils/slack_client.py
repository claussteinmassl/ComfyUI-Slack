import os
import re

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from .slack_resolve import resolve_channel

_CHANNEL_ID_RE = re.compile(r'^[CGDZ][A-Z0-9]{8,}$')


def get_client() -> WebClient:
    token = os.environ.get("SLACK_BOT_TOKEN")
    if not token:
        raise EnvironmentError(
            "SLACK_BOT_TOKEN environment variable is not set. "
            "Set it to your Slack bot token (xoxb-...) before running ComfyUI."
        )
    return WebClient(token=token)


def upload_file_to_slack(
    client: WebClient,
    channel: str,
    file_path: str,
    filename: str,
    title: str = "",
    message: str = "",
    thread_ts: str | None = None,
) -> None:
    # Accept a channel name or ID; resolve_channel passes IDs through untouched
    # (no API call) and turns names like "#general" into a C… ID.
    channel = resolve_channel(client, channel)
    if not _CHANNEL_ID_RE.match(channel):  # defense-in-depth; resolve_channel already guarantees this
        raise ValueError(
            f"'{channel}' is not a valid Slack channel ID. "
            "Slack requires the channel ID (e.g. C1234567890), not the channel name. "
            "To find it: open Slack, right-click the channel → View channel details → copy the ID at the bottom."
        )
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
