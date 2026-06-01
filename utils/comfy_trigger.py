"""Inject Slack request values into a workflow template and POST it to ComfyUI.

The triggered workflow itself ends in a SlackSendImage/SlackSendVideo node, so
output delivery is handled by the existing send path -- this module only has to
queue the prompt, not wait for completion.
"""

import copy
import json
import urllib.error
import urllib.request
from uuid import uuid4

from . import config

_CLIENT_ID = uuid4().hex

# Per class_type, the input field that holds the prompt text.
_PROMPT_FIELDS = {
    "CLIPTextEncode": "text",
    "PrimitiveNode": "value",
    "PrimitiveString": "value",
    "String": "value",
    "StringConstant": "string",
}


def _title(node: dict) -> str:
    return node.get("_meta", {}).get("title", "")


def _set_prompt(node: dict, prompt: str) -> None:
    inputs = node.setdefault("inputs", {})
    field = _PROMPT_FIELDS.get(node.get("class_type"))
    if field is None:
        # Fallback: first string-valued input.
        field = next(
            (k for k, v in inputs.items() if isinstance(v, str)), None
        )
    if field is None:
        field = "text"
    inputs[field] = prompt


def inject(workflow_graph: dict, req) -> dict:
    """Return a deep copy of *workflow_graph* with Slack values injected.

    Targets are located by ``_meta.title`` markers: SLACK_PROMPT,
    SLACK_INPUT_IMAGE, SLACK_INPUT_VIDEO, SLACK_OUTPUT.
    """
    graph = copy.deepcopy(workflow_graph)

    for node in graph.values():
        if not isinstance(node, dict):
            continue
        title = _title(node)

        if title == "SLACK_PROMPT":
            _set_prompt(node, req.prompt)
        elif title == "SLACK_INPUT_IMAGE" and req.input_kind == "image":
            node.setdefault("inputs", {})["image"] = req.input_path
        elif title == "SLACK_INPUT_VIDEO" and req.input_kind == "video":
            node.setdefault("inputs", {})["video"] = req.input_path
        elif title == "SLACK_OUTPUT":
            inputs = node.setdefault("inputs", {})
            inputs["channel"] = req.channel
            inputs["thread_ts"] = req.thread_ts

    return graph


def submit_prompt(graph: dict) -> str:
    """POST a graph to ComfyUI's /prompt endpoint; return the prompt_id."""
    payload = {"prompt": graph, "client_id": _CLIENT_ID}

    # comfy.org API nodes authenticate via a token the browser frontend normally
    # injects into the prompt. A listener-queued prompt has none, so pass the key
    # explicitly as extra_data.api_key_comfy_org (the field ComfyUI's executor
    # forwards to those nodes' auth header). Skipped when no key is configured.
    api_key = config.comfy_api_key()
    if api_key:
        payload["extra_data"] = {"api_key_comfy_org": api_key}

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        config.comfy_base_url() + "/prompt",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as resp:
            result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("error", parsed)
        except json.JSONDecodeError:
            pass
        raise RuntimeError(f"ComfyUI rejected the workflow: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Could not reach ComfyUI at {config.comfy_base_url()}: {e.reason}"
        ) from e

    prompt_id = result.get("prompt_id")
    if not prompt_id:
        raise RuntimeError(f"/prompt returned no prompt_id: {result}")
    return prompt_id


def run(workflow, req) -> str:
    """Inject *req* into *workflow* and queue it. Returns the prompt_id."""
    return submit_prompt(inject(workflow.graph, req))
