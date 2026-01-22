"""Command-line interface for bump-version."""

from __future__ import annotations

import argparse
import os
import re
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


def print_info(message: str) -> None:
    """Print an info message in blue."""
    print(Color.wrap(message, Color.BLUE))


def print_success(message: str) -> None:
    """Print a success message in green."""
    print(Color.wrap(message, Color.GREEN))


def print_warning(message: str) -> None:
    """Print a warning message in yellow."""
    print(Color.wrap(message, Color.YELLOW))


def print_error(message: str) -> None:
    """Print an error message in red to stderr."""
    print(Color.wrap(message, Color.RED), file=sys.stderr)


def run_git(*args: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
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


def is_git_repo() -> bool:
    """Check if the current directory is a git repository."""
    result = run_git("rev-parse", "--git-dir", check=False)
    return result.returncode == 0


def get_remotes() -> list[str]:
    """Get list of configured remotes."""
    result = run_git("remote")
    return [r.strip() for r in result.stdout.strip().split("\n") if r.strip()]


def get_current_branch() -> str | None:
    """Get the current branch name, or None if detached HEAD."""
    result = run_git("symbolic-ref", "--short", "HEAD", check=False)
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def sync_repo() -> None:
    """Sync the repository by fetching tags and pulling the current branch."""
    print_info("Syncing repository...")

    remotes = get_remotes()
    if not remotes:
        print_warning("No remote configured, skipping sync")
        return

    remote = remotes[0]

    # Fetch all tags
    print_info(f"Fetching tags from {remote}...")
    result = run_git("fetch", remote, "--tags", check=False)
    if result.returncode == 0:
        print_success("Tags fetched successfully")
    else:
        print_warning("Could not fetch tags (network issue or no remote access)")

    # Pull current branch
    branch = get_current_branch()
    if branch:
        print_info(f"Pulling latest changes for branch '{branch}'...")
        result = run_git("pull", remote, branch, check=False)
        if result.returncode == 0:
            print_success("Branch updated successfully")
        else:
            print_warning("Could not pull branch (may have uncommitted changes or no tracking)")


def get_version_tags(prefix: str = "v") -> list[str]:
    """
    Get all version tags matching semantic versioning pattern.

    Returns tags sorted by version number (lowest to highest).
    """
    # Build pattern based on prefix
    if prefix:
        pattern = f"{prefix}[0-9]*.[0-9]*.[0-9]*"
    else:
        pattern = "[0-9]*.[0-9]*.[0-9]*"

    result = run_git("tag", "-l", pattern, check=False)
    if result.returncode != 0:
        return []

    tags = [t.strip() for t in result.stdout.strip().split("\n") if t.strip()]

    # Sort by version number
    def version_key(tag: str) -> tuple[int, int, int]:
        version = parse_version(tag, prefix)
        if version:
            return (version.major, version.minor, version.patch)
        return (0, 0, 0)

    return sorted(tags, key=version_key)


def parse_version(tag: str, prefix: str = "v") -> Version | None:
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


def get_current_version(prefix: str = "v") -> Version | None:
    """Get the current (latest) version from tags."""
    tags = get_version_tags(prefix)
    if not tags:
        return None

    # Return the highest version (last in sorted list)
    return parse_version(tags[-1], prefix)


def get_initial_version(bump_type: BumpType, prefix: str = "v") -> Version:
    """Get the initial version when no tags exist."""
    if bump_type == BumpType.MAJOR:
        return Version(1, 0, 0, prefix)
    elif bump_type == BumpType.MINOR:
        return Version(0, 1, 0, prefix)
    else:  # PATCH
        return Version(0, 0, 1, prefix)


def prompt_yes_no(message: str, default: bool = False) -> bool:
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


def prompt_bump_type() -> BumpType:
    """Prompt the user to select a bump type."""
    print()
    print_info("What type of version bump would you like to make?")
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
            print_warning("Invalid choice. Please enter 1, 2, or 3.")


def prompt_message(default_message: str) -> str:
    """Prompt the user for a tag message, with option to edit in $EDITOR."""
    print()
    print_info(f"Default tag message: {default_message}")
    print("  1) Use default message")
    print("  2) Type a custom message")
    print("  3) Edit in $EDITOR")
    print()

    while True:
        try:
            choice = input("Enter choice [1-3] (default: 1): ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return default_message

        if choice == "" or choice == "1":
            return default_message
        elif choice == "2":
            try:
                custom = input("Enter message: ").strip()
                if custom:
                    return custom
                print_warning("Message cannot be empty, using default")
                return default_message
            except (EOFError, KeyboardInterrupt):
                print()
                return default_message
        elif choice == "3":
            return edit_message_in_editor(default_message)
        else:
            print_warning("Invalid choice. Please enter 1, 2, or 3.")


def edit_message_in_editor(default_message: str) -> str:
    """Open $EDITOR to edit the tag message."""
    editor = os.environ.get("EDITOR", os.environ.get("VISUAL", "vi"))

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        prefix="bump-version-msg-",
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
            print_warning(f"Editor exited with code {result.returncode}, using default message")
            return default_message

        with open(temp_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Filter out comment lines and strip
        message_lines = [
            line.rstrip("\n\r") for line in lines if not line.strip().startswith("#")
        ]
        message = "\n".join(message_lines).strip()

        if not message:
            print_warning("Empty message, using default")
            return default_message

        return message
    except FileNotFoundError:
        print_warning(f"Editor '{editor}' not found, using default message")
        return default_message
    except OSError as e:
        print_warning(f"Could not open editor: {e}, using default message")
        return default_message
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass


def create_tag(tag: str, message: str, dry_run: bool = False) -> bool:
    """Create an annotated git tag."""
    if dry_run:
        print_info(f"[DRY RUN] Would create tag: {tag}")
        print_info(f"[DRY RUN] Message: {message}")
        return True

    print_info(f"Creating tag '{tag}'...")
    result = run_git("tag", "-a", tag, "-m", message, check=False)

    if result.returncode == 0:
        print_success(f"Tag '{tag}' created successfully")
        return True
    else:
        print_error(f"Failed to create tag: {result.stderr}")
        return False


def push_tag(tag: str, dry_run: bool = False) -> bool:
    """Push a tag to the remote repository."""
    if dry_run:
        print_info(f"[DRY RUN] Would push tag: {tag}")
        return True

    remotes = get_remotes()
    if not remotes:
        print_warning("No remote configured, skipping push")
        return True

    remote = remotes[0]
    print_info(f"Pushing tag '{tag}' to {remote}...")
    result = run_git("push", remote, tag, check=False)

    if result.returncode == 0:
        print_success("Tag pushed successfully")
        return True
    else:
        print_error(f"Failed to push tag: {result.stderr}")
        return False


def cmd_current(args: argparse.Namespace) -> int:
    """Handle the 'current' command."""
    version = get_current_version(args.prefix)
    if version:
        print(str(version))
        return 0
    else:
        print("No version tags found")
        return 1


def cmd_bump(args: argparse.Namespace, bump_type: BumpType | None = None) -> int:
    """Handle version bump commands."""
    # Sync if requested
    if args.sync:
        sync_repo()
    elif not args.yes:
        print()
        if prompt_yes_no("Would you like to sync/pull the repository and tags first?"):
            sync_repo()

    # Get current version
    current = get_current_version(args.prefix)

    if current is None:
        print_warning(f"No existing version tags found (looking for {args.prefix}X.Y.Z pattern)")
    else:
        print_info(f"Current version: {current}")

    # Get bump type
    if bump_type is None:
        bump_type = prompt_bump_type()

    # Calculate new version
    if current is None:
        new_version = get_initial_version(bump_type, args.prefix)
    else:
        new_version = current.bump(bump_type)

    print()
    print_info(f"Bump type: {bump_type.value}")
    if current:
        print_info(f"Version change: {current} -> {new_version}")
    else:
        print_info(f"New version: {new_version}")

    # Set tag message
    default_message = f"Release {new_version}"
    if args.message:
        # Message provided via command line
        tag_message = args.message
    elif args.yes:
        # Non-interactive mode, use default
        tag_message = default_message
    else:
        # Interactive mode, prompt for message
        tag_message = prompt_message(default_message)

    # Confirm
    if not args.yes and not args.dry_run:
        print()
        if not prompt_yes_no(f"Create tag '{new_version}' with message '{tag_message}'?"):
            print_warning("Aborted")
            return 0

    # Create tag
    if not create_tag(str(new_version), tag_message, args.dry_run):
        return 1

    # Push if requested
    if args.push:
        if not push_tag(str(new_version), args.dry_run):
            return 1
    elif not args.dry_run and not args.yes:
        print()
        if prompt_yes_no("Would you like to push the tag to remote?"):
            if not push_tag(str(new_version), args.dry_run):
                return 1

    print()
    print_success("Done!")
    if not args.dry_run:
        print_info(f"New version: {new_version}")

    return 0


def create_parser() -> argparse.ArgumentParser:
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
    parser = create_parser()
    args = parser.parse_args(argv)

    # Check we're in a git repo
    if not is_git_repo():
        print_error("Error: Not a git repository")
        sys.exit(1)

    # Route to appropriate command
    if args.command == "current":
        sys.exit(cmd_current(args))
    elif args.command == "major":
        sys.exit(cmd_bump(args, BumpType.MAJOR))
    elif args.command == "minor":
        sys.exit(cmd_bump(args, BumpType.MINOR))
    elif args.command == "patch":
        sys.exit(cmd_bump(args, BumpType.PATCH))
    else:
        # Interactive mode
        sys.exit(cmd_bump(args))


if __name__ == "__main__":
    main()
