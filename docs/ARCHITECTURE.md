# Architecture

The high-level map: why bump-version exists, what its parts are, and how one
run gets from the tags already in a repository to a new annotated tag. Read
this before changing anything under `src/bump_version/`. The user-facing surface
(commands, options, examples) is [README.md](../README.md); why things are the
way they are is [DECISIONS.md](DECISIONS.md). This file points at both rather
than restating them.

## Purpose

bump-version turns "cut a release" into one command: find the highest
semantic-version tag, show what changed since it, choose major/minor/patch,
write a message, create an **annotated** tag, and optionally push **only that
tag** ([DECISIONS.md](DECISIONS.md) 002). The git tag is meant to be the single
source of truth for a project's version, so the tool refuses to tag a Python
repo whose `pyproject.toml` still pins a static version
([DECISIONS.md](DECISIONS.md) 003) and ships a one-time migration,
`dynamic-pyproject`, that moves a hatchling project to tag-derived versions.

It is a public CLI installed with `uvx`/`pip` onto arbitrary hosts, which sets
two hard constraints every part below respects: **zero runtime dependencies**
(stdlib only, `argparse` by decision — [DECISIONS.md](DECISIONS.md) 004) and
**git is driven as a subprocess**, never through a library.

## Components

The tool is the `src/bump_version/` package, one module per component below.
Each heading names its module (`output` is `src/bump_version/output.py`, and
so on), and each module's docstring repeats what it holds and what it may
import. The package was a single `cli.py` until
[DECISIONS.md](DECISIONS.md) 006 split it along these seams.
`src/bump_version/__init__.py` only resolves `__version__` from installed
package metadata. The entry point `bump_version.cli:main` (`pyproject.toml`
`[project.scripts]`) lives in `cli`, and it must stay there.

### Output (`output`)

Everything the user sees goes through here. `Color` holds the ANSI codes and
decides per stream whether to use them (`Color.enabled(stream)`: that stream
is a tty and `NO_COLOR` is unset or empty); `_emit` writes one message to one
stream, testing the tty status of *that* stream. `_print_info` (blue), `_print_success` (green) and
`_print_warning` (yellow) write to stdout; `_print_error` (red) writes to
stderr. A non-empty `NO_COLOR` turns color off even on a terminal (an empty
one does not), per no-color.org. Color never carries meaning alone — every
line says its status in words. Plain `print()` is still used directly for menus, commit listings and
the `current` result.

### Exit statuses (`exit_status`)

`EXIT_OK`, `EXIT_FAILURE`, `EXIT_DECLINED` and `EXIT_INTERRUPTED`: the CLI's
exit-status contract, named at every exit site rather than written as bare
integers. They have a module of their own because the modules that name a
status (`prompts`, `pyproject`, `dynamic_pyproject`, `cli`) sit at different
layers, and a home that imports nothing can be imported from any of them.
What each status means is under
[Exit statuses and streams](#exit-statuses-and-streams) below.

### Git shell-out (`git`)

`_run_git(*args, check=, capture=)` is the one place `git` is invoked: an
argument list (never a shell string), output captured, and decoded as
**UTF-8 by decision** rather than the host locale, so non-ASCII tag messages
and commit subjects survive `LANG=C`. Built on it:

- repository queries — `_is_git_repo`, `_get_git_dir` (absolute git dir, so
  worktrees resolve), `_get_git_root`, `_get_remotes`, `_get_default_remote`
  (the **first** configured remote, not necessarily `origin`),
  `_get_current_branch` (`None` on detached HEAD), `_get_commits_since_tag`
  (commit subjects, `tag..HEAD` or the whole history);
- repository actions — `_sync_repo` (fetch tags, then pull the current branch
  from the default remote; failures are warnings, not errors), `_create_tag`
  (`git tag -a TAG -m MSG`) and `_push_tag` (`git push REMOTE TAG`). Both write
  actions honor `dry_run` by printing `[DRY RUN]` lines instead.

### Version model (`version`)

`BumpType` (major/minor/patch — its values are exactly the bump subcommand
names) and `Version` (a dataclass that renders itself as the tag string and
returns a new `Version` from `bump()`). `_parse_version(tag, prefix)` strips
the prefix and matches a leading `N.N.N`; `_get_version_tags(prefix)` lists
tags with a `git tag -l` glob and sorts them numerically;
`_get_current_version(prefix)` is the highest of them, or `None` for an
untagged repo. This is the one component with no user interaction.

### Prompting and the editor (`prompts`)

The interactive layer. `_prompt_yes_no` and `_prompt_bump_type` are the plain
numbered-menu prompts ([DECISIONS.md](DECISIONS.md) 001: text prompts, not
arrow-key selection). `_prompt_message` shows the default tag message and
offers to use it, edit the summary line (`_edit_summary`, which pre-fills the
line through `readline` via `_input_with_prefill`), or compose in `$EDITOR`.
The editor choice returns an `_EditorRequest` rather than a string, and
`_create_tag_via_editor` owns the rest: it seeds `<git-dir>/TAG_EDITMSG` with
the default message and, when there is a previous tag, a `git commit -v`-style
**scissors line** (`_SCISSORS_LINE`) followed by `git diff PREV..HEAD`
(`_build_editor_seed`); runs the editor; strips everything from the scissors
line down plus `#` lines (`_strip_editor_content`); aborts on an empty result;
and creates the tag from a temp file with `git tag -a -F … --cleanup=verbatim`.
Its docstring records why the tool owns this loop instead of using
`git tag -e`. `_get_editor` resolves `$EDITOR`, then `$VISUAL`, then `vi`.

The editor runs inside `_editor_signals_ignored`, which is git's `editor.c`
behaviour. SIGINT, and SIGQUIT where the platform has it, are ignored in
bump-version from just before the editor starts until it exits, and the
previous handlers come back in a `finally`. The editor itself starts with
its original handlers (restored in the child through `preexec_fn`), so the
editor decides what Ctrl-C means. If the editor dies of SIGINT or SIGQUIT,
`_create_tag_via_editor` raises `KeyboardInterrupt`, as git re-raises the
signal on itself. The guard wraps the editor call and nothing else. It never
wraps a prompt.

### The static-version guard (`pyproject`)

`_read_pyproject` parses `pyproject.toml` at the git root (absent → `None`).
`_parse_pyproject` is the one parse-or-exit rule for the file, and the
migration uses it too: an unparseable file exits 1 with the same message
either way. `_check_pyproject_version` refuses the bump when
`[project] version` is static and not listed in `dynamic`, unless
`[tool.bump-version] allow-static-version = true`; a non-boolean value there is
itself an error. The refusal message names both ways forward. Rationale:
[DECISIONS.md](DECISIONS.md) 003.

### The dynamic-pyproject migration (`dynamic_pyproject`)

`_cmd_dynamic_pyproject`, the command handler that drives the migration, lives
here rather than in `cli`. It calls this module's own steps in order and
nothing from `cli`, so keeping it here keeps the whole migration in one file.
The module also holds the `_dynpp_*` family and the constants it writes
(`_GIT_ARCHIVAL_CONTENT`, `_GITATTRIBUTES_BLOCK`, `_MIGRATION_FILES`). It rewrites `pyproject.toml` as
**surgical text edits validated by re-parsing**, because the stdlib has no
TOML writer ([DECISIONS.md](DECISIONS.md) 003, Consequences). In order:
`_dynpp_preconditions` (file present and parseable, hatchling backend, a static
version to convert, every file `_MIGRATION_FILES` names clean in git),
`_dynpp_check_drift` (warn and confirm when the static version disagrees with
the latest tag), `_dynpp_rewrite` (`_dynpp_convert_version`,
`_dynpp_add_hatch_vcs`, append `[tool.hatch.version]`, then `_dynpp_validate`),
and only then any write: `pyproject.toml`, `_dynpp_write_archival_files`,
`_dynpp_warn_hardcoded_versions` (warns, never rewrites), and
`_dynpp_offer_commit` (a pathspec-limited commit of just those files). Every
refusal before the write goes through `_dynpp_abort` or an explicit exit, so a
failed run leaves the tree untouched. It reads `pyproject.toml` itself rather
than through `_read_pyproject`, because it needs the raw text to edit, and it
parses that text through `pyproject`'s `_parse_pyproject`.

### Command dispatch and the bump flow (`cli`)

`_create_parser` builds the `argparse` tree. `main` parses, refuses outside a
git repository, and hands the parsed arguments to `_dispatch`, which routes
them: `current` → `_cmd_current`, `dynamic-pyproject` →
`_cmd_dynamic_pyproject` (in `dynamic_pyproject`), and anything else →
`_cmd_bump` with the subcommand converted to a `BumpType` (no subcommand
means interactive, `None`). `main` is also the one place an interrupt becomes
an exit status (see [below](#exit-statuses-and-streams)). `_cmd_bump` is the
release flow below, decomposed into `_maybe_sync`,
`_show_changes_since_version`, `_resolve_message_and_create_tag` (with
`_resolve_tag_message` choosing the message source) and `_maybe_push`.

### How the components depend on each other

Imports run one way, so there are no import cycles. A module imports only
from the modules its row names:

| Module              | Imports from                                                                                               |
| ------------------- | ---------------------------------------------------------------------------------------------------------- |
| `output`            | nothing                                                                                                    |
| `exit_status`       | nothing                                                                                                    |
| `git`               | `output`                                                                                                   |
| `version`           | `git` (the tag listing)                                                                                    |
| `prompts`           | `output`, `exit_status`, `git` (git dir, seed diff, tag creation), `version` (`BumpType`)                  |
| `pyproject`         | `output`, `exit_status`, `git` (git root)                                                                  |
| `dynamic_pyproject` | `output`, `exit_status`, `git`, `version` (drift check), `prompts` (`_prompt_yes_no`), `pyproject` (parse) |
| `cli`               | all of the above, plus `__version__` from the package                                                      |

Re-derive the real edges with `grep -n '^from bump_version' src/bump_version/*.py`.
A new import that is not in its module's row either belongs in the table, if
it keeps the graph one-way, or means the code is in the wrong module.

## Data flow: from the current tag to a new one

`bump-version [major|minor|patch] [options]`, through `_cmd_bump`:

1. **Parse and route** (`main`, then `_dispatch`). Not a git repository →
   exit 1 before anything else runs.
1. **Sync, maybe** (`_maybe_sync`). `--sync` runs `_sync_repo`; without it, an
   interactive run (no `--yes`) asks first. Sync is not skipped by
   `--dry-run`.
1. **Static-version guard** (`_check_pyproject_version`). A static
   `pyproject.toml` version stops the run here, before any tag is read.
1. **Discover the current tag** (`_get_current_version` with `--prefix`). The
   highest `PREFIX N.N.N` tag, or none.
1. **Show what changed** (`_show_changes_since_version`). Commit subjects since
   that tag (or the start of history, of which only the first few are shown).
   A tagged repo with **no new commits** stops here: exit 1, nothing to bump.
1. **Choose the bump.** From the subcommand, else `_prompt_bump_type`. The new
   version is `current.bump(type)`, or `0.0.0` bumped when there is no tag
   (README `## Starting Fresh`).
1. **Compose the message** (`_resolve_message_and_create_tag`). The default is
   `Release <tag>` plus a `Changes:` list of those subjects. Its source is
   `-m` if given, else the default under `--yes`, else `_prompt_message`.
1. **Create the annotated tag.** Two paths:
   - *direct* — confirm (skipped under `--yes` or `--dry-run`; answering no
     exits 2), then `_create_tag`;
   - *editor* — `_create_tag_via_editor`; saving the editor is the
     confirmation. An emptied message aborts with exit 2, a failing editor
     with exit 1.
1. **Push, maybe** (`_maybe_push`). `--push` pushes the one tag to the first
   remote; otherwise an interactive, non-dry run asks. Branches are never
   pushed ([DECISIONS.md](DECISIONS.md) 002).
1. **Report.** `Done!` and the new version.

`current` is steps 1 and 4 only, printing the tag. `dynamic-pyproject` does not
touch tags beyond the drift check; its flow is the ordered steps in its
component section above.

## Data structures

Small repo, so these live here rather than in `docs/data-structures/`
(DOCS Practice 2).

**`Version`** (`version`) — a dataclass of `major`, `minor`, `patch` (ints)
and `prefix` (default `"v"`, `""` allowed). `str(version)` *is* the tag name,
so the same object is the parsed current tag, the computed new tag, the
`prev_tag` handed to the editor seed, and the range start for
`git log`/`git diff`. `bump()` returns a new instance and resets the lower
components. Anything after `N.N.N` in a tag (a pre-release suffix) is ignored
by `_parse_version`, so such tags sort with their base version.

**`BumpType`** (`version`) — an enum whose values are the strings
`"major"`, `"minor"`, `"patch"`. That equality is load-bearing: `_dispatch` turns
the subcommand name into a `BumpType` with `BumpType(args.command)`, so a new
bump subcommand and a new enum member must arrive together.

**The `argparse.Namespace`** (`cli`) — the only configuration object; there is
no config file of the tool's own and no environment variable beyond the
editor ones. Fields the handlers read:

| Field     | Set by           | Read by                                                                                |
| --------- | ---------------- | -------------------------------------------------------------------------------------- |
| `command` | subparser `dest` | `_dispatch` (routing); `None` means interactive bump                                   |
| `prefix`  | `--prefix`       | `_cmd_current`, `_cmd_bump`, `_dynpp_check_drift`                                      |
| `yes`     | `-y/--yes`       | `_maybe_sync`, `_resolve_tag_message`, confirmations, `_maybe_push`, migration prompts |
| `dry_run` | `-n/--dry-run`   | tag creation, editor path, push, migration (diff instead of write)                     |
| `sync`    | `-s/--sync`      | `_maybe_sync`                                                                          |
| `push`    | `-p/--push`      | `_maybe_push`                                                                          |
| `message` | `-m/--message`   | `_resolve_tag_message`                                                                 |

The shared options are declared on the top-level parser and again on each of
`major`/`minor`/`patch`/`current`, from one helper (`_add_bump_options`);
`dynamic-pyproject` declares only `--dry-run`, `--yes` and `--prefix`, though
its Namespace still carries the other fields at their top-level defaults.
argparse copies a subparser's whole namespace over the top-level one, so the
subparsers are built with `argument_default=argparse.SUPPRESS`: they write
only what was typed after the subcommand, and every default is set once, on
the top-level parser, from `_SHARED_DEFAULTS`. So an option works **before or
after** the subcommand (`bump-version -p patch` and `bump-version patch -p`
both push), and typed in both places the one after the subcommand wins. A
subparser option given its own `default=` would bring back the bug this
prevents: it would silently overwrite the value typed before the subcommand.

**`_EditorRequest`** (`prompts`) — a frozen dataclass holding
`default_message`. It is a sentinel, not a message: `_prompt_message` returns
either the final message `str` or this, and `_resolve_message_and_create_tag`
branches on `isinstance` to take the editor path. The default message itself is
a plain string: `Release <tag>`, then a blank line and a `Changes:` list of
commit subjects when there are any.

**The parsed `pyproject.toml`** (`pyproject`, `dynamic_pyproject`) — the plain
`dict` `tomllib` returns; no schema object wraps it. The keys that matter:
`project.version` and `project.dynamic` (the guard and the migration),
`tool.bump-version.allow-static-version` (the guard's opt-out; must be a
boolean), `build-system.build-backend` (must be `hatchling.build` to migrate),
and after migration `build-system.requires` containing `hatch-vcs` and
`tool.hatch.version.source == "vcs"` (what `_dynpp_validate` asserts). Each
lookup is type-checked as it goes, because the file is user-authored.

**Return conventions.** Git helpers return `subprocess.CompletedProcess[str]`
from `_run_git` and are called with `check=False` wherever failure is a normal
outcome, so callers branch on `returncode`. `_create_tag` and `_push_tag`
return `bool` (success); `_create_tag_via_editor` returns an exit status,
because its outcomes include a decline (an emptied buffer) as well as failure. `_resolve_message_and_create_tag` returns `int | None`: an
exit status to stop with, or `None` to carry on to the push.

## Exit statuses and streams

README's "Exit statuses" section is the user-facing contract; this is how the code
keeps it.

- **stdout** carries information, success, warnings, prompts, menus and
  listings. **stderr** carries only `_print_error` output. Color is decided
  per stream, and `NO_COLOR` turns it off everywhere, so a redirected stream
  is always plain text.
- **`EXIT_OK` (0)**: success. That includes a genuine no-op (`dynamic-pyproject`
  on an already-dynamic project, dry runs) and a declined **optional step**:
  answering no to sync, to push, or to committing the migration. The work the
  run was for still happened, so declining the extra step is not a decline of
  the run.
- **`EXIT_FAILURE` (1)**: something went wrong. Not a git repository, the
  static-version refusal, an unparseable `pyproject.toml`, no commits since
  the current tag, tag creation or push failing, the editor exiting non-zero
  or not being found, every migration precondition or validation failure,
  staging or committing the migration failing, and `current` finding no tags.
- **`EXIT_DECLINED` (2)**: the operator declined **the operation** and nothing
  was changed. That is answering no to "Create tag …?" or to "Continue with
  migration?", or saving the `$EDITOR` buffer empty. `argparse`'s own usage
  errors also exit 2. The two share the meaning "nothing was changed".
- **`EXIT_INTERRUPTED` (130)**: end-of-input or Ctrl-C, at a prompt or
  anywhere else (during `git fetch` or `git push`, for example). The prompt
  helpers do not catch `EOFError` or `KeyboardInterrupt`. Both propagate to
  the single `try` in `main` around `_dispatch`, which prints `Interrupted` and
  exits 130. An interrupt is never read as "no" or as "use the default".
  While `$EDITOR` runs, bump-version ignores Ctrl-C and leaves it to the
  editor. The run becomes an interrupt only if the editor dies of the signal,
  and then `_create_tag_via_editor` raises `KeyboardInterrupt` into the same
  `try`.

Helpers that refuse (the guard, the migration's preconditions and aborts, the
no-commits check) exit directly with `sys.exit(EXIT_…)` rather than returning a
status up the stack. Otherwise the command handlers return the status `main`
exits with.

## Areas: before you change one

The components above are also the areas a change lands in. What to know first
(ADR numbers are [DECISIONS.md](DECISIONS.md) entries):

- **Output.** Keep the tty test on the stream being written to (`_emit`'s
  docstring says why), and keep every colored line meaningful in words alone.
  Errors belong on stderr via `_print_error`; nothing else does. Keep
  `NO_COLOR` honoured in `Color.enabled`.
- **Git shell-out.** New git calls go through `_run_git`, never a bare
  `subprocess` call and never `shell=True`; keep the explicit UTF-8 decoding.
  Decide per call whether failure is an error (`check=True`) or an outcome to
  branch on (`check=False`). Push stays tag-only (ADR 002).
- **Version model.** Tag discovery is a `git tag -l` glob plus a regex; a change
  to what counts as a version tag touches both, and the `--prefix` handling in
  each.
- **Prompting and the editor.** Menus stay plain numbered text (ADR 001). A
  prompt never catches end-of-input or Ctrl-C: it lets them propagate to
  `main`, which exits `EXIT_INTERRUPTED`. Only the editor call runs with
  Ctrl-C ignored (`_editor_signals_ignored`). Keep it that narrow. The editor loop's
  recovery contract — `TAG_EDITMSG` left in place on abort, a separate temp
  file for the cleaned message — is described in `_create_tag_via_editor`'s
  docstring and exercised with a real repository in `tests/test_editor_tag.py`.
- **Static-version guard.** The opt-out is a config key, deliberately not a
  flag (ADR 003). `current` never runs the guard.
- **dynamic-pyproject migration.** Every refusal must happen before the first
  write, and every rewrite must pass `_dynpp_validate`; an edit the text
  helpers cannot make safely aborts with a "do it manually" message rather than
  guessing.
- **Dispatch and the bump flow.** The public entry point
  `bump_version.cli:main` must not move, and the interrupt handling stays the
  one `try` around `_dispatch`. The flow's order matters: sync runs
  before the guard and the tag read, so both see the freshly pulled tree and
  tags.

Tests are grouped by concern rather than one file per module; to find the
tests for a function, `grep -ln '<function name>' tests/`. A test imports each
name from the module that owns it. It patches a name in the module that
looks the name up at call time, which is not always the module that defines
it. `cli` calls `_prompt_yes_no`, so a test of the bump flow patches
`bump_version.cli._prompt_yes_no`. `_edit_summary` calls
`_input_with_prefill` from within `prompts`, so its tests patch
`bump_version.prompts._input_with_prefill`. `tests/conftest.py`
holds the shared fixtures — a real throwaway git repository, a `pyproject.toml`
writer, and a `Namespace` builder (`bump_args`) with the fields in the table
above, defaulting to the non-interactive `yes=True`.
