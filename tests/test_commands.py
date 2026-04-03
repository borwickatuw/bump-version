"""Tests for command functions and interactive helpers."""

import argparse
import subprocess

import pytest

from bump_version.cli import (
    BumpType,
    Version,
    _cmd_bump,
    _cmd_current,
    _create_tag,
    _edit_summary,
    _get_default_remote,
    _get_remotes,
    _print_error,
    _print_info,
    _print_success,
    _print_warning,
    _prompt_bump_type,
    _prompt_message,
    _prompt_yes_no,
    _push_tag,
    _show_changes_since_version,
    _sync_repo,
    main,
)


@pytest.fixture()
def git_repo(tmp_path, monkeypatch):
    """Create a temporary git repository for testing."""
    monkeypatch.chdir(tmp_path)
    subprocess.run(["git", "init"], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        check=True,
        capture_output=True,
    )
    (tmp_path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        check=True,
        capture_output=True,
    )
    return tmp_path


def _make_args(**kwargs) -> argparse.Namespace:
    """Create an argparse.Namespace with default bump-version options."""
    defaults = {
        "sync": False,
        "push": False,
        "dry_run": False,
        "message": None,
        "prefix": "v",
        "yes": True,
        "command": None,
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


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

    def test_eof_returns_false(self, monkeypatch):
        def raise_eof(_):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        assert _prompt_yes_no("Continue?") is False

    def test_keyboard_interrupt_returns_false(self, monkeypatch):
        def raise_interrupt(_):
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", raise_interrupt)
        assert _prompt_yes_no("Continue?") is False


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

    def test_no_version(self, git_repo, capsys):
        args = _make_args()
        result = _cmd_current(args)
        assert result == 1
        assert "No version" in capsys.readouterr().out

    def test_with_version(self, git_repo, capsys):
        _create_tag("v1.2.3", "Release")
        args = _make_args()
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

    def test_eof_exits(self, monkeypatch):
        def raise_eof(_):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        with pytest.raises(SystemExit) as exc_info:
            _prompt_bump_type()
        assert exc_info.value.code == 0

    def test_invalid_then_valid(self, monkeypatch):
        inputs = iter(["invalid", "2"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        assert _prompt_bump_type() == BumpType.MINOR


class TestEditSummary:
    """Tests for _edit_summary."""

    def test_returns_updated_message(self, monkeypatch):
        monkeypatch.setattr(
            "bump_version.cli._input_with_prefill",
            lambda _prompt, _prefill: "New summary",
        )
        result = _edit_summary("Old summary", "Old summary\n\nDetails")
        assert result == "New summary\n\nDetails"

    def test_empty_summary_uses_default(self, monkeypatch):
        monkeypatch.setattr(
            "bump_version.cli._input_with_prefill",
            lambda _prompt, _prefill: "",
        )
        result = _edit_summary("Summary", "Summary\n\nDetails")
        assert result == "Summary\n\nDetails"

    def test_eof_uses_default(self, monkeypatch):
        def raise_eof(_prompt, _prefill):
            raise EOFError

        monkeypatch.setattr("bump_version.cli._input_with_prefill", raise_eof)
        result = _edit_summary("Summary", "Summary\n\nDetails")
        assert result == "Summary\n\nDetails"


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
            "bump_version.cli._edit_summary",
            lambda _s, _f: "Edited",
        )
        result = _prompt_message("Summary", "Full message")
        assert result == "Edited"

    def test_choice_3_opens_editor(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "3")
        monkeypatch.setattr(
            "bump_version.cli._edit_message_in_editor",
            lambda _d: "Editor result",
        )
        result = _prompt_message("Summary", "Full message")
        assert result == "Editor result"

    def test_eof_uses_default(self, monkeypatch):
        def raise_eof(_):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        result = _prompt_message("Summary", "Full message")
        assert result == "Full message"

    def test_invalid_then_valid(self, monkeypatch):
        inputs = iter(["9", "1"])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))
        result = _prompt_message("Summary", "Full message")
        assert result == "Full message"


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


class TestCmdBump:
    """Tests for _cmd_bump in non-interactive mode."""

    def test_bump_patch_dry_run(self, git_repo, capsys):
        _create_tag("v1.0.0", "Initial")
        (git_repo / "fix.txt").write_text("fix")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Bug fix"],
            check=True,
            capture_output=True,
        )
        args = _make_args(dry_run=True)
        result = _cmd_bump(args, BumpType.PATCH)
        assert result == 0
        output = capsys.readouterr().out
        assert "v1.0.1" in output

    def test_bump_from_scratch(self, git_repo, capsys):
        args = _make_args(dry_run=True)
        result = _cmd_bump(args, BumpType.MAJOR)
        assert result == 0
        output = capsys.readouterr().out
        assert "v1.0.0" in output

    def test_bump_no_changes_exits(self, git_repo):
        _create_tag("v1.0.0", "Initial")
        args = _make_args()
        with pytest.raises(SystemExit) as exc_info:
            _cmd_bump(args, BumpType.PATCH)
        assert exc_info.value.code == 1

    def test_bump_with_custom_message(self, git_repo, capsys):
        _create_tag("v1.0.0", "Initial")
        (git_repo / "feature.txt").write_text("feature")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add feature"],
            check=True,
            capture_output=True,
        )
        args = _make_args(message="Custom release note", dry_run=True)
        result = _cmd_bump(args, BumpType.MINOR)
        assert result == 0

    def test_bump_with_sync_no_remote(self, git_repo, capsys):
        """Sync flag with no remote should warn but continue."""
        (git_repo / "f.txt").write_text("f")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Commit"],
            check=True,
            capture_output=True,
        )
        args = _make_args(sync=True, dry_run=True)
        result = _cmd_bump(args, BumpType.PATCH)
        assert result == 0

    def test_bump_creates_tag(self, git_repo, capsys):
        """Non-dry-run actually creates the tag."""
        (git_repo / "f.txt").write_text("f")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Feature"],
            check=True,
            capture_output=True,
        )
        args = _make_args()
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
