"""Tests for pyproject.toml awareness (static-version refusal)."""

import argparse

import pytest

from bump_version.cli import (
    BumpType,
    _check_pyproject_version,
    _cmd_bump,
    _read_pyproject,
)


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


class TestReadPyproject:
    """Tests for _read_pyproject."""

    def test_missing_pyproject_returns_none(self, git_repo):
        assert _read_pyproject() is None

    def test_parses_pyproject(self, write_pyproject):
        write_pyproject()
        data = _read_pyproject()
        assert data["project"]["version"] == "1.2.3"

    def test_found_from_subdirectory(self, git_repo, write_pyproject, monkeypatch):
        write_pyproject()
        subdir = git_repo / "src" / "pkg"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        data = _read_pyproject()
        assert data["project"]["version"] == "1.2.3"

    def test_malformed_toml_fails_fast(self, git_repo, capsys):
        (git_repo / "pyproject.toml").write_text("[project\nversion = ")
        with pytest.raises(SystemExit) as exc_info:
            _read_pyproject()
        assert exc_info.value.code == 1
        assert "could not parse" in capsys.readouterr().err


class TestCheckPyprojectVersion:
    """Tests for _check_pyproject_version."""

    def test_static_version_refuses(self, write_pyproject, capsys):
        write_pyproject()
        with pytest.raises(SystemExit) as exc_info:
            _check_pyproject_version()
        assert exc_info.value.code == 1
        err = capsys.readouterr().err
        assert "pins version 1.2.3 statically" in err
        assert "dynamic-pyproject" in err
        assert "allow-static-version" in err

    def test_missing_pyproject_proceeds(self, git_repo):
        _check_pyproject_version()

    def test_no_project_table_proceeds(self, write_pyproject):
        write_pyproject('[tool.other]\nkey = "value"\n')
        _check_pyproject_version()

    def test_no_version_key_proceeds(self, write_pyproject):
        write_pyproject('[project]\nname = "example"\ndynamic = ["version"]\n')
        _check_pyproject_version()

    def test_dynamic_version_listed_proceeds(self, write_pyproject):
        # Both version and dynamic present (invalid per PEP 621, but the
        # dynamic declaration wins: the tree does not pin the version).
        write_pyproject(
            '[project]\nname = "example"\nversion = "1.0.0"\ndynamic = ["version"]\n'
        )
        _check_pyproject_version()

    def test_override_proceeds_with_info(self, write_pyproject, capsys):
        write_pyproject(
            '[project]\nname = "example"\nversion = "1.0.0"\n\n'
            "[tool.bump-version]\nallow-static-version = true\n"
        )
        _check_pyproject_version()
        assert "allow-static-version" in capsys.readouterr().out

    def test_override_false_refuses(self, write_pyproject):
        write_pyproject(
            '[project]\nname = "example"\nversion = "1.0.0"\n\n'
            "[tool.bump-version]\nallow-static-version = false\n"
        )
        with pytest.raises(SystemExit) as exc_info:
            _check_pyproject_version()
        assert exc_info.value.code == 1

    def test_non_bool_override_fails_fast(self, write_pyproject, capsys):
        write_pyproject(
            '[project]\nname = "example"\nversion = "1.0.0"\n\n'
            '[tool.bump-version]\nallow-static-version = "yes"\n'
        )
        with pytest.raises(SystemExit) as exc_info:
            _check_pyproject_version()
        assert exc_info.value.code == 1
        assert "must be a boolean" in capsys.readouterr().err


class TestCmdBumpPyprojectGuard:
    """The guard wired into _cmd_bump."""

    def test_static_version_blocks_bump(self, write_pyproject, capsys):
        write_pyproject()
        args = _make_args(dry_run=True)
        with pytest.raises(SystemExit) as exc_info:
            _cmd_bump(args, BumpType.PATCH)
        assert exc_info.value.code == 1
        assert "statically" in capsys.readouterr().err

    def test_override_allows_bump(self, write_pyproject, capsys):
        write_pyproject(
            '[project]\nname = "example"\nversion = "1.0.0"\n\n'
            "[tool.bump-version]\nallow-static-version = true\n"
        )
        args = _make_args(dry_run=True)
        result = _cmd_bump(args, BumpType.PATCH)
        assert result == 0

    def test_dynamic_version_allows_bump(self, write_pyproject):
        write_pyproject('[project]\nname = "example"\ndynamic = ["version"]\n')
        args = _make_args(dry_run=True)
        result = _cmd_bump(args, BumpType.PATCH)
        assert result == 0

    def test_no_pyproject_allows_bump(self, git_repo):
        args = _make_args(dry_run=True)
        result = _cmd_bump(args, BumpType.PATCH)
        assert result == 0
