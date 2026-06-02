import os
import shutil
import tempfile

import numpy as np
from PIL import Image

from ..utils.slack_client import get_client, upload_file_to_slack
from ..utils.local_save import resolve_save_path, SAVE_LOCATIONS

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
                "channel": ("STRING", {"default": "", "tooltip": "Channel or user: #general, @alice, or a raw ID. A user (@name or U…) is sent as a direct message. Names resolve automatically; the bot must be a member of private channels."}),
                "filename_prefix": ("STRING", {"default": "ComfyUI"}),
                "save_output": ("BOOLEAN", {"default": False, "label_on": "save", "label_off": "don't save", "tooltip": "Also write the image to disk in addition to sending it to Slack."}),
                "save_location": (SAVE_LOCATIONS, {"tooltip": "Where the saved copy is written. 'ComfyUI output folder' uses ComfyUI's output directory with an auto-incrementing counter; 'Absolute path' writes into the folder set below."}),
                "output_folder": ("STRING", {"default": "", "placeholder": "D:/exports", "tooltip": "Base folder for the saved copy. Used only when save_location is 'Absolute path'; combined with filename_prefix."}),
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

    def send(self, images, channel, filename_prefix, save_output, save_location, output_folder, format, quality, title="", message="", thread_ts="", user_id=""):
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

                # Copy to the local destination before uploading, so the saved
                # artifact persists even if the Slack upload fails.
                if save_output:
                    dest = resolve_save_path(
                        save_location, output_folder, filename_prefix, ext,
                        width=pil_img.width, height=pil_img.height, index=i,
                    )
                    shutil.copy2(tmp_path, dest)

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
