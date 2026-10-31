# Contributing to `pytrove`

An Arabic translation is kept in [`CONTRIBUTING.ar.md`](CONTRIBUTING.ar.md); this English text is the reference when the two differ.

This file is the single source of the project's rules. It has two parts: **the workflow**, which walks a change from a fresh clone to a merged pull request, and **the rules** it points at. The rules keep their numbers (`0.1`–`5.8`) because `pyproject.toml`, the `Makefile`, CI and comments in the code cite them. The mechanical rules are enforced by `ruff` and `ty`, configured only in `pyproject.toml` under `[tool.ruff]` and `[tool.ty]`, where each selected rule set names the rule it enforces and each ignore says why; the rest are checked in review.

## The workflow

### 1. Set up once

[`uv`](https://docs.astral.sh/uv/) is the only prerequisite: it provisions the interpreter and the environment from `uv.lock`. Every command runs through `make`; the `Makefile` is the only place the commands are written down, and CI, the `pre-commit` hooks and this file all call the same recipes.

```bash
make sync     # the locked environment with every extra (`make sync-minimal`: without any extra)
make hooks    # the pre-commit hooks: `make lint` and `make typecheck` before every commit
```

Tooling lives in `[dependency-groups]` in `pyproject.toml` (`lint`, `test`, `devtools`), not in an extra, so `pip install pytrove[dev]` is not a thing.

### 2. Start a branch

One cohesive change per branch, never on `main`, ending in a pull request (5.8). Large work is split into successive pull requests, each reviewable on its own.

### 3. Put each piece where it belongs

| what you are adding | where it goes | rule |
|---|---|---|
| a public tool | a public module of its section's package, under 300 lines | 1.4, 3.1, 3.2 |
| an enum, a type, a model, an exception | `enums`, `typings`, `models`, `errors`; never a tool file | 1.4 |
| a public constant (listed in an `__all__`) | the module of its kind in `constants`, under a name that says what it is; a private constant stays beside its use | 1.4, 4.3 |
| a helper one section uses | that section's own `_internal.py` (or `_internal/` package) | 1.5 |
| a helper two or more sections use | `pytrove/_internal/` | 1.5 |
| an external dependency | an extra in `pyproject.toml`, guarded through `pytrove/_internal/_optional.py`; then `uv lock`, and `uv.lock` is committed with it | 2.1–2.4 |
| a test | `tests/unit/<section>/` or `tests/tools/<group>/`, mirroring the library; a static type test in `tests/typing/<group>/` | 0.1 |

A split module keeps one unified interface in its `__init__.py` (1.8). A new public name goes into its module's `__all__` and reaches one of the six entry points (1.2, 1.7).

### 4. Write the code

- Lay the module out in the fixed order: docstring, `from __future__ import annotations as _annotations`, grouped imports, constants and types, classes, functions, `__all__` (3.3, 4.2).
- Hint every parameter and return, internal functions included, with built-in generics and `|` unions and no quoted annotations; only a `cast` target is quoted (4.1, 4.2, 4.6).
- `Final` on module constants, `ClassVar` on class constants, the `object` class as the "not passed" sentinel (4.3, 4.4).
- Raise with the message in a variable first; never `assert` as a guard (4.5).
- Every `noqa` and `ty: ignore` names its code and says why (4.7).
- Bundled data is read on first use, never at import (1.6).
- Python 3.10 through 3.14 all have to work (1.1).
- A public name, signature or behaviour does not change without documentation and a migration path (1.3). When the code and a rule disagree, the code is what gets fixed (1.10).

### 5. Test it

Every element gets a direct test of its behaviour, branches and error paths, in the test file that mirrors its module (0.1, 0.2). Code behind an extra is tested with the extra and without it (0.3).

### 6. Document it

A Google-style docstring on every function and class, a one-line docstring under every model field and enum member, backticks around code names in comments, and an `Example` that runs as a doctest where showing beats telling (5.2–5.5). `README.md` gets concepts, not tables that change with every addition (5.6).

### 7. Run the checks

| command | what it runs | when |
|---|---|---|
| `make format` | `ruff format` over `pytrove`, `tests` and `devtools` | before committing |
| `make lint` | `ruff check` and `ruff format --check` over the same tree | every commit (the hook) |
| `make typecheck` | `ty` over `pytrove` and the static type tests in `tests/typing`, against the 3.10 floor | every commit (the hook) |
| `make test` | the suite with every extra installed | before the pull request |
| `make test-doctest` | every `Example` section (5.5) | after touching an `Example` |
| `make test-minimal` | the bare package plus the test runner (0.3) | after touching code behind an extra |
| `make test-floor`, `make test-ceil` | the lowest and the newest dependency versions, on 3.10 and on 3.14 (2.3) | after changing a dependency |

CI runs every check above on each pull request: `test`, `test-doctest` and `test-minimal` on Python 3.10 through 3.14, the rest on the version each needs. A rule set is never narrowed, nor an ignore widened, in `pyproject.toml` to make a change pass (1.10).

### 8. Commit and open the pull request

Conventional Commits for the message and the title, `!` plus a `BREAKING CHANGE` note when compatibility breaks, and a short body with the objective and the test results (5.7). A breaking change also adds its entry, with the migration, under `[Unreleased]` in `CHANGELOG.md`.

## The rules

### Priority 0 — Tests

**0.1 Test tree.** `tests/unit/<section>/` (`enums/`, `errors/`, `models/`, `typings/`, …) holds the unit tests and `tests/tools/<group>/` (`archive/`, `async/`, `files/`, …) the tool tests, mirroring the library's own structure. `tests/typing/<group>/` holds the static type tests of a tool group (`assert_type` checks and calls that must fail `ty`), one file per module it checks, mirroring `tests/tools/<group>/`; `make typecheck` checks them and pytest runs them too. Unrelated tests are never grouped in a general file or directory.

**0.2 Every element is tested.** Every function, tool, class, method, property, internal helper, constant, enum and module-level definition has a test that verifies its own behaviour, branches, edge cases and error paths; importing the module or passing over the element incidentally does not count. The public interface is tested too, including the six entry points of 1.2. A module that reads bundled data is tested to not load it at import and to load it on first use.

**0.3 Optional dependencies.** The suite runs with none of the optional dependencies installed, so the base import and the unrelated features stay valid. Each optional feature is also tested with its extra installed, and its absence has to raise its specified clear error without disturbing the rest of the library.

### Priority 1 — Compatibility and the public interface

**1.1 Python versions.** `3.10` through `3.14` are supported; every tool and feature considers all of them.

**1.2 Entry points.** The public interface is these six, each collecting the public elements of its kind and nothing internal; importing a single name, such as `from pytrove import encrypt`, stays possible.

```python
from pytrove import *            # all public tools
from pytrove.typings import *    # all public types
from pytrove.errors import *     # all public exceptions
from pytrove.models import *     # all public models
from pytrove.enums import *      # all public enums
from pytrove.constants import *  # all public constants
```

**1.3 Compatibility.** The names in `__all__`, their signatures and their observable behaviour are the public interface. None is removed or changed in a breaking way without documenting the change, its impact and a migration path; gradual deprecation with a transition period is preferred whenever practical, and a break is never silent.

**1.4 Sections by responsibility.** Code goes in the section its nature dictates: `enums`, `typings`, `models`, `errors`, `constants`, or the tools. Enum, type, model and error code never lives in a tool or helper file. Every public constant, one listed in an `__all__` and so importable by a user, lives in `constants`, grouped by kind in a module of its own (bundled-data paths, patterns, time zones, ...), under a name that says what it is (`TG_CHAT_LINK_PATTERN`, not `CHAT_LINK_PATTERN`); a private constant (`_NAME`) stays beside its use (4.3). The one exception is a tool-specific internal helper, placed by 1.5.

**1.5 Internal helpers.** A helper shared by two or more sections lives in `pytrove/_internal/`, neither duplicated nor exported. A helper specific to one section lives in its own file inside that section's package (`_internal.py`, or an `_internal/` package), apart from the tool module even when that module is short; a section without a package gets one.

**1.6 Lazy data.** Data stored or bundled in library files is never read at import; it is loaded on the first use of the feature that needs it, and may be cached when that is safe.

**1.7 Public versus internal.** Every module lists what it exports in `__all__`; an internal helper never reaches the public interface by accident.

**1.8 Aggregated interfaces.** A group split into subfiles exposes one unified interface from its directory's `__init__.py`; a user never needs to know the internal file layout.

**1.9 `__all__` and wildcard imports.** `__all__` comes last in a module, after the interface it lists. Wildcard imports are forbidden in implementation modules and allowed only in interface-aggregation `__init__.py` files, which contain just the docstring, the `from .<module> import *` lines and `__all__ = (*a.__all__, *b.__all__, ...)`: no `from . import a, b`, because the wildcard import already binds each submodule, and no `__future__` import, because there are no annotations for it to act on. The top-level `pytrove/__init__.py` also holds the `__version__` line, which the build backend reads.

**1.10 Code versus rule.** Code that violates a rule is fixed to comply. A rule is never changed, removed or weakened to justify the code.

### Priority 2 — Dependencies

**2.1 Optional by default.** Each dependency is tied to the feature that needs it and never required by the rest of the library, through the single mechanism in `pytrove/_internal/_optional.py`; no copy of it exists elsewhere.

**2.2 Compatibility dependencies.** A dependency a Python version needs, such as `typing_extensions>=4.4; python_version<'3.13'`, is a required dependency under its version marker, not an optional one. So is `packaging`, which the optional-import mechanism itself needs to evaluate each extra's requirements.

**2.3 Version bounds.** Every dependency has a floor and, by default, no ceiling; the reason for each bound is a comment beside it in `pyproject.toml`. A ceiling is added only for a real break with a major version, with its reason.

**2.4 Adding a dependency.**

1. Add it to `[project.optional-dependencies]` in `pyproject.toml`, in the group of its feature.
2. Add it to the `full` group, which installs every optional feature.
3. Import it through the optional-import mechanism, so the base import survives its absence, and end each import line with `# type: ignore[import-not-found]  # Optional: the `<extra>` extra.`, so the editor of a user without the extra shows no warning on it.
4. Guard the public function or class that needs it by the extra's name, `_optional_import("<extra>")`, so the error appears only on use; the gate reads the versions from `pyproject.toml` through the installed metadata, so no version is written in the code. A module that imports the package itself also checks `_has_requirement("<extra>", "<package>")`, since an older release may be importable.
5. Make the absence message name the extra and the install command.

### Priority 3 — Files and layout

**3.1 Files by responsibility.** Tools are grouped by function and logic, never by element type (all functions in one file, all classes in another). A cohesive group is one file, or one directory of files, by its size.

**3.2 300 lines.** A tool file holds at most 300 lines of code, its helpers included. Over that, it becomes a directory of cohesive subgroups; a split that only spreads lines around is not acceptable.

**3.3 Module order.**

1. The module docstring; every module and package has one, however short (`D100`, `D104`).
2. `from __future__ import annotations as _annotations`.
3. Imports: standard library, then external, then internal, a blank line between the groups.
4. Constants and type definitions.
5. Classes.
6. Functions.
7. `__all__`.

Related classes and functions stay together. Imports are ordered consistently and none is unused (`F` and `I002` enforce that part; the order itself is not mechanical). Wildcard imports follow 1.9. Inside one `from ... import (...)`, names go classes, functions, constants, then ordinary variables:

```python
from .source import (
    SourceModel,       # class
    normalize_source,  # function
    DEFAULT_LIMIT,     # constant
    default_source,    # ordinary variable
)
```

### Priority 4 — Types, constants and runtime behaviour

**4.1 Type syntax.** Built-in generics and `|` unions, never the [deprecated `typing` aliases](https://docs.python.org/3/library/typing.html#deprecated-aliases): `list[str]`, not `List[str]`; `int | None`, not `Optional[int]` (`UP`).

**4.2 Deferred annotations.** Every module has `from __future__ import annotations as _annotations` right after its docstring. The `_annotations` alias stays even though nothing uses it: it marks the import as there for its side effect. Types imported under `TYPE_CHECKING` are therefore used unquoted, and a quoted annotation is prohibited (`I002`, `UP037`). Three exceptions: an aggregation `__init__.py` (1.9) omits the import; the target of `typing.cast` is a quoted string, as in `cast("Iterator[Leaf]", x)`, because `cast` evaluates its first argument at runtime, so a quoted target lets its names stay under `TYPE_CHECKING` (`TC006` enforces it; the casts exist mostly because `ty` cannot yet solve the recursive `NestedContainer`, astral-sh/ty#1703); and before 3.12 a self-referential alias defined by plain assignment may quote its own name, as in `NestedContainer: TypeAlias = Container["NestedContainer[_T]"] | _T`, because the right-hand side is evaluated at import and nothing else lets it refer to itself; on 3.12 and later the same alias is a PEP 695 `type` statement with no quotes.

**4.3 Constants.** A module constant is `NAME: Final[T] = value`; a public one lives in `constants` (1.4). A class constant is `NAME: ClassVar[T] = value`, upper-case with an explicit type, never `ClassVar[Final[T]]`. `__version__` takes no `Final`, because the build backend reads only the plain `__version__ = "..."` form. A class attribute meant to be overridden is a setting, not a constant: lower-case name, plain annotation.

**4.4 Omitted versus `None`.** When a parameter has to tell "not passed" from `None`, its default is the `object` class itself, not an instance of it. Check how the surrounding code already does this and reuse that pattern rather than introducing another.

**4.5 Guards and exceptions.** `assert` is never a runtime guard (`-O` removes it). Raise `RuntimeError` or something more specific, with the message assigned to a variable first (`S101`, `EM`):

```python
msg = f"connection not open (state={self._state})"
raise RuntimeError(msg)
```

**4.6 Complete hints.** Every function and method, internal ones included, hints its parameters and its return (`ANN`); attributes and variables are hinted when the type is unclear or the hint helps checking. `Any` is never a way around a type error; `ANN401` is unselected for the honest cases, not as a licence. Hints work on every supported version and pass `ty` (`make typecheck`) with no unhandled warning or error.

**4.7 Suppressions carry reasons.** A hint that needs special handling, or a warning that cannot be fixed correctly, gets a concise comment with the technical reason. Every `type: ignore`, `ty: ignore` and `noqa` names its code and its reason; a bare one is prohibited (`PGH003`).

### Priority 5 — Style, documentation and Git

**5.1 Clarity.** Names describe their purpose, each function and class has one understandable responsibility, and duplication and needless complexity are avoided. Type support is real, not decorative.

**5.2 Code in comments.** Every code reference inside a comment is in backticks, every time, not only the first:

```python
# Correct: Call `Client.stop()` before `Client.start()`.
# Incorrect: Call Client.stop() before Client.start().
```

**5.3 Docstrings.** Every function, operation and tool has a concise Google-style docstring, however small it is (`D` with `convention = "google"` enforces presence and format; the content rules below are not mechanical).

**5.4 Classes, models, types and constants.** Each is documented where its name does not say enough: purpose, meaning, constraints, units. In a model (`dataclass`, `TypedDict`, `NamedTuple`, any class that is a list of fields) and in an enum, every field or member has a docstring of its own, a string literal on the next line, and the class docstring does not repeat them in an `Attributes` section:

```python
class ArchiveLimits(TypedDict):
    """Caps applied while extracting an archive."""

    max_members: int
    """Members allowed in one archive; extraction stops at the first one past it."""

    max_ratio: float
    """Highest allowed uncompressed-to-compressed ratio, as a guard against bombs."""
```

**5.5 Docstring sections.** A brief description, then `Args`, `Returns` and `Raises` when they apply, and `Example` when the use is clearer shown than described. No section that does not apply, nothing the name or signature already says. An `Example` is a doctest (`>>>` lines and the exact output), runs under `make test-doctest`, fails the build when wrong, and needs no network, filesystem or optional dependency; a function that cannot be shown that way gets no `Example` rather than a skipped one.

```python
def chunk(items: Sequence[_T], size: int) -> list[list[_T]]:
    """Split `items` into consecutive lists of at most `size` elements.

    Args:
        items: The sequence to split.
        size: The largest chunk length; must be positive.

    Returns:
        The chunks, in order; the last one may be shorter.

    Example:
        >>> chunk([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
    """
```

**5.6 Public documentation.** `README.md` and its like explain concepts and never carry data that changes with every addition, such as a table of extras and the packages each installs. Changing details have one reference source, which is linked rather than copied.

**5.7 Commits and pull requests.** Commit messages and pull-request titles are concise Conventional Commits, `<type>[optional scope]: <short description>`, such as `feat(archive): add lazy loading for bundled data` or `fix(types): correct optional dependency annotations`. The pull-request body and review comments say what the change is for and how it was tested, briefly and without detail that does not aid review; they need not follow the format. A breaking change puts `!` in the title and a `BREAKING CHANGE` note with the required migration, and adds an entry with the same migration under `[Unreleased]` in `CHANGELOG.md` in the same pull request, so users upgrading find every break in one place.

**5.8 Branches.** Every independent change gets its own branch and pull request; nothing lands on `main` directly. One cohesive subject per branch, in the smallest independent pieces, and large work in successive pull requests.

## Scope of Application

Every rule applies to the whole library, existing code as well as new, with no exemption for code written before a rule was adopted; the 300-line limit included. Non-compliant code is brought into compliance on its own branch and pull request.

## Extending the rules

Before working in a new domain, reread this file. If the domain needs a rule of its own, add it here at the right priority and update the related tests and documentation. No rules are assumed for domains not yet worked on.
