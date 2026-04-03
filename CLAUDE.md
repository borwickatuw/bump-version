# bump-version

CLI tool to bump semantic version tags in Git repositories. Zero external dependencies — uses only Python stdlib.

## Related Projects

- **claude-meta** - Cross-repo standards and audit tooling

## Coding Standards

Supports Python >=3.9 (broader than the standard >=3.12) because this is a public CLI tool installed via `uvx`/`pip` on diverse systems. Uses `from __future__ import annotations` for modern type hint syntax.

All code is in a single file (`src/bump_version/cli.py`). This is intentional for a focused CLI utility — see `docs/DECISIONS.md` for rationale on design choices.

## Security

Run `make security` before committing. This checks:
- Bandit Python security linter
- pip-audit for dependency vulnerabilities

## pysmelly

Read [docs/PYSMELLY.md](docs/PYSMELLY.md) before running pysmelly code smell analysis on this project.

## Cross-Repository Ideas

    claude-idea bump-version "Description of the pattern or improvement"
