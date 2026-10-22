"""Prompting and the editor: the interactive layer.

The plain numbered-menu and yes/no prompts, the tag-message prompt with its
readline-prefilled summary edit, and the `$EDITOR` path: `_EditorRequest`,
the scissors-line seed and strip, and `_create_tag_via_editor`, which owns
the editor loop and creates the tag from the edited message. EOF and Ctrl-C
at a prompt propagate to `cli.main`; while the editor runs, Ctrl-C is the
editor's (`_editor_signals_ignored`). May import: `output`, `exit_status`, `git` (git
dir, seed diff, tag creation), `version` (`BumpType`).
"""

from __future__ import annotations

import contextlib
import os
import readline
import shlex
import signal
import subprocess
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from bump_version.exit_status import EXIT_DECLINED, EXIT_FAILURE, EXIT_OK
from bump_version.git import _get_git_dir, _run_git
from bump_version.output import _print_error, _print_info, _print_success, _print_warning
from bump_version.version import BumpType


def _prompt_yes_no(message: str, *, default: bool = False) -> bool:
    """Prompt the user for a yes/no response.

    EOF and Ctrl-C are not answers: they propagate to `main`, which exits
    EXIT_INTERRUPTED. Reading them as "no" would make an interrupted run
    indistinguishable from a deliberate decline.
    """
    suffix = "[Y/n]" if default else "[y/N]"
    response = input(f"{message} {suffix}: ").strip().lower()

    if not response:
        return default
    return response in {"y", "yes"}


def _prompt_bump_type() -> BumpType:
    """Prompt the user to select a bump type."""
    print()
    _print_info("What type of version bump would you like to make?")
    print("  1) major - Breaking changes (X.0.0)")
    print("  2) minor - New features, backwards compatible (x.Y.0)")
    print("  3) patch - Bug fixes, backwards compatible (x.y.Z)")
    print()

    while True:
        # EOF and Ctrl-C propagate to `main` (EXIT_INTERRUPTED).
        choice = input("Enter choice [1-3]: ").strip().lower()

        if choice in {"1", "major"}:
            return BumpType.MAJOR
        elif choice in {"2", "minor"}:
            return BumpType.MINOR
        elif choice in {"3", "patch"}:
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
    """Prompt to edit the summary line of a tag message.

    EOF and Ctrl-C propagate to `main` (EXIT_INTERRUPTED) rather than falling
    back to the default message, which would go on to create the tag.
    """
    new_summary = _input_with_prefill("Summary: ", summary).strip()

    if not new_summary:
        _print_warning("Summary cannot be empty, using default")
        return full_message

    lines = full_message.split("\n")
    lines[0] = new_summary
    return "\n".join(lines)


@dataclass(frozen=True)
class _EditorRequest:
    """Sentinel: user chose to compose the message in $EDITOR.

    Caller hands this to `_create_tag_via_editor`, which owns the editor
    lifecycle: it seeds `<git-dir>/TAG_EDITMSG` (recognized by editor modes
    like magit's git-commit-mode) and creates the tag via `git tag -a -F`
    after stripping scissors content and comment lines.
    """

    default_message: str


def _prompt_message(summary: str, full_message: str) -> str | _EditorRequest:
    """Prompt the user for a tag message, with option to edit in $EDITOR.

    EOF and Ctrl-C propagate to `main` (EXIT_INTERRUPTED) rather than falling
    back to the default message, which would go on to create the tag.

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
        choice = input("Enter choice [1-3] (default: 1): ").strip()

        if not choice or choice == "1":
            return full_message
        elif choice == "2":
            return _edit_summary(summary, full_message)
        elif choice == "3":
            return _EditorRequest(full_message)
        else:
            _print_warning("Invalid choice. Please enter 1, 2, or 3.")


# Canonical scissors line, matching `git commit -v`. Lines from here down
# are dropped by _strip_editor_content. Hardcoded `#` (not core.commentChar)
# because git itself uses `#` for this template regardless of config.
_SCISSORS_LINE = "# ------------------------ >8 ------------------------"


def _build_editor_seed(default_message: str, prev_tag: str | None) -> str:
    """Build the editor seed: default message plus optional scissors-cut diff.

    When prev_tag is known and `git diff prev_tag..HEAD` produces output,
    appends a `commit -v`-style section below a scissors line so the user
    can see what's being released while composing the message.
    """
    if not prev_tag:
        return default_message
    diff = _run_git("diff", f"{prev_tag}..HEAD", check=False)
    if diff.returncode != 0 or not diff.stdout:
        return default_message
    return (
        f"{default_message}\n\n"
        f"{_SCISSORS_LINE}\n"
        # Metadata for editor hooks (e.g. magit) that want to know what
        # we're tagging against. Stripped along with the rest by our
        # default `#`-line cleanup; never reaches the tag message.
        f"# bump-version: prev-tag={prev_tag}\n"
        "# Lines above the scissors will be the tag message.\n"
        "# Lines below (and the scissors line itself) are stripped.\n"
        "#\n"
        f"# Diff against {prev_tag} (`git diff {prev_tag}..HEAD`):\n"
        f"{diff.stdout}"
    )


def _strip_editor_content(content: str) -> str:
    """Apply git's default `strip` cleanup plus scissors cut.

    Drops the scissors line and everything below it, removes lines starting
    with `#`, and strips leading/trailing whitespace. Returns the message
    git would accept; empty string means "nothing left, abort".
    """
    lines = content.splitlines()
    cut = next(
        (i for i, line in enumerate(lines) if line.rstrip() == _SCISSORS_LINE),
        len(lines),
    )
    kept = [line for line in lines[:cut] if not line.startswith("#")]
    return "\n".join(kept).strip()


# What a terminal sends the whole foreground process group on Ctrl-C and
# Ctrl-\. SIGQUIT does not exist on Windows.
_EDITOR_SIGNALS: tuple[signal.Signals, ...] = (signal.SIGINT,) + (
    (signal.SIGQUIT,) if hasattr(signal, "SIGQUIT") else ()
)


@contextlib.contextmanager
def _editor_signals_ignored() -> Iterator[Callable[[], None]]:
    """Ignore Ctrl-C and Ctrl-\\ in bump-version while `$EDITOR` runs.

    A terminal delivers Ctrl-C to the whole foreground process group, so the
    editor and bump-version both receive it. An editor like vim treats it as
    a keystroke, but bump-version would raise KeyboardInterrupt, and
    `subprocess.run` then SIGKILLs the editor with the edit lost. Git's
    `editor.c` ignores SIGINT and SIGQUIT in itself for as long as the editor
    runs and restores them after; this does the same. The previous handlers
    come back in a `finally`, whatever the editor call does.

    Two deliberate differences in *when*, not in what the editor sees:

    * The signals are ignored **before** the editor starts (git ignores just
      after `start_command`), so no Ctrl-C can reach bump-version while the
      editor is already up.
    * An ignored disposition is inherited across exec (`restore_signals` does
      not cover SIGINT/SIGQUIT), which would leave a naive editor impossible
      to interrupt. The yielded callable restores the saved handlers; pass it
      as the editor's `preexec_fn` so the child starts with exactly what it
      would have had without this guard, as git's editor does. The editor
      decides what Ctrl-C means.

    Wrap only the editor call, never a prompt: at a prompt, Ctrl-C must still
    propagate to `cli.main` and exit EXIT_INTERRUPTED.
    """
    previous = {sig: signal.getsignal(sig) for sig in _EDITOR_SIGNALS}

    def restore() -> None:
        for sig, handler in previous.items():
            signal.signal(sig, handler)

    try:
        for sig in previous:
            signal.signal(sig, signal.SIG_IGN)
        yield restore
    finally:
        restore()


def _create_tag_via_editor(
    tag: str,
    default_message: str,
    prev_tag: str | None = None,
    *,
    dry_run: bool = False,
) -> int:
    """Create an annotated git tag via $EDITOR with diff context.

    Writes `<git-dir>/TAG_EDITMSG` (mirroring git's own location, so editor
    modes like magit's git-commit-mode that key off the `.git/` parent
    auto-activate), seeds it with the default message plus a `commit -v`-
    style scissors section containing `git diff <prev_tag>..HEAD` when
    prev_tag is given, launches $EDITOR, then strips/cuts and creates the
    tag via `git tag -a -F`.

    We own the editor (rather than `git tag -e -F`) because:
      * `git tag` rejects `--cleanup=scissors` (only commit accepts it), and
      * `git tag -a -e -F` skips its empty-message check when -F is set,
        so an emptied buffer would otherwise create an empty-message tag.
    Owning the loop lets us cut scissors content and abort on empty input.

    Returns an exit status. Emptying the buffer is the operator's way to
    decline, so it is EXIT_DECLINED; a nonzero editor exit stays
    EXIT_FAILURE, as it does in git, because a crash and a deliberate `:cq`
    look the same from here.

    Ctrl-C while the editor runs is the editor's to handle
    (`_editor_signals_ignored`). If the editor dies of SIGINT or SIGQUIT,
    that is an interrupt, not an editor failure: this raises
    KeyboardInterrupt for `cli.main` to exit EXIT_INTERRUPTED, as git
    re-raises the editor's signal on itself.

    On success, `git tag -a` cleans up `TAG_EDITMSG` itself. On editor
    failure or empty-message abort, the file is left in place so the user
    can recover their pre-strip edit on the next run — matches what git
    does for its own tag editing flow.
    """
    if dry_run:
        _print_info(f"[DRY RUN] Would open editor to create tag: {tag}")
        _print_info(f"[DRY RUN] Default message: {default_message}")
        return EXIT_OK

    editor = _get_editor()
    tag_editmsg = os.path.join(_get_git_dir(), "TAG_EDITMSG")

    with open(tag_editmsg, "w", encoding="utf-8") as f:
        f.write(_build_editor_seed(default_message, prev_tag))

    _print_info(f"Opening {editor} to create tag '{tag}'...")
    try:
        with _editor_signals_ignored() as restore_in_child:
            # shlex.split handles editors like `emacsclient -t` or
            # `code --wait` that carry arguments in $EDITOR. The tool is
            # single-threaded, which is what makes preexec_fn safe here.
            edit = subprocess.run(
                [*shlex.split(editor), tag_editmsg],
                check=False,
                preexec_fn=restore_in_child if os.name == "posix" else None,
            )
    except FileNotFoundError:
        _print_error(f"Editor '{editor}' not found")
        return EXIT_FAILURE
    if -edit.returncode in _EDITOR_SIGNALS:
        _print_warning(
            f"Editor killed by {signal.Signals(-edit.returncode).name}; aborting tag creation"
        )
        raise KeyboardInterrupt
    if edit.returncode != 0:
        _print_warning(f"Editor exited with code {edit.returncode}; aborting tag creation")
        return EXIT_FAILURE

    with open(tag_editmsg, encoding="utf-8") as f:
        message = _strip_editor_content(f.read())

    if not message:
        _print_warning("Empty message; aborting tag creation")
        return EXIT_DECLINED

    # Pass the cleaned message via a separate tempfile so TAG_EDITMSG keeps
    # the user's pre-strip edits (matches git's recovery semantics).
    with tempfile.NamedTemporaryFile(
        mode="w",
        prefix="bump-version-",
        suffix=".msg",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(message + "\n")
        msg_path = f.name
    try:
        _print_info(f"Creating tag '{tag}'...")
        result = _run_git("tag", "-a", "-F", msg_path, "--cleanup=verbatim", tag, check=False)
        if result.returncode == 0:
            _print_success(f"Tag '{tag}' created successfully")
            return EXIT_OK
        _print_error(f"Failed to create tag: {result.stderr}")
        return EXIT_FAILURE
    finally:
        with contextlib.suppress(OSError):
            os.unlink(msg_path)
