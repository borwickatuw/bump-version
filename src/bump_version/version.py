"""The version model: bump types, versions, and tag discovery.

`BumpType` (whose values are exactly the bump subcommand names) and
`Version` (which renders itself as the tag string), plus parsing a tag into
a `Version` and finding the highest version tag. No user interaction.
May import: `git` (the tag listing).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from bump_version.git import _run_git


class BumpType(Enum):
    """Version bump types."""

    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


@dataclass
class Version:
    """Semantic version representation."""

    major: int
    minor: int
    patch: int
    prefix: str = "v"

    def __str__(self) -> str:
        return f"{self.prefix}{self.major}.{self.minor}.{self.patch}"

    def bump(self, bump_type: BumpType) -> Version:
        """Return a new Version with the specified component bumped."""
        if bump_type == BumpType.MAJOR:
            return Version(self.major + 1, 0, 0, self.prefix)
        elif bump_type == BumpType.MINOR:
            return Version(self.major, self.minor + 1, 0, self.prefix)
        else:  # PATCH
            return Version(self.major, self.minor, self.patch + 1, self.prefix)


def _get_version_tags(prefix: str = "v") -> list[str]:
    """
    Get all version tags matching semantic versioning pattern.

    Returns tags sorted by version number (lowest to highest).
    """
    # Build pattern based on prefix
    pattern = f"{prefix}[0-9]*.[0-9]*.[0-9]*" if prefix else "[0-9]*.[0-9]*.[0-9]*"

    result = _run_git("tag", "-l", pattern, check=False)
    if result.returncode != 0:
        return []

    tags = [t.strip() for t in result.stdout.strip().split("\n") if t.strip()]

    # Sort by version number
    def version_key(tag: str) -> tuple[int, int, int]:
        version = _parse_version(tag, prefix)
        if version:
            return (version.major, version.minor, version.patch)
        return (0, 0, 0)

    return sorted(tags, key=version_key)


def _parse_version(tag: str, prefix: str = "v") -> Version | None:
    """Parse a version tag into a Version object."""
    # Remove prefix
    version_str = tag
    if prefix and tag.startswith(prefix):
        version_str = tag[len(prefix) :]

    # Match semver pattern
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version_str)
    if not match:
        return None

    return Version(
        major=int(match.group(1)),
        minor=int(match.group(2)),
        patch=int(match.group(3)),
        prefix=prefix,
    )


def _get_current_version(prefix: str = "v") -> Version | None:
    """Get the current (latest) version from tags."""
    tags = _get_version_tags(prefix)
    if not tags:
        return None

    # Return the highest version (last in sorted list)
    return _parse_version(tags[-1], prefix)
