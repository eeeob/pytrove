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
