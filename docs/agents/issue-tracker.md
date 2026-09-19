# Issue tracker: GitHub

Public issues and specs for this repo live as **GitHub issues** in
`Cbow2018/colophon`, driven by the `gh` CLI. That is the tracker anyone can
read, file against and be answered in.

**Linear is the maintainer's private todo list and nothing else.** Workspace
`cbow`, team **Athenaeus**, project **Colophon**; identifiers look like
`CBO-36`. It is planning, not a tracker: nothing there is public, nothing is
mirrored into GitHub, and a `CBO-*` number means nothing to a contributor. An
agent may read it when the maintainer points at a ticket by number, and should
never treat it as the place to file, answer or look up public work.

## Conventions

### GitHub — the public tracker

- **List issues**: `gh issue list`, narrowed with `--label`, `--state` or
  `--search`.
- **Read one**: `gh issue view <number> --comments`.
- **Create one**: `gh issue create --title … --body-file <file>`, with the
  triage labels that fit.
- **Comment**: `gh issue comment <number> --body …`.
- **Close**: `gh issue close <number>`, with a comment saying what closed it.
- **Labels**: the five roles in `triage-labels.md`, applied as written.
- **Pull requests as a request surface for triage: yes.** An external pull
  request is a contribution to read and answer, and a feature request that
  arrives as one is still a feature request. (Set this to `no` if that ever
  changes; `/triage` reads the flag.)

### Linear — the maintainer's notes

Only when the maintainer names a ticket by number. Read it with `get_issue`,
plus `includeRelations=true` when the blocking edges matter. The states
(`Backlog` → `Todo` → `In Progress` → `In Review` → `Done`), the parent links
and the labels are the maintainer's own, and a hand-set state can be
overwritten by whatever automation the maintainer runs.

## Pull requests

Review happens on GitHub, in `Cbow2018/colophon`.

- **Open one**: `gh pr create --base main --head <branch> --title "…"
  --body-file <file>`. A branch for one of the maintainer's own tickets names
  it, so the title or body says which `CBO-*` it came from; a contribution from
  anyone else usually has no ticket at all.
- **Read one**: `gh pr view <number> --comments`, `gh pr diff <number>`.
- **Checks**: `gh pr checks <number> --watch`.

## When a skill says "publish to the issue tracker"

`gh issue create` — a GitHub issue, with triage labels.

## When a skill says "fetch the relevant ticket"

A `CBO-*` identifier is a Linear note the maintainer is pointing at: `get_issue`
with the identifier, and `includeRelations=true`. Anything else is a GitHub
issue: `gh issue view <number>`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single GitHub issue labelled
`wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. Its **child
tickets** are GitHub issues carrying the map's number in their body and a
`wayfinder:<type>` label — `research`, `prototype`, `grilling` or `task`.

- **Frontier query**: list the map's children (`gh issue list --label
  wayfinder:<type>`), drop any blocked by an open issue or already assigned;
  first in map order wins.
- **Claim**: assign it (`gh issue edit <number> --add-assignee @me`).
- **Resolve**: comment the answer (`gh issue comment`), close it (`gh issue
  close`), then append a context pointer — the gist and the link — to the map's
  Decisions-so-far.
