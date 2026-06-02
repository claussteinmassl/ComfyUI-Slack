"""Unit tests for utils/local_save.py (save-path resolution)."""

import os

import pytest

from utils import local_save


def test_save_locations_constant():
    assert local_save.SAVE_LOCATIONS == ["ComfyUI output folder", "Absolute path"]


# --------------------------------------------------------------------------- #
# Absolute path mode
# --------------------------------------------------------------------------- #
def test_absolute_path_builds_and_creates_dir(tmp_path):
    target = tmp_path / "exports"
    out = local_save.resolve_save_path(
        "Absolute path", str(target), "ComfyUI", "png", index=0
    )
    assert out == os.path.join(str(target), "ComfyUI_00000.png")
    assert target.is_dir()  # created by os.makedirs


def test_absolute_path_index_zero_padded(tmp_path):
    out = local_save.resolve_save_path(
        "Absolute path", str(tmp_path), "clip", "mp4", index=42
    )
    assert out.endswith("clip_00042.mp4")


def test_absolute_path_strips_whitespace(tmp_path):
    padded = f"  {tmp_path}  "
    out = local_save.resolve_save_path("Absolute path", padded, "x", "wav", index=1)
    assert out == os.path.join(str(tmp_path), "x_00001.wav")


@pytest.mark.parametrize("folder", ["", "   "])
def test_absolute_path_empty_folder_raises(folder):
    with pytest.raises(ValueError, match="output_folder is empty"):
        local_save.resolve_save_path("Absolute path", folder, "x", "png")


# --------------------------------------------------------------------------- #
# ComfyUI output folder mode
# --------------------------------------------------------------------------- #
def test_comfy_mode_without_folder_paths_raises(monkeypatch):
    monkeypatch.setattr(local_save, "folder_paths", None)
    with pytest.raises(RuntimeError, match="folder_paths unavailable"):
        local_save.resolve_save_path("ComfyUI output folder", "", "ComfyUI", "png")


def test_comfy_mode_uses_folder_paths(monkeypatch, tmp_path):
    out_dir = tmp_path / "comfy_out"

    class FakeFolderPaths:
        @staticmethod
        def get_output_directory():
            return str(out_dir)

        @staticmethod
        def get_save_image_path(prefix, output_dir, width, height):
            # full_output_folder, filename, counter, subfolder, prefix
            return str(out_dir), prefix, 7, "", prefix

    monkeypatch.setattr(local_save, "folder_paths", FakeFolderPaths)
    out = local_save.resolve_save_path(
        "ComfyUI output folder", "", "ComfyUI", "png", width=64, height=64
    )
    assert out == os.path.join(str(out_dir), "ComfyUI_00007_.png")
    assert out_dir.is_dir()
