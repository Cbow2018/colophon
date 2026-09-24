---
status: proposed
---

# A stated Series Placement is part of a Work's identity

CBO-68 groups a title search's candidates into Works by title head and author letters, and keeps one Standard Edition per Work. Series Placement was deliberately left out of that key (D22). So two Works that share a title and author but sit at different places in a series were merged, and whichever came out as the Standard Edition had its placement written onto the file. Because CBO-68's key ignores ISBN and year, it merges more of these pairs than `main`'s `dedupe()` did, not fewer. We decided that a stated Series Placement is part of Work identity. A group whose members state conflicting placements splits into one Work per placement. An Edition with no placement joins a group that states at most one placement, and is left out when the group states two or more. `collapse()` and `dedupe()` share the split. The file's own Claimed Placement then separates the two Works through the existing series weight, or they tie and grade medium, so neither placement is ever written unless the file supports it (CBO-65 Q1–Q11; `research-cbo-65.md` §3–§5).

This amends the consequence in the Standard Edition ADR that says "Series position is not part of Work identity yet". D22's reason still holds: an Edition with no placement keeps merging, so Hardcover and Google Editions of one Work still collapse.

## Considered Options

- **Drop a conflicting group from the pool.** Rejected. It throws away the right Work even when the file names it, and empties the pool to `none` in 288 of 720 swept scenarios.
- **Keep the group merged and strip the placement from its survivor.** Rejected. The survivor's other fields (publisher, blurb, ISBN, date) may belong to the wrong Work, so the silent error moves from the series to the rest of what gets written.
- **Keep the group merged and force the pool to medium.** Rejected. It's safe but refuses every book, including those whose Claimed Placement decides it (0 correct writes in the sweep).
- **Put the placement in the key strictly, with no placement as a value of its own.** Rejected. A Hardcover Edition with a placement and a Google Edition without one would stop merging, and a strong single candidate would drop to a medium pair. The ticket feared exactly this, and D22 was written to prevent it.
- **Only refuse to merge in `dedupe()`.** Rejected. Because `dedupe` keeps the first candidate of each group, an Edition with no placement would join whichever conflicting group it met first, and the result would depend on reply order (CBO-68 D10).
- **Change the scoring weights.** Not considered. CBO-59 F1–F3 settled that.

## Consequences

- A file with no Claimed Placement, facing two Works with conflicting placements, is marked `colophon:unverified` on an install with no LLM. It isn't written.
- When a Work merges a placement with a blank, its Standard Edition can be the Edition with no placement, and the series then isn't written. Gap fill (CBO-61) must be able to take donors from Editions the collapse removed.
- Works at the same position in differently named series always grade medium, because the scorer compares positions only.
- The real-world rate is unmeasured. The fixtures hold no such pair, and CBO-76's tuning set must include one.
