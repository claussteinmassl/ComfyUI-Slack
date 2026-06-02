"""Shared test setup.

Registers the repo's ``utils/`` directory as a top-level ``utils`` package so
the listener modules that use relative imports (``from . import config``) can be
imported by name. Crucially this never imports the repo-root ``__init__.py`` (the
ComfyUI entry point, whose ``from .nodes ...`` imports pull in numpy/torch and
only work inside a running ComfyUI). ``utils/__init__.py`` is empty, so loading
the package on its own is side-effect free.

With ``utils`` registered, tests do plain ``from utils import router`` etc. The
two older test files keep loading their target by file path under a private name;
that coexists fine (different module identities).
"""

import importlib.util
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_UTILS_DIR = os.path.join(_REPO, "utils")

if "utils" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "utils",
        os.path.join(_UTILS_DIR, "__init__.py"),
        submodule_search_locations=[_UTILS_DIR],
    )
    _pkg = importlib.util.module_from_spec(_spec)
    sys.modules["utils"] = _pkg
    _spec.loader.exec_module(_pkg)
