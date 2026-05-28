from .nodes.slack_send_image import SlackSendImage
from .nodes.slack_send_video import SlackSendVideo

NODE_CLASS_MAPPINGS = {
    "SlackSendImage": SlackSendImage,
    "SlackSendVideo": SlackSendVideo,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SlackSendImage": "Send Image to Slack",
    "SlackSendVideo": "Send Video to Slack",
}

# Optionally start the Slack -> ComfyUI listener (opt-in via SLACK_LISTENER_ENABLED).
# This never raises: a misconfigured listener only logs a warning.
from .utils.listener_bootstrap import maybe_start_listener

maybe_start_listener()
