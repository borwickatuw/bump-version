"""The exit-status contract, driven end to end through main().

README.md's "Exit statuses" section is the public contract these pin: 0 for
success (a genuine no-op and a declined *optional* step included), 1 for
failure, 2 when the operator declines the operation itself, 130 when EOF or
Ctrl-C lands at a prompt or mid-run. Each test scripts the operator's answers
through `input()`; running out of answers raises EOFError, exactly as closed
stdin does.
"""

import subprocess
from collections.abc import Callable

import pytest

from bump_version.cli import main
from bump_version.exit_status import EXIT_DECLINED, EXIT_FAILURE, EXIT_INTERRUPTED, EXIT_OK
from bump_version.git import _create_tag


@pytest.fixture()
def operator(monkeypatch) -> Callable[..., list[str]]:
    """Script the answers typed at successive prompts.

    An answer may be an exception class, raised at that prompt (Ctrl-C is
    KeyboardInterrupt). Once the script runs out, input() raises EOFError, as
    it does when stdin is closed. Returns the list of prompts shown.
    """

    def _script(*answers: str | type[BaseException]) -> list[str]:
        remaining = list(answers)
        shown: list[str] = []

        def _input(prompt: str = "") -> str:
            shown.append(prompt)
            if not remaining:
                raise EOFError
            answer = remaining.pop(0)
            if isinstance(answer, type):
                raise answer
            return answer

        monkeypatch.setattr("builtins.input", _input)
        # The summary edit reads through readline's prefill; route it to the
        # same script.
        monkeypatch.setattr(
            "bump_version.prompts._input_with_prefill", lambda prompt, _prefill: _input(prompt)
        )
        return shown

    return _script


def _run(argv: list[str]) -> int:
    """Run main() and return the status it exits with."""
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    return exc_info.value.code


def _tags() -> str:
    return subprocess.run(
        ["git", "tag", "-l"], capture_output=True, text=True, check=True
    ).stdout.strip()


def _porcelain() -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout.strip()


def test_statuses_are_the_documented_values():
    """README.md documents these numbers; scripts compare against them."""
    assert (EXIT_OK, EXIT_FAILURE, EXIT_DECLINED, EXIT_INTERRUPTED) == (0, 1, 2, 130)


class TestBumpDeclines:
    """Declining the operation itself exits 2 and leaves no tag."""

    def test_decline_create_tag_prompt(self, git_repo, operator, capsys):
        # sync? no / message: default / create tag? no
        operator("n", "1", "n")

        assert _run(["patch"]) == EXIT_DECLINED
        assert "Aborted; no tag created" in capsys.readouterr().out
        assert _tags() == ""

    def test_empty_editor_buffer_declines(self, git_repo, operator, monkeypatch, tmp_path_factory):
        editor = tmp_path_factory.mktemp("bin") / "empty-editor"
        editor.write_text('#!/bin/sh\n: > "$1"\n')
        editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(editor))
        # sync? no / message: edit in $EDITOR
        operator("n", "3")

        assert _run(["patch"]) == EXIT_DECLINED
        assert _tags() == ""

    def test_failing_editor_is_a_failure(self, git_repo, operator, monkeypatch, tmp_path_factory):
        editor = tmp_path_factory.mktemp("bin") / "failing-editor"
        editor.write_text("#!/bin/sh\nexit 1\n")
        editor.chmod(0o755)
        monkeypatch.setenv("EDITOR", str(editor))
        operator("n", "3")

        assert _run(["patch"]) == EXIT_FAILURE
        assert _tags() == ""


class TestOptionalStepsStaySuccess:
    """Saying no to sync or push declines a step, not the bump: exit 0."""

    def test_decline_sync_and_push_still_bumps(self, git_repo, operator, capsys):
        # sync? no / message: default / create tag? yes / push? no
        shown = operator("n", "1", "y", "n")

        assert _run(["patch"]) == EXIT_OK
        assert _tags() == "v0.0.1"
        assert any("push the tag" in prompt for prompt in shown)
        assert "Done!" in capsys.readouterr().out


class TestInterrupts:
    """EOF or Ctrl-C at any prompt exits 130 cleanly, never as a decline."""

    @pytest.mark.usefixtures("git_repo")
    @pytest.mark.parametrize("interrupt", [EOFError, KeyboardInterrupt])
    @pytest.mark.parametrize(
        "case",
        [
            pytest.param((["patch"], []), id="sync-prompt"),
            pytest.param(([], ["n"]), id="bump-type-prompt"),
            pytest.param((["patch"], ["n"]), id="message-prompt"),
            pytest.param((["patch"], ["n", "2"]), id="summary-edit"),
            pytest.param((["patch"], ["n", "1"]), id="create-tag-prompt"),
        ],
    )
    def test_interrupt_before_tagging_exits_130_without_a_tag(
        self, operator, capsys, interrupt, case
    ):
        argv, answers = case
        operator(*answers, interrupt)

        assert _run(argv) == EXIT_INTERRUPTED
        assert "Interrupted" in capsys.readouterr().out
        # Before, an interrupt at the message prompts fell back to the default
        # message and went on to tag.
        assert _tags() == ""

    def test_interrupt_at_push_prompt_keeps_the_created_tag(self, git_repo, operator):
        operator("n", "1", "y", KeyboardInterrupt)

        assert _run(["patch"]) == EXIT_INTERRUPTED
        assert _tags() == "v0.0.1"

    def test_interrupt_outside_a_prompt(self, git_repo, monkeypatch, capsys):
        """Ctrl-C during git work (here, the sync) is caught at the boundary too."""

        def _interrupted_sync():
            raise KeyboardInterrupt

        monkeypatch.setattr("bump_version.cli._sync_repo", _interrupted_sync)

        assert _run(["patch", "--sync", "-y"]) == EXIT_INTERRUPTED
        assert "Interrupted" in capsys.readouterr().out


class TestDynamicPyproject:
    """The migration's prompts follow the same contract."""

    def test_decline_migration_exits_2_untouched(self, write_pyproject, operator, capsys):
        write_pyproject()  # static 1.2.3, no tags: drift, so it asks
        operator("n")

        assert _run(["dynamic-pyproject"]) == EXIT_DECLINED
        assert "left unmodified" in capsys.readouterr().out
        assert _porcelain() == ""

    def test_interrupt_at_migration_prompt_exits_130_untouched(self, write_pyproject, operator):
        write_pyproject()
        operator()  # EOF at the first prompt

        assert _run(["dynamic-pyproject"]) == EXIT_INTERRUPTED
        assert _porcelain() == ""

    def test_decline_commit_is_an_optional_step(self, write_pyproject, operator):
        write_pyproject()
        _create_tag("v1.2.3", "Release v1.2.3")  # no drift: only the commit prompt
        operator("n")

        assert _run(["dynamic-pyproject"]) == EXIT_OK
        # Migrated but left for the operator to review and commit.
        assert "pyproject.toml" in _porcelain()

    def test_already_dynamic_is_a_no_op_success(self, write_pyproject):
        write_pyproject(
            '[project]\nname = "example"\ndynamic = ["version"]\n\n'
            '[build-system]\nrequires = ["hatchling", "hatch-vcs"]\n'
            'build-backend = "hatchling.build"\n'
        )

        assert _run(["dynamic-pyproject"]) == EXIT_OK
