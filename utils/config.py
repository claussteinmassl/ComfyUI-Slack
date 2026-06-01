"""Centralized configuration for ComfyUI-Slack.

All values are read lazily from environment variables at call time (never at
import time) so that an unset variable or an unavailable ComfyUI import can
never crash extension loading.
"""

import os

_TRUE = {"1", "true", "yes", "on"}


def _csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def listener_enabled() -> bool:
    """Master opt-in switch for the Slack -> ComfyUI listener."""
    return os.environ.get("SLACK_LISTENER_ENABLED", "").strip().lower() in _TRUE


def app_token() -> str | None:
    """Slack app-level token (xapp-...) with the connections:write scope."""
    return os.environ.get("SLACK_APP_TOKEN") or None


def bot_token() -> str | None:
    """Slack bot token (xoxb-...). Also used to authenticate file downloads."""
    return os.environ.get("SLACK_BOT_TOKEN") or None


def workflow_dir() -> str | None:
    """Folder containing manifest.json plus the API-format template files."""
    return os.environ.get("SLACK_WORKFLOW_DIR") or None


def comfy_api_key() -> str | None:
    """comfy.org API key for authenticating partner/API nodes in headless runs.

    The ComfyUI frontend injects a login token into every prompt queued from the
    browser, which is how comfy.org API nodes (e.g. the OpenAI nodes) authenticate.
    A prompt POSTed by the listener has no such token, so any API node would fail
    with "Unauthorized: Please login first to use this node." Setting this lets us
    send the key as `extra_data.api_key_comfy_org` instead. Generate one at
    platform.comfy.org. Returns None when unset (only needed by workflows that use
    comfy.org API nodes).
    """
    return os.environ.get("SLACK_COMFY_API_KEY") or None


def allowed_users() -> set[str]:
    """Slack user IDs (Uxxxx) permitted to trigger workflows."""
    return _csv(os.environ.get("SLACK_ALLOWED_USERS"))


def allowed_channels() -> set[str]:
    """Slack channel IDs (Cxxxx) permitted to trigger workflows."""
    return _csv(os.environ.get("SLACK_ALLOWED_CHANNELS"))


def max_input_mb() -> int:
    """Maximum size (MB) of an attached file the bot will download."""
    raw = os.environ.get("SLACK_MAX_INPUT_MB", "")
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 20


def comfy_base_url() -> str:
    """Resolve the local ComfyUI HTTP base URL for the /prompt endpoint.

    Resolution order: SLACK_COMFY_URL override -> running PromptServer instance
    -> comfy.cli_args -> http://127.0.0.1:8188. The listen address 0.0.0.0/* is
    normalized to 127.0.0.1 for the loopback call.
    """
    override = os.environ.get("SLACK_COMFY_URL")
    if override:
        return override.rstrip("/")

    host, port = "127.0.0.1", 8188

    try:
        import server  # ComfyUI's server module

        instance = getattr(server.PromptServer, "instance", None)
        if instance is not None:
            addr = getattr(instance, "address", None)
            prt = getattr(instance, "port", None)
            if addr:
                host = addr
            if prt:
                port = int(prt)
    except Exception:
        pass

    try:
        from comfy.cli_args import args

        if getattr(args, "listen", None):
            host = args.listen
        if getattr(args, "port", None):
            port = int(args.port)
    except Exception:
        pass

    if host in ("0.0.0.0", "*", "::", ""):
        host = "127.0.0.1"

    return f"http://{host}:{port}"
