"""Runtime bootstrap for iLOrest.

The CLI is normally used with the companion ``python-redfish-library`` source
checkout or installed package present on ``sys.path``. When developing from a
source tree layout in which the library is a sibling checkout (for example
``C:\\git_pqc\\python-redfish-library``), the tool package can discover that
checkout automatically — but **only** when the environment variable
``ILOREST_DEV_MODE=1`` is set.  In production installs (no env var) the
bootstrap is a no-op and the pip-installed ``redfish`` package is used as-is.
"""

from __future__ import annotations

import os
import sys


def _candidate_redfish_roots() -> list[str]:
    """Yield likely filesystem roots that contain a ``redfish`` package."""
    roots: list[str] = []

    for env_name in ("ILOREST_REDFISH_SRC", "REDFISH_SRC", "REDFISH_LIBRARY_SRC"):
        value = os.environ.get(env_name)
        if value:
            roots.extend(part for part in value.split(os.pathsep) if part)

    tool_root = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(tool_root)
    parent_root = os.path.dirname(repo_root)

    for base in (
        tool_root,
        repo_root,
        parent_root,
        os.path.join(repo_root, "src"),
        os.path.join(parent_root, "python-redfish-library"),
        os.path.join(parent_root, "python-ilorest-library"),
        os.path.join(parent_root, "python-redfish-library", "src"),
        os.path.join(parent_root, "python-ilorest-library", "src"),
    ):
        if base:
            roots.extend((base, os.path.join(base, "src")))

    ordered: list[str] = []
    seen: set[str] = set()
    for root in roots:
        candidate = os.path.abspath(root)
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return ordered


def _candidate_has_redfish_package(root: str) -> bool:
    """Return True when *root* is a parent of the ``redfish`` package."""
    pkg_dir = os.path.join(root, "redfish")
    return (
        os.path.isdir(pkg_dir)
        and os.path.isfile(os.path.join(pkg_dir, "__init__.py"))
        and os.path.isfile(os.path.join(pkg_dir, "rest", "pqc.py"))
        and os.path.isfile(os.path.join(pkg_dir, "rest", "connections.py"))
    )


def _ensure_redfish_available() -> None:
    """Prefer a sibling source checkout over any older installed ``redfish`` package.

    Only active when ``ILOREST_DEV_MODE=1`` is set in the environment to avoid
    silently substituting the pip-installed library in production installs.
    """
    if os.environ.get("ILOREST_DEV_MODE", "").strip() != "1":
        return

    import logging as _logging

    _log = _logging.getLogger(__name__)
    for root in _candidate_redfish_roots():
        if _candidate_has_redfish_package(root):
            _log.warning(
                "ILOREST_DEV_MODE: substituting redfish package from %r "
                "(overriding any pip-installed version).",
                root,
            )
            if root not in sys.path:
                sys.path.insert(0, root)
            for name in list(sys.modules):
                if name == "redfish" or name.startswith("redfish."):
                    sys.modules.pop(name, None)
            return


_ensure_redfish_available()
