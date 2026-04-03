"""bump-version: A CLI tool to bump semantic version tags in Git repositories."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("bump-version")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"
