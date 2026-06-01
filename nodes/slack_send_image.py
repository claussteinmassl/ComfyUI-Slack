import os
import tempfile

import numpy as np
from PIL import Image

from ..utils.slack_client import get_client, upload_file_to_slack

_FORMAT_EXT = {
    "PNG": "png",
    "JPEG": "jpg",
    "WEBP": "webp",
}


class SlackSendImage:
    CATEGORY = "Slack"
    OUTPUT_NODE = True
    RETURN_TYPES = ()
    FUNCTION = "send"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "channel": ("STRING", {"default": "", "tooltip": "Slack channel ID (e.g. C1234567890). Right-click the channel in Slack → View channel details → copy the ID at the bottom."}),
                "filename_prefix": ("STRING", {"default": "ComfyUI"}),
                "format": (["PNG", "JPEG", "WEBP"],),
                "quality": ("INT", {"default": 85, "min": 1, "max": 100, "step": 1}),
            },
            "optional": {
                "title": ("STRING", {"default": ""}),
                "message": ("STRING", {"default": ""}),
                "thread_ts": ("STRING", {"default": "", "tooltip": "Slack thread timestamp to reply under. Leave blank to post to the channel root. Auto-filled by the Slack listener."}),
                "user_id": ("STRING", {"default": "", "tooltip": "Slack user ID to @-mention in the result message. Auto-filled by the Slack listener."}),
            },
        }

    def send(self, images, channel, filename_prefix, format, quality, title="", message="", thread_ts="", user_id=""):
        client = get_client()
        ext = _FORMAT_EXT[format]
        comment = f"<@{user_id}> {message}".strip() if user_id else message

        for i, img_tensor in enumerate(images):
            arr = np.clip(255.0 * img_tensor.cpu().numpy(), 0, 255).astype(np.uint8)
            pil_img = Image.fromarray(arr)

            filename = f"{filename_prefix}_{i:05d}.{ext}"

            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp_path = tmp.name

            try:
                if format == "PNG":
                    pil_img.save(tmp_path, format="PNG")
                elif format == "JPEG":
                    if pil_img.mode == "RGBA":
                        pil_img = pil_img.convert("RGB")
                    pil_img.save(tmp_path, format="JPEG", quality=quality)
                elif format == "WEBP":
                    pil_img.save(tmp_path, format="WEBP", quality=quality)

                upload_file_to_slack(
                    client=client,
                    channel=channel,
                    file_path=tmp_path,
                    filename=filename,
                    title=title,
                    message=comment if i == 0 else "",
                    thread_ts=thread_ts or None,
                )
            finally:
                os.unlink(tmp_path)

        return ()
