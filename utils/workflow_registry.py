"""Workflow registry: load and validate API-format templates from a folder.

The folder (SLACK_WORKFLOW_DIR) must contain a ``manifest.json`` listing the
available workflows plus the API-format template files it references. Each
template is validated for the required ``_meta.title`` markers at load time;
bad entries are logged and skipped rather than crashing the listener.
"""

import json
import os
import re
from dataclasses import dataclass, field

# Markers a template must contain to be usable.
REQUIRED_MARKERS = ("SLACK_PROMPT", "SLACK_OUTPUT")
VALID_MODALITIES = ("text", "image", "video", "any")

# Image-input slot markers: bare == slot 1, _<n> == slot n.
_IMAGE_SLOT_RE = re.compile(r"^SLACK_INPUT_IMAGE(?:_(\d+))?$")


@dataclass
class Workflow:
    name: str
    label: str
    description: str
    modality: str
    keywords: list[str]
    template_path: str
    graph: dict = field(repr=False)
    image_inputs: int = 0


def _node_titles(graph: dict) -> set[str]:
    titles = set()
    for node in graph.values():
        if isinstance(node, dict):
            title = node.get("_meta", {}).get("title")
            if title:
                titles.add(title)
    return titles


def _image_input_count(titles: set[str]) -> int:
    """Number of SLACK_INPUT_IMAGE / SLACK_INPUT_IMAGE_<n> markers.

    Slot indices: bare marker == 1, _<n> == n. Raises ValueError if the present
    slots are not the contiguous set 1..N (e.g. _2 without a base marker).
    """
    slots = set()
    for t in titles:
        m = _IMAGE_SLOT_RE.match(t)
        if m:
            slots.add(int(m.group(1)) if m.group(1) else 1)
    if not slots:
        return 0
    expected = set(range(1, max(slots) + 1))
    if slots != expected:
        raise ValueError(
            f"image input markers must be contiguous 1..N; got slots "
            f"{sorted(slots)} (expected {sorted(expected)})"
        )
    return len(slots)


def load(dir_path: str) -> dict[str, Workflow]:
    """Parse ``manifest.json`` in *dir_path* and return name -> Workflow.

    Invalid entries are skipped with a printed warning. Returns an empty dict
    if the directory or manifest is missing/unreadable.
    """
    registry: dict[str, Workflow] = {}

    manifest_path = os.path.join(dir_path, "manifest.json")
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except FileNotFoundError:
        print(f"[ComfyUI-Slack] No manifest.json found in {dir_path}.")
        return registry
    except (json.JSONDecodeError, OSError) as e:
        print(f"[ComfyUI-Slack] Failed to read manifest.json: {e}")
        return registry

    entries = manifest.get("workflows") if isinstance(manifest, dict) else manifest
    if not isinstance(entries, list):
        print("[ComfyUI-Slack] manifest.json must contain a 'workflows' list.")
        return registry

    for entry in entries:
        try:
            name = entry["name"]
            template_file = entry["template"]
            modality = entry.get("modality", "text")

            if modality not in VALID_MODALITIES:
                print(f"[ComfyUI-Slack] Workflow '{name}': invalid modality "
                      f"'{modality}' (expected one of {VALID_MODALITIES}); skipped.")
                continue

            template_path = os.path.join(dir_path, template_file)
            with open(template_path, "r", encoding="utf-8") as tf:
                graph = json.load(tf)

            titles = _node_titles(graph)
            missing = [m for m in REQUIRED_MARKERS if m not in titles]
            if missing:
                print(f"[ComfyUI-Slack] Workflow '{name}': template missing required "
                      f"node title marker(s) {missing}; skipped.")
                continue

            try:
                image_inputs = _image_input_count(titles)
            except ValueError as e:
                print(f"[ComfyUI-Slack] Workflow '{name}': {e}; skipped.")
                continue

            registry[name] = Workflow(
                name=name,
                label=entry.get("label", name),
                description=entry.get("description", ""),
                modality=modality,
                keywords=[k.lower() for k in entry.get("keywords", [])],
                template_path=template_path,
                graph=graph,
                image_inputs=image_inputs,
            )
        except KeyError as e:
            print(f"[ComfyUI-Slack] Skipping workflow entry missing field {e}.")
        except (json.JSONDecodeError, OSError) as e:
            print(f"[ComfyUI-Slack] Skipping workflow '{entry.get('name', '?')}': {e}")

    print(f"[ComfyUI-Slack] Loaded {len(registry)} workflow(s): "
          f"{', '.join(registry) or '(none)'}")
    return registry


def list_all(registry: dict[str, Workflow]) -> list[Workflow]:
    return list(registry.values())


def get(registry: dict[str, Workflow], name: str) -> Workflow | None:
    return registry.get(name)


def for_modality(registry: dict[str, Workflow], modality: str) -> list[Workflow]:
    """Templates that accept *modality* input (exact match or 'any')."""
    return [w for w in registry.values() if w.modality in (modality, "any")]
