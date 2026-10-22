"""Tests for CLI argument parsing and command routing."""

import io

import pytest

from bump_version.cli import _create_parser
from bump_version.output import Color, _print_error, _print_info
from bump_version.prompts import _get_editor


class FakeStream(io.StringIO):
    """A stream whose terminal-ness is declared rather than inherited."""

    def __init__(self, *, tty: bool) -> None:
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


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


class TestSharedOptionPosition:
    """A shared option applies whether it comes before or after the subcommand.

    Before v2.1.0 the subparsers' own defaults overwrote whatever the
    top-level parser had already parsed, so `bump-version -p patch` did not
    push while `bump-version patch -p` did.
    """

    @pytest.mark.parametrize(
        ("argv", "expected"),
        [
            (["-p", "patch"], {"command": "patch", "push": True}),
            (["patch", "-p"], {"command": "patch", "push": True}),
            (["-s", "-n", "minor"], {"command": "minor", "sync": True, "dry_run": True}),
            (["--prefix", "", "major"], {"command": "major", "prefix": ""}),
            (["-m", "msg", "patch"], {"command": "patch", "message": "msg"}),
            (["-y", "patch"], {"command": "patch", "yes": True}),
            (["-p"], {"command": None, "push": True}),
            (["--prefix", "x", "current"], {"command": "current", "prefix": "x"}),
            (["current", "--prefix", "x"], {"command": "current", "prefix": "x"}),
            (
                ["-n", "-y", "--prefix", "x", "dynamic-pyproject"],
                {"command": "dynamic-pyproject", "dry_run": True, "yes": True, "prefix": "x"},
            ),
            (
                ["dynamic-pyproject", "-n", "-y", "--prefix", "x"],
                {"command": "dynamic-pyproject", "dry_run": True, "yes": True, "prefix": "x"},
            ),
        ],
        ids=lambda value: " ".join(value) if isinstance(value, list) else None,
    )
    def test_option_applies_in_either_position(self, argv, expected):
        args = _create_parser().parse_args(argv)
        assert {key: getattr(args, key) for key in expected} == expected

    @pytest.mark.parametrize("argv", [[], ["patch"], ["current"], ["dynamic-pyproject"]], ids=repr)
    def test_untyped_options_keep_their_defaults(self, argv):
        """Every shared field is present with its default when nothing is typed."""
        args = _create_parser().parse_args(argv)
        assert vars(args) == {
            "command": argv[0] if argv else None,
            "sync": False,
            "push": False,
            "dry_run": False,
            "message": None,
            "prefix": "v",
            "yes": False,
        }

    @pytest.mark.parametrize(
        ("argv", "field", "expected"),
        [
            (["-m", "before", "patch", "-m", "after"], "message", "after"),
            (["--prefix", "x", "major", "--prefix", "y"], "prefix", "y"),
        ],
    )
    def test_subcommand_position_wins(self, argv, field, expected):
        """Given in both positions, the value after the subcommand is used."""
        assert getattr(_create_parser().parse_args(argv), field) == expected


class TestColor:
    """Tests for Color helper."""

    @pytest.fixture(autouse=True)
    def _no_inherited_no_color(self, monkeypatch):
        """A developer's own NO_COLOR must not decide these tests."""
        monkeypatch.delenv("NO_COLOR", raising=False)

    def test_wrap_adds_color_when_tty(self):
        result = Color.wrap("hello", Color.RED, FakeStream(tty=True))
        assert Color.RED in result
        assert Color.RESET in result
        assert "hello" in result

    def test_wrap_no_color_when_not_tty(self):
        result = Color.wrap("hello", Color.RED, FakeStream(tty=False))
        assert result == "hello"

    def test_no_color_disables_on_tty(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        assert Color.enabled(FakeStream(tty=True)) is False
        assert Color.wrap("hello", Color.RED, FakeStream(tty=True)) == "hello"

    def test_empty_no_color_does_not_disable(self, monkeypatch):
        """no-color.org: only a present *and non-empty* NO_COLOR opts out."""
        monkeypatch.setenv("NO_COLOR", "")
        assert Color.enabled(FakeStream(tty=True)) is True

    def test_unset_no_color_enables_on_tty(self, monkeypatch):
        monkeypatch.delenv("NO_COLOR", raising=False)
        assert Color.enabled(FakeStream(tty=True)) is True

    @pytest.mark.parametrize("no_color", [None, "", "1"])
    def test_non_tty_stays_plain_regardless(self, monkeypatch, no_color):
        if no_color is None:
            monkeypatch.delenv("NO_COLOR", raising=False)
        else:
            monkeypatch.setenv("NO_COLOR", no_color)
        assert Color.enabled(FakeStream(tty=False)) is False

    def test_no_color_keeps_the_words(self, monkeypatch):
        """Color never carries meaning alone, so stripping it loses nothing."""
        monkeypatch.setenv("NO_COLOR", "1")
        stderr = FakeStream(tty=True)
        monkeypatch.setattr("sys.stderr", stderr)
        _print_error("Error: boom")
        assert stderr.getvalue() == "Error: boom\n"

    def test_error_color_follows_stderr_not_stdout(self, monkeypatch):
        """A redirected error log stays plain even when stdout is a terminal."""
        stdout, stderr = FakeStream(tty=True), FakeStream(tty=False)
        monkeypatch.setattr("sys.stdout", stdout)
        monkeypatch.setattr("sys.stderr", stderr)
        _print_error("boom")
        assert stderr.getvalue() == "boom\n"
        assert stdout.getvalue() == ""

    def test_info_color_follows_stdout_not_stderr(self, monkeypatch):
        """Piping stdout drops color from stdout even when stderr is a terminal."""
        stdout, stderr = FakeStream(tty=False), FakeStream(tty=True)
        monkeypatch.setattr("sys.stdout", stdout)
        monkeypatch.setattr("sys.stderr", stderr)
        _print_info("hello")
        assert stdout.getvalue() == "hello\n"
        assert stderr.getvalue() == ""


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
