# AGENTS.md

## Agent skills

### Issue tracker

Two trackers with separate jobs. **Linear** (workspace `cbow`, team **Athenaeus**, project **Colophon**, identifiers like `CBO-36`, reached with the `mcp__linear__*` tools) is the internal build plan — specs and build tickets — and it is where "fetch the relevant ticket", "publish to the issue tracker", `/to-spec`, `/to-tickets`, `/wayfinder` and `/code-review`'s spec lookup all point. **GitHub issues** in `Cbow2018/colophon`, driven by `gh`, are the public tracker for contributors, and `/triage` works there; external pull requests are a request surface. An accepted public issue gets a linked Linear build ticket, and the fix PR is titled `CBO-N: …` with `Closes #<issue>` in its body. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary — `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: one `CONTEXT.md` plus `docs/adr/` at the repo root. See `docs/agents/domain.md`.
