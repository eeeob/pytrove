# The one place the development commands are written down. CI, pre-commit and
# CONTRIBUTING.md all call these recipes, so they cannot drift apart.
#
# `uv` owns the environment: `uv run` creates `.venv` and installs from
# `uv.lock` whenever it is missing or out of date, so no recipe has to build
# one first and there is no step a contributor can forget.

UV := uv
RUN := $(UV) run

# The two ends of the supported range (CONTRIBUTING 1.1). Keep both in sync
# with `requires-python` and the classifiers in `pyproject.toml`.
PYTHON_FLOOR := 3.10
PYTHON_CEIL := 3.14

# Throwaway environments built from `pyproject.toml`, never from `uv.lock`
# (`.gitignore` covers `.venv*`). `uv sync` is not usable for them: asked for
# a resolution other than the locked one it rewrites `uv.lock` to match.
VENV_MIN := $(CURDIR)/.venv-minimal
VENV_FLOOR := $(CURDIR)/.venv-floor
VENV_CEIL := $(CURDIR)/.venv-ceil
# Where a virtual environment keeps its interpreter: `Scripts` on Windows
# (`OS` is set there by the system), `bin` everywhere else.
BIN := $(if $(OS),Scripts,bin)

# `--no-project --with` keeps it to one ephemeral package, because the release
# jobs read the version without syncing the project.
VERSION = $(shell $(UV) run --no-project --with hatchling hatchling version)

.PHONY: sync sync-minimal hooks format lint typecheck test test-doctest test-minimal test-floor test-ceil build version clean

# No other recipe needs this: they all sync on their own. It exists so CI can
# install in a step of its own, which makes a resolution failure read as one.
sync:
	$(UV) sync --all-extras

# The tooling groups without any extra: enough to lint, type-check the core and
# run the tests, every extra-dependent one of which then skips.
sync-minimal:
	$(UV) sync

# Once per clone: every commit then runs `make lint` and `make typecheck`.
# `pre-commit` comes from the `lint` group, so this needs nothing installed
# first. Safe to repeat: it rewrites `.git/hooks/pre-commit` in place.
hooks:
	$(RUN) pre-commit install

format:
	$(RUN) ruff format pytrove tests devtools

lint:
	$(RUN) ruff check pytrove tests devtools
	$(RUN) ruff format --check pytrove tests devtools

# The target version and platform are fixed in `[tool.ty.environment]`. Run it
# from an environment that holds every extra: the `mongo` extra skips 3.10, and
# `ty` 0.0.88 overflows its stack against a 3.14 interpreter, so CI runs this
# on 3.11. `typings/_core_py312.py` is PEP 695 syntax, excluded in
# `[tool.ty.src]` and checked on its own against 3.12.
typecheck:
	$(RUN) ty check pytrove
	$(RUN) ty check --python-version 3.12 pytrove/typings/_core_py312.py

test:
	$(RUN) pytest

# CONTRIBUTING 5.5: every `Example` section is a doctest and must be correct.
test-doctest:
	$(RUN) pytest --doctest-modules pytrove --ignore=pytrove/typings/_core_py312.py

# CONTRIBUTING 0.3: the bare package plus the test runner, nothing optional.
# `import pytrove` first, because that is the promise `pip install pytrove`
# makes; then the whole suite, where every extra-dependent test must skip.
test-minimal:
	$(UV) venv --clear $(VENV_MIN)
	VIRTUAL_ENV=$(VENV_MIN) $(UV) pip install . --group test
	$(VENV_MIN)/$(BIN)/python -c "import pytrove; print(len(pytrove.__all__), 'symbols exported OK')"
	$(VENV_MIN)/$(BIN)/python -m pytest

# Both ends of every dependency range (CONTRIBUTING 2.3): the lowest version
# each floor allows on the oldest Python, and the newest release on the newest.
test-floor:
	$(UV) venv --clear --python $(PYTHON_FLOOR) $(VENV_FLOOR)
	VIRTUAL_ENV=$(VENV_FLOOR) $(UV) pip install --resolution lowest-direct --all-extras --group test -r pyproject.toml
	$(VENV_FLOOR)/$(BIN)/python -m pytest

test-ceil:
	$(UV) venv --clear --python $(PYTHON_CEIL) $(VENV_CEIL)
	VIRTUAL_ENV=$(VENV_CEIL) $(UV) pip install --all-extras --group test -r pyproject.toml
	$(VENV_CEIL)/$(BIN)/python -m pytest

build:
	$(UV) build

version:
	@printf '%s\n' "$(VERSION)"

clean:
	rm -rf .venv .venv-minimal .venv-floor .venv-ceil dist build
