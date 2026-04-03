"""Tests for CLI argument parsing and command routing."""

from unittest.mock import patch

from bump_version.cli import (
    Color,
    _create_parser,
    _get_editor,
)


class TestCreateParser:
    """Tests for argument parser construction."""

    def test_parser_has_subcommands(self):
        parser = _create_parser()
        # Parse known subcommands without error
        args = parser.parse_args(["major"])
        assert args.command == "major"

    def test_parser_minor(self):
        args = _create_parser().parse_args(["minor"])
        assert args.command == "minor"

    def test_parser_patch(self):
        args = _create_parser().parse_args(["patch"])
        assert args.command == "patch"

    def test_parser_current(self):
        args = _create_parser().parse_args(["current"])
        assert args.command == "current"

    def test_parser_no_command_defaults_to_none(self):
        args = _create_parser().parse_args([])
        assert args.command is None

    def test_parser_sync_flag(self):
        args = _create_parser().parse_args(["patch", "--sync"])
        assert args.sync is True

    def test_parser_push_flag(self):
        args = _create_parser().parse_args(["patch", "--push"])
        assert args.push is True

    def test_parser_dry_run_flag(self):
        args = _create_parser().parse_args(["minor", "--dry-run"])
        assert args.dry_run is True

    def test_parser_message_flag(self):
        args = _create_parser().parse_args(["patch", "-m", "Release notes"])
        assert args.message == "Release notes"

    def test_parser_prefix_default(self):
        args = _create_parser().parse_args([])
        assert args.prefix == "v"

    def test_parser_prefix_custom(self):
        args = _create_parser().parse_args(["--prefix", ""])
        assert not args.prefix

    def test_parser_yes_flag(self):
        args = _create_parser().parse_args(["patch", "-y"])
        assert args.yes is True

    def test_subcommand_inherits_options(self):
        args = _create_parser().parse_args(["major", "--sync", "--push", "-y"])
        assert args.command == "major"
        assert args.sync is True
        assert args.push is True
        assert args.yes is True


class TestColor:
    """Tests for Color helper."""

    def test_wrap_adds_color_when_tty(self):
        with patch.object(Color, "enabled", return_value=True):
            result = Color.wrap("hello", Color.RED)
            assert Color.RED in result
            assert Color.RESET in result
            assert "hello" in result

    def test_wrap_no_color_when_not_tty(self):
        with patch.object(Color, "enabled", return_value=False):
            result = Color.wrap("hello", Color.RED)
            assert result == "hello"


class TestGetEditor:
    """Tests for _get_editor."""

    def test_uses_editor_env(self, monkeypatch):
        monkeypatch.setenv("EDITOR", "nano")
        monkeypatch.delenv("VISUAL", raising=False)
        assert _get_editor() == "nano"

    def test_uses_visual_env(self, monkeypatch):
        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.setenv("VISUAL", "code")
        assert _get_editor() == "code"

    def test_editor_takes_precedence(self, monkeypatch):
        monkeypatch.setenv("EDITOR", "vim")
        monkeypatch.setenv("VISUAL", "code")
        assert _get_editor() == "vim"

    def test_defaults_to_vi(self, monkeypatch):
        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.delenv("VISUAL", raising=False)
        assert _get_editor() == "vi"
