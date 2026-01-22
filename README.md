# bump-version

A command-line utility for managing semantic version tags in Git repositories.

## Overview

`bump-version` simplifies the process of creating new version tags following [Semantic Versioning](https://semver.org/) (SemVer) conventions. It examines existing tags in your repository to determine the current version, then creates a new tag with the appropriate version bump.

## Installation

### Using uv (recommended)

Run directly without installation:

```bash
uvx --from git+https://github.com/yourusername/bump-version bump-version
```

Or clone and run locally:

```bash
git clone https://github.com/yourusername/bump-version.git
cd bump-version
uv run bump-version --help
```

### Install globally with uv

```bash
uv tool install git+https://github.com/yourusername/bump-version
```

### Install with pip

```bash
pip install git+https://github.com/yourusername/bump-version
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

| Command   | Description                              |
|-----------|------------------------------------------|
| `major`   | Bump the major version (X.0.0)           |
| `minor`   | Bump the minor version (x.Y.0)           |
| `patch`   | Bump the patch/point version (x.y.Z)     |
| `current` | Show the current version                 |

### Options

| Option              | Description                                      |
|---------------------|--------------------------------------------------|
| `-s, --sync`        | Sync repository and tags before bumping          |
| `-p, --push`        | Push the new tag to remote after creating        |
| `-n, --dry-run`     | Show what would be done without making changes   |
| `-m, --message MSG` | Custom message for the tag                       |
| `--prefix PREFIX`   | Version prefix (default: "v", use "" for none)   |
| `-y, --yes`         | Skip confirmation prompts                        |
| `-v, --version`     | Show program version                             |
| `-h, --help`        | Show help message                                |

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

Create tag 'v1.2.4' with message 'Release v1.2.4'? [y/N]: y
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
2. **Version Parsing**: Extracts the highest version number from existing tags
3. **Version Calculation**: Increments the appropriate component based on bump type
4. **Tag Creation**: Creates an annotated Git tag with the new version
5. **Optional Push**: Pushes the new tag to the remote repository

## Requirements

- Python 3.9+
- Git
- A Git repository with (or without) existing version tags

## Development

```bash
# Clone the repository
git clone https://github.com/yourusername/bump-version.git
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

MIT License - feel free to use and modify as needed.
