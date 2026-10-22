"""Tests for command functions and interactive helpers."""

import subprocess

import pytest

from bump_version.cli import _cmd_bump, _cmd_current, _show_changes_since_version, main
from bump_version.git import _create_tag, _get_default_remote, _get_remotes, _push_tag, _sync_repo
from bump_version.output import _print_error, _print_info, _print_success, _print_warning
from bump_version.prompts import (
    _EditorRequest,
    _edit_summary,
    _prompt_bump_type,
    _prompt_message,
    _prompt_yes_no,
    _strip_editor_content,
)
from bump_version.version import BumpType, Version


class TestPrintHelpers:
    """Tests for print helper functions."""

    def test_print_info(self, capsys):
        _print_info("hello")
        assert "hello" in capsys.readouterr().out

    def test_print_success(self, capsys):
        _print_success("done")
        assert "done" in capsys.readouterr().out

    def test_print_warning(self, capsys):
        _print_warning("careful")
        assert "careful" in capsys.readouterr().out

    def test_print_error(self, capsys):
        _print_error("bad")
        assert "bad" in capsys.readouterr().err


class TestPromptYesNo:
    """Tests for _prompt_yes_no."""

    def test_default_yes(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert _prompt_yes_no("Continue?", default=True) is True

    def test_default_no(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        assert _prompt_yes_no("Continue?", default=False) is False

    def test_yes_response(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        assert _prompt_yes_no("Continue?") is True

    def test_yes_full(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "yes")
        assert _prompt_yes_no("Continue?") is True

    def test_no_response(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        assert _prompt_yes_no("Continue?") is False

    @pytest.mark.parametrize("interrupt", [EOFError, KeyboardInterrupt])
    def test_interrupt_is_not_an_answer(self, monkeypatch, interrupt):
        """EOF and Ctrl-C propagate for main() to turn into EXIT_INTERRUPTED."""

        def raise_interrupt(_):
            raise interrupt

        monkeypatch.setattr("builtins.input", raise_interrupt)
        with pytest.raises(interrupt):
            _prompt_yes_no("Continue?")


class TestGetRemotes:
    """Tests for _get_remotes."""

    def test_no_remotes(self, git_repo):
        remotes = _get_remotes()
        assert remotes == []


class TestSyncRepo:
    """Tests for _sync_repo."""

    def test_no_remote_skips(self, git_repo, capsys):
        _sync_repo()
        output = capsys.readouterr().out
        assert "No remote" in output or "skipping" in output.lower()


class TestShowChangesSinceVersion:
    """Tests for _show_changes_since_version."""

    def test_no_current_version_shows_all(self, git_repo, capsys):
        commits = _show_changes_since_version(None)
        assert len(commits) >= 1

    def test_shows_changes_since_tag(self, git_repo, capsys):
        _create_tag("v1.0.0", "v1.0.0")
        (git_repo / "new.txt").write_text("new")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "New feature"],
            check=True,
            capture_output=True,
        )
        commits = _show_changes_since_version(Version(1, 0, 0))
        assert len(commits) == 1
        assert "New feature" in commits[0]


class TestPushTag:
    """Tests for _push_tag."""

    def test_dry_run(self, git_repo):
        result = _push_tag("v1.0.0", dry_run=True)
        assert result is True

    def test_no_remote_skips(self, git_repo, capsys):
        result = _push_tag("v1.0.0")
        assert result is True
        assert "No remote" in capsys.readouterr().out


class TestCmdCurrent:
    """Tests for _cmd_current."""

    def test_no_version(self, git_repo, capsys, bump_args):
        args = bump_args()
        result = _cmd_current(args)
        assert result == 1
        assert "No version" in capsys.readouterr().out

    def test_with_version(self, git_repo, capsys, bump_args):
        _create_tag("v1.2.3", "Release")
        args = bump_args()
        result = _cmd_current(args)
        assert result == 0
        assert "v1.2.3" in capsys.readouterr().out


class TestGetDefaultRemote:
    """Tests for _get_default_remote."""

    def test_no_remotes_returns_none(self, git_repo):
        assert _get_default_remote() is None


class TestPromptBumpType:
    """Tests for _prompt_bump_type."""

    def test_major_by_number(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "1")
        assert _prompt_bump_type() == BumpType.MAJOR

    def test_minor_by_name(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "minor")
        assert _prompt_bump_type() == BumpType.MINOR

    def test_patch_by_number(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "3")
        assert _prompt_bump_type() == BumpType.PATCH

    @pytest.mark.parametrize("interrupt", [EOFError, KeyboardInterrupt])
    def test_interrupt_propagates(self, monkeypatch, interrupt):
        def raise_interrupt(_):
            raise interrupt

        monkeypatch.setattr("builtins.input", raise_interrupt)
        with pytest.raises(interrupt):
            _prompt_bump_type()

    def test_invalid_then_valid(self, monkeypatch):
        inputs = iter(["invalid", "2"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        assert _prompt_bump_type() == BumpType.MINOR


class TestEditSummary:
    """Tests for _edit_summary."""

    def test_returns_updated_message(self, monkeypatch):
        monkeypatch.setattr(
            "bump_version.prompts._input_with_prefill",
            lambda _prompt, _prefill: "New summary",
        )
        result = _edit_summary("Old summary", "Old summary\n\nDetails")
        assert result == "New summary\n\nDetails"

    def test_empty_summary_uses_default(self, monkeypatch):
        monkeypatch.setattr(
            "bump_version.prompts._input_with_prefill",
            lambda _prompt, _prefill: "",
        )
        result = _edit_summary("Summary", "Summary\n\nDetails")
        assert result == "Summary\n\nDetails"

    @pytest.mark.parametrize("interrupt", [EOFError, KeyboardInterrupt])
    def test_interrupt_propagates(self, monkeypatch, interrupt):
        """An interrupt must not fall back to the default and go on to tag."""

        def raise_interrupt(_prompt, _prefill):
            raise interrupt

        monkeypatch.setattr("bump_version.prompts._input_with_prefill", raise_interrupt)
        with pytest.raises(interrupt):
            _edit_summary("Summary", "Summary\n\nDetails")


class TestPromptMessage:
    """Tests for _prompt_message."""

    def test_choice_1_uses_default(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "1")
        result = _prompt_message("Summary", "Full message")
        assert result == "Full message"

    def test_empty_uses_default(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "")
        result = _prompt_message("Summary", "Full message")
        assert result == "Full message"

    def test_choice_2_edits_summary(self, monkeypatch):
        inputs = iter(["2"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        monkeypatch.setattr(
            "bump_version.prompts._edit_summary",
            lambda _s, _f: "Edited",
        )
        result = _prompt_message("Summary", "Full message")
        assert result == "Edited"

    def test_choice_3_returns_editor_request(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "3")
        result = _prompt_message("Summary", "Full message")
        assert result == _EditorRequest("Full message")

    @pytest.mark.parametrize("interrupt", [EOFError, KeyboardInterrupt])
    def test_interrupt_propagates(self, monkeypatch, interrupt):
        """An interrupt must not fall back to the default and go on to tag."""

        def raise_interrupt(_):
            raise interrupt

        monkeypatch.setattr("builtins.input", raise_interrupt)
        with pytest.raises(interrupt):
            _prompt_message("Summary", "Full message")

    def test_invalid_then_valid(self, monkeypatch):
        inputs = iter(["9", "1"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        result = _prompt_message("Summary", "Full message")
        assert result == "Full message"


class TestStripEditorContent:
    """Tests for _strip_editor_content (scissors cut + comment/whitespace strip)."""

    def test_plain_message_passthrough(self):
        assert _strip_editor_content("Release v1.0.0") == "Release v1.0.0"

    def test_drops_comment_lines(self):
        content = "Release v1.0.0\n# a comment\n\nChanges:\n- foo\n"
        assert _strip_editor_content(content) == "Release v1.0.0\n\nChanges:\n- foo"

    def test_cuts_at_scissors_line(self):
        content = (
            "Release v1.0.0\n\nChanges:\n- foo\n\n"
            "# ------------------------ >8 ------------------------\n"
            "# Diff against v0.9.0:\n"
            "diff --git a/f b/f\n"
            "@@ -1 +1 @@\n"
            "-old\n+new\n"
        )
        assert _strip_editor_content(content) == "Release v1.0.0\n\nChanges:\n- foo"

    def test_empty_after_strip(self):
        # Only comments and scissors content — nothing left after strip.
        content = (
            "# everything is a comment\n"
            "# ------------------------ >8 ------------------------\n"
            "anything below\n"
        )
        assert _strip_editor_content(content) == ""

    def test_whitespace_only_returns_empty(self):
        assert _strip_editor_content("\n\n   \n\n") == ""


class TestMain:
    """Tests for main entry point."""

    def test_not_git_repo(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit) as exc_info:
            main(["current"])
        assert exc_info.value.code == 1

    def test_current_command(self, git_repo):
        with pytest.raises(SystemExit) as exc_info:
            main(["current"])
        # No tags, returns 1
        assert exc_info.value.code == 1

    def test_major_command_dry_run(self, git_repo):
        with pytest.raises(SystemExit) as exc_info:
            main(["major", "--dry-run", "-y"])
        assert exc_info.value.code == 0

    def test_minor_command_dry_run(self, git_repo):
        with pytest.raises(SystemExit) as exc_info:
            main(["minor", "--dry-run", "-y"])
        assert exc_info.value.code == 0

    def test_patch_command_dry_run(self, git_repo):
        with pytest.raises(SystemExit) as exc_info:
            main(["patch", "--dry-run", "-y"])
        assert exc_info.value.code == 0

    @pytest.fixture()
    def route(self, git_repo, monkeypatch):
        """Run main() with _cmd_bump stubbed; return the one (args, bump_type) it got."""

        def _route(argv: list[str]):
            calls = []

            def fake_cmd_bump(args, bump_type):
                calls.append((args, bump_type))
                return 0

            monkeypatch.setattr("bump_version.cli._cmd_bump", fake_cmd_bump)
            with pytest.raises(SystemExit) as exc_info:
                main(argv)
            assert exc_info.value.code == 0
            assert len(calls) == 1
            return calls[0]

        return _route

    def test_no_subcommand_routes_to_interactive_bump(self, route):
        """No subcommand reaches _cmd_bump with bump_type None (interactive mode)."""
        args, bump_type = route([])
        assert args.command is None
        assert bump_type is None

    @pytest.mark.parametrize(
        ("command", "expected_bump_type"),
        [
            ("major", BumpType.MAJOR),
            ("minor", BumpType.MINOR),
            ("patch", BumpType.PATCH),
        ],
    )
    def test_bump_routing(self, route, command, expected_bump_type):
        """main() hands _cmd_bump the BumpType its subcommand names.

        This pins the subcommand-name-to-BumpType mapping that _dispatch
        derives rather than spells out.
        """
        args, bump_type = route([command])
        assert args.command == command
        assert bump_type is expected_bump_type

    def test_option_before_subcommand_reaches_cmd_bump(self, route):
        """`bump-version -p -y patch` pushes: the flags are not dropped on the way."""
        args, bump_type = route(["-p", "-y", "patch"])
        assert bump_type is BumpType.PATCH
        assert args.push is True
        assert args.yes is True


class TestCmdBump:
    """Tests for _cmd_bump in non-interactive mode."""

    def test_bump_patch_dry_run(self, git_repo, capsys, bump_args):
        _create_tag("v1.0.0", "Initial")
        (git_repo / "fix.txt").write_text("fix")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Bug fix"],
            check=True,
            capture_output=True,
        )
        args = bump_args(dry_run=True)
        result = _cmd_bump(args, BumpType.PATCH)
        assert result == 0
        output = capsys.readouterr().out
        assert "v1.0.1" in output

    def test_bump_from_scratch(self, git_repo, capsys, bump_args):
        args = bump_args(dry_run=True)
        result = _cmd_bump(args, BumpType.MAJOR)
        assert result == 0
        output = capsys.readouterr().out
        assert "v1.0.0" in output

    def test_bump_no_changes_exits(self, git_repo, bump_args):
        _create_tag("v1.0.0", "Initial")
        args = bump_args()
        with pytest.raises(SystemExit) as exc_info:
            _cmd_bump(args, BumpType.PATCH)
        assert exc_info.value.code == 1

    def test_bump_with_custom_message(self, git_repo, capsys, bump_args):
        _create_tag("v1.0.0", "Initial")
        (git_repo / "feature.txt").write_text("feature")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add feature"],
            check=True,
            capture_output=True,
        )
        args = bump_args(message="Custom release note", dry_run=True)
        result = _cmd_bump(args, BumpType.MINOR)
        assert result == 0

    def test_bump_with_sync_no_remote(self, git_repo, capsys, bump_args):
        """Sync flag with no remote should warn but continue."""
        (git_repo / "f.txt").write_text("f")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Commit"],
            check=True,
            capture_output=True,
        )
        args = bump_args(sync=True, dry_run=True)
        result = _cmd_bump(args, BumpType.PATCH)
        assert result == 0

    def test_bump_creates_tag(self, git_repo, capsys, bump_args):
        """Non-dry-run actually creates the tag."""
        (git_repo / "f.txt").write_text("f")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Feature"],
            check=True,
            capture_output=True,
        )
        args = bump_args()
        result = _cmd_bump(args, BumpType.MAJOR)
        assert result == 0
        # Verify tag was created
        check = subprocess.run(
            ["git", "tag", "-l", "v1.0.0"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert "v1.0.0" in check.stdout
