"""Reading `tools/<tool>/schedule/schedule.toml`: who asks, and how often.

Every other module here answers "what does upstream look like now". This one
answers the question that makes the rest of it worth anything: a checker
nobody runs reports nothing, and a source that dies is then found months
later by a build failing for reasons that look like the build's fault.

The file is deliberately almost empty. A cadence is the one thing a workflow
cannot work out for itself, and everything else about a scheduled run is
already decided elsewhere -- which sources to check is `sources.toml`, what
to clean is the janitor's policies, and what counts as a failure is the exit
code. Declaring any of it twice would be inviting the two copies to disagree.
"""

from __future__ import annotations

from .model import Schedule
from .registry import Layout, RegistryError, tomllib

# ============================== the parser ==============================

#: The one table, and every key it may carry. Unknown keys are an error for
#: the same reason they are in the registry: a typo that silently dropped the
#: cron would leave a tool apparently scheduled and never checked.
SECTION = "schedule"
KEYS = frozenset({"cron", "notes"})


def load(tool: str) -> Schedule:
    """Parse one tool's schedule. Raises `RegistryError` on anything odd.

    `RegistryError` rather than a type of its own: to everything upstream of
    here a malformed declaration is one situation with one response, and the
    command line already turns it into the one exit code that means "the
    files that describe this tool are wrong".
    """

    path = Layout.schedule_path(tool)
    where = f"{path.parent.name}/{path.name}"

    if not path.is_file():
        raise RegistryError(f"{where}: {tool} declares no schedule")

    table = tomllib.loads(path.read_text(encoding="utf-8")).get(SECTION)
    if not isinstance(table, dict):
        raise RegistryError(f"{where}: missing the [{SECTION}] table")

    unknown = sorted(set(table) - KEYS)
    if unknown:
        raise RegistryError(f"{where}: unknown key(s) {unknown}")

    cron = str(table.get("cron", "")).strip()
    if not cron:
        raise RegistryError(f"{where}: [{SECTION}] needs cron")

    schedule = Schedule(tool=tool, cron=cron,
                        notes=str(table.get("notes", "")).strip())
    if not schedule.every_days:
        raise RegistryError(
            f"{where}: cron {cron!r} is not a cadence that can be stated in "
            f"days. Use 'm h * * D' for weekly, 'm h D * *' for monthly or "
            f"'m h * * *' for daily -- anything else leaves the escalation "
            f"rule unable to say how long three runs is.")
    return schedule


def find(tool: str) -> Schedule | None:
    """The tool's schedule, or None when it declares none.

    Soft on purpose. A check run by hand needs no cadence at all, and a tool
    is allowed to exist before anyone has decided how often to watch it; the
    place a missing schedule actually matters is the workflow, and a test is
    what notices it there.
    """

    return load(tool) if Layout.schedule_path(tool).is_file() else None
