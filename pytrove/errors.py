"""The exceptions pytrove raises."""

from __future__ import annotations as _annotations


class UtilError(Exception):
    """Base class of every exception pytrove defines."""


class ValidationError(UtilError, ValueError):
    """A value failed one of pytrove's checks.

    It is also a `ValueError`, so code that already catches `ValueError`
    keeps working.
    """


class ArchiveLimitError(UtilError, ValueError):
    """An archive claimed more than `extract_archive` was allowed to write.

    Raised before any of the offending member reaches the disk, so nothing
    partially written needs cleaning up. See `ArchiveLimits` for what can be
    capped; nothing is capped by default.
    """


class ArchivePolicyError(UtilError, ValueError):
    """An archive member asked for something the extraction policy denies.

    Raised for a symlink, a hardlink, an absolute name, a duplicate or an
    existing file when the matching policy is set to "error". Nothing of the
    offending member has been written, but members extracted before it stay
    where they are. It is separate from `ArchiveLimitError` because a limit
    is about how much, while a policy is about what kind.
    """


__all__ = (
    "UtilError",
    "ValidationError",
    "ArchiveLimitError",
    "ArchivePolicyError",
)
