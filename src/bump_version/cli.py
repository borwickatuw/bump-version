"""Command-line interface for bump-version: parsing, dispatch, the bump flow.

`main` (the `bump-version` entry point, `bump_version.cli:main`) parses the
command line, refuses outside a git repository, routes through `_dispatch`
to a command handler, and is the one place an interrupt becomes an exit
status. `_cmd_bump` is the release flow, decomposed into its phase helpers.
May import: every other module in the package.
"""

from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from bump_version import __version__
from bump_version.dynamic_pyproject import _cmd_dynamic_pyproject
from bump_version.exit_status import EXIT_DECLINED, EXIT_FAILURE, EXIT_INTERRUPTED, EXIT_OK
from bump_version.git import (
    _create_tag,
    _get_commits_since_tag,
    _is_git_repo,
    _push_tag,
    _sync_repo,
)
from bump_version.output import _print_error, _print_info, _print_success, _print_warning
from bump_version.prompts import (
    _create_tag_via_editor,
    _EditorRequest,
    _prompt_bump_type,
    _prompt_message,
    _prompt_yes_no,
)
from bump_version.pyproject import _check_pyproject_version
from bump_version.version import BumpType, Version, _get_current_version


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
            max_display = 10
            display_commits = commits[:max_display]
            for commit in display_commits:
                print(f"  • {commit}")
            if len(commits) > max_display:
                print(f"  ... and {len(commits) - max_display} more commits")
    return commits


def _cmd_current(args: argparse.Namespace) -> int:
    """Handle the 'current' command."""
    version = _get_current_version(args.prefix)
    if version:
        print(str(version))
        return EXIT_OK
    else:
        print("No version tags found")
        return EXIT_FAILURE


def _resolve_tag_message(
    args: argparse.Namespace, summary: str, default_message: str
) -> str | _EditorRequest:
    """Pick the tag message source: CLI flag, non-interactive default, or prompt."""
    if args.message:
        return args.message
    if args.yes:
        return default_message
    return _prompt_message(summary, default_message)


def _resolve_message_and_create_tag(
    args: argparse.Namespace,
    new_version: Version,
    current: Version | None,
    commits: list[str],
) -> int | None:
    """Build the tag message and create the tag (editor or direct path).

    Returns an exit status to propagate (EXIT_FAILURE on failure,
    EXIT_DECLINED when the operator declines) or None when the tag was
    created and the caller should continue.
    """
    summary = f"Release {new_version}"
    if commits:
        detail_lines = ["Changes:"] + [f"- {c}" for c in commits]
        default_message = summary + "\n\n" + "\n".join(detail_lines)
    else:
        default_message = summary

    prompt_result = _resolve_tag_message(args, summary, default_message)

    if isinstance(prompt_result, _EditorRequest):
        # Editor path: $EDITOR sees the message + `commit -v`-style diff
        # below a scissors line; saving with an empty buffer aborts.
        # No separate confirmation — exiting the editor IS the confirmation.
        status = _create_tag_via_editor(
            str(new_version),
            prompt_result.default_message,
            prev_tag=str(current) if current else None,
            dry_run=args.dry_run,
        )
        return None if status == EXIT_OK else status

    tag_message = prompt_result

    # Confirm
    if not args.yes and not args.dry_run:
        print()
        # Show first line for confirmation (full message may be long)
        display_msg = tag_message.split("\n")[0] if "\n" in tag_message else tag_message
        if not _prompt_yes_no(
            f"Create tag '{new_version}' with message '{display_msg}'?",
            default=True,
        ):
            _print_warning("Aborted; no tag created")
            return EXIT_DECLINED

    # Create tag
    if not _create_tag(str(new_version), tag_message, dry_run=args.dry_run):
        return EXIT_FAILURE
    return None


def _maybe_sync(args: argparse.Namespace) -> None:
    """Sync the repo if requested, or offer to when running interactively."""
    if args.sync:
        _sync_repo()
    elif not args.yes:
        print()
        if _prompt_yes_no("Would you like to sync/pull the repository and tags first?"):
            _sync_repo()


def _maybe_push(new_version: Version, args: argparse.Namespace) -> bool:
    """Push the tag if requested, or offer to when running interactively."""
    if args.push:
        return _push_tag(str(new_version), dry_run=args.dry_run)
    if not args.dry_run and not args.yes:
        print()
        if _prompt_yes_no("Would you like to push the tag to remote?"):
            return _push_tag(str(new_version), dry_run=args.dry_run)
    return True


def _cmd_bump(args: argparse.Namespace, bump_type: BumpType | None) -> int:
    """Handle version bump commands."""
    _maybe_sync(args)
    _check_pyproject_version()

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
        sys.exit(EXIT_FAILURE)

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

    result = _resolve_message_and_create_tag(args, new_version, current, commits)
    if result is not None:
        return result

    if not _maybe_push(new_version, args):
        return EXIT_FAILURE

    print()
    _print_success("Done!")
    if not args.dry_run:
        _print_info(f"New version: {new_version}")

    return EXIT_OK


# The one place each shared option's default is stated. The top-level parser
# carries these; every subparser is built with argument_default=SUPPRESS
# instead, so it never writes a default of its own (see _create_parser).
_SHARED_DEFAULTS: dict[str, bool | str | None] = {
    "sync": False,
    "push": False,
    "dry_run": False,
    "message": None,
    "prefix": "v",
    "yes": False,
}


def _add_dry_run_option(parser: argparse.ArgumentParser) -> None:
    """Declare -n/--dry-run, shared by every command that writes."""
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )


def _add_yes_option(parser: argparse.ArgumentParser) -> None:
    """Declare -y/--yes, shared by every command that prompts."""
    parser.add_argument(
        "-y",
        "--yes",
        action="store_true",
        help="Skip confirmation prompts",
    )


def _add_bump_options(parser: argparse.ArgumentParser) -> None:
    """Declare the options shared by the top level and the bump subcommands.

    No defaults here: the parser's own `argument_default` or `set_defaults`
    decides them, which is what lets the same declarations serve both levels.
    """
    parser.add_argument(
        "-s",
        "--sync",
        action="store_true",
        help="Sync repository and tags before bumping",
    )
    parser.add_argument(
        "-p",
        "--push",
        action="store_true",
        help="Push the new tag to remote after creating",
    )
    _add_dry_run_option(parser)
    parser.add_argument(
        "-m",
        "--message",
        metavar="MSG",
        help='Custom message for the tag (default: "Release vX.Y.Z")',
    )
    parser.add_argument(
        "--prefix",
        help=f'Version prefix (default: "{_SHARED_DEFAULTS["prefix"]}", use "" for no prefix)',
    )
    _add_yes_option(parser)


def _create_parser() -> argparse.ArgumentParser:
    """Create the argument parser.

    The shared options are accepted before or after the subcommand. argparse
    parses a subcommand's arguments into a fresh namespace and copies every
    attribute of it over the top-level result, so a subparser that carried its
    own defaults would overwrite an option typed before the subcommand. Each
    subparser is therefore built with `argument_default=argparse.SUPPRESS`:
    it writes only what the user typed after the subcommand, and the defaults
    come once, from `_SHARED_DEFAULTS` on the top-level parser. Typed in both
    positions, the value after the subcommand is parsed last and wins.
    """
    parser = argparse.ArgumentParser(
        prog="bump-version",
        description="A CLI tool to bump semantic version tags in Git repositories.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  bump-version                    Interactive mode - prompts for bump type
  bump-version minor              Bump minor version
  bump-version patch --sync       Sync first, then bump patch
  bump-version major -p           Bump major and push to remote
  bump-version current            Show current version
  bump-version dynamic-pyproject  Migrate pyproject.toml to git-tag versioning
""",
    )
    _add_bump_options(parser)
    parser.set_defaults(**_SHARED_DEFAULTS)

    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

    for name, help_text in (
        ("major", "Bump the major version (X.0.0)"),
        ("minor", "Bump the minor version (x.Y.0)"),
        ("patch", "Bump the patch/point version (x.y.Z)"),
        ("current", "Show the current version"),
    ):
        _add_bump_options(
            subparsers.add_parser(name, help=help_text, argument_default=argparse.SUPPRESS)
        )

    # Deliberately not _add_bump_options: push/message/sync don't apply to a
    # one-time migration.
    dynamic_parser = subparsers.add_parser(
        "dynamic-pyproject",
        help="Migrate a static hatchling pyproject.toml to git-tag versioning",
        argument_default=argparse.SUPPRESS,
    )
    _add_dry_run_option(dynamic_parser)
    _add_yes_option(dynamic_parser)
    dynamic_parser.add_argument(
        "--prefix",
        help=f'Version prefix for the tag-drift check (default: "{_SHARED_DEFAULTS["prefix"]}")',
    )

    return parser


def _dispatch(args: argparse.Namespace) -> int:
    """Route parsed arguments to their command and return its exit status."""
    if args.command == "current":
        return _cmd_current(args)
    if args.command == "dynamic-pyproject":
        return _cmd_dynamic_pyproject(args)

    # The remaining subcommand names are exactly BumpType's values
    # ("major", "minor", "patch"); no subcommand means interactive mode.
    return _cmd_bump(args, BumpType(args.command) if args.command else None)


def main(argv: list[str] | None = None) -> NoReturn:
    """Main entry point."""
    parser = _create_parser()
    args = parser.parse_args(argv)

    # Check we're in a git repo
    if not _is_git_repo():
        _print_error("Error: Not a git repository")
        sys.exit(EXIT_FAILURE)

    # The one place an interrupt becomes an exit status. Ctrl-C can land
    # anywhere -- at a prompt, during `git fetch`/`push` -- so no narrower
    # wrapper covers it. While $EDITOR runs, Ctrl-C is ignored here and left
    # to the editor; one that dies of it arrives as KeyboardInterrupt from
    # `_create_tag_via_editor`. EOFError is raised only by the
    # input() calls behind the prompts: stdin closed mid-prompt means the
    # operator cannot answer, which is an interruption, not a "no".
    try:
        status = _dispatch(args)
    except (EOFError, KeyboardInterrupt):
        print()
        _print_warning("Interrupted")
        status = EXIT_INTERRUPTED
    sys.exit(status)


if __name__ == "__main__":
    main()
