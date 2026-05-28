import os
import subprocess
import tempfile

import numpy as np
import imageio_ffmpeg

from ..utils.slack_client import get_client, upload_file_to_slack

# codec: (extension, crf_max or None, extra_args_fn)
# quality INT 0-100: 100 = best (CRF 0), 0 = worst (CRF max)
_CODEC_SETTINGS = {
    "h264-mp4": {
        "ext": "mp4",
        "crf_max": 51,
        "audio_codec": ["-c:a", "aac"],
        "args": lambda crf, fps: [
            "-c:v", "libx264", "-crf", str(crf),
            "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        ],
    },
    "h265-mp4": {
        "ext": "mp4",
        "crf_max": 51,
        "audio_codec": ["-c:a", "aac"],
        "args": lambda crf, fps: [
            "-c:v", "libx265", "-crf", str(crf), "-pix_fmt", "yuv420p",
        ],
    },
    "vp9-webm": {
        "ext": "webm",
        "crf_max": 63,
        "audio_codec": ["-c:a", "libopus"],
        "args": lambda crf, fps: [
            "-c:v", "libvpx-vp9", "-crf", str(crf), "-b:v", "0", "-pix_fmt", "yuv420p",
        ],
    },
    "gif": {
        "ext": "gif",
        "crf_max": None,
        "audio_codec": None,  # GIF has no audio support
        "args": lambda crf, fps: [
            "-vf", "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
            "-loop", "0",
        ],
    },
}


def _pad_to_even(arr: np.ndarray) -> np.ndarray:
    h, w = arr.shape[:2]
    ph, pw = h % 2, w % 2
    if ph or pw:
        arr = np.pad(arr, ((0, ph), (0, pw), (0, 0)), mode="edge")
    return arr


class SlackSendVideo:
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
                "frame_rate": ("FLOAT", {"default": 24.0, "min": 1.0, "max": 120.0, "step": 0.1}),
                "format": (["h264-mp4", "h265-mp4", "vp9-webm", "gif"],),
                "quality": ("INT", {"default": 81, "min": 0, "max": 100, "step": 1}),
            },
            "optional": {
                "audio": ("AUDIO",),
                "title": ("STRING", {"default": ""}),
                "message": ("STRING", {"default": ""}),
                "thread_ts": ("STRING", {"default": "", "tooltip": "Slack thread timestamp to reply under. Leave blank to post to the channel root. Auto-filled by the Slack listener."}),
            },
        }

    def send(self, images, channel, filename_prefix, frame_rate, format, quality, audio=None, title="", message="", thread_ts=""):
        codec = _CODEC_SETTINGS[format]
        ext = codec["ext"]

        first = _pad_to_even(images[0].cpu().numpy())
        h, w = first.shape[:2]

        crf = round((100 - quality) * codec["crf_max"] / 100) if codec["crf_max"] is not None else 0
        codec_args = codec["args"](crf, frame_rate)

        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

        with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            cmd = [
                ffmpeg_exe, "-y",
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "-s", f"{w}x{h}",
                "-r", str(frame_rate),
                "-i", "pipe:0",
                *codec_args,
                tmp_path,
            ]

            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            for img_tensor in images:
                arr = np.clip(255.0 * img_tensor.cpu().numpy(), 0, 255).astype(np.uint8)
                proc.stdin.write(_pad_to_even(arr).tobytes())

            proc.stdin.close()
            _, stderr = proc.communicate()

            if proc.returncode != 0:
                raise RuntimeError(
                    f"FFmpeg encoding failed (exit {proc.returncode}):\n"
                    + stderr.decode("utf-8", errors="replace")
                )

            audio_codec = codec.get("audio_codec")
            if audio is not None and audio_codec is not None:
                waveform = audio["waveform"]  # [1, channels, samples]
                sample_rate = audio["sample_rate"]
                channels = waveform.size(1)
                audio_bytes = waveform.squeeze(0).transpose(0, 1).numpy().tobytes()

                with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as af:
                    muxed_path = af.name

                mux_cmd = [
                    ffmpeg_exe, "-v", "error", "-y",
                    "-i", tmp_path,
                    "-ar", str(sample_rate), "-ac", str(channels),
                    "-f", "f32le", "-i", "-",
                    "-c:v", "copy",
                ] + audio_codec + ["-shortest", muxed_path]

                try:
                    subprocess.run(mux_cmd, input=audio_bytes, check=True, capture_output=True)
                except Exception:
                    os.unlink(muxed_path)
                    raise

                os.unlink(tmp_path)
                tmp_path = muxed_path

            filename = f"{filename_prefix}_00000.{ext}"
            upload_file_to_slack(
                client=get_client(),
                channel=channel,
                file_path=tmp_path,
                filename=filename,
                title=title,
                message=message,
                thread_ts=thread_ts or None,
            )
        finally:
            os.unlink(tmp_path)

        return ()
