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
