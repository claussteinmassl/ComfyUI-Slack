import os
import shutil
import subprocess
import tempfile

import numpy as np
import imageio_ffmpeg

from ..utils.slack_client import get_client, upload_file_to_slack
from ..utils.local_save import resolve_save_path, SAVE_LOCATIONS

# Audio is encoded by piping raw interleaved f32le samples to FFmpeg, the same
# binary and input format the video node uses when muxing audio.
# quality INT 1-100 maps to a bitrate for lossy formats; lossless ignores it.
_AUDIO_SETTINGS = {
    "mp3":  {"ext": "mp3",  "lossy": True,  "codec": ["-c:a", "libmp3lame"]},
    "m4a":  {"ext": "m4a",  "lossy": True,  "codec": ["-c:a", "aac"]},
    "opus": {"ext": "opus", "lossy": True,  "codec": ["-c:a", "libopus"]},
    "flac": {"ext": "flac", "lossy": False, "codec": ["-c:a", "flac"]},
    "wav":  {"ext": "wav",  "lossy": False, "codec": ["-c:a", "pcm_s16le"]},
}


class SlackSendAudio:
    CATEGORY = "Slack"
    OUTPUT_NODE = True
    RETURN_TYPES = ()
    FUNCTION = "send"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "audio": ("AUDIO",),
                "channel": ("STRING", {"default": "", "tooltip": "Channel or user: #general, @alice, or a raw ID. A user (@name or U…) is sent as a direct message. Names resolve automatically; the bot must be a member of private channels."}),
                "filename_prefix": ("STRING", {"default": "ComfyUI"}),
                "save_output": ("BOOLEAN", {"default": False, "label_on": "save", "label_off": "don't save", "tooltip": "Also write the audio to disk in addition to sending it to Slack."}),
                "save_location": (SAVE_LOCATIONS, {"tooltip": "Where the saved copy is written. 'ComfyUI output folder' uses ComfyUI's output directory with an auto-incrementing counter; 'Absolute path' writes into the folder set below."}),
                "output_folder": ("STRING", {"default": "", "placeholder": "D:/exports", "tooltip": "Base folder for the saved copy. Used only when save_location is 'Absolute path'; combined with filename_prefix."}),
                "format": (["mp3", "m4a", "opus", "flac", "wav"],),
                "quality": ("INT", {"default": 85, "min": 1, "max": 100, "step": 1, "tooltip": "Bitrate for lossy formats (mp3/m4a/opus): higher = better. Ignored for lossless (flac/wav)."}),
            },
            "optional": {
                "title": ("STRING", {"default": ""}),
                "message": ("STRING", {"default": ""}),
                "thread_ts": ("STRING", {"default": "", "tooltip": "Slack thread timestamp to reply under. Leave blank to post to the channel root. Auto-filled by the Slack listener."}),
                "user_id": ("STRING", {"default": "", "tooltip": "Slack user ID to @-mention in the result message. Auto-filled by the Slack listener."}),
            },
        }

    def send(self, audio, channel, filename_prefix, save_output, save_location, output_folder, format, quality, title="", message="", thread_ts="", user_id=""):
        settings = _AUDIO_SETTINGS[format]
        ext = settings["ext"]
        comment = f"<@{user_id}> {message}".strip() if user_id else message

        waveform = audio["waveform"]  # [B, channels, samples]
        sample_rate = int(audio["sample_rate"])
        channels = waveform.size(1)
        # Interleave to f32le: [channels, samples] -> [samples, channels].
        audio_bytes = (
            waveform[0].transpose(0, 1).contiguous().cpu().numpy().astype(np.float32).tobytes()
        )

        # 1-100 -> 32-320 kbps for lossy formats; lossless ignores it.
        bitrate_args = []
        if settings["lossy"]:
            bitrate = round(32 + quality / 100 * (320 - 32))
            bitrate_args = ["-b:a", f"{bitrate}k"]

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [
                ffmpeg_exe, "-y",
                "-f", "f32le",
                "-ar", str(sample_rate),
                "-ac", str(channels),
                "-i", "pipe:0",
                *settings["codec"],
                *bitrate_args,
                tmp_path,
            ]

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            _, stderr = proc.communicate(input=audio_bytes)

            if proc.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg audio encoding failed (exit {proc.returncode}):\n"
                    + stderr.decode("utf-8", errors="replace")
                )

            # Copy to the local destination before uploading, so the saved
            # artifact persists even if the Slack upload fails. The file is
            # already encoded, so this is a copy — not a re-encode.
            if save_output:
                dest = resolve_save_path(
                    save_location, output_folder, filename_prefix, ext, index=0,
                )
                shutil.copy2(tmp_path, dest)

            filename = f"{filename_prefix}_00000.{ext}"
            upload_file_to_slack(
                client=get_client(),
                channel=channel,
                file_path=tmp_path,
                filename=filename,
                title=title,
                message=comment,
                thread_ts=thread_ts or None,
            )
        finally:
            os.unlink(tmp_path)

        return ()
