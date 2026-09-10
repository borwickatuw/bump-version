"""Shared test fixtures for bump-version."""

import subprocess

import pytest

# Minimal hatchling project with a static [project] version — the shape the
# static-version guard refuses and `dynamic-pyproject` migrates.
STATIC_HATCHLING_PYPROJECT = """\
[project]
name = "example"
version = "1.2.3"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""


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
    # Create initial commit
    (tmp_path / "README.md").write_text("# test")
    subprocess.run(["git", "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        check=True,
        capture_output=True,
    )
    return tmp_path


@pytest.fixture()
def write_pyproject(git_repo):
    """Return a helper that writes pyproject.toml into git_repo and commits it."""

    def _write(content: str = STATIC_HATCHLING_PYPROJECT):
        path = git_repo / "pyproject.toml"
        path.write_text(content)
        subprocess.run(
            ["git", "add", "pyproject.toml"], check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "Add pyproject.toml"],
            check=True,
            capture_output=True,
        )
        return path

    return _write
