"""Command-line interface for bump-version."""

from __future__ import annotations

import argparse
import os
import re
import readline
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from typing import NoReturn


__version__ = "1.0.0"


class BumpType(Enum):
    """Version bump types."""

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


@dataclass
class Version:
    """Semantic version representation."""

    major: int
    minor: int
    patch: int
    prefix: str = "v"

    def __str__(self) -> str:
        return f"{self.prefix}{self.major}.{self.minor}.{self.patch}"

    def bump(self, bump_type: BumpType) -> Version:
        """Return a new Version with the specified component bumped."""
        if bump_type == BumpType.MAJOR:
            return Version(self.major + 1, 0, 0, self.prefix)
        elif bump_type == BumpType.MINOR:
            return Version(self.major, self.minor + 1, 0, self.prefix)
        else:  # PATCH
            return Version(self.major, self.minor, self.patch + 1, self.prefix)


class Color:
    """ANSI color codes for terminal output."""

    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[0;33m"
    BLUE = "\033[0;34m"
    RESET = "\033[0m"

    @classmethod
    def enabled(cls) -> bool:
        """Check if color output should be enabled."""
        return sys.stdout.isatty()

    @classmethod
    def wrap(cls, text: str, color: str) -> str:
        """Wrap text in color codes if colors are enabled."""
        if cls.enabled():
            return f"{color}{text}{cls.RESET}"
        return text


def _print_info(message: str) -> None:
    """Print an info message in blue."""
    print(Color.wrap(message, Color.BLUE))


def _print_success(message: str) -> None:
    """Print a success message in green."""
    print(Color.wrap(message, Color.GREEN))


def _print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    print(Color.wrap(message, Color.YELLOW))


def _print_error(message: str) -> None:
    """Print an error message in red to stderr."""
    print(Color.wrap(message, Color.RED), file=sys.stderr)


def _run_git(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """
    Run a git command safely.

    Uses subprocess with a list of arguments to avoid shell injection.
    """
    cmd = ["git", *args]
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
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


def _get_version_tags(prefix: str = "v") -> list[str]:
    """
    Get all version tags matching semantic versioning pattern.

    Returns tags sorted by version number (lowest to highest).
    """
    # Build pattern based on prefix
    if prefix:
        pattern = f"{prefix}[0-9]*.[0-9]*.[0-9]*"
    else:
        pattern = "[0-9]*.[0-9]*.[0-9]*"

    result = _run_git("tag", "-l", pattern, check=False)
    if result.returncode != 0:
        return []

    tags = [t.strip() for t in result.stdout.strip().split("\n") if t.strip()]

    # Sort by version number
    def version_key(tag: str) -> tuple[int, int, int]:
        version = _parse_version(tag, prefix)
        if version:
            return (version.major, version.minor, version.patch)
        return (0, 0, 0)

    return sorted(tags, key=version_key)


def _parse_version(tag: str, prefix: str = "v") -> Version | None:
    """Parse a version tag into a Version object."""
    # Remove prefix
    version_str = tag
    if prefix and tag.startswith(prefix):
        version_str = tag[len(prefix) :]

    # Match semver pattern
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version_str)
    if not match:
        return None

    return Version(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prefix=prefix,
    )


def _get_current_version(prefix: str = "v") -> Version | None:
    """Get the current (latest) version from tags."""
    tags = _get_version_tags(prefix)
    if not tags:
        return None

    # Return the highest version (last in sorted list)
    return _parse_version(tags[-1], prefix)


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


def _show_changes_since_version(current_version: Version | None) -> list[str]:
    """Display and return commits since the current version."""
    if current_version:
        tag = str(current_version)
        commits = _get_commits_since_tag(tag)
        if commits:
            print()
            _print_info(f"Changes since {current_version}:")
            for commit in commits:
                print(f"  • {commit}")
    else:
        commits = _get_commits_since_tag(None)
        if commits:
            print()
            _print_info("Commits in repository:")
            # Show last 10 if there are many
            display_commits = commits[:10]
            for commit in display_commits:
                print(f"  • {commit}")
            if len(commits) > 10:
                print(f"  ... and {len(commits) - 10} more commits")
    return commits


def _prompt_yes_no(message: str, default: bool = False) -> bool:
    """Prompt the user for a yes/no response."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        response = input(f"{message} {suffix}: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    if not response:
        return default
    return response in ("y", "yes")


def _prompt_bump_type() -> BumpType:
    """Prompt the user to select a bump type."""
    print()
    _print_info("What type of version bump would you like to make?")
    print("  1) major - Breaking changes (X.0.0)")
    print("  2) minor - New features, backwards compatible (x.Y.0)")
    print("  3) patch - Bug fixes, backwards compatible (x.y.Z)")
    print()

    while True:
        try:
            choice = input("Enter choice [1-3]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

        if choice in ("1", "major"):
            return BumpType.MAJOR
        elif choice in ("2", "minor"):
            return BumpType.MINOR
        elif choice in ("3", "patch"):
            return BumpType.PATCH
        else:
            _print_warning("Invalid choice. Please enter 1, 2, or 3.")


def _get_editor() -> str:
    """Get the editor command from $EDITOR, $VISUAL, or default to vi."""
    return os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"


def _input_with_prefill(prompt: str, prefill: str) -> str:
    """Prompt for input with pre-filled editable text.

    Uses readline to allow editing the prefilled text with standard
    terminal key bindings (Ctrl+A, Ctrl+E, etc.).
    """
    def hook() -> None:
        readline.insert_text(prefill)
        readline.redisplay()

    readline.set_pre_input_hook(hook)
    try:
        return input(prompt)
    finally:
        readline.set_pre_input_hook(None)


def _edit_summary(summary: str, full_message: str) -> str:
    """Prompt to edit the summary line of a tag message."""
    try:
        new_summary = _input_with_prefill("Summary: ", summary).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return full_message

    if not new_summary:
        _print_warning("Summary cannot be empty, using default")
        return full_message

    lines = full_message.split("\n")
    lines[0] = new_summary
    return "\n".join(lines)


def _prompt_message(summary: str, full_message: str) -> str:
    """Prompt the user for a tag message, with option to edit in $EDITOR.

    Args:
        summary: Short summary line for display
        full_message: Full default message including any detail
    """
    editor = _get_editor()

    print()
    _print_info("Default tag message:")
    print()
    # Show the full message with indentation for clarity
    for line in full_message.split("\n"):
        print(f"    {line}")
    print()
    print("  1) Use this message")
    print("  2) Edit the summary")
    print(f"  3) Edit full message in {editor}")
    print()

    while True:
        try:
            choice = input("Enter choice [1-3] (default: 1): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return full_message

        if choice == "" or choice == "1":
            return full_message
        elif choice == "2":
            return _edit_summary(summary, full_message)
        elif choice == "3":
            return _edit_message_in_editor(full_message)
        else:
            _print_warning("Invalid choice. Please enter 1, 2, or 3.")


def _edit_message_in_editor(default_message: str) -> str:
    """Open $EDITOR to edit the tag message."""
    editor = _get_editor()

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix="_TAG_EDITMSG",
        prefix="bump-version-",
        delete=False,
    ) as f:
        f.write(default_message)
        f.write("\n\n# Enter your tag message above.")
        f.write("\n# Lines starting with '#' will be ignored.")
        f.write("\n# An empty message will use the default.")
        temp_path = f.name

    try:
        result = subprocess.run([editor, temp_path], check=False)
        if result.returncode != 0:
            _print_warning(f"Editor exited with code {result.returncode}, using default message")
            return default_message

        with open(temp_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Filter out comment lines and strip
        message_lines = [
            line.rstrip("\n\r") for line in lines if not line.strip().startswith("#")
        ]
        message = "\n".join(message_lines).strip()

        if not message:
            _print_warning("Empty message, using default")
            return default_message

        return message
    except FileNotFoundError:
        _print_warning(f"Editor '{editor}' not found, using default message")
        return default_message
    except OSError as e:
        _print_warning(f"Could not open editor: {e}, using default message")
        return default_message
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def _create_tag(tag: str, message: str, dry_run: bool = False) -> bool:
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


def _push_tag(tag: str, dry_run: bool = False) -> bool:
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


def _cmd_current(args: argparse.Namespace) -> int:
    """Handle the 'current' command."""
    version = _get_current_version(args.prefix)
    if version:
        print(str(version))
        return 0
    else:
        print("No version tags found")
        return 1


def _cmd_bump(args: argparse.Namespace, bump_type: BumpType | None = None) -> int:
    """Handle version bump commands."""
    # Sync if requested
    if args.sync:
        _sync_repo()
    elif not args.yes:
        print()
        if _prompt_yes_no("Would you like to sync/pull the repository and tags first?"):
            _sync_repo()

    # Get current version
    current = _get_current_version(args.prefix)

    if current is None:
        _print_warning(f"No existing version tags found (looking for {args.prefix}X.Y.Z pattern)")
    else:
        _print_info(f"Current version: {current}")

    # Show changes since last version
    commits = _show_changes_since_version(current)

    if not commits and current is not None:
        _print_error(f"No commits since {current}; nothing to bump.")
        sys.exit(1)

    # Get bump type
    if bump_type is None:
        bump_type = _prompt_bump_type()

    # Calculate new version
    if current is None:
        new_version = Version(0, 0, 0, args.prefix).bump(bump_type)
    else:
        new_version = current.bump(bump_type)

    print()
    _print_info(f"Bump type: {bump_type.value}")
    if current:
        _print_info(f"Version change: {current} -> {new_version}")
    else:
        _print_info(f"New version: {new_version}")

    # Build default tag message with summary and detail
    summary = f"Release {new_version}"
    if commits:
        detail_lines = ["Changes:"] + [f"- {c}" for c in commits]
        default_message = summary + "\n\n" + "\n".join(detail_lines)
    else:
        default_message = summary

    if args.message:
        # Message provided via command line
        tag_message = args.message
    elif args.yes:
        # Non-interactive mode, use default
        tag_message = default_message
    else:
        # Interactive mode, prompt for message
        tag_message = _prompt_message(summary, default_message)

    # Confirm
    if not args.yes and not args.dry_run:
        print()
        # Show first line for confirmation (full message may be long)
        display_msg = tag_message.split("\n")[0] if "\n" in tag_message else tag_message
        if not _prompt_yes_no(f"Create tag '{new_version}' with message '{display_msg}'?", default=True):
            _print_warning("Aborted")
            return 0

    # Create tag
    if not _create_tag(str(new_version), tag_message, args.dry_run):
        return 1

    # Push if requested
    if args.push:
        if not _push_tag(str(new_version), args.dry_run):
            return 1
    elif not args.dry_run and not args.yes:
        print()
        if _prompt_yes_no("Would you like to push the tag to remote?"):
            if not _push_tag(str(new_version), args.dry_run):
                return 1

    print()
    _print_success("Done!")
    if not args.dry_run:
        _print_info(f"New version: {new_version}")

    return 0


def _create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    # Common options shared by all subcommands
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument(
        "-s",
        "--sync",
        action="store_true",
        help="Sync repository and tags before bumping",
    )
    common_parser.add_argument(
        "-p",
        "--push",
        action="store_true",
        help="Push the new tag to remote after creating",
    )
    common_parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    common_parser.add_argument(
        "-m",
        "--message",
        metavar="MSG",
        help='Custom message for the tag (default: "Release vX.Y.Z")',
    )
    common_parser.add_argument(
        "--prefix",
        default="v",
        help='Version prefix (default: "v", use "" for no prefix)',
    )
    common_parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompts",
    )

    parser = argparse.ArgumentParser(
        prog="bump-version",
        description="A CLI tool to bump semantic version tags in Git repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[common_parser],
        epilog="""\
Examples:
  bump-version                    Interactive mode - prompts for bump type
  bump-version minor              Bump minor version
  bump-version patch --sync       Sync first, then bump patch
  bump-version major -p           Bump major and push to remote
  bump-version current            Show current version
""",
    )

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    subparsers.add_parser("major", parents=[common_parser], help="Bump the major version (X.0.0)")
    subparsers.add_parser("minor", parents=[common_parser], help="Bump the minor version (x.Y.0)")
    subparsers.add_parser("patch", parents=[common_parser], help="Bump the patch/point version (x.y.Z)")
    subparsers.add_parser("current", parents=[common_parser], help="Show the current version")

    return parser


def main(argv: list[str] | None = None) -> NoReturn:
    """Main entry point."""
    parser = _create_parser()
    args = parser.parse_args(argv)

    # Check we're in a git repo
    if not _is_git_repo():
        _print_error("Error: Not a git repository")
        sys.exit(1)

    # Route to appropriate command
    if args.command == "current":
        sys.exit(_cmd_current(args))
    elif args.command == "major":
        sys.exit(_cmd_bump(args, BumpType.MAJOR))
    elif args.command == "minor":
        sys.exit(_cmd_bump(args, BumpType.MINOR))
    elif args.command == "patch":
        sys.exit(_cmd_bump(args, BumpType.PATCH))
    else:
        # Interactive mode
        sys.exit(_cmd_bump(args))


if __name__ == "__main__":
    main()
