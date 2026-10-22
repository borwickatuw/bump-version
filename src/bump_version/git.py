"""The git shell-out: the one place `git` is invoked.

`_run_git` runs git as an argument list, never through a shell, and decodes
its output as UTF-8. On it are built the repository queries (git dir, git
root, remotes, current branch, commit subjects since a tag) and the
repository actions (sync, create a tag, push one tag), which honour
`dry_run`. May import: `output`.
"""

from __future__ import annotations

import subprocess

from bump_version.output import _print_error, _print_info, _print_success, _print_warning


def _run_git(
    *args: str, check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    """
    Run a git command safely.

    Uses subprocess with a list of arguments to avoid shell injection.

    `encoding` is named rather than left to `text=True`, which decodes with
    the locale default: git's own commit-encoding default is UTF-8, so a tag
    summary or author name outside ASCII would mojibake or raise on a host
    running under LANG=C.
    """
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        capture_output=capture,
        encoding="utf-8",
        check=check,
    )


def _is_git_repo() -> bool:
    """Check if the current directory is a git repository."""
    result = _run_git("rev-parse", "--git-dir", check=False)
    return result.returncode == 0


def _get_remotes() -> list[str]:
    """Get list of configured remotes."""
    result = _run_git("remote")
    return [r.strip() for r in result.stdout.strip().split("\n") if r.strip()]


def _get_default_remote() -> str | None:
    """Get the first configured remote, or None if no remotes exist."""
    remotes = _get_remotes()
    if not remotes:
        return None
    return remotes[0]


def _get_current_branch() -> str | None:
    """Get the current branch name, or None if detached HEAD."""
    result = _run_git("symbolic-ref", "--short", "HEAD", check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def _sync_repo() -> None:
    """Sync the repository by fetching tags and pulling the current branch."""
    _print_info("Syncing repository...")

    remote = _get_default_remote()
    if not remote:
        _print_warning("No remote configured, skipping sync")
        return

    # Fetch all tags
    _print_info(f"Fetching tags from {remote}...")
    result = _run_git("fetch", remote, "--tags", check=False)
    if result.returncode == 0:
        _print_success("Tags fetched successfully")
    else:
        _print_warning("Could not fetch tags (network issue or no remote access)")

    # Pull current branch
    branch = _get_current_branch()
    if branch:
        _print_info(f"Pulling latest changes for branch '{branch}'...")
        result = _run_git("pull", remote, branch, check=False)
        if result.returncode == 0:
            _print_success("Branch updated successfully")
        else:
            _print_warning("Could not pull branch (may have uncommitted changes or no tracking)")


def _get_commits_since_tag(tag: str | None) -> list[str]:
    """
    Get list of commit messages since the given tag.

    If tag is None, returns all commits.
    Returns a list of commit subject lines.
    """
    if tag:
        # Get commits from tag to HEAD
        result = _run_git("log", f"{tag}..HEAD", "--pretty=format:%s", check=False)
    else:
        # No tag, get all commits
        result = _run_git("log", "--pretty=format:%s", check=False)

    if result.returncode != 0 or not result.stdout.strip():
        return []

    return [line.strip() for line in result.stdout.strip().split("\n") if line.strip()]


def _get_git_dir() -> str:
    """Return the absolute path to the repository's git directory.

    Uses `git rev-parse --absolute-git-dir` so worktrees, submodules, and
    non-default `.git` locations all resolve to the right place.
    """
    result = _run_git("rev-parse", "--absolute-git-dir", check=False)
    if result.returncode != 0:
        raise RuntimeError("Could not locate git directory: " + (result.stderr or "").strip())
    return result.stdout.strip()


def _get_git_root() -> str:
    """Return the absolute path to the repository's working-tree root."""
    result = _run_git("rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        raise RuntimeError("Could not locate git root: " + (result.stderr or "").strip())
    return result.stdout.strip()


def _create_tag(tag: str, message: str, *, dry_run: bool = False) -> bool:
    """Create an annotated git tag."""
    if dry_run:
        _print_info(f"[DRY RUN] Would create tag: {tag}")
        _print_info(f"[DRY RUN] Message: {message}")
        return True

    _print_info(f"Creating tag '{tag}'...")
    result = _run_git("tag", "-a", tag, "-m", message, check=False)

    if result.returncode == 0:
        _print_success(f"Tag '{tag}' created successfully")
        return True
    else:
        _print_error(f"Failed to create tag: {result.stderr}")
        return False


def _push_tag(tag: str, *, dry_run: bool = False) -> bool:
    """Push a tag to the remote repository."""
    if dry_run:
        _print_info(f"[DRY RUN] Would push tag: {tag}")
        return True

    remote = _get_default_remote()
    if not remote:
        _print_warning("No remote configured, skipping push")
        return True

    _print_info(f"Pushing tag '{tag}' to {remote}...")
    result = _run_git("push", remote, tag, check=False)

    if result.returncode == 0:
        _print_success("Tag pushed successfully")
        return True
    else:
        _print_error(f"Failed to push tag: {result.stderr}")
        return False
