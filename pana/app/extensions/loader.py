"""Extension file discovery and loading.

Auto-discovery locations (checked in order):

* ``~/.pana/extensions/*.py``
* ``~/.pana/extensions/*/__init__.py``
* ``.pana/extensions/*.py``
* ``.pana/extensions/*/__init__.py``

Additional paths may be supplied via the ``-e`` / ``--extension`` CLI flag.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

from pana.app.extensions.api import SourceInfo

logger = logging.getLogger(__name__)


def discover_extension_paths(extra_paths: list[str] | None = None) -> list[Path]:
    """Return all extension file paths from standard locations plus *extra_paths*."""
    paths: list[Path] = []

    _collect_from_dir(Path.home() / ".pana" / "extensions", paths)
    _collect_from_dir(Path.cwd() / ".pana" / "extensions", paths)

    for raw in extra_paths or []:
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            package_init = path / "__init__.py"
            if package_init.exists():
                paths.append(package_init)
            else:
                logger.warning("Extension directory has no __init__.py: %s", path)
        elif path.exists() and path.suffix == ".py":
            paths.append(path)
        else:
            logger.warning("Extension path not found or not a .py file: %s", raw)

    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def build_source_info(path: Path) -> SourceInfo:
    """Build source metadata for a discovered extension path."""
    resolved_path = path.expanduser().resolve()
    global_root = (Path.home() / ".pana" / "extensions").resolve()
    project_root = (Path.cwd() / ".pana" / "extensions").resolve()

    try:
        resolved_path.relative_to(global_root)
        scope = "global"
    except ValueError:
        try:
            resolved_path.relative_to(project_root)
            scope = "project"
        except ValueError:
            scope = "cli"

    if resolved_path.name == "__init__.py":
        name = resolved_path.parent.name
    else:
        name = resolved_path.stem

    return SourceInfo(path=str(resolved_path), name=name, scope=scope)


def _collect_from_dir(directory: Path, paths: list[Path]) -> None:
    if not directory.is_dir():
        return
    for file_path in sorted(directory.glob("*.py")):
        if not file_path.name.startswith("_"):
            paths.append(file_path)
    for subdirectory in sorted(path for path in directory.iterdir() if path.is_dir()):
        package_init = subdirectory / "__init__.py"
        if package_init.exists():
            paths.append(package_init)


def load_extension(path: Path, api: object) -> bool:
    """Load a single extension file and call its ``setup(pana)`` function."""
    module_name = f"pana_ext_{path.stem}_{abs(hash(str(path)))}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            logger.warning("Could not create module spec for extension: %s", path)
            return False

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]

        setup_fn = getattr(module, "setup", None)
        if setup_fn is None or not callable(setup_fn):
            logger.warning("Extension has no setup() function: %s", path)
            return False

        setup_fn(api)
        logger.info("Loaded extension: %s", path)
        return True
    except Exception:
        logger.exception("Failed to load extension: %s", path)
        return False
