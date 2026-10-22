"""Tests for git operations using a real temporary git repository."""

import subprocess
from unittest.mock import patch

from bump_version.git import (
    _create_tag,
    _get_commits_since_tag,
    _get_current_branch,
    _is_git_repo,
    _run_git,
)
from bump_version.version import Version, _get_current_version, _get_version_tags


class TestRunGit:
    """Tests for _run_git."""

    def test_names_utf8_rather_than_the_host_locale(self):
        """
        Guards the decoding contract the round-trip tests cannot see.

        Every developer host here is already UTF-8, so `text=True` would pass
        those tests while mojibaking on a machine running under LANG=C.
        """
        with patch("subprocess.run") as run:
            _run_git("rev-parse", "--git-dir", check=False)
        assert run.call_args.kwargs["encoding"] == "utf-8"


class TestIsGitRepo:
    """Tests for _is_git_repo."""

    def test_in_git_repo(self, git_repo):
        assert _is_git_repo() is True

    def test_not_in_git_repo(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        assert _is_git_repo() is False


class TestGetCurrentBranch:
    """Tests for _get_current_branch."""

    def test_returns_branch_name(self, git_repo):
        branch = _get_current_branch()
        # Could be main or master depending on git config
        assert branch is not None
        assert isinstance(branch, str)


class TestGetVersionTags:
    """Tests for _get_version_tags."""

    def test_no_tags(self, git_repo):
        assert _get_version_tags() == []

    def test_returns_version_tags_sorted(self, git_repo):
        subprocess.run(
            ["git", "tag", "-a", "v1.0.0", "-m", "v1.0.0"],
            check=True,
            capture_output=True,
        )
        # Add another commit for a new tag
        (git_repo / "file.txt").write_text("content")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Second"], check=True, capture_output=True)
        subprocess.run(
            ["git", "tag", "-a", "v2.0.0", "-m", "v2.0.0"],
            check=True,
            capture_output=True,
        )
        tags = _get_version_tags()
        assert tags == ["v1.0.0", "v2.0.0"]

    def test_ignores_non_version_tags(self, git_repo):
        subprocess.run(
            ["git", "tag", "-a", "v1.0.0", "-m", "v1.0.0"],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "tag", "release-candidate"],
            check=True,
            capture_output=True,
        )
        tags = _get_version_tags()
        assert tags == ["v1.0.0"]

    def test_custom_prefix(self, git_repo):
        subprocess.run(
            ["git", "tag", "-a", "release-1.0.0", "-m", "r1"],
            check=True,
            capture_output=True,
        )
        tags = _get_version_tags(prefix="release-")
        assert tags == ["release-1.0.0"]


class TestGetCurrentVersion:
    """Tests for _get_current_version."""

    def test_no_tags_returns_none(self, git_repo):
        assert _get_current_version() is None

    def test_returns_highest_version(self, git_repo):
        subprocess.run(
            ["git", "tag", "-a", "v1.0.0", "-m", "v1"],
            check=True,
            capture_output=True,
        )
        (git_repo / "a.txt").write_text("a")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "add a"], check=True, capture_output=True)
        subprocess.run(
            ["git", "tag", "-a", "v1.1.0", "-m", "v1.1"],
            check=True,
            capture_output=True,
        )
        v = _get_current_version()
        assert v == Version(1, 1, 0)


class TestGetCommitsSinceTag:
    """Tests for _get_commits_since_tag."""

    def test_commits_since_tag(self, git_repo):
        subprocess.run(
            ["git", "tag", "-a", "v1.0.0", "-m", "v1"],
            check=True,
            capture_output=True,
        )
        (git_repo / "b.txt").write_text("b")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "Add feature B"],
            check=True,
            capture_output=True,
        )
        commits = _get_commits_since_tag("v1.0.0")
        assert len(commits) == 1
        assert "Add feature B" in commits[0]

    def test_non_ascii_summary_round_trips(self, git_repo):
        """A commit summary outside ASCII comes back as written."""
        subprocess.run(
            ["git", "tag", "-a", "v1.0.0", "-m", "v1"],
            check=True,
            capture_output=True,
        )
        (git_repo / "c.txt").write_text("c")
        subprocess.run(["git", "add", "."], check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "한국어 소장품 내보내기"],
            check=True,
            capture_output=True,
        )
        commits = _get_commits_since_tag("v1.0.0")
        assert commits == ["한국어 소장품 내보내기"]

    def test_no_commits_since_tag(self, git_repo):
        subprocess.run(
            ["git", "tag", "-a", "v1.0.0", "-m", "v1"],
            check=True,
            capture_output=True,
        )
        commits = _get_commits_since_tag("v1.0.0")
        assert commits == []

    def test_all_commits_when_no_tag(self, git_repo):
        commits = _get_commits_since_tag(None)
        assert len(commits) >= 1


class TestCreateTag:
    """Tests for _create_tag."""

    def test_create_tag(self, git_repo):
        result = _create_tag("v1.0.0", "Release v1.0.0")
        assert result is True
        # Verify tag exists
        check = subprocess.run(
            ["git", "tag", "-l", "v1.0.0"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert "v1.0.0" in check.stdout

    def test_dry_run_does_not_create_tag(self, git_repo):
        result = _create_tag("v1.0.0", "Release v1.0.0", dry_run=True)
        assert result is True
        check = subprocess.run(
            ["git", "tag", "-l", "v1.0.0"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert "v1.0.0" not in check.stdout

    def test_duplicate_tag_fails(self, git_repo):
        _create_tag("v1.0.0", "Release v1.0.0")
        result = _create_tag("v1.0.0", "Duplicate")
        assert result is False
