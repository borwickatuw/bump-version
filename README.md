# bump-version

A command-line utility for managing semantic version tags in Git repositories.

## Overview

`bump-version` simplifies the process of creating new version tags following [Semantic Versioning](https://semver.org/) (SemVer) conventions. It examines existing tags in your repository to determine the current version, then creates a new tag with the appropriate version bump.

## Installation

### Using uv (recommended)

Run directly without installation:

```bash
uvx --from git+https://github.com/borwickatuw/bump-version bump-version
```

Or clone and run locally:

```bash
git clone https://github.com/borwickatuw/bump-version.git
cd bump-version
uv run bump-version --help
```

### Install globally with uv

```bash
uv tool install git+https://github.com/borwickatuw/bump-version
```

### Install with pip

```bash
pip install git+https://github.com/borwickatuw/bump-version
```

## Usage

```
bump-version [OPTIONS] [COMMAND]
```

If running from the repository directory:

```bash
uv run bump-version [OPTIONS] [COMMAND]
```

### Commands

| Command             | Description                                                       |
| ------------------- | ----------------------------------------------------------------- |
| `major`             | Bump the major version (X.0.0)                                    |
| `minor`             | Bump the minor version (x.Y.0)                                    |
| `patch`             | Bump the patch/point version (x.y.Z)                              |
| `current`           | Show the current version                                          |
| `dynamic-pyproject` | Migrate a static hatchling `pyproject.toml` to git-tag versioning |

### Options

| Option              | Description                                    |
| ------------------- | ---------------------------------------------- |
| `-s, --sync`        | Sync repository and tags before bumping        |
| `-p, --push`        | Push the new tag to remote after creating      |
| `-n, --dry-run`     | Show what would be done without making changes |
| `-m, --message MSG` | Custom message for the tag                     |
| `--prefix PREFIX`   | Version prefix (default: "v", use "" for none) |
| `-y, --yes`         | Skip confirmation prompts                      |
| `-v, --version`     | Show program version                           |
| `-h, --help`        | Show help message                              |

Options other than `-v` may go before or after the command: `bump-version -p patch` and `bump-version patch -p` both push. If you give the same option in both places, the one after the command wins.

_Changed in v2.1.0:_ before this release, an option placed before the command was silently ignored, so `bump-version -p patch` did not push and `bump-version -n patch` was not a dry run. Now it applies.

### Exit statuses

Scripts can tell what happened from the exit status:

| Status | Meaning                                                                                                      |
| ------ | ------------------------------------------------------------------------------------------------------------ |
| `0`    | Success. This includes a genuine no-op, such as a dry run or `dynamic-pyproject` on an already-migrated repo |
| `1`    | Failure, for example not a git repository, no commits since the last tag, or `git tag` or `git push` failed  |
| `2`    | Declined: you said no to the operation itself, so no tag was created and no file was changed                 |
| `130`  | Interrupted: EOF (closed stdin) or Ctrl-C at a prompt or mid-run                                             |

Declining the **operation** is different from declining an **optional step**:

- **Status 2.** You answer no to `Create tag ...?` or to `Continue with migration?`, or you save an empty buffer in `$EDITOR`.
- **Status 0.** You answer no to `sync/pull ... first?`, to `push the tag to remote?`, or to `dynamic-pyproject`'s `Commit the migration now?`. The run skips that step and still finishes its work.

A non-zero exit from `$EDITOR` counts as a failure (`1`), the same as in git, because a crash and a deliberate abort such as Vim's `:cq` both show up only as a non-zero exit. A command-line usage error also exits `2`, because that is argparse's convention. Either way, a `2` means nothing was changed.

An interruption stops at the point where it arrives. If you press Ctrl-C at the push prompt, the tag was already created locally and stays. If you interrupt `dynamic-pyproject` at its commit prompt, the rewritten files stay uncommitted.

While `$EDITOR` is open for the tag message, Ctrl-C belongs to the editor, as it does in git. bump-version ignores it until the editor exits, and then the usual rules apply: a saved message creates the tag, an empty buffer exits `2`, and an editor that exits non-zero exits `1`. An editor such as Vim treats Ctrl-C as a keystroke, so your edit carries on. If the editor is killed by Ctrl-C (or Ctrl-\\), the run stops with `130` and no tag, and `.git/TAG_EDITMSG` keeps what was in the buffer.

_Changed in v2.1.0:_ before this release, Ctrl-C while the editor was open stopped bump-version with `130` and killed the editor, even one that ignores Ctrl-C, so the edit was lost.

_Changed in v2.1.0:_ before this release, the exit statuses were:

- Declining the create-tag or migration prompt exited `0`.
- Ctrl-C at the bump-type prompt exited `0`.
- An emptied editor buffer exited `1`.
- EOF or Ctrl-C at the other prompts counted as "no".

A script that treated `0` as "bumped" was therefore already wrong on those paths. Now each case has its own status.

### Color output

Messages are colored only when the stream they go to is a terminal. Set [`NO_COLOR`](https://no-color.org) to any non-empty value to turn color off even on a terminal. Color never carries meaning on its own: every colored line also says its message in words.

## Examples

### Interactive Mode

Running without arguments will prompt you for the bump type:

```bash
$ uv run bump-version

Would you like to sync/pull the repository and tags first? [y/N]: y
Syncing repository...
Fetching tags from origin...
Tags fetched successfully

Current version: v1.2.3

What type of version bump would you like to make?
  1) major - Breaking changes (X.0.0)
  2) minor - New features, backwards compatible (x.Y.0)
  3) patch - Bug fixes, backwards compatible (x.y.Z)

Enter choice [1-3]: 3

Bump type: patch
Version change: v1.2.3 -> v1.2.4

Create tag 'v1.2.4' with message 'Release v1.2.4'? [Y/n]: y
Creating tag 'v1.2.4'...
Tag 'v1.2.4' created successfully

Would you like to push the tag to remote? [y/N]: y
Pushing tag 'v1.2.4' to origin...
Tag pushed successfully

Done!
New version: v1.2.4
```

### Direct Commands

```bash
# Bump patch version
uv run bump-version patch

# Bump minor version with sync first
uv run bump-version minor --sync

# Bump major version and push automatically
uv run bump-version major --push

# Bump with all options, no prompts
uv run bump-version patch --sync --push --yes

# See current version
uv run bump-version current

# Dry run to see what would happen
uv run bump-version minor --dry-run

# Custom tag message
uv run bump-version patch -m "Hotfix for login issue"

# Use tags without 'v' prefix (e.g., 1.2.3 instead of v1.2.3)
uv run bump-version patch --prefix ""
```

## Semantic Versioning

This tool follows [Semantic Versioning 2.0.0](https://semver.org/):

- **MAJOR** version when you make incompatible API changes
- **MINOR** version when you add functionality in a backwards compatible manner
- **PATCH** version when you make backwards compatible bug fixes

## How It Works

1. **Tag Discovery**: Scans existing Git tags for semantic version patterns (e.g., `v1.2.3` or `1.2.3`)
1. **Version Parsing**: Extracts the highest version number from existing tags
1. **Static Version Guard**: Refuses to bump if `pyproject.toml` pins a static `[project] version` — tagging would leave the tree claiming the old version. Run `bump-version dynamic-pyproject` to migrate to git-tag versioning, or set `allow-static-version = true` under `[tool.bump-version]` to opt out (see [Integrating with Python Projects](#integrating-with-python-projects))
1. **Version Calculation**: Increments the appropriate component based on bump type
1. **Tag Creation**: Creates an annotated Git tag with the new version
1. **Optional Push**: Pushes the new tag to the remote repository

### Note on Tag Pushing

When you push a tag (via `--push` or the interactive prompt), `bump-version` runs `git push origin <tag>`. This pushes the tag and the commit it points to, but **does not update your branch on the remote**.

After pushing a tag, you may still see "Your branch is ahead of origin/main by X commits" because the branch reference wasn't pushed—only the tag was. The commits exist on the remote and are accessible via the tag, but if you want your branch to reflect those commits on the remote, you'll need to run `git push` separately.

## Integrating with Python Projects

Rather than maintaining version strings in multiple places (git tags, `pyproject.toml`, `__init__.py`), you can configure your Python project to derive its version directly from git tags. This keeps the git tag as the single source of truth.

In fact, `bump-version` **refuses to tag** a repo whose `pyproject.toml` pins a static `[project] version`, because the tag would immediately disagree with the tree. You have two ways forward:

### Migrating with `bump-version dynamic-pyproject`

For hatchling-backed projects, the migration is automated:

```bash
bump-version dynamic-pyproject
```

This one-time command:

- Replaces the static `version = "..."` in `[project]` with `dynamic = ["version"]`
- Adds `hatch-vcs` to `[build-system] requires` and appends `[tool.hatch.version] source = "vcs"`
- Writes `.git_archival.txt` and a `.gitattributes` `export-subst` rule so source tarballs (e.g. GitHub "Download ZIP") still resolve a version without a `.git` directory
- Warns if the static version disagrees with your latest tag (built versions become tag-derived), and about hardcoded `__version__` strings in your code (left unchanged)
- Offers to commit the three changed files

All edits are validated by re-parsing before anything is written; `-n/--dry-run` shows the diff without changing anything. After migrating, run `uv sync --reinstall` for editable installs so the environment picks up the tag-derived version.

Undoing it is always a git operation, because the command refuses to start while any of those three files has uncommitted changes — so the pre-migration state is whatever your last commit holds. If you accepted the commit offer, `git revert` that commit. If you did not, restore `pyproject.toml` and `.gitattributes` from `HEAD` and remove `.git_archival.txt` if the command created it.

### Keeping a static version anyway

If your repo intentionally maintains a static version, declare that once in `pyproject.toml`:

```toml
[tool.bump-version]
allow-static-version = true
```

### Using hatch-vcs

If your project uses [hatchling](https://hatch.pypa.io/) as its build backend, add [hatch-vcs](https://github.com/ofek/hatch-vcs) to automatically read versions from git tags (this is what `dynamic-pyproject` sets up):

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "your-package"
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"
```

Now when you run `bump-version` to create a new tag, your package will automatically use that version when built—no need to edit any files.

### Using setuptools-scm

For projects using setuptools, [setuptools-scm](https://github.com/pypa/setuptools-scm) provides similar functionality:

```toml
[build-system]
requires = ["setuptools>=64", "setuptools-scm>=8"]
build-backend = "setuptools.build_meta"

[project]
dynamic = ["version"]

[tool.setuptools_scm]
```

## Requirements

- Python — the floor is `requires-python` in `pyproject.toml`
- Git
- A Git repository with (or without) existing version tags

## Development

[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) is the map of the code — its components, the tag-to-tag flow, and the exit-status and stream conventions — and is the place to start before changing it.

```bash
# Clone the repository
git clone https://github.com/borwickatuw/bump-version.git
cd bump-version

# Install development dependencies
uv sync --group dev

# Run tests
uv run pytest

# Run linting
uv run ruff check src/
```

## Starting Fresh

If your repository has no existing version tags, `bump-version` will start from scratch:

- `bump-version major` → v1.0.0
- `bump-version minor` → v0.1.0
- `bump-version patch` → v0.0.1

## License

BSD 3-Clause License - see [LICENSE](LICENSE) for details.
