"""The static-version guard.

Reads `pyproject.toml` at the git root and refuses a bump while `[project]
version` is static, unless `[tool.bump-version] allow-static-version = true`
(docs/DECISIONS.md 003). May import: `output`, `exit_status`, `git` (git
root).
"""

from __future__ import annotations

import os
import sys
import tomllib

from bump_version.exit_status import EXIT_FAILURE
from bump_version.git import _get_git_root
from bump_version.output import _print_error, _print_info


def _read_pyproject() -> dict | None:
    """Parse pyproject.toml at the git root, or return None if absent.

    A file that exists but fails to parse is a fail-fast error: exit 1
    with a clear message rather than silently skipping the version check.
    """
    path = os.path.join(_get_git_root(), "pyproject.toml")
    if not os.path.exists(path):
        return None
    # Bytes decoded as UTF-8 by hand, exactly as tomllib.load does: text mode
    # would translate a stray bare CR into a newline and accept a file that
    # TOML itself rejects.
    with open(path, "rb") as f:
        return _parse_pyproject(f.read().decode("utf-8"), path)


def _parse_pyproject(text: str, path: str) -> dict:
    """Parse pyproject.toml text, or exit EXIT_FAILURE if it does not parse.

    The one fail-fast rule for an unparseable pyproject.toml, shared by this
    guard and the dynamic-pyproject migration, which needs the raw text as
    well and so reads the file itself.
    """
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        _print_error(f"Error: could not parse {path}: {exc}")
        sys.exit(EXIT_FAILURE)


def _check_pyproject_version() -> None:
    """Refuse to bump when pyproject.toml pins a static [project] version.

    Tagging such a repo would leave the tree claiming the old version. The
    escape hatch is `allow-static-version = true` under [tool.bump-version]
    — a durable per-repo fact, deliberately config rather than a CLI flag.
    """
    pyproject = _read_pyproject()
    if pyproject is None:
        return
    project = pyproject.get("project")
    if not isinstance(project, dict) or "version" not in project:
        return
    if "version" in project.get("dynamic", []):
        return

    tool = pyproject.get("tool")
    config = tool.get("bump-version") if isinstance(tool, dict) else None
    allow = config.get("allow-static-version") if isinstance(config, dict) else None

    if allow is True:
        _print_info(
            "pyproject.toml pins a static version; proceeding anyway (allow-static-version = true)"
        )
        return
    if allow is not None and not isinstance(allow, bool):
        _print_error("Error: allow-static-version under [tool.bump-version] must be a boolean")
        sys.exit(EXIT_FAILURE)

    _print_error(
        f"pyproject.toml pins version {project['version']} statically; "
        "tagging would make it stale.\n"
        "Run 'bump-version dynamic-pyproject' to switch to git-tag "
        "versioning, or set\n"
        "allow-static-version = true under [tool.bump-version] "
        "if this is intentional."
    )
    sys.exit(EXIT_FAILURE)
