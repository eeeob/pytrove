from typing import Optional

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    from enum import Enum
    
    class StrEnum(str, Enum):
        def _generate_next_value_(name, *args):
            return name.lower()
        def __str__(self):
            return str(self.value)
        
from enum import Enum, IntEnum, auto


class TriggerOn(StrEnum):
    SUCCESS = auto()
    ERROR = auto()
    ALWAYS = auto()

class TgMessageLength(IntEnum):
    TEXT = 4096
    CAPTION = 1024

class ArchiveFormat(StrEnum):
    """Container and codec archive_tools.compress_folder writes.

    The value is the extension the archive gets when `dest` names a
    directory rather than a file.
    """

    ZIP = "zip"
    """Deflate, one independently compressed member per file -- so members
    compress in parallel, and a reader can extract one without touching the
    rest. Pure stdlib, and opens natively in Windows Explorer."""

    TAR_GZ = "tar.gz"
    """Gzip over a single tar stream. Universally readable, but the stream
    is one unit: it cannot be compressed in parallel, and extracting one
    member means decompressing everything before it."""

    TAR_ZST = "tar.zst"
    """Zstandard over a single tar stream -- same shape as TAR_GZ, but the
    codec parallelises internally, so it reaches gzip's ratio at several
    times the speed. Needs the `zstd` extra."""

class ArchiveLinkPolicy(StrEnum):
    """What archive_tools.extract_archive does with a link member.

    Both `ArchiveLimits.symlinks` and `ArchiveLimits.hardlinks` take one of these, and
    both default to ERROR. A link is the one member that can still be
    dangerous after its own name has been checked -- what it points at is a
    second name, read later, by something that has forgotten where it came
    from -- so an archive that carries one is not extracted quietly. SKIP
    is the setting for an ordinary tarball full of them; ALLOW is for a
    caller who wants the links themselves.

    None of the three waives containment. A link landing outside the
    destination is refused whatever this says, because a later member
    written "through" it would escape while its own name looked harmless --
    which is the whole reason link members are dangerous.
    """

    ALLOW = auto()
    """Recreate the link, as long as it points inside the destination."""

    SKIP = auto()
    """Leave the member out and log it. The default."""

    ERROR = auto()
    """Stop the extraction with ArchivePolicyError."""


class ArchiveOverwritePolicy(StrEnum):
    """What extract_archive does when a member's path is already taken.

    "Already taken" covers two cases the caller cannot tell apart and
    should not have to: something that was on disk before the extraction
    started, and something an earlier member of the same archive has just
    written there -- which happens without either name being a duplicate,
    since "Readme.txt" and "README.TXT" land on one path on Windows and on
    macOS.

    None of the three lets a member take a path a directory holds.
    Overwriting a file replaces one thing; a directory holds however much
    someone put in it, and OVERWRITE is not a request to delete a tree. A
    link member that lands on one is refused and logged whatever this says,
    even where the directory is one the same archive had just created --
    see _Extractor._link.
    """

    ERROR = auto()
    """Stop the extraction with ArchivePolicyError."""

    SKIP = auto()
    """Keep what is there, leave the member out, and log it."""

    OVERWRITE = auto()
    """Replace what is there. The default, and the only value under which
    two members are allowed to land on one path."""


class ArchiveDuplicatePolicy(StrEnum):
    """What extract_archive does with a member name it has already seen.

    A zip can hold the same name twice -- nothing in the format forbids it,
    and it is how an archive smuggles a second version of a file past a
    reader that only looks at the first. The first one wins either way;
    this decides whether the second is worth stopping for.
    """

    SKIP = auto()
    """Keep the first, leave the rest out, and log them. The default."""

    ERROR = auto()
    """Stop the extraction with ArchivePolicyError."""


class PickleSafety(IntEnum):
    """How much files_tools.read_pickle is willing to reconstruct.

    Ordered by how much it refuses, so a higher member is always at least
    as strict as a lower one -- `>=` comparisons between them are
    meaningful, and STRICT (the highest) is read_pickle's default.
    """

    NONE = 0
    """No restriction at all -- plain pickle.loads, so the file decides what
    runs. Only for a file nothing else on the machine can write."""

    BLOCKLIST = 1
    """Everything except the known code-execution vectors (os/subprocess/
    ctypes/..., builtins.eval/exec/__import__/...). Best-effort by nature:
    a blocklist can only refuse what it has been told about, so treat this
    as a guard against accidents, not against an attacker."""

    MODULES = 2
    """The safe types, plus anything defined in a module named in
    `allow_modules` -- for loading your own app's classes in bulk without
    listing each one."""

    STRICT = 3
    """Only the inert builtin/stdlib types, plus whatever `allow_classes`
    names explicitly. Anything else raises UnpicklingError."""

class ImapEmailProvider(Enum):
    GMAIL = ("imap.gmail.com", 993)
    OUTLOOK = ("outlook.office365.com", 993)
    YAHOO = ("imap.mail.yahoo.com", 993)
    ZOHO = ("imap.zoho.com", 993)

    @property
    def host(self) -> str:
        return self.value[0]

    @property
    def port(self) -> int:
        return self.value[1]
    
    @classmethod
    def from_domain(cls, domain: str) -> Optional["ImapEmailProvider"]:
        return IMAP_DOMAIN_TO_PROVIDER.get(domain.lower())
    
class PlatformDevice(StrEnum):
    ANDROID = auto()
    IOS = auto()
    DESKTOP = auto()

class TimeUnit(IntEnum):
    MINUTE = 60
    HOUR = MINUTE * 60
    DAY = HOUR * 24
    WEEK = DAY * 7
    MONTH = DAY * 30
    YEAR = MONTH * 12


IMAP_DOMAIN_TO_PROVIDER = {
    "gmail.com": ImapEmailProvider.GMAIL,
    "outlook.com": ImapEmailProvider.OUTLOOK,
    "hotmail.com": ImapEmailProvider.OUTLOOK,
    "live.com": ImapEmailProvider.OUTLOOK,
    "yahoo.com": ImapEmailProvider.YAHOO,
    "zoho.com": ImapEmailProvider.ZOHO,
}



__all__ = (
    "ArchiveFormat",
    "ArchiveDuplicatePolicy",
    "ArchiveLinkPolicy",
    "ArchiveOverwritePolicy",
    "ImapEmailProvider",
    "PickleSafety",
    "PlatformDevice",
    "TgMessageLength",
    "TimeUnit", "TriggerOn", 
    "IMAP_DOMAIN_TO_PROVIDER", 

)