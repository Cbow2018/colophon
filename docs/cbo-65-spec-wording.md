# CBO-65: proposed design-spec wording

This goes into the design spec (CBO-33) straight after CBO-68's **The Standard Edition (title path)** rule (`cbo-68-build-brief.md` §1) and CBO-90's audio clause (`cbo-90-spec-wording.md`). It amends CBO-68's D22. Vocabulary is as in `CONTEXT.md`. The evidence is in `research-cbo-65.md`.

---

> **A Series Placement is part of a Work's identity.** Two candidates that share a title head and author letters are still two Works when both state a Series Placement and the placements conflict. Placements conflict when the series (compared ignoring case) or the position differs. A position is compared as a number when it reads as one, so `6` and `6.0` are the same position, and as text otherwise. A candidate that names neither a series nor a position states no placement.
>
> After candidates are grouped by Work, and before a Standard Edition is chosen, each group is split by Series Placement. A group stating at most one placement stays whole: an Edition with no placement belongs to it, and the Standard Edition is chosen from every member as before. A group stating two or more becomes one Work per placement, each choosing its own Standard Edition, and any Edition with no placement is left out, because nothing says which Work it belongs to. `dedupe` applies the same split to its own groups, so no step that merges candidates can join two Works that disagree about their placement. The split depends only on the candidates' values, so a title-path match still comes out the same whatever order a source lists its reply in.
>
> The two Works then go to the scorer like any other pool. A file whose title claims a placement is separated by it: the Work it names leads by the series weight and can grade strong. A file that claims none, or one neither Work has, sees two equal leaders and grades medium, so it is asked about or marked `colophon:unverified` and never written with either placement.

These limits also go into the spec:

* **Only a stated conflict splits.** A Hardcover Edition with a placement and a Google Edition with none are still one Work. If the Google Edition is that Work's Standard Edition, the book is written without a series. Filling the gap from the Hardcover Edition belongs to post-match gap fill (CBO-61), not to the Work rule.
* **The series name only separates Works, not files.** The scorer compares positions and not series names. Two Works at the same position in differently named series always grade medium.
* **The file's claim is its title, not its recorded series.** Only a Claimed Placement (the bracket in the file's title) can pick between two Works. The file's recorded series index is not compared.
* **`Book 6` is read only from the file's title.** No source sends a position in that form. A source that ever does will be compared as text, and will conflict with `6`.
* **A series with no position** conflicts with the same series at a numbered position (open question 1 in the research note; confirm before applying).

---

## Where each clause comes from

| Clause | Grilling decision |
| -- | -- |
| Placement is Work identity; split, not drop, strip or force medium | Q1 |
| Series Placement is a pair; conflict when either half differs | Q2 |
| Numeric comparison, text fallback; `Book 6` only on the file side | Q6 |
| Blank merges with at most one placement, dropped with two or more | Q9 |
| `dedupe` uses the same split | Q4, Q10 |
| Claimed Placement is the title bracket; recorded index not compared | Q3 |
| Gap in a merged Work → CBO-61 | Q5 |
| Amends D22; applied after CBO-68 merges | Q11 |

As with CBO-90's wording, the spec should not name `collapse`, `_identity` or `_series`. Those belong in code comments.
