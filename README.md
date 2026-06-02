# ComfyUI-Slack

Send generated images and videos directly to a Slack channel from within a ComfyUI workflow.

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

You can create the app two ways: paste a ready-made **manifest** (fast), or click through the
settings **by hand** (so you understand what each one does). Both produce the same app — pick one.

### Quick start: create the app from a manifest (recommended)

Slack can build an app from a manifest that pre-fills the name, scopes, and — for the listener —
Socket Mode, interactivity, and event subscriptions in a single step.

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → **From a manifest**.
2. Select your workspace, then click **Next**.
3. Paste the manifest below (leave the format on **YAML**), click **Next**, then **Create**.

```yaml
display_information:
  name: ComfyUI
  description: Send ComfyUI images and videos to Slack, and trigger workflows from Slack.
features:
  bot_user:
    display_name: ComfyUI
    always_online: true
oauth_config:
  scopes:
    bot:
      - files:write          # upload images and videos
      - chat:write           # post messages, status, and choice buttons
      - channels:read        # resolve channel names to IDs
      - app_mentions:read    # listener only — receive @mentions
      - files:read           # listener only — download attached images/videos
settings:
  event_subscriptions:       # listener only
    bot_events:
      - app_mention
  interactivity:             # listener only — needed for the choice buttons
    is_enabled: true
  socket_mode_enabled: true  # listener only — outbound WebSocket, no public URL needed
  org_deploy_enabled: false
  token_rotation_enabled: false
```

This manifest configures **both** the send nodes and the Slack listener. If you only want the
send nodes, you can delete the lines marked *“listener only”* (and the whole `settings:` block) —
or just leave them; the extra scopes are harmless.

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
| `channels:read` | Resolve channel names to IDs |
| `chat:write` | Post messages to channels |

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

### 6. Find Your Channel ID

The nodes accept a **channel ID**, not a channel name. To find it in Slack:

- Right-click the channel → **View channel details**
- Scroll to the bottom of the dialog — the ID looks like `C0B6SUZMHC6`

Alternatively, invite the bot to the channel first:
```
/invite @ComfyUI
```

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

- **Reinstall the app** to your workspace to apply the new scopes, and **invite the bot** to
  the channel (`/invite @ComfyUI`).

### 2. Build a workflow registry

1. In ComfyUI, enable **dev mode** (*Settings → Enable Dev Mode Options*) so the
   **Save (API Format)** button appears.
2. Build a workflow that **ends in a `Send Image to Slack` / `Send Video to Slack` node**,
   then **rename** these nodes (right-click → *Title*) so the listener can find them:

   | Rename this node to | Role |
   |---------------------|------|
   | `SLACK_PROMPT` | The text prompt node (e.g. the positive `CLIPTextEncode`) — receives the message text |
   | `SLACK_OUTPUT` | The final `Send … to Slack` node — receives the channel, thread, and the triggering user to @-mention |
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
| `SLACK_ALLOWED_USERS` | one of these | empty | CSV of allowed user IDs (`U…`) |
| `SLACK_ALLOWED_CHANNELS` | one of these | empty | CSV of allowed channel IDs (`C…`) |
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
$env:SLACK_ALLOWED_USERS = "U0123ABC,U0456DEF"
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
| `channel` | STRING | Slack channel ID (e.g. `C0B6SUZMHC6`) |
| `filename_prefix` | STRING | Base name for the uploaded file |
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
| `channel` | STRING | Slack channel ID |
| `filename_prefix` | STRING | Base name for the uploaded file |
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

## Troubleshooting

**`SLACK_BOT_TOKEN environment variable is not set`** — set the variable in the shell that launches ComfyUI and restart.

**`Slack upload failed: not_in_channel`** — the bot hasn't been invited to the channel. Run `/invite @ComfyUI` in Slack.

**`Slack upload failed: channel_not_found`** — double-check the channel ID in the node. Use the ID (e.g. `C0B6SUZMHC6`), not the channel name.

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

**`template missing required node title marker(s)`** — rename the prompt node to `SLACK_PROMPT`
and the final Slack send node to `SLACK_OUTPUT` in your workflow, then re-export it with
**Save (API Format)**.

**Mention does nothing** — make sure the bot is invited to the channel, `app_mention` is
subscribed under Event Subscriptions, and Socket Mode is enabled. Re-install the app after
changing scopes.

## License

MIT — see [LICENSE](LICENSE). © 2026 Claus Steinmassl.
