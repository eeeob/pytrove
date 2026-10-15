# Contribution Guidelines for `pytrove` — Ordered by Priority

The items are ordered from those with the greatest impact on the library's compatibility and public interface to style and documentation rules. The items below reflect your original instructions, including your adopted decision regarding import interfaces and the placement of `__all__`. Other proposals that you did not adopt are not part of these guidelines.

## Priority 0 — Test Organization and Mandatory Coverage

### 0.1. Test Tree Organization

The `tests` directory must be organized by test type and by the section or subject it tests, while maintaining clear divisions that mirror the structure of the library.

Unit tests must be separated in `tests/unit/` from tool tests in `tests/tools/`. `tests/unit/` must be divided into subdirectories corresponding to library sections, such as `models/`, `enums/`, `typings/`, and `errors/`. `tests/tools/` must likewise be divided by tool groups, such as `archive/`, `async/`, and `files/`.

Example:

```text
tests/
├── unit/
│   ├── enums/
│   ├── errors/
│   ├── models/
│   └── typings/
└── tools/
    ├── archive/
    ├── async/
    └── files/
```

The distribution of tests must clearly reflect the subject being tested; unrelated tests must not be grouped into general files or directories.

### 0.2. Test Every Library Element

Every programmatic element in the library must have a corresponding test; this includes every function, tool, class, method, property, internal helper, constant, enum, and definition or behavior defined at the module level. No programmatic element may exist without a direct test covering its function.

It is not sufficient for a test to import the module or pass over it incidentally; it must verify the expected behavior of the element itself. Tests must cover behavioral branches, edge cases, and relevant error and exception paths. Public-interface and export elements must also be tested, including the five import entry points defined in these rules.

If a module or tool reads data bundled or stored in library files, tests must verify that this data is not loaded when the module is imported, and that it is loaded only when it is actually needed.

### 0.3. Testing Optional Dependencies

The library must be tested in an environment that contains none of the optional dependencies, to ensure that the base import and features unrelated to them remain valid. Each optional feature must also be tested when its extra is installed, and it must be verified that the absence of its dependency produces its specified clear error without disrupting the rest of the library.

## Priority 1 — Compatibility, Public Interface, and Boundaries of Responsibility

### 1.1. Python Version Support

The library must support Python versions from `3.10` through `3.14`. Consider compatibility with these versions when developing tools and adding features.

### 1.2. Public Import Entry Points

The library must provide the following public import entry points, with each entry point collecting its designated public elements:

```python
from pytrove import *           # all public tools
from pytrove.typings import *   # all public types
from pytrove.errors import *    # all public exceptions
from pytrove.models import *    # all public models
from pytrove.enums import *     # all public enums
```

The word “all” means the public elements designated for that entry point, not helpers or internal names. Each interface must reflect what belongs to it: `pytrove` for tools, and the other paths for types, errors, models, and enums. Explicit import of individual elements remains possible, such as `from pytrove import encrypt`.

### 1.3. Protecting the Public Interface and Compatibility

The names exported in `__all__`, their signatures, and their observable behavior are part of the library's public interface. Do not remove a public element or change its signature or behavior in a compatibility-breaking way without documenting the change, stating its impact, and providing migration guidance for users. Use gradual deprecation (`deprecation`) and a transition period whenever practical, and do not introduce a breaking change silently.

### 1.4. Separating Sections by Responsibility

Development must conform to the adopted structure, and every piece of code must be placed in the section appropriate to its nature and responsibility, including:

- `enums`
- `typings`
- `models`
- `errors`
- library files and helper tools

Code belonging to `enums`, `typings`, `models`, or `errors` must not be placed in tool or helper files instead of its designated section.

**Exception:** Internal helpers specific to tools may be placed outside these sections, while complying with the internal-helper organization rule below.

### 1.5. Organizing Internal Helpers

If an internal helper is shared between the logic of two or more sections, it must be placed in the library directory `pytrove/_internal/`; it must not be duplicated in the sections that use it or exported as part of the public interface.

An internal helper specific to one section, however, must be placed in a separate file within that section's package, such as `pytrove/archive/_internal.py`. It must be separated from the section's tool file even if the tool file is under 300 lines. If the section does not yet have a package, a package containing its tools and its dedicated helper file must be created for it.

### 1.6. Lazy Loading of Library Data

Any code or logic that needs to read data stored or bundled in library files must use lazy loading (`lazy loading`). This data must not be read or initialized when the module is imported; rather, it must be loaded upon the first actual use of the feature that needs it. The result may be cached after loading if doing so is safe and compatible with the library's behavior.

### 1.7. Separating Public Elements from Internal Ones

Elements are divided into public tools or helpers intended for direct use, and internal elements intended for use within the library only. Each module must specify in `__all__` the elements it exports, and internal helpers must be prevented from appearing in the public interface by mistake.

### 1.8. Aggregating Interfaces When Splitting Modules

If a group of tools, types, or models is split into subfiles within a directory, that directory's `__init__.py` file must provide a unified interface for importing public elements. A library user must not need to know the internal file distribution.

### 1.9. Placement of `__all__` and Wildcard Imports

Define `__all__` at the end of the module, after defining its public interface. Wildcard imports must not be used in regular implementation modules. They are permitted only in interface-aggregation files, in accordance with the export rules above, so that internal elements are not re-exported.

### 1.10. Handling Conflicts Between Implementation and the Rules

If existing or new code violates an adopted rule, the code or design causing the conflict must be fixed so that it complies with that rule. The rule must not be changed, removed, or weakened merely to justify the noncompliant implementation or avoid fixing it.

## Priority 2 — External Dependencies

### 2.1. Optional Dependencies

External dependencies must be optional by default, and each dependency must be associated only with the tool or feature that needs it, without becoming a requirement for using the rest of the library.

Optional dependencies must be handled through the sole central mechanism in `pytrove/_internal/_optional.py` after moving it from its current path when modifications begin. Do not use a separate copy at the old path or within section packages.

### 2.2. Dependencies Required for Compatibility

Dependencies required to support a particular Python version are excepted, such as:

```text
typing_extensions>=4.0; python_version<'3.13'
```

These dependencies must not be treated as optional; rather, they must be managed as required dependencies under the specified version condition.

### 2.3. Dependency Version Bounds

A minimum bound (`Version Floor`) must be specified for every dependency, and no upper bound is set by default. The rationale for version bounds must be documented next to the dependency definition in `pyproject.toml`.

An upper bound may be set when there is a real compatibility break with a major version, provided the reason is explained in a comment next to the dependency. Do not add upper bounds without a specific technical reason.

### 2.4. Steps for Adding a Dependency

When adding a new external dependency:

1. Add it to `[project.optional-dependencies]` in `pyproject.toml`, within the group appropriate to the feature.
2. Add it to the `full` group if that group is dedicated to installing all optional features.
3. Use the appropriate optional-import mechanism to ensure that the base import does not fail in its absence.
4. Guard the dependent public function or class so that the error appears only when the feature that needs it is used.
5. Make the dependency-absence message clear, and indicate the required extra or dependency and the appropriate installation command.

## Priority 3 — File and Code Organization

### 3.1. Dividing Files by Responsibility

Organize tools according to their functions, sections, or the logic that groups them, not according to the type of programmatic elements.

Files must not be separated merely to put every function in one file and every class in another without considering their functional and logical relationship. Each cohesive group may be represented by a separate file or by a directory containing subfiles, according to the size and nature of the group.

### 3.2. Maximum Length of Tool Files

The length of any file dedicated to tools must not exceed **300 lines of code**, including tools and their internal helpers.

If a file exceeds this limit, it must be converted into a directory containing smaller files, and the tools must be divided into functionally and logically cohesive subgroups. The division must not merely distribute code to meet the line limit; it must preserve clarity of responsibilities and cohesion.

### 3.3. Ordering the Contents of Python Files

Order the contents of Python files according to the following sequence:

1. A module docstring (`Module Docstring`), if present.
2. `from __future__ import annotations as _annotations` immediately after the module docstring.
3. Imports in ordered groups: the Python standard library, then external dependencies, then internal library imports, with a blank line between groups.
4. Module-level constants and type definitions.
5. Classes.
6. Functions.
7. `__all__` at the end of the module.

Consider dependencies and functional cohesion when ordering classes and functions, so that logically related elements remain grouped together.

Order imports consistently, and avoid unused imports. Do not use wildcard imports in regular implementation files; they are permitted in interface-aggregation files in accordance with the `__all__` rule.

When importing specific names from a module using `from ... import ...`, order the imported names in this sequence: classes, then functions, then constants, then ordinary variables. This order applies within the list of names imported from the module and does not change the order of module groups: the Python standard library, then external dependencies, then library imports.

```python
from .source import (
    SourceModel,       # class
    normalize_source,  # function
    DEFAULT_LIMIT,     # constant
    default_source,    # ordinary variable
)
```

## Priority 4 — Types, Constants, and Runtime Behavior

### 4.1. Type Syntax

Use built-in generics (`Built-in Generics`) and type unions instead of legacy aliases from the `typing` module when a corresponding built-in syntax is available.

```python
list[str]    # instead of List[str]
int | None   # instead of Optional[int]
```

The use of legacy aliases is prohibited when the corresponding built-in syntax is available. See the [Python reference for deprecated aliases](https://docs.python.org/3/library/typing.html#deprecated-aliases).

### 4.2. Deferred Evaluation of Annotations

Every Python module must contain the following import immediately after the module docstring:

```python
from __future__ import annotations as _annotations
```

Keep the `_annotations` alias as is, even when it is not used directly; it makes clear that the import is for its side effect.

This permits deferred evaluation of annotations, including the use of types imported inside `TYPE_CHECKING` without putting annotations in quotation marks. Putting type annotations in quotation marks in project files is prohibited, and rule `UP037` must remain enabled.

**Exception — recursive type aliases before Python 3.12:** a self-referential type alias defined by a plain assignment (`X: TypeAlias = ...`) for Python versions earlier than `3.12` may quote its own self-reference, for example `NestedContainer: TypeAlias = Container["NestedContainer[_T]"] | _T`. The right-hand side of such an assignment is evaluated when the module is imported, so `from __future__ import annotations` does not defer it, and on `3.10`/`3.11` there is no other way for the alias to refer to itself. The exception covers only that self-reference inside the pre-`3.12` definition; on `3.12` and later the same alias must be defined with a PEP 695 `type` statement, without quotation marks.

### 4.3. Constants

Add `Final` to module-level constants that are not intended to be reassigned.

```python
from typing import Final

DEFAULT_TIMEOUT: Final[int] = 30
```

### 4.4. Distinguishing Omission of a Parameter from Passing `None`

If a parameter needs to distinguish between not being explicitly passed and being passed `None`, use the object class itself (`Object Class`) as a special default value (`Sentinel`), instead of creating an instance of that class.

Before introducing this pattern in a function or type, check its existing uses in the relevant locations, and reuse the existing pattern whenever appropriate instead of introducing a new pattern unnecessarily.

### 4.5. Runtime Guards and Exceptions

Using `assert` for runtime guards (`Runtime Guards`) is prohibited. Python may remove `assert` statements when run with `-O`, and `AssertionError` does not necessarily provide suitable error context for the user.

Use `RuntimeError` or a more specialized exception appropriate to the situation, with a clear message.

When raising an exception with a message, assign the message to a variable first, then pass the variable to `raise`; do not write the message directly inside the `raise` statement.

```python
msg = f"connection not open (state={self._state})"
raise RuntimeError(msg)
```

### 4.6. Completeness of Type Hints

Complete and correct type hints must be provided for all functions and methods, including internal ones, for their parameters and return values. Add hints to attributes and variables when their type is not clear or when doing so helps static checking. Use the appropriate precise types instead of resorting to `Any` to bypass a type-checking problem.

Hints must be compatible with supported Python versions and pass the project's adopted type checker, `ty` (pinned in the `dev` extra and configured under `[tool.ty]` in `pyproject.toml`), without unhandled warnings or errors.

### 4.7. Comments on Hints and Type Warnings

If a type hint needs special handling, or produces a warning that cannot be fixed correctly, a concise comment must be added next to it explaining the reason for the handling and the technical reason the warning remains. Every use of `type: ignore` or similar suppression must include the specific warning code and a clear reason; suppressing warnings without explanation is prohibited.

## Priority 5 — Style Consistency and Documentation

### 5.1. Code Cleanliness and Clarity

Write code and function, parameter, and variable names in a clear, readable style. Use names that describe the purpose, give every function or class an understandable responsibility, and avoid duplication and unnecessary complexity. Code must properly and completely support type hints in accordance with the type rule, not merely by adding superficial hints.

### 5.2. Code References in Comments

Put every reference to code within comments between backticks, including names of functions, classes, attributes, variables, and other programmatic references. Apply this to every reference in the comment, not only the first reference.

```python
# Correct: Call `Client.stop()` before `Client.start()`.
# Incorrect: Call Client.stop() before Client.start().
```

### 5.3. Documenting Functions and Tools

Write a docstring (`Docstring`) for every function, operation, or tool in the library, regardless of its size or simplicity. The documentation must be concise and clear, and explain the purpose directly without verbosity or unnecessary details.

Use **Google-style Docstring** format in all documentation.

### 5.4. Documenting Classes, Models, Types, and Constants

Write documentation or a concise comment for every class, model, type definition, constant, or enum member that needs clarification. Explain the purpose, meaning, and important constraints, values, or units, without repeating what the name makes clear.

Use the same style used for function documentation: Google-style when appropriate, adapting sections according to the element. A class or model docstring explains its purpose, its attributes or fields, and important constraints; `typings` documentation explains the shape of the type and the meaning of its fields; `enums` members and constants are documented near their definition when their meaning is not clear from the name and value alone. Maintain brevity and cleanliness.

### 5.5. Documentation Sections

An element's documentation includes, according to its nature:

- A brief description explaining its purpose.
- `Args` for parameters, when present.
- `Returns` for the return value, when present.
- `Raises` for exceptions that may be raised as part of the documented behavior, when present.

Do not add sections that do not apply, and avoid repeating information that can be understood directly from the name or signature.

### 5.6. Stability of Public Documentation Files

Public documentation files such as `README.md` must focus on general explanations and concepts that need clarification, and must not contain lists or tables of data that changes continuously and requires updating with every addition or modification.

Avoid repeating feature-maintenance details in public documentation; this includes a table linking every `extra` to the dependencies it installs, because this connects unrelated topics and requires updating the table with every dependency change. If changing details need documentation, they must have a single reference source, which should be referenced rather than copied into `README.md`.

**Example:**

```python
def get_extension(filename: str) -> str:
    """Return the file extension without the leading dot.

    Args:
        filename: The name of the file.

    Returns:
        The file extension, or an empty string if absent.
    """
    ...
```

### 5.7. Commit Messages and Pull Requests

`commit` messages and pull request titles must be as concise as possible and follow the **Conventional Commits** format:

```text
<type>[optional scope]: <short description>
```

Examples:

```text
feat(archive): add lazy loading for bundled data
fix(types): correct optional dependency annotations
```

Write the pull-request body and review comments concisely and clearly, mentioning the objective or impact and test results when needed, without listing details that do not aid review. The pull-request body or review comment does not need to follow the Conventional Commits format; the format is used for the commit message and pull-request title. When there is a breaking change, show that in the title using `!` and state `BREAKING CHANGE` with an explanation of the required migration.

### 5.8. Branches and Scope of Change

Every independent change must be implemented on a separate branch, then a pull request must be submitted for its review and merge. Do not make changes directly on the main branch.

Each branch and pull request must focus on one specific and cohesive subject or logic. Break work down into the smallest independent and understandable changes possible, and avoid grouping unrelated changes in a single branch or pull request. If large work consists of changes that can be reviewed and merged in stages, split it into successive pull requests to facilitate review, monitoring, and tracking.

## Scope of Application

Every rule in this file applies to the whole library — existing code and files as well as new ones — with no exemption for code written before the rule was adopted. This includes the 300-line limit, which applies to existing files too. Existing code that does not comply must be brought into compliance, following the branch and pull-request rules above.

## Mechanism for Expanding the Rules in the Future

When beginning work on a new domain or feature type in the library, review these rules before implementation. If requirements specific to the new domain emerge, formulate an appropriate rule and add it to this file at the appropriate priority level, while updating the related tests and documentation. Do not assume detailed rules for domains on which work has not yet begun.
