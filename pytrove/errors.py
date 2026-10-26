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

    Raised before the offending member is written when its header gives it
    away. A member that lies about its size is stopped mid-write: with
    `atomic` (the default) nothing reaches `dest`; without it, its partial file
    stays unless `cleanup_on_error` is set. See `ArchiveLimits` for what can be
    capped; nothing is capped by default.
    """


class ArchivePolicyError(UtilError, ValueError):
    """An archive member asked for something the extraction policy denies.

    Raised for a symlink, a hardlink, a duplicate or an existing file when the
    matching policy is set to "error"; an absolute or `..` name is never an
    error, it is always logged and skipped. Nothing of the offending member has
    been written. With `atomic` (the default) nothing reaches `dest`; without
    it, members extracted before it stay unless `cleanup_on_error` is set. It
    is separate from `ArchiveLimitError` because a limit is about how much,
    while a policy is about what kind.
    """


__all__ = (
    "UtilError",
    "ValidationError",
    "ArchiveLimitError",
    "ArchivePolicyError",
)
