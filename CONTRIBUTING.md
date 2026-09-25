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
