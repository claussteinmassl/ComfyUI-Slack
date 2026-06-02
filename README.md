# ComfyUI-Slack

Send generated images, videos, text, and audio directly to a Slack channel from within a ComfyUI workflow.

## Installation

### ComfyUI Manager (recommended)

In **ComfyUI Manager**, open **Custom Nodes Manager**, search for **ComfyUI-Slack**, and click
**Install**. Restart ComfyUI when prompted. Dependencies are installed automatically.

### Manual

1. Clone this repository into your ComfyUI `custom_nodes` directory:
   ```
   cd ComfyUI/custom_nodes
   git clone https://github.com/claussteinmassl/ComfyUI-Slack
   ```
2. Install dependencies into the ComfyUI Python environment:
   ```
   pip install -r requirements.txt
   ```
3. Restart ComfyUI.

## Slack App Setup

ComfyUI-Slack requires a Slack Bot Token (`xoxb-...`) from a dedicated Slack App.

> **Why create your own app instead of installing one from the Slack Marketplace?**
> ComfyUI-Slack has no hosted service behind it — it runs entirely on *your* machine and talks
> to Slack directly using a token you control. A Marketplace app would route your images and
> messages through someone else's servers; here nothing leaves your machine except the calls to
> Slack's own API. Slack tokens are also tied to a single workspace, so the app must be created
> and installed inside *your* workspace to get a token that works there. Creating the app is a
> one-time, few-minute setup — the manifest below makes it nearly copy-paste.

You can create the app two ways: paste a ready-made **manifest** (fast), or click through the
settings **by hand** (so you understand what each one does). Both produce the same app — pick one.

### Quick start: create the app from a manifest (recommended)

Slack can build an app from a manifest that pre-fills the name, scopes, and — for the listener —
Socket Mode, interactivity, and event subscriptions in a single step.

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From a manifest**.
2. Select your workspace, then click **Next**.
3. Switch the format toggle to **JSON**, paste the manifest below, click **Next**, then **Create**.

```json
{
  "display_information": {
    "name": "ComfyUI",
    "description": "Send ComfyUI images and videos to Slack, and trigger workflows from Slack."
  },
  "features": {
    "bot_user": {
      "display_name": "ComfyUI",
      "always_online": true
    }
  },
  "oauth_config": {
    "scopes": {
      "bot": [
        "files:write",
        "chat:write",
        "channels:read",
        "groups:read",
        "users:read",
        "im:write",
        "app_mentions:read",
        "files:read"
      ]
    }
  },
  "settings": {
    "event_subscriptions": {
      "bot_events": [
        "app_mention"
      ]
    },
    "interactivity": {
      "is_enabled": true
    },
    "socket_mode_enabled": true,
    "org_deploy_enabled": false,
    "token_rotation_enabled": false
  }
}
```

> Slack's *Create from a manifest* screen defaults to YAML and its YAML parser is currently
> flaky (even the sample manifest can fail to validate). Use the **JSON** toggle instead.

This manifest configures **both** the send nodes and the Slack listener. The scopes
`files:write`, `chat:write`, `channels:read`, `groups:read`, and `im:write` cover the send nodes
(`channels:read`/`groups:read` let you type a channel **name** instead of an ID — public and
private respectively; `im:write` lets you send directly to a **user** as a DM); the listener
additionally needs `users:read` (resolve usernames in the allow-list), `app_mentions:read`, and
`files:read`, plus the entire `"settings"` block (Socket Mode, interactivity, and the `app_mention`
event). If you only want the send nodes you can drop `users:read`, `app_mentions:read`,
`files:read`, and the `"settings"` block — or just leave them; the extras are harmless.

A manifest **cannot** create tokens or install the app, so a few steps remain manual:

- **Install the app** to your workspace and copy the **Bot User OAuth Token** (`xoxb-...`) —
  see steps **3–5** below.
- **Invite the bot** to your channel: `/invite @ComfyUI`.
- **(Listener only)** create an **App-Level Token** with the `connections:write` scope (`xapp-...`).
  App-level tokens can't be set via manifest — see
  [Trigger Workflows from Slack](#trigger-workflows-from-slack-socket-mode).

### Manual setup (what the manifest configures)

Prefer to configure the app by hand, or want to understand each setting the manifest applies?
Follow these steps instead — they produce exactly the same app.

### 1. Create a Slack App

Go to [https://api.slack.com/apps](https://api.slack.com/apps) and click **Create New App** → **From scratch**.

- **App name:** `ComfyUI` (or any name you prefer)
- **Workspace:** select your workspace

### 2. Add Bot Token Scopes

In the left sidebar go to **OAuth & Permissions**, scroll to **Bot Token Scopes**, and add:

| Scope | Purpose |
|-------|---------|
| `files:write` | Upload images and videos |
| `chat:write` | Post messages to channels |
| `channels:read` | Resolve **public** channel names to IDs |
| `groups:read` | Resolve **private** channel names to IDs |
| `im:write` | Send directly to a **user** as a DM |

### 3. Install the App to Your Workspace

Still on **OAuth & Permissions**, click **Install to Workspace** and click **Allow**.

### 4. Copy the Bot Token

After installation you'll see a **Bot User OAuth Token** that starts with `xoxb-`. Copy it — you'll need it in the next step.

### 5. Set the Environment Variable

The token is **never entered in the node UI**. Set it in the environment before launching ComfyUI.

**Windows (PowerShell, current session only):**
```powershell
$env:SLACK_BOT_TOKEN = "xoxb-your-token-here"
```

**Windows (persistent, via System Properties):**

Open *Start → Edit the system environment variables → Environment Variables*, add a new User variable named `SLACK_BOT_TOKEN` with your token as the value. Restart ComfyUI after saving.

**macOS / Linux:**
```bash
export SLACK_BOT_TOKEN="xoxb-your-token-here"
```

Add that line to your shell profile (`~/.zshrc`, `~/.bashrc`, etc.) to make it permanent.

### 6. Choose a Destination

The nodes' `channel` field accepts a **channel or a user**:

| You enter | Goes to |
|-----------|---------|
| `#general`, `general`, or `C0B6SUZMHC6` | that channel |
| `@alice`, or a user ID `U…` | a **direct message** to that user (needs `im:write`) |

Names resolve to IDs automatically. A bare name with no `#`/`@` is treated as a channel first, then
a user — prefix with `#` or `@` to be explicit. For a **private** channel the bot must be a member,
so invite it first:

```
/invite @ComfyUI
```

> Prefer the raw ID? Right-click the channel → **View channel details** → scroll to the bottom;
> it looks like `C0B6SUZMHC6`.

## Trigger Workflows from Slack (Socket Mode)

The package can also work the **other way around**: a user **@mentions the bot in Slack**
with a prompt (and optionally an attached image or video), the bot picks the matching
ComfyUI workflow, runs it, and posts the result back **in the same thread**.

This runs as a background listener inside ComfyUI using Slack **Socket Mode** — an outbound
WebSocket, so **no public URL or ngrok is needed**. It is **opt-in** and off by default; if
you only use the send nodes you can ignore this section entirely.

### How it works

1. You save one or more workflows in **API format** and register them in a `manifest.json`.
2. You @mention the bot: `@ComfyUI a cat astronaut` (optionally attach an image/video).
3. The listener picks a workflow **deterministically** (no AI):
   - by **input type** — no file → a `text` workflow, image → an `image` workflow, video → a `video` workflow;
   - an explicit **`[name]` prefix** always wins, e.g. `@ComfyUI [img2img] make it watercolor`;
   - if several workflows still match, the bot posts **buttons** to choose.
4. The listener injects your prompt / file / channel / thread into the workflow and queues it.
5. The workflow ends in a **Send to Slack** node, which posts the result back in your thread.

### 1. Extra Slack App configuration

> **If you created the app from the manifest above**, Socket Mode, Interactivity, the
> `app_mention` event subscription, and the extra bot scopes are **already set** — you only
> need to create the **App-Level Token** (third bullet) and reinstall/invite the bot.

In addition to the bot token setup above, do the following in your Slack App:

- **Socket Mode** (left sidebar → *Socket Mode*): toggle **Enable Socket Mode** on.
- **Interactivity** (*Interactivity & Shortcuts*): toggle on. With Socket Mode you do **not**
  need a Request URL. (Required for the disambiguation buttons.)
- **App-Level Token** (*Basic Information → App-Level Tokens*): create one with the
  `connections:write` scope. It starts with `xapp-` — this is the `SLACK_APP_TOKEN`.
- **Event Subscriptions** (*Event Subscriptions → Subscribe to bot events*): add `app_mention`.
- **Additional Bot Token Scopes** (*OAuth & Permissions*), on top of the send scopes:

  | Scope | Purpose |
  |-------|---------|
  | `app_mentions:read` | Receive @mentions |
  | `files:read` | Download attached images/videos |
  | `chat:write` | Post status, errors, and choice buttons |
  | `users:read` | Resolve usernames in `SLACK_ALLOWED_USERS` to IDs |

- **Reinstall the app** to your workspace to apply the new scopes, and **invite the bot** to
  the channel (`/invite @ComfyUI`).

### 2. Build a workflow registry

1. In ComfyUI, enable **dev mode** (*Settings → Enable Dev Mode Options*) so the
   **Save (API Format)** button appears.
2. Build a workflow that **ends in a `Send Image to Slack` / `Send Video to Slack` node**.
   The final send node is the only one the listener *requires*; **rename** it
   (right-click → *Title*) to `SLACK_OUTPUT`. Rename any of the optional input
   nodes too if your workflow uses them:

   | Rename this node to | Role |
   |---------------------|------|
   | `SLACK_OUTPUT` | The final `Send … to Slack` node — receives the channel, thread, and the triggering user to @-mention. **Required.** |
   | `SLACK_PROMPT` *(optional)* | The text prompt node (e.g. the positive `CLIPTextEncode`) — receives the message text. Omit it for fixed-prompt or input-only workflows; the message text is then ignored. |
   | `SLACK_INPUT_IMAGE` *(optional)* | A `LoadImage` node — receives an attached image (slot 1) |
   | `SLACK_INPUT_IMAGE_2`, `SLACK_INPUT_IMAGE_3`, … *(optional)* | Extra `LoadImage` nodes for workflows that take several distinct input images. Slot numbers must be contiguous (`SLACK_INPUT_IMAGE`, then `_2`, `_3`, …); the *n*-th attached image fills slot *n* |
   | `SLACK_INPUT_VIDEO` *(optional)* | A video-load node (e.g. VideoHelperSuite `VHS_LoadVideo`) — receives an attached video |

3. Click **Save (API Format)** and put the file in a folder alongside a `manifest.json`.
   See the bundled [`workflows/`](workflows/) folder for working examples
   (`manifest.json`, `txt2img.api.json`, `img2img.api.json`).

`manifest.json` lists your workflows:

```json
{
  "workflows": [
    {
      "name": "txt2img",
      "label": "Generate image",
      "description": "Generate an image from a text prompt",
      "modality": "text",
      "keywords": ["image", "picture", "photo"],
      "template": "txt2img.api.json"
    }
  ]
}
```

| Field | Meaning |
|-------|---------|
| `name` | Used by the `[name]` override and `help` listing |
| `label` | Text shown on the Slack choice button |
| `description` | Shown in the `@ComfyUI help` listing |
| `modality` | `text`, `image`, `video`, or `any` — what input the workflow consumes |
| `keywords` | Optional words that, if present in the message, auto-pick this workflow |
| `template` | The API-format JSON file, relative to the manifest |

> **Video input** needs a video-load node in your template (e.g. VideoHelperSuite). It is not
> a dependency of this package — install the relevant node pack separately.

> **Multiple input images.** A workflow accepts *N* images, where *N* is the number of
> `SLACK_INPUT_IMAGE` slot markers in its template. When you attach *M* images:
> *M = N* runs the workflow once (image *n* → slot *n*); *M* a larger multiple of *N*
> (e.g. 3 images into a 1-slot workflow, or 4 into a 2-slot one) prompts you with
> **Continue / Cancel** and, on Continue, runs the workflow `M / N` times in batches of
> *N*; anything else (too few, or not a clean multiple) is rejected with an explanation.
> Fan-out is capped by `SLACK_MAX_FANOUT` (default 25).

### 3. Set the listener environment variables

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `SLACK_LISTENER_ENABLED` | yes (to turn it on) | off | Master switch — set to `1`/`true` |
| `SLACK_APP_TOKEN` | yes | — | App-level token (`xapp-...`) |
| `SLACK_BOT_TOKEN` | yes | — | Bot token (`xoxb-...`), reused from the send setup |
| `SLACK_WORKFLOW_DIR` | yes | — | Folder containing `manifest.json` + templates |
| `SLACK_ALLOWED_USERS` | one of these | empty | CSV of allowed users — names or IDs (`@alice`, a display name, or `U…`) |
| `SLACK_ALLOWED_CHANNELS` | one of these | empty | CSV of allowed channels — names or IDs (`#general` or `C…`) |
| `SLACK_COMFY_URL` | no | auto | Override the local ComfyUI URL (e.g. `http://127.0.0.1:8188`) |
| `SLACK_MAX_INPUT_MB` | no | `20` | Max size of an attachment to download |
| `SLACK_MAX_FANOUT` | no | `25` | Max number of runs one message may fan out into (see below) |
| `SLACK_NOTIFY_USER` | no | `true` | @-mention the triggering user in result & error replies; set to `false` to disable |
| `SLACK_COMFY_API_KEY` | only for API-node workflows | — | comfy.org API key (`comfyui-...`); see below |

> **comfy.org API nodes (OpenAI, etc.) need a key.** When you queue a workflow in the
> browser, the ComfyUI frontend silently attaches your login token so partner/API nodes can
> authenticate — having credits is not enough on its own. A workflow triggered by the listener
> has no browser session, so any API node fails with
> `Unauthorized: Please login first to use this node`. Generate an API key at
> [platform.comfy.org](https://platform.comfy.org) and set it as `SLACK_COMFY_API_KEY`; the
> listener forwards it with each queued prompt. Workflows using only local nodes don't need it.

> **Authorization is default-deny.** Until you set `SLACK_ALLOWED_USERS` and/or
> `SLACK_ALLOWED_CHANNELS`, every trigger is refused. Each trigger queues a GPU job on your
> machine, so list only the users/channels you trust.

> **Names or IDs in the allow-lists.** Entries may be names (`@alice`, `#general`) or raw IDs
> (`U…`, `C…`); names are resolved automatically. A name that can't be resolved — a typo, an
> ambiguous display name, or a missing `users:read`/`groups:read` scope — is **skipped with a
> warning** in the ComfyUI log rather than failing; ID entries always work. So a scope mistake
> degrades to "ID-only", it never locks everyone out.

> **Running the listener on several machines.** You can point multiple machines at the *same*
> Slack app to share the load. Slack delivers each event to exactly one connection (at random,
> up to 10 connections per app), so a request runs on whichever machine happens to receive it —
> there are no duplicate runs. Buttons (workflow choice and fan-out confirmation) are stateless:
> a click can be handled by any machine, which re-downloads the needed input files on demand.
> For this to behave consistently, give every machine an **identical** `SLACK_WORKFLOW_DIR`
> (same `manifest.json`, templates, and models) and the same allow-lists; otherwise the same
> request can succeed or fail depending on which machine catches it. If you'd rather route all
> Slack traffic to one box, simply leave `SLACK_LISTENER_ENABLED` unset on the others — they can
> still use the send nodes.

**Windows (PowerShell, current session):**
```powershell
$env:SLACK_LISTENER_ENABLED = "1"
$env:SLACK_APP_TOKEN = "xapp-your-token-here"
$env:SLACK_WORKFLOW_DIR = "C:\path\to\your\workflows"
$env:SLACK_ALLOWED_USERS = "@alice,U0456DEF"   # names or IDs
```

On startup you should see `[ComfyUI-Slack] Socket Mode listener started.` and a line listing
the loaded workflows in the ComfyUI terminal.

### 4. Use it

| In Slack | Result |
|----------|--------|
| `@ComfyUI a neon city at night` | Runs the text workflow (or shows buttons if several match) |
| `@ComfyUI [img2img] make it watercolor` + image | Forces the `img2img` workflow |
| `@ComfyUI animate this` + image | Auto-picks the workflow whose `keywords` include `animate` |
| `@ComfyUI help` | Lists the available workflows |

## Nodes

### SlackSendImage

Sends one or more images from a batch to a Slack channel.

| Input | Type | Description |
|-------|------|-------------|
| `images` | IMAGE | Image tensor batch |
| `channel` | STRING | Channel or user — `#general`, `@alice`, or a raw ID. A user is sent a DM. |
| `filename_prefix` | STRING | Base name for the uploaded file |
| `save_output` | BOOLEAN | Also write the image to disk (see [Saving a local copy](#saving-a-local-copy)) |
| `save_location` | COMBO | `ComfyUI output folder` or `Absolute path` |
| `output_folder` | STRING | Base folder for the saved copy; used only in `Absolute path` mode |
| `format` | COMBO | `PNG`, `JPEG`, or `WEBP` |
| `quality` | INT 1–100 | JPEG/WEBP quality; ignored for PNG |
| `title` *(optional)* | STRING | File title shown in Slack |
| `message` *(optional)* | STRING | Message posted alongside the file |

Each image in the batch is uploaded as a separate file named `{filename_prefix}_{index:05d}.{ext}`. The optional message is attached to the first file only.

**Supported formats:**

| Format | Extension | Quality |
|--------|-----------|---------|
| PNG | `.png` | Lossless (quality ignored) |
| JPEG | `.jpg` | 1–100 |
| WEBP | `.webp` | 1–100 |

### SlackSendVideo

Encodes a frame batch into a video via FFmpeg and uploads it to a Slack channel.

| Input | Type | Description |
|-------|------|-------------|
| `images` | IMAGE | Frame batch (B, H, W, C) |
| `channel` | STRING | Channel or user — `#general`, `@alice`, or a raw ID. A user is sent a DM. |
| `filename_prefix` | STRING | Base name for the uploaded file |
| `save_output` | BOOLEAN | Also write the video to disk (see [Saving a local copy](#saving-a-local-copy)) |
| `save_location` | COMBO | `ComfyUI output folder` or `Absolute path` |
| `output_folder` | STRING | Base folder for the saved copy; used only in `Absolute path` mode |
| `frame_rate` | FLOAT | Playback frame rate (1–120 fps) |
| `format` | COMBO | `h264-mp4`, `h265-mp4`, `vp9-webm`, or `gif` |
| `quality` | INT 0–100 | 100 = best quality, 0 = smallest file |
| `audio` *(optional)* | AUDIO | Audio to mux into the video (not supported for GIF) |
| `title` *(optional)* | STRING | File title shown in Slack |
| `message` *(optional)* | STRING | Message posted alongside the file |

**Supported formats:**

| Format | Codec | Container | Quality → CRF |
|--------|-------|-----------|---------------|
| `h264-mp4` | libx264 | MP4 | `(100-q)*51/100` |
| `h265-mp4` | libx265 | MP4 | `(100-q)*51/100` |
| `vp9-webm` | libvpx-vp9 | WebM | `(100-q)*63/100` |
| `gif` | GIF palette | GIF | N/A |

Frames are padded to even dimensions automatically (required by most codecs). FFmpeg is bundled via `imageio-ffmpeg` — no separate installation needed.

### SlackSendText

Posts a text message to a Slack channel (or as a DM). The message field accepts standard Markdown, which is translated to Slack's formatting before sending.

| Input | Type | Description |
|-------|------|-------------|
| `text` | STRING (multiline) | Message body; Markdown is translated to Slack formatting |
| `channel` | STRING | Channel or user — `#general`, `@alice`, or a raw ID. A user is sent a DM. |
| `filename_prefix` | STRING | Base name for the saved `.md` copy (only used when `save_output` is on) |
| `save_output` | BOOLEAN | Also write the message to disk as a `.md` file (see [Saving a local copy](#saving-a-local-copy)) |
| `save_location` | COMBO | `ComfyUI output folder` or `Absolute path` |
| `output_folder` | STRING | Base folder for the saved copy; used only in `Absolute path` mode |
| `thread_ts` *(optional)* | STRING | Thread timestamp to reply under; auto-filled by the Slack listener |
| `user_id` *(optional)* | STRING | User to `@`-mention at the start of the message; auto-filled by the Slack listener |

**Markdown translation:** standard Markdown is rewritten to Slack `mrkdwn`:

| Markdown | Slack |
|----------|-------|
| `**bold**` / `__bold__` | `*bold*` |
| `*italic*` / `_italic_` | `_italic_` |
| `~~strike~~` | `~strike~` |
| `[text](url)` | `<url\|text>` |
| `# Heading` | `*Heading*` (mrkdwn has no headings) |
| `- item` | `• item` |
| `` `code` `` / ```` ```block``` ```` | left as-is (already valid in Slack) |

The local copy (when `save_output` is on) stores the **original** Markdown source, not the translated text.

### SlackSendAudio

Encodes an `AUDIO` input via FFmpeg and uploads it to a Slack channel as a standalone audio file.

| Input | Type | Description |
|-------|------|-------------|
| `audio` | AUDIO | Audio to send |
| `channel` | STRING | Channel or user — `#general`, `@alice`, or a raw ID. A user is sent a DM. |
| `filename_prefix` | STRING | Base name for the uploaded file |
| `save_output` | BOOLEAN | Also write the audio to disk (see [Saving a local copy](#saving-a-local-copy)) |
| `save_location` | COMBO | `ComfyUI output folder` or `Absolute path` |
| `output_folder` | STRING | Base folder for the saved copy; used only in `Absolute path` mode |
| `format` | COMBO | `mp3`, `m4a`, `opus`, `flac`, or `wav` |
| `quality` | INT 1–100 | Bitrate for lossy formats; ignored for `flac`/`wav` |
| `title` *(optional)* | STRING | File title shown in Slack |
| `message` *(optional)* | STRING | Message posted alongside the file |

**Supported formats:**

| Format | Codec | Extension | Quality |
|--------|-------|-----------|---------|
| `mp3` | libmp3lame | `.mp3` | 1–100 → 32–320 kbps |
| `m4a` | aac | `.m4a` | 1–100 → 32–320 kbps |
| `opus` | libopus | `.opus` | 1–100 → 32–320 kbps |
| `flac` | flac | `.flac` | Lossless (quality ignored) |
| `wav` | pcm_s16le | `.wav` | Lossless (quality ignored) |

Audio is encoded by piping the waveform to the bundled FFmpeg — no separate installation needed.

### Saving a local copy

All four send nodes can keep a local copy of what they send. Saving is **additive** — the content is always sent to Slack, and turning `save_output` on simply also writes it to disk (before sending, so the local copy survives even if Slack errors). The text node saves a `.md` file; the others save the uploaded media file.

- **`ComfyUI output folder`** — writes into ComfyUI's standard `output/` directory using the same naming as the built-in Save nodes: `{filename_prefix}_{counter:05}_.{ext}`. `filename_prefix` may include a subfolder (e.g. `renders/Clip`), and the counter auto-increments so existing files are never overwritten.
- **`Absolute path`** — writes into the `output_folder` you specify (created if missing) as `{filename_prefix}_{index:05d}.{ext}`. Leaving `output_folder` empty in this mode raises an error.

In the node UI, `save_location` and `output_folder` are greyed out while `save_output` is off, and `output_folder` stays greyed out unless `Absolute path` is selected.

## Troubleshooting

**`SLACK_BOT_TOKEN environment variable is not set`** — set the variable in the shell that launches ComfyUI and restart.

**`Slack upload failed: not_in_channel`** — the bot hasn't been invited to the channel. Run `/invite @ComfyUI` in Slack.

**`Slack channel "…" not found`** — the channel name in the node couldn't be resolved. Check the
spelling; for a **private** channel, invite the bot first (`/invite @ComfyUI`) — private channels
resolve only when the bot is a member, and need the `groups:read` scope. You can always fall back
to the raw channel ID (e.g. `C0B6SUZMHC6`).

**Allow-list names are ignored** — a name in `SLACK_ALLOWED_USERS`/`SLACK_ALLOWED_CHANNELS` is
skipped (with a warning in the ComfyUI log) when it can't be resolved: a typo, an ambiguous
display name, or a missing `users:read`/`groups:read` scope. Add the scope and **reinstall the
app**, fix the spelling, or use the raw ID (`U…`/`C…`).

**FFmpeg encoding failed** — check that the frame batch is not empty and that the selected codec is compatible with your FFmpeg build.

**Listener doesn't start** — confirm `SLACK_LISTENER_ENABLED` is `1`/`true` and that
`SLACK_APP_TOKEN`, `SLACK_BOT_TOKEN`, and `SLACK_WORKFLOW_DIR` are all set. The terminal logs
the exact missing piece on startup.

**Bot replies "You're not authorized"** — set `SLACK_ALLOWED_USERS` and/or
`SLACK_ALLOWED_CHANNELS`. Authorization is default-deny, so an empty allowlist blocks everyone.

**`Unauthorized: Please login first to use this node`** — the workflow uses a comfy.org
API/partner node (e.g. an OpenAI node). The browser login that authenticates these nodes in the
GUI isn't present for a listener-triggered run, and credits alone don't authenticate the request.
Generate an API key at [platform.comfy.org](https://platform.comfy.org) and set
`SLACK_COMFY_API_KEY` before launching ComfyUI.

**`template missing required node title marker(s)`** — rename the final Slack send node to
`SLACK_OUTPUT` in your workflow (the only required marker), then re-export it with
**Save (API Format)**. A `SLACK_PROMPT` node is optional.

**Mention does nothing** — make sure the bot is invited to the channel, `app_mention` is
subscribed under Event Subscriptions, and Socket Mode is enabled. Re-install the app after
changing scopes.

## License

MIT — see [LICENSE](LICENSE). © 2026 Claus Steinmassl.
