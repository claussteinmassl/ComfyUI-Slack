"""Workflow registry: load and validate API-format templates from a folder.

The folder (SLACK_WORKFLOW_DIR) must contain a ``manifest.json`` listing the
available workflows plus the API-format template files it references. Each
template is validated for the required ``_meta.title`` markers at load time;
bad entries are logged and skipped rather than crashing the listener.
"""

import json
import os
from dataclasses import dataclass, field

# Markers a template must contain to be usable.
REQUIRED_MARKERS = ("SLACK_PROMPT", "SLACK_OUTPUT")
VALID_MODALITIES = ("text", "image", "video", "any")


@dataclass
class Workflow:
    name: str
    label: str
    description: str
    modality: str
    keywords: list[str]
    template_path: str
    graph: dict = field(repr=False)


def _node_titles(graph: dict) -> set[str]:
    titles = set()
    for node in graph.values():
        if isinstance(node, dict):
            title = node.get("_meta", {}).get("title")
            if title:
                titles.add(title)
    return titles


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

            registry[name] = Workflow(
                name=name,
                label=entry.get("label", name),
                description=entry.get("description", ""),
                modality=modality,
                keywords=[k.lower() for k in entry.get("keywords", [])],
                template_path=template_path,
                graph=graph,
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
