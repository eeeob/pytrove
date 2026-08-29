class UtilError(Exception):
    pass

class ValidationError(UtilError, ValueError):
    pass

class ArchiveLimitError(UtilError, ValueError):
    """An archive claimed more than extract_archive was allowed to write.

    Raised before any of the offending member reaches the disk, so nothing
    partially written has to be cleaned up by the caller. See
    archive_tools.ArchiveLimits for what can be capped and why none of it is
    capped by default.
    """


class ArchivePolicyError(UtilError, ValueError):
    """An archive member asked for something the extraction policy denies.

    Raised for the kinds of member that can reach outside the destination
    or overwrite what is already there -- a symlink, a hardlink, an
    absolute name, a duplicate, an existing file -- when the matching
    policy is set to "error" rather than to skipping quietly. Nothing of
    the offending member has been written when it is raised, but members
    already extracted stay where they are.

    Separate from ArchiveLimitError because the two answer different
    questions: a limit is about how much, a policy is about what kind.
    """


__all__ = (
    "UtilError", 
    "ValidationError", 
    "ArchiveLimitError",
    "ArchivePolicyError", 

)
