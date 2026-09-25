---
status: accepted
---

# Colophon declares its dependencies but is not a package

Colophon is standard library only (CBO-33). It runs as `python -m colophon` from
the source tree, both in the Docker image — `ENTRYPOINT ["python", "-m",
"colophon"]`, into which only `colophon/` is copied — and on a developer's
machine. Until CBO-77 it had no `pyproject.toml`: its Python floor was implied by
the Dockerfile and by CI, and its one dev tool, ruff, was pinned inside a CI
script alone. A `pyproject.toml` is the standard place to state both, but the
usual next step — add a `[build-system]` and install the project with
`pip install -e ".[dev]"` — would make Colophon a package, and that means a build
backend download, `build/` and `*.egg-info/` output, and Colophon installed into
the venv. Nothing needs any of that: nobody imports Colophon as a library, and it
is not published to PyPI.

So `pyproject.toml` holds only `[project]` with `name`, `version`,
`requires-python` and an empty `dependencies` list, and one `[dependency-groups]`
entry, `dev`: the development tools, each pinned exactly. The group is installed
with `pip install --group dev`, which needs pip 25.1 or later, so the pip upgrade
comes first. There is no `[build-system]`, no `[project.scripts]`, and nothing
runs `pip install .`. The Docker image installs nothing, because there is nothing
to install. `requires-python` also sets ruff's target version, which is intended:
ruff lints against the floor Colophon actually supports, rather than the py310
default it read before there was a file to read.

## Considered Options

- **`[project.optional-dependencies] dev` and `pip install -e ".[dev]"`.**
  Rejected: it works on older pip, but it builds and installs Colophon as a
  package for no benefit.
- **A `requirements-dev.txt`.** Rejected: a second file and a second format for
  one line, and it cannot state the Python floor.
- **Keep `target-version = "py310"` in `[tool.ruff]`.** Rejected: it would
  contradict the floor the manifest states, to avoid a three-line autofix.

## Consequences

- A contributor needs Python 3.11+ and one install command, and only for the
  linter. The tests need nothing installed.
- Adding a runtime dependency is now a visible change to `dependencies = []`, and
  it breaks CBO-33's "standard library only" principle. That needs its own
  decision, not a drive-by edit.
- Raising `requires-python` changes what ruff enforces, so expect autofixable
  findings in the same PR. CBO-77's own two — `import tomllib` sorted as
  third-party, and `timezone.utc` where the `UTC` alias exists — are the example.
- pip does not check `requires-python` for a `--group` install. A contributor on
  3.10 gets ruff installed and then an import error from `tomllib`. The floor is
  enforced by `CONTRIBUTING.md` and by that error, not by pip.
- If Colophon is ever published to PyPI, or needs a console command, add
  `[build-system]` and `[project.scripts]` then, and replace this ADR.
