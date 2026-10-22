"""Tests for this repo's own tooling wiring.

Not tests of the ``bump_version`` package: these guard config couplings that
fail silently, so nothing else in the suite would catch a regression.
"""

import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

requires_pysmelly = pytest.mark.skipif(
    shutil.which("pysmelly") is None,
    reason="pysmelly is an on-demand tool, not a locked dependency",
)


def _make_recipe(target: str) -> list[str]:
    """Return the recipe lines of one Makefile target, tabs and @ stripped."""
    lines = (REPO_ROOT / "Makefile").read_text().splitlines()
    for index, line in enumerate(lines):
        if re.match(rf"^{re.escape(target)}:", line):
            recipe = []
            for candidate in lines[index + 1 :]:
                if not candidate.startswith("\t"):
                    break
                recipe.append(candidate.lstrip("\t").lstrip("@").strip())
            return recipe
    pytest.fail(f"No {target} target in Makefile")


def _run_make_pysmelly() -> str:
    """Run the Makefile's pysmelly recipe verbatim; return its combined output."""
    (command,) = _make_recipe("pysmelly")
    argv = command.split()
    argv[0] = shutil.which(argv[0])
    result = subprocess.run(argv, cwd=REPO_ROOT, capture_output=True, text=True, check=False)
    return result.stdout + result.stderr


class TestPysmellyWiring:
    """pysmelly reads ``[tool.pysmelly]`` from the *target* directory only.

    It does not walk upward looking for a pyproject.toml, so ``pysmelly src/``
    runs with no config and the exclude list is silently ignored -- a green
    run that is in fact misconfigured (PYSMELLY-REVIEW.md Tells).
    """

    def test_target_is_the_directory_holding_the_config(self):
        assert _make_recipe("pysmelly") == ["pysmelly ."]

    def test_config_section_exists_to_be_loaded(self):
        pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
        assert "pysmelly" in pyproject["tool"]

    @requires_pysmelly
    def test_run_does_not_warn_that_config_was_missed(self):
        """pysmelly reports a missed config itself; assert it stays quiet."""
        assert "no config in" not in _run_make_pysmelly()

    @requires_pysmelly
    def test_run_honours_the_tests_exclude(self):
        """The exclude is load-bearing only if the run actually applies it."""
        output = _run_make_pysmelly()
        parsed = re.search(r"Parsed (\d+) Python files", output)
        assert parsed is not None, output
        assert int(parsed.group(1)) == len(list((REPO_ROOT / "src").rglob("*.py")))
