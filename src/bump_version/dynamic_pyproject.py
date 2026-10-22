"""The dynamic-pyproject migration, and the command that drives it.

The `_dynpp_*` steps and the constants they write move a static hatchling
`pyproject.toml` to hatch-vcs tag-derived versioning, as surgical text edits
validated by re-parsing; every refusal happens before the first write.
`_cmd_dynamic_pyproject` runs the steps in order. May import: `output`,
`exit_status`, `git`, `version` (the drift check), `prompts`
(`_prompt_yes_no`), `pyproject` (the shared parse-or-exit).
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
import tomllib
from typing import NoReturn

from bump_version.exit_status import EXIT_DECLINED, EXIT_FAILURE, EXIT_OK
from bump_version.git import _get_git_root, _run_git
from bump_version.output import _print_error, _print_info, _print_success, _print_warning
from bump_version.prompts import _prompt_yes_no
from bump_version.pyproject import _parse_pyproject
from bump_version.version import _get_current_version

# The exact archival content PYTHON.md §16 prescribes: enough commit metadata
# for hatch-vcs to resolve a version from a `git archive` tarball.
_GIT_ARCHIVAL_CONTENT = (
    "node: $Format:%H$\n"
    "node-date: $Format:%cI$\n"
    "describe-name: $Format:%(describe:tags=true,match=*[0-9]*)$\n"
    "ref-names: $Format:%D$\n"
)

_GITATTRIBUTES_BLOCK = (
    "# Substitute commit metadata into .git_archival.txt when `git archive`"
    " builds\n"
    '# a source tarball (e.g. GitHub "Download ZIP"), so hatch-vcs can'
    " resolve a\n"
    "# version without a .git directory.\n"
    ".git_archival.txt  export-subst\n"
)

_MIGRATION_FILES = ["pyproject.toml", ".gitattributes", ".git_archival.txt"]


def _dynpp_abort(message: str) -> NoReturn:
    """Abort the migration without having modified pyproject.toml."""
    _print_error(f"Error: {message}; pyproject.toml left unmodified")
    sys.exit(EXIT_FAILURE)


def _dynpp_preconditions(root: str) -> tuple[str, dict]:
    """Check migration preconditions; return pyproject.toml (text, parsed)."""
    path = os.path.join(root, "pyproject.toml")
    if not os.path.exists(path):
        _print_error("Error: no pyproject.toml at the git root; nothing to migrate")
        sys.exit(EXIT_FAILURE)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    pyproject = _parse_pyproject(text, path)

    project = pyproject.get("project")
    if not isinstance(project, dict):
        _print_error("Error: pyproject.toml has no [project] table")
        sys.exit(EXIT_FAILURE)
    if "version" not in project and "version" in project.get("dynamic", []):
        _print_success("pyproject.toml already uses dynamic versioning; nothing to do")
        sys.exit(EXIT_OK)

    backend = pyproject.get("build-system", {}).get("build-backend")
    if backend != "hatchling.build":
        _print_error(f"Error: only hatchling is supported (build-backend is {backend!r})")
        sys.exit(EXIT_FAILURE)
    if "version" not in project:
        _print_error("Error: [project] has no version key to convert")
        sys.exit(EXIT_FAILURE)

    dirty = _run_git("status", "--porcelain", "--", *_MIGRATION_FILES, check=False)
    if dirty.stdout.strip():
        _print_error(
            "Error: uncommitted changes in "
            + "/".join(_MIGRATION_FILES)
            + "; commit or stash them first"
        )
        sys.exit(EXIT_FAILURE)
    return text, pyproject


def _dynpp_check_drift(static_version: str, args: argparse.Namespace) -> None:
    """Warn (and confirm) when the static version disagrees with the tags."""
    current = _get_current_version(args.prefix)
    tag_version = f"{current.major}.{current.minor}.{current.patch}" if current else None
    if tag_version == static_version:
        return
    if current:
        _print_warning(
            f"pyproject.toml says {static_version} but the latest tag is "
            f"{current}.\nAfter migration, built versions derive from tags "
            f"(builds become {tag_version}-based)."
        )
    else:
        _print_warning(
            f"pyproject.toml says {static_version} but no "
            f"{args.prefix}X.Y.Z tags exist.\nAfter migration, built versions "
            "derive from tags; tag the repo to restore the version."
        )
    if args.dry_run or args.yes:
        return
    if not _prompt_yes_no("Continue with migration?"):
        _print_warning("Aborted; pyproject.toml left unmodified")
        sys.exit(EXIT_DECLINED)


def _dynpp_find_project_lines(lines: list[str]) -> tuple[int | None, int | None]:
    """Locate the version and dynamic lines within the [project] table."""
    section = None
    version_idx = dynamic_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
        elif section == "[project]" and re.match(r"version\s*=", stripped):
            version_idx = i
        elif section == "[project]" and re.match(r"dynamic\s*=", stripped):
            dynamic_idx = i
    return version_idx, dynamic_idx


def _dynpp_append_to_dynamic(line: str) -> str:
    """Append "version" to a single-line `dynamic = [...]` entry."""
    idx = line.rfind("]")
    if idx == -1:
        _dynpp_abort(
            "cannot edit a multi-line dynamic = [...] entry automatically; "
            'add "version" to it manually'
        )
    before = line[:idx].rstrip()
    if before.endswith("["):
        insert = '"version"'
    elif before.endswith(","):
        insert = ' "version"'
    else:
        insert = ', "version"'
    return before + insert + line[idx:]


def _dynpp_convert_version(text: str) -> str:
    """Replace the static [project] version with a dynamic declaration."""
    lines = text.splitlines(keepends=True)
    version_idx, dynamic_idx = _dynpp_find_project_lines(lines)
    if version_idx is None:
        _dynpp_abort("could not find the version line under [project]")
    if dynamic_idx is None:
        lines[version_idx] = 'dynamic = ["version"]\n'
    elif '"version"' in lines[dynamic_idx] or "'version'" in lines[dynamic_idx]:
        del lines[version_idx]
    else:
        lines[dynamic_idx] = _dynpp_append_to_dynamic(lines[dynamic_idx])
        del lines[version_idx]
    return "".join(lines)


def _dynpp_add_hatch_vcs(text: str) -> str:
    """Insert "hatch-vcs" into [build-system] requires, after "hatchling"."""
    lines = text.splitlines(keepends=True)
    section = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("["):
            section = stripped
        elif section == "[build-system]" and re.match(r"requires\s*=", stripped):
            if "hatch-vcs" in line:
                return text
            if '"hatchling"' not in line or "]" not in line:
                _dynpp_abort(
                    "cannot edit [build-system] requires automatically; "
                    'add "hatch-vcs" to it manually'
                )
            lines[i] = line.replace('"hatchling"', '"hatchling", "hatch-vcs"', 1)
            return "".join(lines)
    _dynpp_abort("could not find the requires line under [build-system]")


def _dynpp_validate(new_text: str) -> None:
    """Re-parse the rewritten pyproject.toml and assert the migration took."""
    try:
        parsed = tomllib.loads(new_text)
    except tomllib.TOMLDecodeError as exc:
        _dynpp_abort(f"rewritten pyproject.toml does not parse: {exc}")
    project = parsed.get("project", {})
    hatch_version = parsed.get("tool", {}).get("hatch", {}).get("version", {}).get("source")
    ok = (
        "version" not in project
        and "version" in project.get("dynamic", [])
        and "hatch-vcs" in parsed.get("build-system", {}).get("requires", [])
        and hatch_version == "vcs"
    )
    if not ok:
        _dynpp_abort("rewritten pyproject.toml failed validation")


def _dynpp_rewrite(text: str) -> str:
    """Produce the migrated pyproject.toml text, validated by re-parsing."""
    new_text = _dynpp_convert_version(text)
    new_text = _dynpp_add_hatch_vcs(new_text)
    if not new_text.endswith("\n"):
        new_text += "\n"
    new_text += '\n[tool.hatch.version]\nsource = "vcs"\n'
    _dynpp_validate(new_text)
    return new_text


def _dynpp_write_archival_files(root: str) -> None:
    """Write .git_archival.txt and ensure the export-subst rule exists."""
    archival = os.path.join(root, ".git_archival.txt")
    with open(archival, "w", encoding="utf-8") as f:
        f.write(_GIT_ARCHIVAL_CONTENT)
    _print_success("Wrote .git_archival.txt")

    attributes = os.path.join(root, ".gitattributes")
    existing = ""
    if os.path.exists(attributes):
        with open(attributes, encoding="utf-8") as f:
            existing = f.read()
    if re.search(r"^\.git_archival\.txt\s+export-subst", existing, re.MULTILINE):
        _print_info(".gitattributes already has the export-subst rule")
        return
    with open(attributes, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write(_GITATTRIBUTES_BLOCK)
    _print_success("Added the export-subst rule to .gitattributes")


def _dynpp_warn_hardcoded_versions(root: str) -> None:
    """Warn (never rewrite) about hardcoded __version__ literals in code."""
    result = _run_git("ls-files", "--full-name", "--", root, check=False)
    pattern = re.compile(r"__version__\s*=\s*[\"']\d")
    hits = []
    for name in result.stdout.splitlines():
        if not name.endswith(".py"):
            continue
        try:
            with open(os.path.join(root, name), encoding="utf-8") as f:
                if pattern.search(f.read()):
                    hits.append(name)
        except OSError:
            continue
    if not hits:
        return
    _print_warning("Hardcoded __version__ strings found (left unchanged):")
    for name in hits:
        _print_warning(f"  {name}")
    _print_warning(
        "Consider deriving them from package metadata instead:\n"
        "    from importlib.metadata import version\n"
        '    __version__ = version("your-package")'
    )


def _dynpp_print_dry_run(old_text: str, new_text: str, root: str) -> None:
    """Show what the migration would do without changing anything."""
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile="pyproject.toml",
        tofile="pyproject.toml",
    )
    _print_info("[DRY RUN] Would rewrite pyproject.toml:")
    print("".join(diff), end="")
    _print_info("[DRY RUN] Would write .git_archival.txt")
    attributes = os.path.join(root, ".gitattributes")
    verb = "append the export-subst rule to" if os.path.exists(attributes) else "create"
    _print_info(f"[DRY RUN] Would {verb} .gitattributes")
    _print_info("[DRY RUN] Would offer to commit the migration")


def _dynpp_offer_commit(root: str, args: argparse.Namespace) -> int:
    """Offer to commit the three migration files (default yes).

    Declining is declining an optional step, not the migration: the files
    are already rewritten, so it exits EXIT_OK like any other success.
    """
    if not args.yes:
        print()
        if not _prompt_yes_no("Commit the migration now?", default=True):
            _print_info("Not committed; review and commit when ready")
            return EXIT_OK
    paths = [os.path.join(root, name) for name in _MIGRATION_FILES]
    add = _run_git("add", "--", *paths, check=False)
    if add.returncode != 0:
        _print_error(f"Failed to stage migration files: {add.stderr}")
        return EXIT_FAILURE
    # Pathspec-limited commit so unrelated staged changes stay staged.
    commit = _run_git(
        "commit",
        "-m",
        "Switch to dynamic versioning via hatch-vcs",
        "--",
        *paths,
        check=False,
    )
    if commit.returncode != 0:
        _print_error(f"Failed to commit migration: {commit.stderr}")
        return EXIT_FAILURE
    _print_success("Committed the migration")
    return EXIT_OK


def _cmd_dynamic_pyproject(args: argparse.Namespace) -> int:
    """Handle the 'dynamic-pyproject' command: migrate to git-tag versioning."""
    root = _get_git_root()
    text, pyproject = _dynpp_preconditions(root)
    _dynpp_check_drift(pyproject["project"]["version"], args)
    new_text = _dynpp_rewrite(text)

    if args.dry_run:
        _dynpp_print_dry_run(text, new_text, root)
        return EXIT_OK

    with open(os.path.join(root, "pyproject.toml"), "w", encoding="utf-8") as f:
        f.write(new_text)
    _print_success("Rewrote pyproject.toml for dynamic versioning")
    _dynpp_write_archival_files(root)
    _dynpp_warn_hardcoded_versions(root)

    result = _dynpp_offer_commit(root, args)
    print()
    _print_info(
        "For editable installs, run 'uv sync --reinstall' so the environment\n"
        "picks up the tag-derived version; 'uv build' is a good sanity check."
    )
    return result
