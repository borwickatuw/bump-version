"""Tests for the dynamic-pyproject migration subcommand."""

import argparse
import subprocess
import tomllib

import pytest

from bump_version.cli import (
    _check_pyproject_version,
    _cmd_dynamic_pyproject,
    _create_tag,
    main,
)
from conftest import STATIC_HATCHLING_PYPROJECT


def _make_args(**kwargs) -> argparse.Namespace:
    """Create an argparse.Namespace with dynamic-pyproject defaults."""
    defaults = {
        "dry_run": False,
        "yes": True,
        "prefix": "v",
        "command": "dynamic-pyproject",
    }
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


def _porcelain() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class TestCmdDynamicPyproject:
    """Tests for _cmd_dynamic_pyproject."""

    def test_happy_path_rewrites_and_commits(self, git_repo, write_pyproject):
        write_pyproject()
        _create_tag("v1.2.3", "Release v1.2.3")  # matches static 1.2.3: no drift
        result = _cmd_dynamic_pyproject(_make_args())
        assert result == 0

        parsed = tomllib.loads((git_repo / "pyproject.toml").read_text())
        assert "version" not in parsed["project"]
        assert parsed["project"]["dynamic"] == ["version"]
        assert parsed["build-system"]["requires"] == ["hatchling", "hatch-vcs"]
        assert parsed["tool"]["hatch"]["version"]["source"] == "vcs"

        archival = (git_repo / ".git_archival.txt").read_text()
        assert "describe-name: $Format:%(describe:tags=true,match=*[0-9]*)$" in archival
        attributes = (git_repo / ".gitattributes").read_text()
        assert ".git_archival.txt  export-subst" in attributes

        # Committed, exactly the three migration files, clean tree.
        show = subprocess.run(
            ["git", "show", "--name-only", "--format="],
            capture_output=True,
            text=True,
            check=True,
        )
        assert sorted(show.stdout.split()) == [
            ".git_archival.txt",
            ".gitattributes",
            "pyproject.toml",
        ]
        assert _porcelain() == ""

    def test_already_dynamic_exits_zero(self, write_pyproject, capsys):
        write_pyproject(
            '[project]\nname = "example"\ndynamic = ["version"]\n\n'
            '[build-system]\nrequires = ["hatchling", "hatch-vcs"]\n'
            'build-backend = "hatchling.build"\n'
        )
        with pytest.raises(SystemExit) as exc_info:
            _cmd_dynamic_pyproject(_make_args())
        assert exc_info.value.code == 0
        assert "nothing to do" in capsys.readouterr().out

    def test_non_hatchling_refuses(self, write_pyproject, capsys):
        write_pyproject(
            '[project]\nname = "example"\nversion = "1.0.0"\n\n'
            '[build-system]\nrequires = ["setuptools"]\n'
            'build-backend = "setuptools.build_meta"\n'
        )
        with pytest.raises(SystemExit) as exc_info:
            _cmd_dynamic_pyproject(_make_args())
        assert exc_info.value.code == 1
        assert "only hatchling is supported" in capsys.readouterr().err

    def test_missing_pyproject_refuses(self, git_repo, capsys):
        with pytest.raises(SystemExit) as exc_info:
            _cmd_dynamic_pyproject(_make_args())
        assert exc_info.value.code == 1
        assert "no pyproject.toml" in capsys.readouterr().err

    def test_dirty_pyproject_refuses(self, git_repo, write_pyproject, capsys):
        write_pyproject()
        (git_repo / "pyproject.toml").write_text(
            STATIC_HATCHLING_PYPROJECT + "\n# local edit\n"
        )
        with pytest.raises(SystemExit) as exc_info:
            _cmd_dynamic_pyproject(_make_args())
        assert exc_info.value.code == 1
        assert "uncommitted changes" in capsys.readouterr().err

    def test_drift_decline_aborts(self, git_repo, write_pyproject, monkeypatch):
        # No tags at all: static 1.2.3 vs nothing is drift.
        write_pyproject()
        monkeypatch.setattr("builtins.input", lambda _: "n")
        with pytest.raises(SystemExit) as exc_info:
            _cmd_dynamic_pyproject(_make_args(yes=False))
        assert exc_info.value.code == 0
        assert _porcelain() == ""

    def test_drift_yes_proceeds(self, git_repo, write_pyproject, capsys):
        _create_tag("v1.0.0", "Release v1.0.0")
        write_pyproject()  # static 1.2.3 vs tag v1.0.0
        result = _cmd_dynamic_pyproject(_make_args())
        assert result == 0
        out = capsys.readouterr().out
        assert "latest tag is v1.0.0" in out

    def test_existing_dynamic_list_gets_appended(self, git_repo, write_pyproject):
        write_pyproject(
            '[project]\nname = "example"\nversion = "1.0.0"\n'
            'dynamic = ["readme"]\n\n'
            '[build-system]\nrequires = ["hatchling"]\n'
            'build-backend = "hatchling.build"\n'
        )
        result = _cmd_dynamic_pyproject(_make_args())
        assert result == 0
        parsed = tomllib.loads((git_repo / "pyproject.toml").read_text())
        assert "version" not in parsed["project"]
        assert parsed["project"]["dynamic"] == ["readme", "version"]

    def test_unparseable_requires_aborts_untouched(
        self, git_repo, write_pyproject, capsys
    ):
        content = (
            '[project]\nname = "example"\nversion = "1.0.0"\n\n'
            "[build-system]\n"
            'requires = [\n    "hatchling",\n]\n'
            'build-backend = "hatchling.build"\n'
        )
        write_pyproject(content)
        with pytest.raises(SystemExit) as exc_info:
            _cmd_dynamic_pyproject(_make_args())
        assert exc_info.value.code == 1
        assert "cannot edit" in capsys.readouterr().err
        assert (git_repo / "pyproject.toml").read_text() == content
        assert _porcelain() == ""

    def test_dry_run_leaves_tree_clean(self, git_repo, write_pyproject, capsys):
        write_pyproject()
        _create_tag("v1.2.3", "Release v1.2.3")
        result = _cmd_dynamic_pyproject(_make_args(dry_run=True))
        assert result == 0
        out = capsys.readouterr().out
        assert "[DRY RUN]" in out
        assert '+dynamic = ["version"]' in out
        assert _porcelain() == ""
        assert not (git_repo / ".git_archival.txt").exists()

    def test_hardcoded_version_warning(self, git_repo, write_pyproject, capsys):
        (git_repo / "pkg.py").write_text('__version__ = "1.2.3"\n')
        subprocess.run(["git", "add", "pkg.py"], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add pkg"], check=True, capture_output=True
        )
        write_pyproject()
        _create_tag("v1.2.3", "Release v1.2.3")
        result = _cmd_dynamic_pyproject(_make_args())
        assert result == 0
        out = capsys.readouterr().out
        assert "Hardcoded __version__" in out
        assert "pkg.py" in out
        assert "importlib.metadata" in out
        # Never rewrites code.
        assert (git_repo / "pkg.py").read_text() == '__version__ = "1.2.3"\n'

    def test_migrated_repo_passes_bump_guard(self, git_repo, write_pyproject):
        write_pyproject()
        _create_tag("v1.2.3", "Release v1.2.3")
        assert _cmd_dynamic_pyproject(_make_args()) == 0
        _check_pyproject_version()  # must not exit


class TestMainDynamicPyproject:
    """The subcommand routed through main()."""

    def test_dry_run_via_main(self, git_repo, write_pyproject):
        write_pyproject()
        _create_tag("v1.2.3", "Release v1.2.3")
        with pytest.raises(SystemExit) as exc_info:
            main(["dynamic-pyproject", "--dry-run", "-y"])
        assert exc_info.value.code == 0
        assert _porcelain() == ""
