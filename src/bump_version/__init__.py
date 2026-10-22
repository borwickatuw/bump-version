"""bump-version: A CLI tool to bump semantic version tags in Git repositories."""

# Aliased: bound as `version`, the function would share the package attribute
# `bump_version.version` with the `bump_version.version` submodule.
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

try:
    __version__ = _distribution_version("bump-version")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
