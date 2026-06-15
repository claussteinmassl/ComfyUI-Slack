from .nodes.slack_send_image import SlackSendImage
from .nodes.slack_send_video import SlackSendVideo
from .nodes.slack_send_text import SlackSendText
from .nodes.slack_send_audio import SlackSendAudio
from .nodes.slack_thread_start import SlackThreadStart

NODE_CLASS_MAPPINGS = {
    "SlackSendImage": SlackSendImage,
    "SlackSendVideo": SlackSendVideo,
    "SlackSendText": SlackSendText,
    "SlackSendAudio": SlackSendAudio,
    "SlackThreadStart": SlackThreadStart,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SlackSendImage": "Send Image to Slack",
    "SlackSendVideo": "Send Video to Slack",
    "SlackSendText": "Send Text to Slack",
    "SlackSendAudio": "Send Audio to Slack",
    "SlackThreadStart": "Slack Thread Start",
}

# Frontend extension: greys out the save-location widgets when "Save output" is
# off / not in absolute-path mode. ComfyUI auto-serves every .js file here.
WEB_DIRECTORY = "./js"

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]

# Optionally start the Slack -> ComfyUI listener (opt-in via SLACK_LISTENER_ENABLED).
# This never raises: a misconfigured listener only logs a warning.
from .utils.listener_bootstrap import maybe_start_listener

maybe_start_listener()
