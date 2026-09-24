# CBO-77 — proposed changes (drafts, not applied)

Everything below is a draft for the build session. Nothing here has been written to the repo. Research and evidence: `research-cbo-77.md`. The decision numbers (D1–D11) refer to its §6.

Files the build touches: `pyproject.toml` (new), `colophon/config.py` and `colophon/relay.py` (ruff autofix, 3 lines), `.github/workflows/tests.yml` (ruff job, 2 lines), `CONTRIBUTING.md` (new), `README.md` (one section), `docs/adr/NNNN-…md` (new). **Not touched:** `Dockerfile`, `docker-compose.example.yml`, `AGENTS.md`.

---

## 1. `pyproject.toml` (new, repo root)

Tested in the sandbox: it parses with `tomllib`, `pip install --group dev` installs ruff 0.16.8, and ruff picks up target version 3.11 from it.

```toml
# Colophon is standard library only: nothing needs installing to run it or its
# tests. This file states the Python floor and pins the development tools.
# It is deliberately not a package: no [build-system], and nothing runs
# `pip install .` (see docs/adr/ — "Colophon declares its dependencies but is
# not a package").

[project]
name = "colophon"
version = "0.0.0" # placeholder until CBO-47 tags v1.0.0
# tomllib and datetime.UTC both arrived in 3.11. ruff also reads this line as
# its target version.
requires-python = ">=3.11"
dependencies = []

[dependency-groups]
dev = [
    # Exact pin: ruff's default rule set grows between releases, so an unpinned
    # install would silently change what CI enforces (commit 3d0962a).
    "ruff==0.16.8",
]
```

Things left out on purpose: `[build-system]`, `[project.scripts]`, `readme`, `license`, `authors` and classifiers. Nothing reads them, because nothing is built or published. Add them only if Colophon is ever distributed on PyPI (see the ADR).

---

## 1a. Ruff autofix that must land with it (D1)

Once `requires-python` exists, ruff targets 3.11 and flags two lines. Apply with `ruff check --fix .`:

```diff
--- a/colophon/config.py
+++ b/colophon/config.py
@@ -5,11 +5,10 @@
 import os
+import tomllib
 from dataclasses import dataclass
 from pathlib import Path

-import tomllib
-
 from colophon.matching import normalise
```

```diff
--- a/colophon/relay.py
+++ b/colophon/relay.py
@@ -10,7 +10,7 @@
 import sqlite3
-from datetime import datetime, timezone
+from datetime import UTC, datetime
 from pathlib import Path
@@ -267,7 +267,7 @@ def _utc_now():
-    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
+    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
```

Suggested commit message: *"CBO-77: ruff now targets 3.11 — tomllib is stdlib, UTC alias. requires-python undoes the py310 assumption 3d0962a worked around."*

---

## 2. `.github/workflows/tests.yml`, ruff job only (D10)

```diff
       - uses: actions/setup-python@v5
         with:
           python-version: "3.11"
-      - name: Install ruff
-        run: pip install ruff==0.16.8
+      - name: Install the dev tools from pyproject.toml
+        run: |
+          python -m pip install --upgrade pip
+          pip install --group dev
       - name: Lint
         run: ruff check .
```

The pip upgrade is there because `--group` needs pip 25.1 or later. The `tests` job (installs nothing) and the `container` job stay as they are. Python stays on 3.11 in this job.

---

## 3. `README.md`: replace "Running the tests" (lines 374–382) (D8)

Current:

````markdown
## Running the tests

No dependencies to install:

```
python -m unittest discover -s tests -t .
```

They run on every push in GitHub Actions, on Python 3.11 and 3.12.
````

Proposed:

```markdown
## Contributing

Colophon needs Python 3.11 or newer and nothing else: it has no dependencies.
How to set up, run the tests and run the linter is in
[CONTRIBUTING.md](CONTRIBUTING.md).
```

Nothing is lost, because the unittest command and the CI Python versions move into CONTRIBUTING.md.

---

## 4. `CONTRIBUTING.md` (new, repo root) (D6, D7, D9)

Written for someone who doesn't use the terminal much. Setup only. The contribution process comes later (§6).

````markdown
# Contributing to Colophon

This page gets you from a fresh copy of the code to running the tests and the
linter, the same checks GitHub runs on every pull request.

## What you need

- **Python 3.11 or newer.** Check with:

  ```
  python3 --version
  ```

  It should say `Python 3.11` or higher. (On Windows, type `python` instead of
  `python3` everywhere on this page.)

- **git**, to copy the code.

Colophon uses only Python's standard library. There is nothing to install to
run it or its tests. The steps below install one tool, the linter `ruff`, so
that you can check your code the same way GitHub does.

## 1. Copy the code

```
git clone https://github.com/Cbow2018/colophon.git
cd colophon
```

## 2. Make a virtual environment

A virtual environment keeps the linter in this folder instead of installing it
for your whole computer. Do this once:

```
python3 -m venv .venv
```

Then switch it on. Do this every time you open a new terminal:

- macOS / Linux:

  ```
  source .venv/bin/activate
  ```

- Windows:

  ```
  .venv\Scripts\activate
  ```

Your prompt now starts with `(.venv)`. From here on, `python` means the
virtual environment's Python on every system.

## 3. Install the linter

```
python -m pip install --upgrade pip
pip install --group dev
```

The first line updates pip, because older versions don't understand `--group`.
The second installs the tools listed under `[dependency-groups]` in
`pyproject.toml`. Today that's just `ruff`, at the exact version CI uses.

## 4. Run the tests

```
python -m unittest discover -s tests -t .
```

The last line should say `OK`. GitHub runs the same tests on Python 3.11 and
3.12 for every push.

## 5. Run the linter

```
ruff check .
ruff format --check .
```

Both should pass. If `ruff format --check` complains, `ruff format .` fixes the
formatting for you. Check what it changed before you commit.

## When you're done

`deactivate` switches the virtual environment off. The `.venv` folder is
ignored by git, so you can leave it where it is.
````

---

## 5. Dockerfile: no change (D5)

It already says "Colophon is standard library only, so there is nothing to install" and copies only `colophon/`. There is no install list to reconcile, so the acceptance criterion "The Dockerfile … install[s] from the manifest" is met because nothing needs installing. Say so in the PR description so a reviewer doesn't read it as missed.

---

## 6. Draft follow-up ticket (Callum asked for it; not yet created in Linear)

**Title:** Fill out CONTRIBUTING.md with the contribution process
**Parent:** CBO-33 · **Blocked by:** CBO-47 (v1.0.0 release) · **Related:** CBO-77, CBO-63

> ## Why
>
> CBO-77 added `CONTRIBUTING.md` with setup steps only: Python floor, venv, dev tools, tests, linter. It says nothing about *how* to contribute. Before v1 that was deliberate: the process is written for agents in `AGENTS.md` and points at Linear, which outside contributors can't see.
>
> ## What to build
>
> Extend `CONTRIBUTING.md` for a human contributor, after v1.0.0 ships:
>
> - Raise a GitHub Issue first. It gets triaged with `needs-triage` / `needs-info` / `ready-for-human` / `wontfix` (`docs/agents/triage-labels.md`).
> - What happens to an accepted issue: it gets a linked internal build ticket, and the fix PR is titled `CBO-N: …` with `Closes #N`. Decide whether external PRs follow the same title rule or keep their own.
> - Test-first expectation, and that CI (tests on 3.11 and 3.12, ruff, container) must be green.
> - The licence: contributions are AGPL-3.0. Decide whether a DCO sign-off is wanted (default: no).
> - Where the design lives (`docs/research/`, the design spec) and that it changes by ticket, not by drive-by PR.
>
> ## Acceptance criteria
>
> - [ ] A first-time contributor can go from idea to merged PR using `CONTRIBUTING.md` alone
> - [ ] Nothing in it depends on Linear access
> - [ ] It matches `AGENTS.md` and `docs/agents/*` (same labels, same PR conventions), or those are updated in the same PR
>
> ## Notes
>
> Ponytail: one page, no templates or bots unless the grilling proves they're needed.

---

## 7. Notes for other tickets (to add when they're next touched)

- **CBO-47:** replace `version = "0.0.0"` in `pyproject.toml` with the release version.
- **CBO-64:** add `pytest`, `pyright` and `pip-audit` to `[dependency-groups] dev` as each is adopted, and add them to the CI job that runs them.
- **CBO-63:** the README's test section is already a pointer to CONTRIBUTING.md. For the "no content lost" check, count CONTRIBUTING.md as a valid destination.
