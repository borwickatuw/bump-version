"""Tests for the $EDITOR tag-creation flow.

`_create_tag_via_editor` owns the editor loop rather than delegating to
`git tag -e -F` (see its docstring), so its abort and recovery semantics are
only observable here: these tests drive it with a real throwaway git repo and
a shell script standing in for $EDITOR.
"""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest

from bump_version.exit_status import EXIT_DECLINED, EXIT_FAILURE, EXIT_INTERRUPTED, EXIT_OK
from bump_version.prompts import _build_editor_seed, _create_tag_via_editor, _SCISSORS_LINE


def _fake_editor(tmp_path, body: str, name: str = "fake-editor") -> str:
    """Write an executable stand-in for $EDITOR and return its path.

    The script receives the seeded TAG_EDITMSG path as `$1`, exactly as the
    real editor does.
    """
    script = tmp_path / name
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(0o755)
    return str(script)


def _commit(path, name: str, text: str) -> None:
    """Write a file into the repo and commit it."""
    (path / name).write_text(text)
    subprocess.run(["git", "add", name], check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"Add {name}"], check=True, capture_output=True)


def _tag_message(tag: str) -> str:
    """Return the annotated message git stored for a tag."""
    result = subprocess.run(
        ["git", "tag", "-l", "--format=%(contents)", tag],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _tag_editmsg(repo_path):
    """Path git and bump-version both use for the tag-message buffer."""
    return repo_path / ".git" / "TAG_EDITMSG"


class TestBuildEditorSeed:
    """Tests for the seed written into TAG_EDITMSG before the editor opens."""

    def test_no_prev_tag_is_message_only(self, git_repo):
        assert _build_editor_seed("Release v1.0.0", None) == "Release v1.0.0"

    def test_prev_tag_with_empty_diff_is_message_only(self, git_repo):
        subprocess.run(["git", "tag", "v0.9.0"], check=True, capture_output=True)
        # v0.9.0 is HEAD, so `git diff v0.9.0..HEAD` produces nothing.
        assert _build_editor_seed("Release v1.0.0", "v0.9.0") == "Release v1.0.0"

    def test_prev_tag_with_diff_appends_scissors_section(self, git_repo):
        subprocess.run(["git", "tag", "v0.9.0"], check=True, capture_output=True)
        _commit(git_repo, "feature.txt", "new\n")

        seed = _build_editor_seed("Release v1.0.0", "v0.9.0")

        message, _, below = seed.partition(_SCISSORS_LINE)
        assert message.strip() == "Release v1.0.0"
        assert "# bump-version: prev-tag=v0.9.0" in below
        assert "feature.txt" in below
        # Everything below the scissors is comment or diff, never message.
        assert below.strip().startswith("#")

    def test_missing_prev_tag_falls_back_to_message(self, git_repo):
        # `git diff` fails on an unknown revision; the seed must not carry
        # the error, it must degrade to the plain default message.
        assert _build_editor_seed("Release v1.0.0", "v9.9.9") == "Release v1.0.0"


class TestCreateTagViaEditor:
    """Tests for the editor-driven annotated-tag flow."""

    def test_dry_run_creates_no_tag(self, git_repo, capsys):
        result = _create_tag_via_editor("v1.0.0", "Release v1.0.0", dry_run=True)

        assert result == EXIT_OK
        assert "[DRY RUN]" in capsys.readouterr().out
        assert _tag_message("v1.0.0") == ""
        assert not _tag_editmsg(git_repo).exists()

    def test_editor_message_becomes_tag(self, git_repo, monkeypatch):
        editor = _fake_editor(git_repo, 'printf "Hand written\\n\\nBody line\\n" > "$1"\n')
        monkeypatch.setenv("EDITOR", editor)

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_OK
        assert _tag_message("v1.0.0").strip() == "Hand written\n\nBody line"
        # git removes its own buffer once the tag is created.
        assert not _tag_editmsg(git_repo).exists()

    def test_editor_sees_seed_and_unedited_seed_strips_to_default(self, git_repo, monkeypatch):
        subprocess.run(["git", "tag", "v0.9.0"], check=True, capture_output=True)
        _commit(git_repo, "feature.txt", "new\n")
        # Copy the seed aside, then leave it untouched — the scissors section
        # must be cut rather than land in the tag message.
        editor = _fake_editor(git_repo, 'cp "$1" seen-seed.txt\n')
        monkeypatch.setenv("EDITOR", editor)

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0", prev_tag="v0.9.0") == EXIT_OK

        seen = (git_repo / "seen-seed.txt").read_text()
        assert _SCISSORS_LINE in seen
        assert "feature.txt" in seen
        assert _tag_message("v1.0.0").strip() == "Release v1.0.0"

    def test_editor_with_arguments_is_split(self, git_repo, monkeypatch):
        # $EDITOR carrying flags (`emacsclient -t`, `code --wait`) must be
        # shlex-split, not treated as one executable name.
        editor = _fake_editor(
            git_repo, 'printf "%s\\n" "$1" > arg.txt\nprintf "Via args\\n" > "$2"\n'
        )
        monkeypatch.setenv("EDITOR", f"{editor} --wait")

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_OK
        assert (git_repo / "arg.txt").read_text().strip() == "--wait"
        assert _tag_message("v1.0.0").strip() == "Via args"

    def test_empty_message_aborts_and_keeps_buffer(self, git_repo, monkeypatch, capsys):
        editor = _fake_editor(git_repo, ': > "$1"\n')
        monkeypatch.setenv("EDITOR", editor)

        # Emptying the buffer is the operator declining, not a failure.
        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_DECLINED
        assert "Empty message" in capsys.readouterr().out
        assert _tag_message("v1.0.0") == ""
        # Buffer is left behind so the user can recover their edit.
        assert _tag_editmsg(git_repo).exists()

    def test_comments_only_message_aborts(self, git_repo, monkeypatch):
        editor = _fake_editor(git_repo, 'printf "# nothing but a comment\\n" > "$1"\n')
        monkeypatch.setenv("EDITOR", editor)

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_DECLINED
        assert _tag_message("v1.0.0") == ""

    def test_editor_failure_aborts_and_keeps_buffer(self, git_repo, monkeypatch, capsys):
        editor = _fake_editor(git_repo, 'printf "Never used\\n" > "$1"\nexit 3\n')
        monkeypatch.setenv("EDITOR", editor)

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_FAILURE
        assert "exited with code 3" in capsys.readouterr().out
        assert _tag_message("v1.0.0") == ""
        assert _tag_editmsg(git_repo).exists()

    def test_missing_editor_reports_error(self, git_repo, monkeypatch, capsys):
        monkeypatch.setenv("EDITOR", str(git_repo / "no-such-editor"))

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_FAILURE
        assert "not found" in capsys.readouterr().err
        assert _tag_message("v1.0.0") == ""

    def test_existing_tag_reports_git_failure(self, git_repo, monkeypatch, capsys):
        subprocess.run(
            ["git", "tag", "-a", "-m", "first", "v1.0.0"], check=True, capture_output=True
        )
        editor = _fake_editor(git_repo, 'printf "Second attempt\\n" > "$1"\n')
        monkeypatch.setenv("EDITOR", editor)

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_FAILURE
        assert "Failed to create tag" in capsys.readouterr().err
        assert _tag_message("v1.0.0").strip() == "first"


@pytest.mark.parametrize("prev_tag", [None, "v0.9.0"])
def test_editor_buffer_lives_in_git_dir(git_repo, monkeypatch, prev_tag):
    """TAG_EDITMSG must sit in the git dir so editor modes auto-activate."""
    if prev_tag:
        subprocess.run(["git", "tag", prev_tag], check=True, capture_output=True)
    editor = _fake_editor(git_repo, 'printf "%s\\n" "$1" > seen-path.txt\nexit 1\n')
    monkeypatch.setenv("EDITOR", editor)

    _create_tag_via_editor("v1.0.0", "Release v1.0.0", prev_tag=prev_tag)

    seen = (git_repo / "seen-path.txt").read_text().strip()
    assert seen == str(_tag_editmsg(git_repo))


# The signals bump-version ignores while the editor runs, as git's editor.c
# does. SIGQUIT is POSIX-only.
_EDITOR_SIGNALS = [signal.SIGINT] + ([signal.SIGQUIT] if hasattr(signal, "SIGQUIT") else [])


@pytest.fixture()
def sentinel_handlers() -> Iterator[dict[int, object]]:
    """Install a recognisable Python handler per editor signal; undo it after.

    Restoring "whatever was there before" is only provable against a handler
    that is neither SIG_DFL nor SIG_IGN nor Python's default_int_handler.
    """

    def _make(signum: int):
        def _handler(_signum, _frame) -> None:  # pragma: no cover - never delivered
            pytest.fail(f"sentinel handler for {signum} ran")

        return _handler

    originals = {sig: signal.getsignal(sig) for sig in _EDITOR_SIGNALS}
    installed = {sig: _make(sig) for sig in _EDITOR_SIGNALS}
    for sig, handler in installed.items():
        signal.signal(sig, handler)
    try:
        yield installed
    finally:
        for sig, handler in originals.items():
            signal.signal(sig, handler)


def _patch_editor_run(monkeypatch, fake) -> None:
    """Route the editor launch to `fake`; git calls still run for real.

    `prompts` and `git` share the one `subprocess` module, so patching
    `subprocess.run` for the editor would otherwise swallow `git tag` too.
    """
    real_run = subprocess.run

    def _run(cmd, *args, **kwargs):
        if cmd[0] == "fake-editor":
            return fake(cmd, **kwargs)
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setenv("EDITOR", "fake-editor")
    monkeypatch.setattr(subprocess, "run", _run)


class TestEditorSignalGuard:
    """While $EDITOR runs, Ctrl-C belongs to the editor (git's editor.c).

    Only the editor call is guarded; the handlers bump-version had before are
    back the moment it returns, however it returns.
    """

    def test_signals_ignored_during_editor_and_restored_after(
        self, git_repo, monkeypatch, sentinel_handlers
    ):
        seen: dict[int, object] = {}

        def fake_run(cmd, **_kwargs):
            seen.update({sig: signal.getsignal(sig) for sig in _EDITOR_SIGNALS})
            with open(cmd[-1], "w", encoding="utf-8") as f:
                f.write("Written while ignored\n")
            return subprocess.CompletedProcess(cmd, 0)

        _patch_editor_run(monkeypatch, fake_run)

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_OK
        assert seen == {sig: signal.SIG_IGN for sig in _EDITOR_SIGNALS}
        assert {sig: signal.getsignal(sig) for sig in _EDITOR_SIGNALS} == sentinel_handlers
        assert _tag_message("v1.0.0").strip() == "Written while ignored"

    def test_handlers_restored_when_editor_call_raises(
        self, git_repo, monkeypatch, sentinel_handlers
    ):
        class _LaunchError(Exception):
            """Stands in for anything the editor launch might raise."""

        def fake_run(_cmd, **_kwargs):
            assert signal.getsignal(signal.SIGINT) is signal.SIG_IGN
            raise _LaunchError

        _patch_editor_run(monkeypatch, fake_run)

        with pytest.raises(_LaunchError):
            _create_tag_via_editor("v1.0.0", "Release v1.0.0")
        assert {sig: signal.getsignal(sig) for sig in _EDITOR_SIGNALS} == sentinel_handlers

    def test_handlers_restored_when_editor_not_found(
        self, git_repo, monkeypatch, sentinel_handlers
    ):
        monkeypatch.setenv("EDITOR", str(git_repo / "no-such-editor"))

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_FAILURE
        assert {sig: signal.getsignal(sig) for sig in _EDITOR_SIGNALS} == sentinel_handlers

    @pytest.mark.skipif(sys.platform == "win32", reason="preexec_fn is POSIX-only")
    def test_editor_child_starts_with_the_original_handlers(
        self, git_repo, monkeypatch, sentinel_handlers
    ):
        # An ignored signal is inherited across exec. The child must get back
        # what it would have had without the guard, as git's editor does
        # (git ignores only after starting it), so the editor decides what
        # Ctrl-C means.
        in_child: dict[int, object] = {}

        def fake_run(cmd, **kwargs):
            kwargs["preexec_fn"]()  # what runs in the forked child before exec
            in_child.update({sig: signal.getsignal(sig) for sig in _EDITOR_SIGNALS})
            return subprocess.CompletedProcess(cmd, 1)

        _patch_editor_run(monkeypatch, fake_run)

        assert _create_tag_via_editor("v1.0.0", "Release v1.0.0") == EXIT_FAILURE
        assert in_child == sentinel_handlers

    @pytest.mark.parametrize("signum", _EDITOR_SIGNALS, ids=lambda s: signal.Signals(s).name)
    def test_editor_killed_by_signal_is_an_interrupt(self, git_repo, monkeypatch, capsys, signum):
        # git re-raises the editor's SIGINT/SIGQUIT on itself; here that is
        # KeyboardInterrupt, which `main` turns into EXIT_INTERRUPTED.
        def fake_run(cmd, **_kwargs):
            return subprocess.CompletedProcess(cmd, -signum)

        _patch_editor_run(monkeypatch, fake_run)

        with pytest.raises(KeyboardInterrupt):
            _create_tag_via_editor("v1.0.0", "Release v1.0.0")
        assert signal.Signals(signum).name in capsys.readouterr().out
        assert _tag_message("v1.0.0") == ""
        assert _tag_editmsg(git_repo).exists()


# Stand-ins for $EDITOR in the end-to-end test. Each writes a sentinel once it
# is running, sleeps long enough to be signalled, then saves a message. The
# vim-like one ignores SIGINT in its own process, as vim does; the naive one
# keeps the default disposition and dies of it.
_VIM_LIKE_EDITOR = """\
trap '' INT
: > "$SENTINEL"
sleep 1
printf 'Saved after Ctrl-C\\n' > "$1"
"""
_NAIVE_EDITOR = """\
: > "$SENTINEL"
sleep 1
printf 'Never saved\\n' > "$1"
"""


@pytest.mark.skipif(sys.platform == "win32", reason="process groups and SIGINT are POSIX")
@pytest.mark.parametrize(
    ("editor_body", "expected_status", "expected_tag"),
    [
        (_VIM_LIKE_EDITOR, EXIT_OK, "Saved after Ctrl-C"),
        (_NAIVE_EDITOR, EXIT_INTERRUPTED, None),
    ],
    ids=["editor-ignores-sigint", "editor-dies-of-sigint"],
)
def test_ctrl_c_during_editor_end_to_end(git_repo, editor_body, expected_status, expected_tag):
    """A terminal Ctrl-C while the editor is open, against the real CLI.

    The CLI runs in its own session, so it leads its own process group the
    way a shell's foreground job does; `killpg` then delivers SIGINT to the
    CLI and the editor together, exactly as the terminal driver would.
    """
    subprocess.run(["git", "tag", "-a", "-m", "v1", "v1.0.0"], check=True, capture_output=True)
    _commit(git_repo, "feature.txt", "new\n")
    sentinel = git_repo / "editor-running"
    editor = _fake_editor(git_repo, editor_body)
    env = {**os.environ, "EDITOR": editor, "SENTINEL": str(sentinel), "NO_COLOR": "1"}

    proc = subprocess.Popen(
        [sys.executable, "-m", "bump_version.cli", "patch"],
        cwd=git_repo,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        start_new_session=True,
    )
    try:
        # No sync; compose in $EDITOR; no push.
        proc.stdin.write("n\n3\nn\n")
        proc.stdin.flush()
        deadline = time.monotonic() + 30
        while not sentinel.exists():
            assert proc.poll() is None, "bump-version exited before the editor started"
            assert time.monotonic() < deadline, "editor never started"
            time.sleep(0.02)
        os.killpg(proc.pid, signal.SIGINT)
        output, _ = proc.communicate(timeout=30)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()

    assert proc.returncode == expected_status, output
    if expected_tag is None:
        assert "Interrupted" in output
        assert _tag_message("v1.0.1") == ""
        assert _tag_editmsg(git_repo).exists()
    else:
        assert _tag_message("v1.0.1").strip() == expected_tag
