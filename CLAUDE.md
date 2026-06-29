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
│   ├── slack_send_audio.py      # SlackSendAudio — encodes AUDIO via FFmpeg, sends to Slack
│   └── slack_thread_start.py    # SlackThreadStart — posts a root message, outputs thread_ts to group send nodes
├── utils/
│   ├── slack_client.py          # get_client() + upload_file_to_slack() + post_message_to_slack() (returns the message ts)
│   ├── slack_resolve.py         # resolve_destination()/resolve_channel()/resolve_user() — name→ID, channel-or-user
│   ├── markdown_to_slack.py     # markdown_to_mrkdwn() — Markdown → Slack mrkdwn translator
│   ├── thread_root.py           # resolve_thread_root() — posts/caches the Slack Thread Start root message
│   └── local_save.py            # resolve_save_path() + SAVE_LOCATIONS for the "Save output" toggle
├── js/
│   ├── slack_save_output.js               # moves the save group to the bottom + greys it out per save_output / save_location
│   ├── slack_hide_listener_fields.js      # hides the listener-only user_id widget on all send nodes
│   └── slack_disable_channel_on_thread.js # greys out the channel widget while the thread_ts input is connected
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

### Threading (`SlackThreadStart`)

To post several outputs of one workflow into the **same Slack thread**, add a
`SlackThreadStart` node and wire its `thread_ts` output into the `thread_ts`
input of any send node. The send nodes already forward `thread_ts` to
`upload_file_to_slack()` / `post_message_to_slack()`; the input is exposed as a
connectable socket via `forceInput: True` (and is otherwise the same field the
listener injects). Wiring it also forces the send nodes to execute **after** the
thread root exists.

The root is created with `chat_postMessage` (which reliably returns the message
`ts` — a `files_upload_v2` response does not), via
`utils/thread_root.py:resolve_thread_root()`. Two modes:

- **New thread each run** — `IS_CHANGED` returns `NaN`, so ComfyUI re-executes
  the node every queue and posts a fresh root.
- **Reuse existing thread** — `IS_CHANGED` returns a stable key
  (`unique_id|channel|header`), so the node is cached and its `ts` is reused;
  a process-local `_thread_roots` cache also guards against a duplicate root if
  the node is re-executed. The reuse cache lives for the ComfyUI session only
  (a restart, or a changed channel/header, starts a new thread).

`SlackThreadStart` is `OUTPUT_NODE = False` and has `RETURN_TYPES = ("STRING",)`
/ `RETURN_NAMES = ("thread_ts",)`. Leaving a send node's `thread_ts`
unconnected posts to the channel root as before.

### Listener output redirection

A workflow triggered from Slack normally has its `SLACK_OUTPUT` send node's
`channel`/`thread_ts`/`user_id` injected by `utils/comfy_trigger.py:inject()`,
so the result posts back into the thread the request came from. **Wiring a
`SlackThreadStart` (or any node) into the send node's `thread_ts` input opts out
of that**: a connected input is serialized as a `[node_id, slot]` list, so
`inject()` leaves `channel`/`thread_ts`/`user_id` untouched and the result lands
wherever the workflow points (a different channel or a user DM) instead of back
at the sender. `utils/comfy_trigger.py:output_redirected()` reports this (true
only when *every* `SLACK_OUTPUT` node is wired), and the listener uses it to word
its confirmation: a redirected run promises "the result will be delivered
automatically" rather than "the result will post here". The submit-confirmation
itself still posts to the sender's thread so the requester knows the job was
queued.

The thread already fixes the destination channel, so the value travelling over
the `thread_ts` socket is not a bare `ts` but a `"<channel_id>@<ts>"` reference
(`utils/thread_root.py:encode_thread_ref()`; the channel is resolved with
`resolve_destination` so a `@user` becomes the DM's `D…` id). Each send node
calls `split_thread_ref()` first: when a channel is embedded it **overrides** the
node's own `channel` field, so that field becomes redundant — `js/slack_disable_channel_on_thread.js`
greys out the `channel` widget whenever the `thread_ts` input is connected, and
re-enables it when disconnected. A bare `ts` (the literal the listener injects,
alongside its own `channel`) has no separator, so `split_thread_ref()` returns
`(None, ts)` and the node keeps using its `channel` field.

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
