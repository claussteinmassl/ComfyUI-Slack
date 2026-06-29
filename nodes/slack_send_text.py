import os

from ..utils.slack_client import get_client, post_message_to_slack
from ..utils.markdown_to_slack import markdown_to_mrkdwn
from ..utils.local_save import resolve_save_path, SAVE_LOCATIONS
from ..utils.thread_root import split_thread_ref


class SlackSendText:
    CATEGORY = "Slack"
    OUTPUT_NODE = True
    RETURN_TYPES = ()
    FUNCTION = "send"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"default": "", "multiline": True, "tooltip": "Message to post. Standard Markdown (**bold**, _italic_, [text](url), # headings, `code`, - bullets) is translated to Slack formatting."}),
                "channel": ("STRING", {"default": "", "tooltip": "Channel or user: #general, @alice, or a raw ID. A user (@name or U…) is sent as a direct message. Names resolve automatically; the bot must be a member of private channels."}),
                "filename_prefix": ("STRING", {"default": "ComfyUI"}),
                "save_output": ("BOOLEAN", {"default": False, "label_on": "save", "label_off": "don't save", "tooltip": "Also write the message to disk (as a .md file) in addition to sending it to Slack."}),
                "save_location": (SAVE_LOCATIONS, {"tooltip": "Where the saved copy is written. 'ComfyUI output folder' uses ComfyUI's output directory with an auto-incrementing counter; 'Absolute path' writes into the folder set below."}),
                "output_folder": ("STRING", {"default": "", "placeholder": "D:/exports", "tooltip": "Base folder for the saved copy. Used only when save_location is 'Absolute path'; combined with filename_prefix."}),
            },
            "optional": {
                "thread_ts": ("STRING", {"default": "", "forceInput": True, "tooltip": "Slack thread to reply under. Connect a Slack Thread Start node here to post into the same thread as other send nodes. Leave unconnected to post to the channel root. Also auto-filled by the Slack listener."}),
                "user_id": ("STRING", {"default": "", "tooltip": "Slack user ID to @-mention at the start of the message. Auto-filled by the Slack listener."}),
            },
        }

    def send(self, text, channel, filename_prefix, save_output, save_location, output_folder, thread_ts="", user_id=""):
        body = markdown_to_mrkdwn(text)
        message = f"<@{user_id}> {body}".strip() if user_id else body

        # A Slack Thread Start node carries its channel in the thread reference,
        # so the thread's channel wins and this node's own channel is ignored
        # (its widget is disabled in the editor). A bare ts (listener-injected)
        # leaves channel untouched.
        thread_channel, thread_ts = split_thread_ref(thread_ts)
        channel = thread_channel or channel

        # Save the original Markdown source before posting, so the saved
        # artifact persists even if the Slack call fails.
        if save_output:
            dest = resolve_save_path(
                save_location, output_folder, filename_prefix, "md", index=0,
            )
            with open(dest, "w", encoding="utf-8") as f:
                f.write(text)

        post_message_to_slack(
            client=get_client(),
            channel=channel,
            text=message,
            thread_ts=thread_ts or None,
        )

        return ()
