import os
import re

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

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
) -> None:
    if not _CHANNEL_ID_RE.match(channel):
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
        )
    except SlackApiError as e:
        raise RuntimeError(f"Slack upload failed: {e.response['error']}") from e
