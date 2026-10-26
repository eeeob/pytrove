from __future__ import annotations as _annotations

from pytrove.enums import ArchiveDuplicatePolicy, ArchiveLinkPolicy, ArchiveOverwritePolicy
from pytrove.typings import ArchiveLimits


def test_archive_limits_defaults_cap_nothing_and_refuse_links() -> None:
    limits = ArchiveLimits()
    assert limits[:8] == (None,) * 8
    assert limits.symlinks is ArchiveLinkPolicy.ERROR
    assert limits.hardlinks is ArchiveLinkPolicy.ERROR
    assert limits.overwrite is ArchiveOverwritePolicy.OVERWRITE
    assert limits.duplicates is ArchiveDuplicatePolicy.SKIP


def test_archive_limits_compare_and_hash_by_value() -> None:
    assert ArchiveLimits(max_files=3) == ArchiveLimits(max_files=3)
    assert hash(ArchiveLimits(max_files=3)) == hash(ArchiveLimits(max_files=3))


def test_permissive_limits_allow_links_and_keep_other_fields() -> None:
    limits = ArchiveLimits.permissive(max_files=5)
    assert limits.symlinks is ArchiveLinkPolicy.ALLOW
    assert limits.hardlinks is ArchiveLinkPolicy.ALLOW
    assert limits.max_files == 5


def test_permissive_limits_let_either_link_policy_be_overridden() -> None:
    limits = ArchiveLimits.permissive(symlinks=ArchiveLinkPolicy.SKIP)
    assert limits.symlinks is ArchiveLinkPolicy.SKIP
    assert limits.hardlinks is ArchiveLinkPolicy.ALLOW

    limits = ArchiveLimits.permissive(hardlinks=ArchiveLinkPolicy.ERROR)
    assert limits.symlinks is ArchiveLinkPolicy.ALLOW
    assert limits.hardlinks is ArchiveLinkPolicy.ERROR


def test_a_policy_may_be_given_as_its_string_value() -> None:
    # Stored as given; `extract_archive` coerces it (and refuses a misspelling).
    limits = ArchiveLimits(symlinks="skip", overwrite="error")
    assert limits.symlinks == ArchiveLinkPolicy.SKIP
    assert limits.overwrite == ArchiveOverwritePolicy.ERROR
