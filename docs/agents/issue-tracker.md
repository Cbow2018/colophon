# Issue tracker: Linear

Issues and specs for this repo live in **Linear** — workspace `cbow`, team
**Athenaeus**, project **Colophon**. Identifiers look like `CBO-35`. The design
spec is **CBO-33**, and the build tickets are its sub-issues.

GitHub is where the **code and pull requests** live (`Cbow2018/colophon`); the
`CBO-*` tickets are not mirrored into GitHub Issues, so `gh` is for pull
requests and CI only. If you are looking for a ticket, look in Linear.

## Conventions

Agents reach Linear through its own tools (`mcp__linear__*`), not the web UI.

- **Read an issue**: `get_issue` with the identifier, plus
  `includeRelations=true` when the blocking edges matter — they usually do.
- **List issues**: `list_issues` with `team="Athenaeus"`, narrowing with
  `state`, `label`, `project`, `assignee` or `cycle`. `query` searches title and
  description. `limit` is capped at 250, and pages use `cursor`.
- **Create an issue**: `save_issue` with `team="Athenaeus"`, a `title`, a
  markdown `description`, and `project="Colophon"`. Titles in this project are
  numbered by build order, e.g. `02 Exact ISBN match via Hardcover`.
- **Update**: `save_issue` with the identifier in `id` and only the fields that
  changed — `state`, `assignee="me"`, `addLabels`, `priority`, `estimate`.
- **Comment**: `save_comment` with `issueId`.
- **Attach the pull request**: pass `links=[{url, title}]` to `save_issue`. The
  Linear GitHub integration attaches PRs on its own as well, once the ticket
  identifier appears in the title or branch.
- **Close**: `save_issue` with `state="Done"`. A ticket is finished when its PR
  is merged, not before.

## Blocking, sub-issues and labels

- **Blocking**: `blockedBy` and `blocks` on `save_issue` (append-only), removed
  with `removeBlockedBy` / `removeBlocks`. A ticket is unblocked when every
  blocker is Done. `get_issue` reports these under `relations`.
- **Sub-issues**: `parentId`. Every build ticket names CBO-33 as its parent.
- **Labels**: the vocabulary the skills speak is listed in
  `docs/agents/triage-labels.md`; apply it with `labels` (which replaces the
  set) or `addLabels` (which only adds).

## States

`Backlog` → `Todo` → `In Progress` → `In Review` → `Done`, plus `Duplicate` and
`Canceled`.

The GitHub integration moves issues by itself: opening a PR can push a ticket to
**In Progress**, and marking a PR ready for review can move it to **In Review**.
Set a state by hand only when the automation will not, and expect a hand-set
state to be overridden moments later if a PR event disagrees with it.

## Pull requests

Review happens on GitHub, in `Cbow2018/colophon`.

- **Open one**: `gh pr create --base main --head <branch> --title "CBO-35: …"
  --body-file <file>`, with the ticket identifier in the title so Linear links
  it.
- **Read one**: `gh pr view <number> --comments`, `gh pr diff <number>`.
- **Checks**: `gh pr checks <number> --watch`.
- **PRs as a request surface for triage: no.** External pull requests are not
  feature requests here; new work is filed in Linear. (Set this to `yes` if that
  ever changes; `/triage` reads the flag.)

## When a skill says "publish to the issue tracker"

Create a Linear issue: `save_issue` with `team="Athenaeus"`,
`project="Colophon"`, a title and a markdown description.

## When a skill says "fetch the relevant ticket"

`get_issue` with the identifier, `includeRelations=true`.

## Wayfinding operations

Used by `/wayfinder`. The **map** is a single Linear issue labelled
`wayfinder:map`, holding the Notes / Decisions-so-far / Fog body. Its **child
tickets** are sub-issues (`parentId`), labelled `wayfinder:<type>` —
`research`, `prototype`, `grilling` or `task`.

- **Frontier query**: list the map's open children
  (`list_issues` with `parentId`), drop any with an open blocker
  (`relations.blockedBy` holding a ticket that is not Done) or an assignee;
  first in map order wins.
- **Claim**: `save_issue` with `assignee="me"` and `state="In Progress"` — the
  session's first write.
- **Resolve**: `save_comment` with the answer, `save_issue` with
  `state="Done"`, then append a context pointer — the gist and the link — to the
  map's Decisions-so-far.
