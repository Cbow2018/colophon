# CBO-77 research — dependency manifest

**Ticket:** [CBO-77](https://linear.app/cbow/issue/CBO-77/no-pyprojecttoml-or-dependency-manifest-a-contributor-cannot-install) — No pyproject.toml or dependency manifest; a contributor cannot install the project
**Researched:** 2026-09-24, against `main` at `22f456b` (merge of PR #19, CBO-74)
**Mode:** research only. No repo, git, Linear or local-machine writes. Grilled with Callum; every design branch closed.
**Companion files:** `cbo-77-proposed-changes.md` (the drafts), `cbo-77-adr-draft.md`

---

## 1. Summary

- **Colophon has no third-party dependencies at all.** Every import in `colophon/`, `tests/` and `tools/` is standard library. The ticket's premise ("works only because the maintainer's machine happens to have the right packages installed") does not hold. The Dockerfile and the CI tests job already install nothing, and the README already says "No dependencies to install".
- **The only dev tool is ruff, pinned at 0.16.8** in one CI line. The suite is `unittest`, and nothing uses pytest today. CBO-64 plans to bring in pytest, pyright and pip-audit.
- **The Python floor is 3.11**, because the code uses `tomllib` and `datetime.UTC`. Confirmed in the sandbox: the suite passes on 3.11, 3.12 and 3.13 and fails on 3.10 with `No module named 'tomllib'`.
- **Stating the floor changes what ruff enforces.** ruff reads `requires-python` as its target version, and today it defaults to py310. With `>=3.11` present, `ruff check` reports two new errors (I001 in `config.py`, UP017 in `relay.py`). Both are auto-fixable, three lines in total, with no change in behaviour. The build PR has to fix them, or CI goes red.
- **What to build:** a `pyproject.toml` with no build system, holding `[project]` (name, placeholder version, `requires-python`, empty `dependencies`) and a `[dependency-groups] dev` list. Also a `CONTRIBUTING.md` with the setup steps, a two-line README pointer, and two lines changed in the CI ruff job. The Dockerfile stays as it is.

---

## 2. Checking the ticket's premise

| Ticket claim | Finding |
|---|---|
| Root has no `pyproject.toml`, `requirements.txt` or lockfile | **Still true** at `22f456b`. The root is `.git-blame-ignore-revs`, `.github/`, `.gitignore`, `AGENTS.md`, `Dockerfile`, `LICENSE`, `README.md`, `colophon/`, `config.example.toml`, `docker-compose.example.yml`, `docs/`, `tests/`, `tools/`. `tools/` (the fixture recorder) arrived after the ticket was written. The `scratch/` and `pr-cbo-*.md` in the ticket's list are gitignored local files, so a clean clone doesn't have them. No `ruff.toml`, `.python-version`, `setup.cfg`, `tox.ini` or lockfile anywhere. |
| "Works today only because … the maintainer's machine happens to have the right packages installed" | **False.** There are no third-party imports (§4). Any Python 3.11+ runs it and its tests with nothing installed. |
| "No stated Python version" | **Partly true.** The README says the tests run "on Python 3.11 and 3.12" in CI, the Dockerfile says `python:3.11-slim`, and CBO-33 says "Python 3.11+". Nothing machine-readable states it. |
| "CI is installing dependencies some other way … the de facto manifest" | **Only ruff.** The tests job installs nothing. The ruff job runs `pip install ruff==0.16.8` (`tests.yml:29`). The container job builds the Dockerfile, which installs nothing. |
| Dev deps: "pytest, ruff at its existing pin" | **pytest is not used** (§4.2). ruff only. |
| "ruff is pinned at 0.16.8 and that pin is load-bearing" | **True.** The reason is in §4.3. |

So the real gap is narrower than the ticket describes. Two things are missing: (1) the Python floor is not declared anywhere a tool can read it, and (2) the ruff pin lives only in a CI script, and there is no written contributor path. The acceptance criteria still apply as written.

---

## 3. Where dependencies live today

| Place | What it installs or implies | Evidence |
|---|---|---|
| `Dockerfile` | Nothing. `FROM python:3.11-slim`, copies `colophon/`, `ENTRYPOINT ["python", "-m", "colophon"]` | `Dockerfile:1,3,16`: "Colophon is standard library only, so there is nothing to install." |
| `.github/workflows/tests.yml` job `tests` | Nothing. Matrix of 3.11 and 3.12, runs `python -m unittest discover -s tests -t . --verbose` | `tests.yml:12,19` |
| `.github/workflows/tests.yml` job `ruff` | `pip install ruff==0.16.8` on Python 3.11, then `ruff check .` and `ruff format --check .` | `tests.yml:27,29` |
| `.github/workflows/tests.yml` job `container` | Builds the image, relays one book through a read-only, non-root container | no installs |
| `docker-compose.example.yml` | Pulls `ghcr.io/cbow2018/colophon:v1.0.0`. No dependency implications | — |
| `README.md` "Running the tests" | "No dependencies to install", the unittest command, "on Python 3.11 and 3.12" | `README.md:374–382` |
| `AGENTS.md` | Nothing about dependencies (trackers, triage labels, domain docs only) | — |
| `.gitignore` | Stock GitHub Python template. Already ignores `.venv`, `venv/`, `build/`, `*.egg-info/`, `.pytest_cache/` | lines 11–26, 51, 153–158 |

**Other tickets.** PR #18 (CBO-68, In Review) adds only `docs/research-cbo-68.md` and changes no dependency, import, Dockerfile or workflow (`git diff main...pr18 --stat`: 1 file). CBO-63 (README declutter) doesn't mention dependencies. The new README pointer is two lines, which fits its direction.

---

## 4. The dependency list, taken from the code

### 4.1 Runtime

Method: an AST walk over every `.py` under `colophon/`, `tests/` and `tools/`. Each top-level imported module was checked against `sys.stdlib_module_names` (3.11). The only dynamic import is `importlib.util.spec_from_file_location` in `tests/test_recording_tools.py:22`, which loads `tools/record-fixtures.py`, and that file is also stdlib only.

| Tree | Non-stdlib imports |
|---|---|
| `colophon/` | **none** (dataclasses, datetime, difflib, hashlib, itertools, json, logging, os, pathlib, re, shutil, signal, sqlite3, sys, threading, time, tomllib, unicodedata, urllib, xml, zipfile) |
| `tests/` | **none** (the above, plus base64, contextlib, http, importlib, inspect, io, secrets, struct, tempfile, textwrap, unittest, zlib) |
| `tools/` | **none** (argparse, json, os, pathlib, re, sys, time, urllib) |

**Runtime dependencies: none.** This matches CBO-33 ("standard library only") and the Dockerfile comment.

### 4.2 Dev and test tools

| Tool | Used by | Installed by | Status |
|---|---|---|---|
| `unittest` | the whole suite, CI `tests` job, README | stdlib | nothing to declare |
| `ruff==0.16.8` | CI `ruff` job (`check` and `format --check`) | `tests.yml:29` | **declare it, exact pin** |
| pytest | nothing | nothing | **not used.** Searched every branch, all 19 PR heads and all history (`git log --all -S pytest`, `git grep` on every ref). The only hits are `.pytest_cache/` in the template `.gitignore` and a figure of speech in `docs/research-cbo-59.md:136`. No `conftest.py`, no `@pytest` anywhere. |
| pytest, pyright, pip-audit | **planned** in CBO-64 (risk-first audit, Phase 4 "parameterised pytest tests", Phase 7 tooling) | — | CBO-64 adds each to the `dev` group when it starts using it (decision D4) |

Nothing is installed without being used. Nothing is used without being installed.

### 4.3 Why ruff is pinned at 0.16.8

From commit `3d0962a` (2026-09-19, PR #4, "Add a ruff lint job to CI and fix what it flags"):

> ruff is pinned to 0.16.8 because its default rule set has grown well past the old E/F core: 0.16.8 enables 413 rules across 36 linters, including isort (I) and flake8-simplify (SIM), so an unpinned install would silently change what CI enforces. There is deliberately no config file, so the job lints with ruff defaults alone.
>
> … config.py imported tomllib alongside the stdlib imports, but with no config file ruff assumes target-version py310, where tomllib is not yet stdlib, so it sorts as third-party.

CBO-50 (`0a364ad`, `bdfecd8`, PR #15) later added `ruff format --check` under the same pin. `0a364ad` is listed in `.git-blame-ignore-revs`.

**This affects CBO-77:** the `tomllib` workaround described above is exactly what `requires-python = ">=3.11"` undoes (§6).

---

## 5. Python version floor: **3.11**

| Evidence | Needs |
|---|---|
| `colophon/config.py:11` `import tomllib` (also `:237`, `:242`) | 3.11 |
| `colophon/llm.py:643` `datetime.datetime.now(datetime.UTC)` | 3.11 |
| Sandbox: `python3.10 -m unittest discover -s tests -t .` | **FAILED (errors=5)**: `ModuleNotFoundError: No module named 'tomllib'` (test_config, test_correction, test_llm, test_main, test_relay fail to import) |
| Sandbox: the same on 3.11.15, 3.12.3, 3.13.13 | **876 tests, OK (skipped=1)** on each |
| No 3.12+ feature is needed | the suite passes on 3.11 |
| CI | tests on 3.11 and 3.12; ruff on 3.11 |
| Dockerfile | `python:3.11-slim` |

The floor matches everywhere it is currently implied. `requires-python = ">=3.11"` states it. No upper bound, because capping Python is a known anti-pattern and 3.13 passes.

---

## 6. Decisions (grilled 2026-09-24)

| # | Decision | Why |
|---|---|---|
| D1 | **Fix the two new ruff findings in the build PR** (`ruff check --fix`): `config.py` I001 moves `import tomllib` into the stdlib block, and `relay.py` UP017 changes `timezone.utc` to `UTC`. Three lines, no behaviour change. | Keeping `target-version = "py310"` would contradict the floor that was just stated. Leaving `requires-python` out fails the acceptance criteria. |
| D2 | **Dev tools go in a PEP 735 dependency group** (`[dependency-groups] dev`), installed with `pip install --group dev`. **No `[build-system]`, no `pip install .`, no `[project.scripts]`.** | Nothing needs Colophon to be a package. It runs as `python -m colophon` from the source tree (Dockerfile `ENTRYPOINT`, README). Tested alternative: `[project.optional-dependencies]` with `pip install -e ".[dev]"` works on pip 24.0, but it downloads setuptools, builds and installs Colophon into the venv, and writes `build/` and `colophon.egg-info/`. That is packaging for nothing. → ADR draft. |
| D2a | **Upgrade pip first** (`python -m pip install --upgrade pip`) in CONTRIBUTING and CI. | `--group` needs pip ≥ 25.1. A fresh venv on 3.11 or 3.12 comes with **pip 24.0**, which fails with `no such option: --group` (sandbox). 3.13 comes with 26.0.1, where the upgrade does no harm. |
| D3 | **`version = "0.0.0"`** placeholder. | `[project]` needs a version. There is no `__version__` and no tag. Nothing reads it (no build). **CBO-47 sets the real version at v1.0.0.** |
| D4 | **Dev group = `ruff==0.16.8` only**, exact, with its reason as a comment. `dependencies = []` written out. No pytest. | Nothing uses pytest. **CBO-64 adds pytest, pyright and pip-audit to `dev` when it introduces them.** Runtime floors or pins: none needed, because there are no runtime dependencies. |
| D5 | **Dockerfile unchanged.** | It installs nothing because there is nothing to install. "The Dockerfile installs from the manifest" is already true. Adding `pip install .` would build a package into the image for no benefit. The image has no pip step to reconcile. |
| D6 | **Contributor steps go in a new `CONTRIBUTING.md`** (GitHub links to it from new issues and PRs). | Callum's choice over editing the README section where it is. |
| D7 | **CONTRIBUTING.md covers setup only**: Python 3.11+, clone, venv, upgrade pip, install the dev group, run the tests, run ruff. macOS/Linux, plus the Windows activate line. | The ticket asks for setup. The PR and issue conventions in `AGENTS.md` are written for agents working from Linear. **A follow-up ticket fills out CONTRIBUTING.md after v1** (draft in `cbo-77-proposed-changes.md` §6). |
| D8 | **README: "Running the tests" becomes a short "Contributing" section** stating the 3.11 floor, no runtime dependencies, and a link to CONTRIBUTING.md for tests and contributions. | Nothing is lost (CBO-63's rule). The unittest command and the "3.11 and 3.12 in CI" line move to CONTRIBUTING.md. "From the README alone" holds, because the README links straight to the steps. |
| D9 | **The README includes the ruff commands**, and says the tests alone need nothing installed. | CI fails a PR on either ruff command. The venv only exists for ruff. |
| D10 | **CI ruff job:** `pip install ruff==0.16.8` becomes `python -m pip install --upgrade pip` + `pip install --group dev`. The tests job and matrix stay as they are. | One list. The upgrade line removes any dependence on the runner's bundled pip version, which couldn't be checked from here. |
| D11 | **ADR draft** for "Colophon declares its dependencies but is not a package". **No glossary draft.** | This is the decision a helpful future PR is most likely to undo (adding `[build-system]` or `pip install -e .`). The ticket introduces no domain terms. |

---

## 7. Sandbox log

All in throwaway directories under the session scratchpad on the cloud container, never on Callum's Mac or in any working tree. Fresh `git clone https://github.com/Cbow2018/colophon.git` at `22f456b` each time. Everything was deleted at the end (`rm -rf …/sandbox …/final`).

Interpreters: CPython 3.10.20, 3.11.15, 3.12.3, 3.13.13. Bundled pip: 23.0.1, **24.0**, **24.0**, 26.0.1.

### 7.1 Baseline, nothing installed

| Command | Result |
|---|---|
| `python3.10 -m unittest discover -s tests -t .` | 430 run, **FAILED (errors=5)**, `No module named 'tomllib'` |
| `python3.11 …` / `python3.12 …` / `python3.13 …` | **876 run, OK (skipped=1)** each |
| venv 3.11 → `pip install ruff==0.16.8` → `ruff check .` / `ruff format --check .` | All checks passed / 62 files already formatted |
| `ruff check --show-settings colophon/config.py` (no pyproject) | `linter.unresolved_target_version = none`, `analyze.target_version = 3.10` |

### 7.2 With `requires-python = ">=3.11"` added

| Command | Result |
|---|---|
| `ruff check --show-settings …` | target version **3.11** (linter, formatter and analyze) |
| `ruff check .` | **2 errors**: `colophon/config.py:7:1 I001 Import block is un-sorted or un-formatted`, `colophon/relay.py:270:25 UP017 Use datetime.UTC alias`. Both `[*]` fixable. |
| `ruff format --check .` | 62 files already formatted (no change) |
| `ruff check --fix .` | `config.py`: `import tomllib` moves into the stdlib block after `import os`. `relay.py`: `from datetime import UTC, datetime` and `datetime.now(UTC)`. 2 files, +3 −4. (The fix run reports "4 fixed" because fixing UP017 briefly unsorts the import it touches and ruff then re-sorts it. The final diff is the one above.) |
| after the fix: `ruff check .` / `format --check .` | All checks passed / 62 files already formatted |
| after the fix: tests on 3.11, 3.12, 3.13 | OK (skipped=1) each |

### 7.3 Install paths

| Path | pip | Result |
|---|---|---|
| A: `pip install --group dev` | 24.0 (fresh 3.11 venv) | **`no such option: --group`** |
| A: `python -m pip install --upgrade pip` then `pip install --group dev` | 26.2.1 | `Successfully installed ruff-0.16.8`. `pip list`: pip, ruff, setuptools only. **Nothing built**, no `build/` or `*.egg-info` |
| B: `[project.optional-dependencies] dev` + `pip install -e ".[dev]"` (no `[build-system]`) | 24.0 | Works: "Successfully built colophon", installs `colophon-0.0.0` + ruff. Creates `build/` and `colophon.egg-info/` (both gitignored). setuptools auto-discovery picks only `colophon` as top-level. Rejected (D2). |
| A on 3.12 | 24.0 → upgraded | ruff installed, `ruff check` passes, tests OK |
| A on 3.13 | 26.0.1 (upgrade harmless) | ruff installed |
| A on **3.10** | upgraded | **`--group` installs ruff anyway. pip does not check `requires-python` for a group install.** The tests then fail on `tomllib`. So the floor is only enforced by the docs and by the error itself. CONTRIBUTING.md therefore starts with a `python3 --version` check. |

### 7.4 Final run: the CONTRIBUTING.md steps exactly, on 3.11

With the draft `pyproject.toml` from `cbo-77-proposed-changes.md` copied into a fresh clone (the TOML parses: `tomllib.load` round-trips it):

```
python3.11 -m venv .venv
. .venv/bin/activate
python --version                              # Python 3.11.15
python -m pip install --upgrade pip           # 24.0 -> 26.2.1
pip install --group dev                       # Successfully installed ruff-0.16.8
python -m unittest discover -s tests -t .     # Ran 876 tests … OK (skipped=1)
ruff check .                                  # Found 2 errors (before D1's fix) -> All checks passed! (after)
ruff format --check .                         # 62 files already formatted
```

- `.venv` inside the repo: `git status` doesn't show it (already gitignored), and `ruff check --show-files` lists no `.venv` path (ruff's default excludes).
- `git status --short` after the build's edits: ` M colophon/config.py`, ` M colophon/relay.py`, `?? pyproject.toml`, which is exactly the intended diff (plus the docs files, not simulated).

**Not tested:** the GitHub-hosted runner itself (its bundled pip version is unknown, and D10's upgrade line covers that), and `docker build` (the Dockerfile is unchanged and copies only `colophon/`, so `pyproject.toml` never reaches the image). The Windows activate line wasn't run either (no Windows host).

---

## 8. Open questions (not blocking the build)

1. **Add 3.13 to the CI test matrix?** The suite passes on 3.13.13 in the sandbox. Out of scope for CBO-77. Worth a line in CBO-64 or its own small ticket.
2. **Fill out CONTRIBUTING.md after v1** (issue-first via GitHub Issues, PR title and `Closes #N` conventions, how a public issue becomes a Linear ticket). Callum asked for a ticket. The draft is in `cbo-77-proposed-changes.md` §6, **not yet created in Linear** (this session made no Linear writes).
3. **CBO-47 (v1.0.0)** should replace `version = "0.0.0"`. Add a line to CBO-47's checklist when it's next touched.
4. **CBO-64** should add `pytest`, `pyright` and `pip-audit` to the `dev` group as it adopts them. Leave pyright's pin policy to CBO-64. If pyright is added, it also reads `requires-python`.
5. **CBO-63** gets a README that already points to CONTRIBUTING.md. Nothing to move for this section, but CBO-63's "no content lost" check should count CONTRIBUTING.md as a valid destination.
6. **Amend the CBO-77 description** (optional): the "maintainer's machine happens to have packages" and "pytest" lines are wrong (§2). Leaving them is harmless once this research is linked.

---

## 9. Implementation plan (for the build session)

One branch, one PR titled `CBO-77: …`. Test-first where there is anything to test, but this change is almost entirely config and docs. The "test" is CI itself plus a clean-clone run through CONTRIBUTING.md.

1. **Add `pyproject.toml`** exactly as drafted (`cbo-77-proposed-changes.md` §1).
2. **Run `ruff check .`**, which should show the two findings (I001 `config.py`, UP017 `relay.py`). Then run `ruff check --fix .` and `ruff format --check .`. Commit this separately from step 1 so the reason is clear: *"requires-python makes ruff target 3.11; this undoes the tomllib workaround 3d0962a describes."*
3. **Edit `.github/workflows/tests.yml`**, ruff job only (§2 of proposed changes).
4. **Add `CONTRIBUTING.md`** (§4 of proposed changes).
5. **Replace README "Running the tests"** with the "Contributing" section (§3 of proposed changes).
6. **Add the ADR** from `cbo-77-adr-draft.md` under `docs/adr/` with the next free number. That folder doesn't exist yet on `main`; `docs/agents/domain.md` names it as the ADR home.
7. **Check it:** fresh clone of the branch into a temp directory. Follow CONTRIBUTING.md word for word on 3.11 (and 3.12 if you have it). Confirm tests OK, `ruff check` clean, `ruff format --check` clean, and a clean `git status` apart from `.venv` being ignored. Push and confirm all three CI jobs are green, especially that the ruff job's pip upgrade and `--group` install work on the runner.
8. **PR description:** link this research, say that runtime dependencies are none by design (not an oversight), and list follow-ups: CBO-47 version, CBO-64 dev tools, the CONTRIBUTING-after-v1 ticket.

Dockerfile: **no change** (D5).
