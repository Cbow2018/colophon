# Issue trackers

This repo has **two**, with separate jobs that must not be confused.

| Tracker | What lives there | Who it is for |
| --- | --- | --- |
| **Linear** | The internal build plan: specs and build tickets (`CBO-*`, the design spec **CBO-33**, build tickets as its sub-issues) | The maintainer, planning |
| **GitHub issues** | The public tracker: bug reports and feature requests from contributors, in `Cbow2018/colophon` | Anyone |

An internal ticket and a public issue are not the same object and nothing is
mirrored between them. When a public issue is accepted, it gets a **linked
Linear build ticket** (see [Handoff](#handoff-from-a-public-issue)).

## Linear — the internal build plan

Workspace `cbow`, team **Athenaeus**, project **Colophon**. Identifiers look like
`CBO-35`. Agents reach it through its own tools (`mcp__linear__*`), not the web
UI.

### Conventions

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

### Blocking, sub-issues and labels

- **Blocking**: `blockedBy` and `blocks` on `save_issue` (append-only), removed
  with `removeBlockedBy` / `removeBlocks`. A ticket is unblocked when every
  blocker is Done. `get_issue` reports these under `relations`.
- **Sub-issues**: `parentId`. Every build ticket names CBO-33 as its parent.
- **Labels**: `ready-for-agent` and `ready-for-human` mark a build ticket as
  ready for an agent or for a human to implement. Apply them with `addLabels`
  (which only adds); the full vocabulary is in `docs/agents/triage-labels.md`.

`/to-spec`, `/to-tickets`, `/wayfinder` and `/code-review`'s spec lookup all
plan against this tracker; `/triage` is the one that works GitHub.

### States

`Backlog` → `Todo` → `In Progress` → `In Review` → `Done`, plus `Duplicate` and
`Canceled`.

The GitHub integration moves issues by itself: opening a PR can push a ticket to
**In Progress**, and marking a PR ready for review can move it to **In Review**.
Set a state by hand only when the automation will not, and expect a hand-set
state to be overridden moments later if a PR event disagrees with it.

## GitHub — the public tracker

Bug reports and feature requests from outside, in `Cbow2018/colophon`, driven by
the `gh` CLI. This is the tracker a contributor can read, file against and be
answered in.

- **List issues**: `gh issue list`, narrowed with `--label`, `--state` or
  `--search`.
- **Read one**: `gh issue view <number> --comments`.
- **Create one**: `gh issue create --title … --body-file <file>`, with the
  triage labels that fit.
- **Comment**: `gh issue comment <number> --body …`.
- **Close**: `gh issue close <number>`, with a comment saying what closed it.
- **Labels**: the five triage roles in `docs/agents/triage-labels.md`, applied
  as written.
- **PRs as a request surface for triage: yes.** An external pull request is a
  contribution to read and answer, and a feature request that arrives as one is
  still a feature request. (Set this to `no` if that ever changes; `/triage`
  reads the flag.)

`/triage` is the skill that works this tracker.

## Handoff from a public issue

An accepted public issue becomes work on the internal plan, and the two stay
linked:

1. **Create a Linear build ticket** for the accepted issue, with the GitHub
   issue URL in its `description` so the two can be read together either way.
   This is a `save_issue` against `team="Athenaeus"`, `project="Colophon"`.
2. **Label it** `ready-for-agent` or `ready-for-human`, per
   `docs/agents/triage-labels.md`.
3. **The fix PR is titled `CBO-N: …`** after that ticket, and its **body says
   `Closes #<issue>`** for the GitHub issue, so merging closes the public report
   and the Linear ticket is linked by its identifier in the title.

## Pull requests

Review happens on GitHub, in `Cbow2018/colophon`.

- **Open one**: `gh pr create --base main --head <branch> --title "CBO-35: …"
  --body-file <file>`, with the ticket identifier in the title so Linear links
  it, and `Closes #<issue>` in the body when it closes a public issue.
- **Read one**: `gh pr view <number> --comments`, `gh pr diff <number>`.
- **Checks**: `gh pr checks <number> --watch`.

## When a skill says "publish to the issue tracker"

**Linear.** `/to-spec`, `/to-tickets` and the rest of the build skills are
planning against the internal plan: create a Linear issue with `save_issue`
(`team="Athenaeus"`, `project="Colophon"`, a title and a markdown description).

Public issues are already on GitHub; `/triage` labels and answers them there,
and an accepted one gets a Linear ticket per the Handoff section.

## When a skill says "fetch the relevant ticket"

A `CBO-*` identifier is a Linear ticket: `get_issue` with the identifier,
`includeRelations=true`. A bare `#42` is a GitHub issue: `gh issue view 42`.

This is what `/code-review` uses to find the spec behind a branch: the branch
name carries the `CBO-*` identifier, and the spec is that Linear ticket — or
CBO-33, the design spec it hangs off.

## Wayfinding operations

Used by `/wayfinder`, on **Linear** — the map is internal planning, not a public
issue.

The **map** is a single Linear issue labelled `wayfinder:map`, holding the
Notes / Decisions-so-far / Fog body. Its **child tickets** are sub-issues
(`parentId`), labelled `wayfinder:<type>` — `research`, `prototype`, `grilling`
or `task`.

- **Frontier query**: list the map's open children
  (`list_issues` with `parentId`), drop any with an open blocker
  (`relations.blockedBy` holding a ticket that is not Done) or an assignee;
  first in map order wins.
- **Claim**: `save_issue` with `assignee="me"` and `state="In Progress"` — the
  session's first write.
- **Resolve**: `save_comment` with the answer, `save_issue` with `state="Done"`,
  then append a context pointer — the gist and the link — to the map's
  Decisions-so-far.
