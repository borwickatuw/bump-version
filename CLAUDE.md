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
- `uv audit` for dependency CVEs + adverse statuses

**No secrets gate, by decision.** This repo has no `.secrets.baseline` and no
`security-secrets` target. `SECURITY.md` Practice #8 scopes that gate to apps
with credentials, and this repo handles none: no `.env` or `.env.example`, and
no tracked file contains a credential-shaped string (verified 2026-08-12
across all 18 tracked files). The absence is deliberate, not an oversight —
revisit if this repo ever gains credentials or environment config.

## pysmelly

Read [docs/PYSMELLY.md](docs/PYSMELLY.md) before running pysmelly code smell analysis on this project.

## Cross-Repository Ideas

    claude-idea bump-version "Description of the pattern or improvement"
