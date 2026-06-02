"""Resolve where a "Save output" copy of a sent file should be written.

Both send nodes optionally keep a local copy of what they upload to Slack. The
destination is either ComfyUI's standard output directory (with the same
subfolder + auto-incrementing counter behavior as the built-in Save nodes) or a
user-supplied absolute folder. This module owns that path logic so the two nodes
don't duplicate it.
"""

import os

try:
    import folder_paths  # only available inside ComfyUI
except Exception:  # pragma: no cover - only available inside ComfyUI
    folder_paths = None

# Dropdown options for the nodes' ``save_location`` widget. Imported by both
# nodes for the combo options and the mode comparison, so the strings stay in
# sync with the comparison below and with the frontend extension.
SAVE_LOCATIONS = ["ComfyUI output folder", "Absolute path"]


def resolve_save_path(
    save_location: str,
    output_folder: str,
    filename_prefix: str,
    ext: str,
    width: int = 0,
    height: int = 0,
    index: int = 0,
) -> str:
    """Return the absolute path to write to, creating parent dirs as needed."""
    if save_location == "Absolute path":
        base = (output_folder or "").strip()
        if not base:
            raise ValueError(
                "Save output: 'Absolute path' selected but output_folder is empty."
            )
        os.makedirs(base, exist_ok=True)
        return os.path.join(base, f"{filename_prefix}_{index:05d}.{ext}")

    # ComfyUI output folder — reuse the same helper the built-in Save nodes use;
    # it handles subfolders inside filename_prefix and an auto-incrementing
    # counter so files are never overwritten.
    if folder_paths is None:
        raise RuntimeError(
            "ComfyUI folder_paths unavailable; cannot resolve the output directory."
        )
    full_output_folder, filename, counter, _subfolder, _ = folder_paths.get_save_image_path(
        filename_prefix, folder_paths.get_output_directory(), width, height
    )
    os.makedirs(full_output_folder, exist_ok=True)
    return os.path.join(full_output_folder, f"{filename}_{counter:05}_.{ext}")
