"""Tests for the prompted (non-`--yes`) half of a bump.

Every other `_cmd_bump` test runs with `yes=True`, so the branches that only
exist for an interactive operator -- the offer to sync, the confirmation
before tagging, the offer to push -- had no coverage. These drive them with
`_prompt_yes_no` stubbed, and push against a local bare repo standing in for
the remote so the real push and fetch paths run without a network.
"""

import subprocess

import pytest

from bump_version.cli import _maybe_push, _maybe_sync, _resolve_message_and_create_tag
from bump_version.exit_status import EXIT_DECLINED, EXIT_FAILURE, EXIT_OK
from bump_version.git import _create_tag, _push_tag, _sync_repo
from bump_version.prompts import _EditorRequest
from bump_version.version import Version


@pytest.fixture()
def answer(monkeypatch):
    """Stub `_prompt_yes_no` with a scripted reply.

    Returns the list the stub records `(prompt, default)` into, so a test can
    assert both what the operator was asked and which way the prompt leaned
    when they just hit return.
    """

    def _answer(*, reply: bool) -> list[tuple[str, bool]]:
        asked: list[tuple[str, bool]] = []

        def _fake(message: str, *, default: bool = False) -> bool:
            asked.append((message, default))
            return reply

        monkeypatch.setattr("bump_version.cli._prompt_yes_no", _fake)
        return asked

    return _answer


@pytest.fixture()
def local_remote(git_repo, tmp_path_factory):
    """Add a bare repo as `origin` and return its path.

    The bare repo lives in its own temp dir, not beside `git_repo`: sibling
    directories under the pytest tmp root are shared between tests, and a
    shared remote lets one test's push satisfy another's assertion.
    """
    bare = tmp_path_factory.mktemp("origin") / "origin.git"
    subprocess.run(["git", "init", "--bare", str(bare)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(git_repo), "remote", "add", "origin", str(bare)],
        check=True,
        capture_output=True,
    )
    return bare


def _tags_in(bare) -> str:
    """List the tags that reached the bare remote."""
    result = subprocess.run(
        ["git", "--git-dir", str(bare), "tag", "-l"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


class TestMaybeSync:
    """Tests for the sync-or-offer-to-sync decision."""

    def test_flag_syncs_without_asking(self, git_repo, bump_args, answer, capsys):
        asked = answer(reply=False)

        _maybe_sync(bump_args(sync=True))

        assert asked == []
        assert "Syncing repository" in capsys.readouterr().out

    def test_non_interactive_neither_asks_nor_syncs(self, git_repo, bump_args, answer, capsys):
        asked = answer(reply=True)

        _maybe_sync(bump_args(yes=True))

        assert asked == []
        assert capsys.readouterr().out.strip() == ""

    def test_interactive_accept_syncs(self, git_repo, bump_args, answer, capsys):
        asked = answer(reply=True)

        _maybe_sync(bump_args(yes=False))

        assert len(asked) == 1
        prompt, default = asked[0]
        assert "sync/pull" in prompt
        # Syncing is opt-in: bare return declines.
        assert default is False
        assert "Syncing repository" in capsys.readouterr().out

    def test_interactive_decline_skips(self, git_repo, bump_args, answer, capsys):
        answer(reply=False)

        _maybe_sync(bump_args(yes=False))

        assert "Syncing repository" not in capsys.readouterr().out


class TestSyncRepo:
    """Tests for the sync itself, against a real local remote."""

    def test_no_remote_warns(self, git_repo, capsys):
        _sync_repo()
        assert "No remote configured" in capsys.readouterr().out

    def test_fetches_tags_and_pulls(self, git_repo, local_remote, capsys):
        subprocess.run(["git", "push", "origin", "HEAD"], check=True, capture_output=True)

        _sync_repo()

        out = capsys.readouterr().out
        assert "Tags fetched successfully" in out
        assert "Branch updated successfully" in out


class TestMaybePush:
    """Tests for the push-or-offer-to-push decision."""

    def test_flag_pushes_without_asking(self, git_repo, local_remote, bump_args, answer):
        asked = answer(reply=False)
        subprocess.run(["git", "tag", "v1.0.0"], check=True, capture_output=True)

        assert _maybe_push(Version(1, 0, 0), bump_args(push=True)) is True
        assert asked == []
        assert "v1.0.0" in _tags_in(local_remote)

    def test_dry_run_never_offers(self, git_repo, bump_args, answer):
        asked = answer(reply=True)

        assert _maybe_push(Version(1, 0, 0), bump_args(yes=False, dry_run=True)) is True
        assert asked == []

    def test_interactive_accept_pushes(self, git_repo, local_remote, bump_args, answer):
        asked = answer(reply=True)
        subprocess.run(["git", "tag", "v1.0.0"], check=True, capture_output=True)

        assert _maybe_push(Version(1, 0, 0), bump_args(yes=False)) is True
        assert "push the tag" in asked[0][0]
        assert "v1.0.0" in _tags_in(local_remote)

    def test_interactive_decline_does_not_push(self, git_repo, local_remote, bump_args, answer):
        answer(reply=False)
        subprocess.run(["git", "tag", "v1.0.0"], check=True, capture_output=True)

        assert _maybe_push(Version(1, 0, 0), bump_args(yes=False)) is True
        assert "v1.0.0" not in _tags_in(local_remote)


class TestPushTag:
    """Tests for the push itself."""

    def test_push_reaches_remote(self, git_repo, local_remote, capsys):
        subprocess.run(["git", "tag", "v1.0.0"], check=True, capture_output=True)

        assert _push_tag("v1.0.0") is True
        assert "Tag pushed successfully" in capsys.readouterr().out
        assert "v1.0.0" in _tags_in(local_remote)

    def test_unknown_tag_reports_failure(self, git_repo, local_remote, capsys):
        assert _push_tag("v9.9.9") is False
        assert "Failed to push tag" in capsys.readouterr().err


class TestConfirmBeforeTagging:
    """Tests for the confirmation between message and `git tag`."""

    def test_decline_aborts_without_tagging(self, git_repo, bump_args, answer, capsys):
        asked = answer(reply=False)
        args = bump_args(yes=False, message="Release note")

        result = _resolve_message_and_create_tag(args, Version(1, 0, 0), None, [])

        assert result == EXIT_DECLINED
        prompt, default = asked[0]
        assert "Create tag 'v1.0.0'" in prompt
        # The operator already chose to bump; bare return confirms.
        assert default is True
        assert "Aborted" in capsys.readouterr().out
        assert _tags_in(git_repo / ".git") == ""

    def test_accept_creates_tag(self, git_repo, bump_args, answer):
        answer(reply=True)
        args = bump_args(yes=False, message="Release note")

        assert _resolve_message_and_create_tag(args, Version(1, 0, 0), None, []) is None
        assert "v1.0.0" in _tags_in(git_repo / ".git")

    def test_confirmation_shows_only_first_line(self, git_repo, bump_args, answer):
        asked = answer(reply=True)
        args = bump_args(yes=False, message="Release v1.0.0\n\nChanges:\n- one\n- two")

        _resolve_message_and_create_tag(args, Version(1, 0, 0), None, [])

        assert "Release v1.0.0" in asked[0][0]
        assert "- one" not in asked[0][0]

    def test_existing_tag_propagates_failure(self, git_repo, bump_args, answer):
        answer(reply=True)
        _create_tag("v1.0.0", "first")
        args = bump_args(yes=False, message="second")

        assert _resolve_message_and_create_tag(args, Version(1, 0, 0), None, []) == 1

    def test_commits_become_the_default_message_body(self, git_repo, bump_args, answer):
        answer(reply=True)
        args = bump_args(yes=True)

        assert _resolve_message_and_create_tag(args, Version(1, 0, 0), None, ["one", "two"]) is None

        message = subprocess.run(
            ["git", "tag", "-l", "--format=%(contents)", "v1.0.0"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "Changes:" in message
        assert "- one" in message


class TestEditorRequestPath:
    """Tests for the branch where the prompt hands off to $EDITOR.

    Exiting the editor is the confirmation, so this path must not ask again.
    """

    @pytest.fixture()
    def editor_choice(self, monkeypatch):
        """Make the message prompt request the editor, and record the handoff."""

        def _choose(*, status: int) -> list[dict]:
            calls: list[dict] = []

            monkeypatch.setattr(
                "bump_version.cli._prompt_message",
                lambda _summary, full: _EditorRequest(full),
            )

            def _fake_editor(tag, default_message, prev_tag=None, *, dry_run=False):
                calls.append(
                    {
                        "tag": tag,
                        "default_message": default_message,
                        "prev_tag": prev_tag,
                        "dry_run": dry_run,
                    }
                )
                return status

            monkeypatch.setattr("bump_version.cli._create_tag_via_editor", _fake_editor)
            return calls

        return _choose

    def test_handoff_carries_prev_tag_and_message(self, git_repo, bump_args, answer, editor_choice):
        asked = answer(reply=False)
        calls = editor_choice(status=EXIT_OK)
        args = bump_args(yes=False)

        result = _resolve_message_and_create_tag(args, Version(1, 0, 0), Version(0, 9, 0), ["one"])

        assert result is None
        assert calls == [
            {
                "tag": "v1.0.0",
                "default_message": "Release v1.0.0\n\nChanges:\n- one",
                "prev_tag": "v0.9.0",
                "dry_run": False,
            }
        ]
        # The editor was the confirmation; no second prompt.
        assert asked == []

    def test_no_prev_tag_when_there_is_no_current_version(
        self, git_repo, bump_args, answer, editor_choice
    ):
        answer(reply=False)
        calls = editor_choice(status=EXIT_OK)

        _resolve_message_and_create_tag(bump_args(yes=False), Version(0, 1, 0), None, [])

        assert calls[0]["prev_tag"] is None
        assert calls[0]["default_message"] == "Release v0.1.0"

    @pytest.mark.parametrize("status", [EXIT_FAILURE, EXIT_DECLINED])
    def test_editor_status_propagates(self, git_repo, bump_args, answer, editor_choice, status):
        answer(reply=False)
        editor_choice(status=status)

        result = _resolve_message_and_create_tag(bump_args(yes=False), Version(1, 0, 0), None, [])

        assert result == status
