# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ComfyUI-Slack is a ComfyUI custom node package that sends generated images and videos directly to a Slack channel from within a ComfyUI workflow.

## File Structure

```
ComfyUI-Slack/
├── __init__.py                  # NODE_CLASS_MAPPINGS + NODE_DISPLAY_NAME_MAPPINGS
├── nodes/
│   ├── slack_send_image.py      # SlackSendImage — sends IMAGE tensor to Slack
│   └── slack_send_video.py      # SlackSendVideo — encodes frame batch via FFmpeg, sends to Slack
├── utils/
│   └── slack_client.py          # get_client() + upload_file_to_slack()
├── requirements.txt
└── pyproject.toml
```

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

File naming: `{filename_prefix}_{counter:05d}.{ext}`. Both nodes write to a temp file, upload via `files_upload_v2`, then delete the temp file.

## ComfyUI Custom Node Conventions

- `INPUT_TYPES` must be a `@classmethod`; node classes carry no instance state.
- Nodes that only produce side effects set `OUTPUT_NODE = True` and return `()`.
- IMAGE tensors have shape `[B, H, W, C]`, dtype float32, range 0–1. Convert with `np.clip(255.0 * tensor.cpu().numpy(), 0, 255).astype(np.uint8)`.
- Video encoding pipes raw RGB24 frames to FFmpeg stdin via `subprocess.Popen`; uses `imageio_ffmpeg.get_ffmpeg_exe()` for the binary. Dimensions are padded to even numbers before encoding (required by most codecs).

## Development Setup

Install into the ComfyUI Python environment:
```
pip install -r requirements.txt
```

Restart ComfyUI to reload custom nodes after code changes. Registration errors appear in the ComfyUI terminal on startup.
