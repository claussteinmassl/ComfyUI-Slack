# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ComfyUI-Slack is a ComfyUI custom node package that sends generated images, videos, text messages, and audio directly to a Slack channel from within a ComfyUI workflow.

## File Structure

```
ComfyUI-Slack/
├── __init__.py                  # NODE_CLASS_MAPPINGS + NODE_DISPLAY_NAME_MAPPINGS + WEB_DIRECTORY
├── nodes/
│   ├── slack_send_image.py      # SlackSendImage — sends IMAGE tensor to Slack
│   ├── slack_send_video.py      # SlackSendVideo — encodes frame batch via FFmpeg, sends to Slack
│   ├── slack_send_text.py       # SlackSendText — posts a Markdown message to Slack
│   └── slack_send_audio.py      # SlackSendAudio — encodes AUDIO via FFmpeg, sends to Slack
├── utils/
│   ├── slack_client.py          # get_client() + upload_file_to_slack() + post_message_to_slack()
│   ├── markdown_to_slack.py     # markdown_to_mrkdwn() — Markdown → Slack mrkdwn translator
│   └── local_save.py            # resolve_save_path() + SAVE_LOCATIONS for the "Save output" toggle
├── js/
│   └── slack_save_output.js     # greys out save-location widgets based on save_output / save_location
├── requirements.txt
└── pyproject.toml
```

`__init__.py` exports `WEB_DIRECTORY = "./js"` so ComfyUI serves the frontend extension. (The tree above lists only the core node files; the optional Slack→ComfyUI listener adds further `utils/` modules.)

## Bot Token

The Slack bot token is **never a node input**. It is read from the `SLACK_BOT_TOKEN` environment variable at execution time inside `utils/slack_client.py:get_client()`. Set it in the shell that launches ComfyUI before starting.

## Supported Formats

### Images (`SlackSendImage`)

| Format | Extension | Quality input |
|--------|-----------|---------------|
| PNG    | `.png`    | Ignored (lossless) |
| JPEG   | `.jpg`    | 1–100 |
| WEBP   | `.webp`   | 1–100 |

### Videos (`SlackSendVideo`)

| Format     | Codec       | Container | Quality→CRF mapping |
|------------|-------------|-----------|---------------------|
| h264-mp4   | libx264     | MP4       | `crf = (100-q)*51/100` |
| h265-mp4   | libx265     | MP4       | `crf = (100-q)*51/100` |
| vp9-webm   | libvpx-vp9  | WebM      | `crf = (100-q)*63/100` |
| gif        | GIF palette | GIF       | N/A |

### Text (`SlackSendText`)

Posts a multiline message via `chat.postMessage` (no file upload). Standard
Markdown is translated to Slack's `mrkdwn` by `utils/markdown_to_slack.py`
(`**bold**`→`*bold*`, `_italic_`, `~~strike~~`→`~strike~`, `[text](url)`→`<url|text>`,
`# Heading`→`*Heading*`, `- bullet`→`• bullet`; backtick code spans/blocks are
left verbatim). With "Save output" on, the original Markdown source is written as
a `.md` file.

### Audio (`SlackSendAudio`)

| Format | Codec         | Extension | Quality input |
|--------|---------------|-----------|---------------|
| mp3    | libmp3lame    | `.mp3`    | 1–100 → 32–320 kbps |
| m4a    | aac           | `.m4a`    | 1–100 → 32–320 kbps |
| opus   | libopus       | `.opus`   | 1–100 → 32–320 kbps |
| flac   | flac          | `.flac`   | Ignored (lossless) |
| wav    | pcm_s16le     | `.wav`    | Ignored (lossless) |

Audio is encoded by piping interleaved `f32le` samples to FFmpeg stdin (same
binary as video). Bitrate for lossy formats: `bitrate = round(32 + q/100*288)` kbps.

File naming: `{filename_prefix}_{counter:05d}.{ext}`. The image/video/audio nodes write to a temp file, upload via `files_upload_v2`, then delete the temp file.

## ComfyUI Custom Node Conventions

- `INPUT_TYPES` must be a `@classmethod`; node classes carry no instance state.
- Nodes that only produce side effects set `OUTPUT_NODE = True` and return `()`.
- IMAGE tensors have shape `[B, H, W, C]`, dtype float32, range 0–1. Convert with `np.clip(255.0 * tensor.cpu().numpy(), 0, 255).astype(np.uint8)`.
- Video encoding pipes raw RGB24 frames to FFmpeg stdin via `subprocess.Popen`; uses `imageio_ffmpeg.get_ffmpeg_exe()` for the binary. Dimensions are padded to even numbers before encoding (required by most codecs).
- AUDIO tensors are a dict `{"waveform": tensor[B, channels, samples], "sample_rate": int}`. Audio encoding pipes interleaved `f32le` samples (`waveform[0].transpose(0, 1)`) to the same FFmpeg binary.

## Development Setup

Install into the ComfyUI Python environment:
```
pip install -r requirements.txt
```

Restart ComfyUI to reload custom nodes after code changes. Registration errors appear in the ComfyUI terminal on startup.
