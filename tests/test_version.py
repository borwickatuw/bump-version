"""Tests for Version dataclass and version parsing."""

from bump_version.cli import BumpType, Version, _parse_version


class TestVersion:
    """Tests for the Version dataclass."""

    def test_str_with_default_prefix(self):
        v = Version(1, 2, 3)
        assert str(v) == "v1.2.3"

    def test_str_with_custom_prefix(self):
        v = Version(1, 2, 3, prefix="release-")
        assert str(v) == "release-1.2.3"

    def test_str_with_no_prefix(self):
        v = Version(1, 2, 3, prefix="")
        assert str(v) == "1.2.3"

    def test_str_zero_version(self):
        v = Version(0, 0, 0)
        assert str(v) == "v0.0.0"

    def test_bump_major(self):
        v = Version(1, 2, 3)
        new = v.bump(BumpType.MAJOR)
        assert new == Version(2, 0, 0)

    def test_bump_minor(self):
        v = Version(1, 2, 3)
        new = v.bump(BumpType.MINOR)
        assert new == Version(1, 3, 0)

    def test_bump_patch(self):
        v = Version(1, 2, 3)
        new = v.bump(BumpType.PATCH)
        assert new == Version(1, 2, 4)

    def test_bump_preserves_prefix(self):
        v = Version(1, 0, 0, prefix="release-")
        new = v.bump(BumpType.MINOR)
        assert new.prefix == "release-"
        assert str(new) == "release-1.1.0"

    def test_bump_major_resets_minor_and_patch(self):
        v = Version(1, 5, 9)
        new = v.bump(BumpType.MAJOR)
        assert new.minor == 0
        assert new.patch == 0

    def test_bump_minor_resets_patch(self):
        v = Version(1, 5, 9)
        new = v.bump(BumpType.MINOR)
        assert new.patch == 0
        assert new.minor == 6

    def test_bump_from_zero(self):
        """Bumping from 0.0.0 gives expected first versions."""
        v = Version(0, 0, 0)
        assert v.bump(BumpType.MAJOR) == Version(1, 0, 0)
        assert v.bump(BumpType.MINOR) == Version(0, 1, 0)
        assert v.bump(BumpType.PATCH) == Version(0, 0, 1)

    def test_bump_does_not_mutate_original(self):
        v = Version(1, 2, 3)
        v.bump(BumpType.MAJOR)
        assert v == Version(1, 2, 3)


class TestParseVersion:
    """Tests for _parse_version."""

    def test_parse_standard_tag(self):
        v = _parse_version("v1.2.3")
        assert v == Version(1, 2, 3, prefix="v")

    def test_parse_no_prefix(self):
        v = _parse_version("1.2.3", prefix="")
        assert v == Version(1, 2, 3, prefix="")

    def test_parse_custom_prefix(self):
        v = _parse_version("release-1.0.0", prefix="release-")
        assert v == Version(1, 0, 0, prefix="release-")

    def test_parse_invalid_returns_none(self):
        assert _parse_version("not-a-version") is None

    def test_parse_partial_version_returns_none(self):
        assert _parse_version("v1.2") is None

    def test_parse_large_numbers(self):
        v = _parse_version("v100.200.300")
        assert v == Version(100, 200, 300)

    def test_parse_zero_version(self):
        v = _parse_version("v0.0.0")
        assert v == Version(0, 0, 0)

    def test_parse_with_extra_after_patch(self):
        """Tags like v1.2.3-rc1 should still parse the numeric part."""
        v = _parse_version("v1.2.3-rc1")
        assert v is not None
        assert v.major == 1
        assert v.minor == 2
        assert v.patch == 3
