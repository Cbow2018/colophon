# ADR draft — Colophon declares its dependencies but is not a package

*Draft from the CBO-77 research (2026-09-24). The build session files it as `docs/adr/NNNN-dependencies-not-a-package.md` with the next free number.*

**Status:** proposed

## Context

Colophon is standard library only (CBO-33). It runs as `python -m colophon` from the source tree, both in the Docker image (`ENTRYPOINT ["python", "-m", "colophon"]`, which copies only `colophon/`) and on a developer's machine. Until CBO-77 it had no `pyproject.toml`. Its Python floor was implied by the Dockerfile and CI, and its one dev tool, ruff, was pinned only inside a CI script.

A `pyproject.toml` is the standard place to state both. The usual next step, adding a `[build-system]` and installing the project with `pip install -e ".[dev]"`, would make Colophon a package. That means a build backend download, `build/` and `*.egg-info/` output, and Colophon installed into the venv. Nothing needs any of that: nobody imports Colophon as a library, and it isn't published to PyPI.

## Decision

`pyproject.toml` holds only:

- `[project]` with `name`, `version`, `requires-python` and an empty `dependencies` list
- `[dependency-groups] dev`, the development tools, each pinned exactly. It is installed with `pip install --group dev`, which needs pip ≥ 25.1, so the pip upgrade comes first.

There is **no** `[build-system]`, no `[project.scripts]`, and nothing runs `pip install .`. The Docker image installs nothing.

`requires-python` also sets ruff's target version. That is intended: ruff lints against the floor Colophon actually supports, rather than the py310 default it used before.

## Consequences

- A contributor needs Python 3.11+ and one install command, and only for the linter. The tests need nothing installed.
- Adding a runtime dependency is now a visible change to `dependencies = []`, and it breaks CBO-33's "standard library only" principle. That needs its own decision, not a drive-by edit.
- Raising `requires-python` changes what ruff enforces, so expect autofixable findings in the same PR.
- pip doesn't check `requires-python` for a `--group` install. A contributor on 3.10 gets ruff installed and then an import error from `tomllib`. The floor is enforced by `CONTRIBUTING.md` and by that error, not by pip.
- If Colophon is ever published to PyPI, or needs a console command, add `[build-system]` and `[project.scripts]` then, and replace this ADR.

## Alternatives rejected

- **`[project.optional-dependencies] dev` + `pip install -e ".[dev]"`:** works on older pip, but builds and installs Colophon as a package for no benefit.
- **`requirements-dev.txt`:** a second file and a second format for one line, and it can't state the Python floor.
- **Keep `target-version = "py310"` in `[tool.ruff]`:** would contradict the floor this file states, just to avoid a 3-line autofix.
