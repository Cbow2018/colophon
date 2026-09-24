# CBO-65: two Works that differ only in Series Placement are merged, and the wrong placement gets written

Research only (2026-09-24). Nothing in the repository was changed, committed, branched, stashed or pushed, and no Linear status was changed. Every measurement came from a throwaway clone in a cloud sandbox, and the clone was deleted at the end (§8). This note and the other CBO-65 files are the only output.

Read with: CBO-65 and its D22 comment, CBO-68 (PR #18, `dsh/cbo-68-standard-edition-rule`), `research-cbo-68.md` (session 1b), `cbo-68-build-brief.md`, `adr-draft-standard-edition.md`, `docs/research-cbo-59.md` F1–F3, CBO-58, CBO-61, CBO-69, CBO-72, CBO-73 and CBO-76. Vocabulary is as in `CONTEXT.md` in this folder: **Work**, **Edition**, **Standard Edition**, **Series Placement** and **Claimed Placement**.

## Answers, in the order asked

1. **Rate.** In the recorded fixtures it is **0**: 0 conflicting groups among 51 replies and 74 candidates, under both `main`'s key and CBO-68's Work key. The real-world rate **can't be measured**. CBO-76 doesn't exist yet, and no fixture holds two Hardcover Works that share a title and author but differ in Series Placement. The mechanism does exist: Hardcover already holds 3 separate *Good Omens* Works (`works-good-omens-authors.json`). §2 has the details.
2. **The rule.** A stated Series Placement is part of a Work's identity. A group with conflicting placements **splits** into one Work per placement, and the scorer decides between them. A missing placement merges with the group when the group states at most one placement, and is **dropped** when it states two or more. The same split is used by both `collapse()` and `dedupe()`. Placements are compared as a (series, position) pair, with the position read as a number where it parses. §4 has the rule and §5 the decisions.
3. **Band impact.** On the fixture walk, **no band changes under any option** (§3.1). F2's population is single-candidate pools, which no merge rule can touch (§3.2). On a 720-scenario sweep of two-Work pools, the chosen rule removes every wrong and every unsupported write: CBO-68 alone makes 30 wrong writes and 60 unsupported guesses, and the chosen rule makes 0 and 0. It also raises correct writes from 60 to 118 (§3.3). On the placement-plus-blank case the chosen rule is **identical to CBO-68** in all 96 scenarios (§3.4).
4. **CBO-68 interaction.** CBO-68 **widens** the hole. Its Work key ignores both ISBN and year, so two Works carrying ISBNs are now merged; on `main` they never were. It also makes the survivor deterministic (order-dependent scenarios drop from 40 to 0), so where it's wrong, it's wrong on every run. D22 is amended rather than reversed: Editions with no placement still merge (§6).
5. **Scoring was not reweighted.** No weight, threshold or `BAND_GAP` value was changed or proposed. The chosen rule works *because* the existing series weight (0.20) separates the two Works once the scorer is allowed to see both.

---

## 1. Current behaviour, with code references (`main` at `22f456b`)

* **`dedupe()`** (`colophon/matching.py:476-499`) keeps the first candidate of each group, so the order is input order. The key is `_identity()` (`:773-783`): the ISBN-13 when there is one, otherwise `("key", comparison_text(title), _name(first author), year)`. A candidate with an ISBN is never grouped with one without (`test_a_record_with_an_isbn_is_not_grouped_with_one_without`).
* **Where it runs.** Only on the title path: `correction.py:706`, `pool = dedupe([*pool, *candidates])`, inside `_gather`. The ISBN path (`_by_isbn`, `:566-576`) writes the first source's hit and never pools.
* **Where the placement comes from.** Only Hardcover supplies one. `hardcover._series()` picks the featured membership (`hardcover.py:410-431`), and `_as_position()` stores the number as `{float:g}` (`:434-441`). Google Books never sets `series` or `series_number`.
* **The file's side.** `score_candidate` reads the **Claimed Placement** from the file's title bracket (`_parts_of`, `matching.py:626-642`, which also uses `{float:g}`). It compares it with `str(file) == str(candidate)` (`:427-429`, `SERIES_WEIGHT` 0.20). The file's recorded OPF `series_index` is never compared.
* **Where the placement is written.** `correction.py:1290-1327` (`_series_edits`) writes the winning candidate's series and number under `overwrite` (`config.py:71`), as long as the book ends up in that series.
* **Hardcover pre-collapse on `main`.** `hardcover._candidates` (`:337-356`) keeps the first Edition of each `book.id`. Two different Works therefore both reach the pool, and only `dedupe()` can merge them.

**When `main` merges two Works with different placements.** Both candidates must have the same normalised full title, the same first author and the same year, **and** either both lack an ISBN-13 or they share one. Since CBO-73 put the ISBN back into the Hardcover title query, 2 of the 8 Hardcover title-path Editions in the fixtures lack an ISBN-13 (Belsay's, and one of Berwick's two). 2 of the 26 Google title-path Editions lack one too. CBO-59 F3's reproduction ("`dedupe` returns 1") used candidates with no ISBN. So on `main` the hole exists but is narrow.

**When the wrong placement is written *silently*.** The file must have no Claimed Placement, i.e. no bracket in its title. With a bracket, a merged survivor that contradicts it scores 0.9000 alone (0.9070 with a year). That is below `singleton_score` 0.95, so the book is graded medium and marked `colophon:unverified` on a default install. It isn't written.

**The design already expects the two-Work pool.** `test_matching.py` ranks {#6, #11} against a `Book 6` file to strong (gap 0.1000 at denominator 2.00, 0.0930 at 2.15). That pool can't reach the scorer while `dedupe()` merges it first.

## 2. The rate

### 2.1 Fixture census (`scratch/census65.py`, Appendix A)

| Measure | Value |
| -- | -- |
| Replies (every Hardcover and Google fixture, hand-made included) | 51 |
| Candidates, every Edition handed up (D12) | 74 |
| Candidates carrying a Series Placement | 26 (all Hardcover) |
| Groups with **conflicting** placements, `main`'s `_identity` key | **0** |
| Groups with **conflicting** placements, CBO-68 Work key | **0** |
| Groups mixing one placement with a blank, `_identity` | 2: Cragside and The Infirmary (Ross), Hardcover + Google sharing an ISBN |
| Groups mixing one placement with a blank, Work key | 4: Cragside, Berwick, Belsay, The Infirmary (Ross) |

Every Hardcover title fixture gives all Editions of a Work the same placement, which is expected since `book_series` is a field on the Work.

### 2.2 Fixture walk

Across the whole fixture walk (§3.1): 7 books plus 3 dated Cragside files, × 4 source configurations, × 7 modes, with 50 shuffled replays each. The split fires **0 times**, so `main` = `mainA` and `c68` = A = B = C = D in every cell.

### 2.3 What the rate can't tell us

The corpus has one author's series and one public-domain story, so it can't produce two Works that share a title and author. The case needs Hardcover to hold duplicate Works, or a novel and a novella with the same title in one series. The first is known to happen: `works-good-omens-authors.json` holds three *Good Omens* Works, `2955939`, `315038` and `438096`. `main`'s first-author key would merge `315038` and `438096` if their years matched and neither had an ISBN. That fixture carries no series data, so it can't show a conflict.

**Decision (CBO-65 Q7):** the rate is reported as unmeasurable, and CBO-76's tuning set must include at least one duplicate-Work series case. §7 lists this.

## 3. Band impact, measured

Every mode is simulated around the shipped walk. Only the pool-merge line changes, and nothing in `colophon/` is edited. There is **no LLM** (`llm=None`), so medium means `colophon:unverified`.

| Mode | What it is |
| -- | -- |
| `main` | Shipped code |
| `mainA` | `main`, with `dedupe()` splitting groups by placement (the chosen rule, without CBO-68) |
| `c68` | CBO-68 as briefed: Work key (title head + author letters after `_name`), Standard Edition by D15 (date → source list → completeness → payload), Hardcover handing up every Edition (D12), then `dedupe()` |
| **A (chosen)** | `c68`, with `collapse()` and `dedupe()` splitting by placement; a blank placement merges only when there's one placement, and is dropped when there are two or more |
| B | `c68`, dropping a conflicting group entirely |
| C | `c68`, keeping the group merged but stripping series and position from its survivor |
| D | `c68`, keeping the group merged but capping the pool at medium when the leader came from a conflicting group |

**About the PR #18 branch.** The branch contains `docs/research-cbo-68.md` only (`git diff --stat main...origin/dsh/cbo-68-standard-edition-rule`: 1 file, 618 insertions). There is no `collapse()` to run. So `c68` simulates the build brief's §1 rule with D15, reusing session 1b's `research-cbo-68-probe.py` transports and population unchanged. `main` versus `c68` is the difference between the two branches.

### 3.1 The fixture walk: before and after

The real `Corrector.correct` runs on EPUBs, with 50 shuffled replays per cell. A cell shows band(pool size) and [distinct outcomes].

**Band counts per configuration** (10 files each):

| Configuration | `main` | `mainA` | `c68` | A | B | C | D |
| -- | -- | -- | -- | -- | -- | -- | -- |
| Hardcover, then Google (shipped order) | 6 strong / 3 med / 1 none | same | same | same | same | same | same |
| Google, then Hardcover | 4 / 5 / 1 | 4 / 5 / 1 | 6 / 3 / 1 | 6 / 3 / 1 | 6 / 3 / 1 | 6 / 3 / 1 | 6 / 3 / 1 |
| Hardcover only | 6 / 2 / 2 | same | same | same | same | same | same |
| Google only | 4 / 5 / 1 | 4 / 5 / 1 | 6 / 3 / 1 | 6 / 3 / 1 | 6 / 3 / 1 | 6 / 3 / 1 | 6 / 3 / 1 |

* **CBO-65's options change nothing on the fixtures.** A = B = C = D = `c68`, and `mainA` = `main`, in every cell, band and written placement alike. Every change in the table is CBO-68's (Cragside moves from medium to strong on the Google-first configurations, and Cragside dated 2017 likewise), which agrees with session 1b §0.4.
* **Written placements are unchanged.** Cragside #6, Berwick #24, Belsay #23 and The Infirmary (Ross) #11 are written wherever they were strong before.
* **Determinism.** `main` and `mainA` vary by reply order on Berwick (2 outcomes), The Infirmary (Ross) (3) and Poe (10). This is CBO-68's defect and is untouched by CBO-65. Every CBO-68-based mode gives 1 outcome everywhere.
* **Caveat:** on configurations that ask Hardcover, Poe and *The Cragside Compendium of Nothing* have no Hardcover recording. The walk records Hardcover as errored and those books are held. This is the same limit as session 1b §0.1 item 6.

### 3.2 F2's baseline

F2 (`docs/research-cbo-59.md`) is a sweep of single-candidate pools: 1,071 rows, and a 4,950-pair census. A pool of one has nothing to merge. Checked directly: `merge([c]) == [c]` in every mode. **F2's band distribution is unchanged under every option, including the chosen one.** F2's own probe scripts weren't committed, so its sweep wasn't re-run. The check above is the proof that it can't move.

### 3.3 The two-Work sweep, which is where the options differ

This is the F2 shape extended with pools of two Works. `twin_sweep` in Appendix A defines it: **720 scenarios**.

* **Pair**: position conflict (#6 against #11, same series), or series conflict (both #6, "DCI Ryan Mysteries" against "Another Series").
* **ISBNs**: both Works carry one, or neither does.
* **The second Work's date**: same (2017-07-07), later (2019) or earlier (2016).
* **Google Edition with no placement**: absent, present with the same date, or present and earliest (2016).
* **Claimed Placement**: `Book 6`, `Book 11`, `Book 3` (neither) or none.
* **File year**: none, 2017 or 2019.
* **Source order**: Hardcover first or Google first.
* **Each scenario is run with Hardcover's reply in both orders.**

An outcome counts once per distinct result the reply orders can produce.

| Outcome | `main` | `mainA` | `c68` | **A** | B | C | D |
| -- | -- | -- | -- | -- | -- | -- | -- |
| Correct write (the claimed Work's placement) | 96 | 92 | 60 | **118** | 0 | 0 | 0 |
| **Wrong write**: contradicts the Claimed Placement | 12 | 0 | **30** | **0** | 0 | 0 | 0 |
| **Unsupported guess**: no Claimed Placement, one of two Works written | 24 | 0 | **60** | **0** | 0 | 0 | 0 |
| Not written, medium (unverified) | 446 | 452 | 408 | 458 | 144 | 336 | 528 |
| Not written, none (empty pool) | 0 | 0 | 0 | 0 | 288 | 0 | 0 |
| Written with no series | 182 | 176 | 162 | 144 | 288 | 384 | 192 |
| Scenarios whose outcome depends on reply order | **40** | 0 | 0 | 0 | 0 | 0 | 0 |

The same table restricted to **both Works carrying an ISBN**, which is the normal Hardcover case since CBO-73:

| Outcome | `main` | `c68` | **A** |
| -- | -- | -- | -- |
| Correct write | 45 | 30 | **59** |
| Wrong write | **0** | **15** | 0 |
| Unsupported guess | **0** | **30** | 0 |

**Reading it:**

* **A is the only option with no wrong writes, no unsupported guesses, and more correct writes than today.** A `Book 6` or `Book 11` file facing a position conflict gets the right Work strong. A file with no claim, or a claim of `Book 3`, gets medium, so the book is marked and not written.
* **A does give up some correct writes: 30 scenarios against `c68` and 12 against `main`, all of them series-name conflicts.** In those scenarios `c68` and `main` write the merged survivor whatever the file claims, so they are right only when the claim happens to match the survivor; the same scenario with the other claim is one of their wrong writes. A grades them medium instead (see the series-name bullet below). So the loss is a lucky guess, not a correct match. (`check65.py`.)
* **B (drop the group)** never writes a series-bearing Work. It turns 288 pools into `none`, and it throws away the right Work even when the file names it.
* **C (strip the series)** writes the survivor's *other* fields: its publisher, blurb, ISBN and date. Those may come from the wrong Work, which moves the silent error from the series to the rest of the payload. It is also the largest source of "written with no series" (384).
* **D (force medium)** is safe but refuses every book, including the ones whose claim decides it (0 correct writes).
* **Series-name conflicts** (both #6, different series): the scorer only compares numbers, so the two Works tie and A grades them medium. That's safe, but not better than medium. It's accepted as part of Q1.
* **Where A's "written with no series" (144) comes from:** Google answering first with a strong single Edition, so the walk exits before Hardcover is asked. That's the existing early exit (CBO-58), not the merge.

### 3.4 One placement plus a blank (acceptance criterion 3)

One Work: Hardcover #6, plus a Google Edition with no placement. **96 scenarios** covering the ISBN relation (shared, different, Google with none, neither), the Google Edition's date (same, earlier, later), the claim (`Book 6` or none), the file year (none or 2017) and the source order.

| Measure | `main` | `mainA` | `c68` | **A** |
| -- | -- | -- | -- | -- |
| Pooled to **one** candidate | 32 | 32 | 96 | **96** |
| Left as two | 64 | 64 | 0 | 0 |
| Pooled band strong / medium | 28 / 68 | 28 / 68 | 80 / 16 | **80 / 16** |
| Walk band strong / medium | 80 / 16 | 80 / 16 | 88 / 8 | **88 / 8** |
| Walk writes #6 | 48 | 48 | 56 | **56** |
| Walk writes with no series | 32 | 32 | 32 | 32 |

**A differs from `c68` in 0 of 96 scenarios, and `mainA` differs from `main` in 0 of 96.** The genuine duplicate still merges into one candidate, and no strong single candidate is downgraded to a medium pair. That meets acceptance criterion 3, and it removes the ticket's reason to fear putting the placement in the key.

"Walk writes with no series" is 32 in every mode. These are cases where the Standard Edition, or an early-exiting Google-first single candidate, is the Google Edition. CBO-65 Q5 hands this to CBO-61 (§7).

## 4. The rule

Settled in the grilling. The spec text is in `cbo-65-spec-wording.md`.

1. Two candidates' **Series Placements conflict** when both state one and the series (compared ignoring case) or the position differs. A position is compared as `{float:g}` when it parses as a number, and as trimmed, case-folded text otherwise. A candidate that names neither a series nor a position has **no placement**.
2. Grouping (the CBO-68 Work key in `collapse()`, `_identity()` in `dedupe()`) runs first, and then each group is split:
   * **0 or 1 distinct placements**: the group stays as it is, and blanks merge. The Standard Edition (`collapse`) or the first candidate (`dedupe`) is chosen from the whole group, as today.
   * **2 or more**: one part per placement, in the order each placement first appears. Blanks are **dropped**, because they can't be assigned to either part. Each part picks its own survivor.
3. `collapse()` and `dedupe()` use **one shared split**. The split doesn't depend on reply order, because it's a function of the group's values and not of positions.
4. The scorer, weights, `BAND_GAP` and every threshold stay as they are. The two Works are then separated by the file's Claimed Placement (`SERIES_WEIGHT`), or they tie and grade medium.

## 5. Decisions from the grilling (2026-09-24)

All the recommendations were accepted as asked.

| # | Decision |
| -- | -- |
| Q1 | A stated Series Placement is part of a Work's identity. Two candidates with conflicting placements are two Works: **split**, not dropped, stripped or forced to medium. |
| Q2 | New term **Series Placement**: the featured series plus the position, compared as a pair. A conflict is when either half differs. |
| Q3 | New term **Claimed Placement**: the placement in the file's title bracket. The recorded OPF `series_index` is **not** used to break ties (that would be the reweighting F1–F3 ruled out); it's left open for CBO-71. |
| Q4 | One shared conflict check (the split) is used by both `collapse()` and `dedupe()`. Deleting `dedupe()` is out of scope. |
| Q5 | A merged Work whose Standard Edition has no placement is accepted here. CBO-61 must be able to take gap-fill donors from Editions the collapse removed. D15 is unchanged. |
| Q6 | One normaliser: numeric `{:g}`, falling back to trimmed, case-folded text. `Book 6` is only parsed on the file side, since no source sends it. |
| Q7 | The rate is the fixture census plus the synthetic sweep, stated as unmeasurable in the real world. CBO-76 must include a duplicate-Work series case. |
| Q8 | Band impact is measured on the real fixture walk and on the synthetic two-Work sweep (§3). |
| Q9 | Blanks in a group with 2 or more placements are dropped. |
| Q10 | `dedupe()` splits exactly as `collapse()` does. Refusing to merge alone would depend on order and break D10. |
| Q11 | Recorded as **amending CBO-68's D22**, applied by CBO-65 after CBO-68 merges (D9). PR #18 and the CBO-68 brief aren't touched. |
| Q12 | ADR drafted: `cbo-65-adr-draft.md`. |
| Q13 | The unverified mark and log line don't name the split. That's an open question. |
| Q14 | Acceptance tests: unit tests on the split, **and** walk-level tests through `Corrector` with `llm=None` (§9). |

Also settled: `cbo-65-context-draft.md` was renamed on request to **`CONTEXT.md`**, the main draft glossary in this folder. It merges CBO-68's and CBO-90's terms.

## 6. Interaction with CBO-68

* **The Standard Edition rule doesn't prevent any merge.** It makes the survivor deterministic. Order-dependent scenarios fall from 40 on `main` to 0 on `c68`, so a wrong survivor is wrong on every run instead of some runs.
* **It creates new merges.** The Work key has no ISBN and no year, so two Works with ISBNs, or with different years, now merge. On Works that carry ISBNs, `main` makes 0 wrong writes and `c68` makes 15 wrong writes and 30 unsupported guesses (§3.3). **Built without CBO-65, CBO-68 makes this bug worse**, which is one more reason to keep D9's order, with CBO-65 following closely.
* **What "same Edition" means.** Under the glossary, every Edition of one Work shares its Series Placement, so candidates that differ in placement aren't Editions of one Work. The ticket's title ("editions differing only in series position") is describing two Works. The dedupe group becomes "one Work", and the split is how placement takes part in Work identity.
* **D22 is amended, not reversed.** D22's reason (Hardcover Editions must still merge with Google volumes, which never carry a position) is kept: a blank merges. Only two *stated* and conflicting placements now split.
* **Q5's consequence comes from CBO-68.** D15 can pick a Google Standard Edition for a Work whose Hardcover Edition has the placement. On the fixtures that's Berwick (Google 2026-01-22 against Hardcover 2026-02-26), which only shows up when both sources are pooled. It's measured as 32 of 96 in §3.4, identical with and without CBO-65.

## 7. Open questions

1. **A series with no position.** Hardcover's `position` can be null. The probe treats (series, none) as a stated placement that conflicts with (same series, 6), so they split: at worst medium, never a wrong write. Recommendation: keep it that way and say so in the spec. This needs Callum's sign-off.
2. **CBO-76 must include a duplicate-Work series case.** Two Hardcover Works sharing a title and author letters, with different placements. Candidate: search Hardcover for series books with duplicate Works, as *Good Omens* shows. Until then the real-world rate is unknown.
3. **CBO-61 donors** (Q5): gap fill must be able to take `series` and `series_number` from Editions of the winning Work that the collapse removed. They aren't in the ranked pool, and the strong-band donor rule can't reach them today.
4. **The recorded OPF `series_index` as a tiebreak** (Q3): for CBO-71, not here.
5. **What an unverified book says about the split** (Q13): the log already shows both candidates. Whether the reason text should name "two Works with conflicting Series Placements" is left open.
6. **The scorer compares with raw `str()`** (`matching.py:428`). That's correct today, since both sides are `{float:g}`. If a future source sends an unnormalised position, the split and the scorer would disagree. Using the shared normaliser there touches scoring code, though not weights, so it's left for a decision.
7. **Series-name conflicts can't be told apart by the scorer**, which only compares numbers. Such pools always grade medium. Accepted under Q1. Comparing series names in the scorer would be a scoring change, and out of scope.
8. **Whether `dedupe()` survives CBO-68.** Its only remaining job is merging across author spellings through a shared ISBN. That's a separate ticket.

## 8. Sandbox commands and results

Everything below ran in a temporary clone in the cloud sandbox, not in your repo or on your Mac. The clone was deleted at the end.

```
git clone https://github.com/Cbow2018/colophon.git            # main @ 22f456b
git fetch origin dsh/cbo-68-standard-edition-rule              # 728c7ea
git log --oneline main..origin/dsh/cbo-68-standard-edition-rule   # 2 commits
git diff --stat main...origin/dsh/cbo-68-standard-edition-rule    # docs/research-cbo-68.md only
python3 -m unittest -q                                          # 876 tests OK (1 skipped), before any probe
mkdir scratch
cp <Colophone>/research-cbo-68-probe.py scratch/probe68.py      # session 1b probe, unchanged
python3 scratch/census65.py                                     # §2.1
python3 scratch/probe65.py --part fixtures --shuffle 50         # §3.1
python3 scratch/analyse65.py                                    # §3.3 (runs twin_sweep)
python3 scratch/analyse65_mixed.py                              # §3.4 (runs mixed_sweep)
python3 scratch/check65.py                                      # §3.3: correct writes A gives up, by pair and claim
python3 -c "…merge([c]) == [c] for every mode…"                 # §3.2
git status --short                                              # '?? scratch/' only: no tracked file changed
rm -rf <sandbox>                                                # discarded
```

Changes made in the sandbox: only new files under `scratch/`. Nothing in `colophon/` or `tests/` was edited. The options were simulated by subclassing `Corrector._gather` and swapping `correction.band_of` in the running process only, as session 1b did. Appendix A has the probe source, so it can be re-run.

## 9. Test plan for the TDD session

Build test-first, after CBO-68 merges (D9). Every walk-level test uses `llm=None`. The first two are the acceptance criteria.

1. **Acceptance criterion 2, no silent write.** Walk-level: a file titled `Cragside` by L. J. Ross (no Claimed Placement). Hardcover offers two Works titled `Cragside` by L.J. Ross, dated 2017-07-07, placed DCI Ryan Mysteries #6 and #11, **each with an ISBN** (the case CBO-68 newly merges). Assert the book is **not matched**, is **marked unverified**, and that no `series` or `series_number` edit is produced. Repeat with both Hardcover reply orders and both source orders.
2. **Acceptance criterion 3, a genuine duplicate still merges.** Walk-level: Hardcover #6 plus a Google Edition with no placement, same title and author, with ISBN shared, different and absent. Assert **one** candidate in the ranked pool and band strong for an undated file.
3. **Acceptance criterion 1, the right Work wins when the file names it.** The same two Works, with a file titled `Cragside (The DCI Ryan Mysteries Book 6)`. Assert matched and `series_number` `6` written. Repeat for `Book 11` (writes 11) and `Book 3` (medium, nothing written).
4. **Unit tests on the split:**
   * {#6, blank} → one group.
   * {#6, #11, blank} → two groups, blank dropped.
   * {DCI Ryan #6, Another Series #6} → two groups.
   * {`6`, `6.0`} → one group.
   * {`Book 6` on a candidate} → compared as text (documents the limit).
   * Every permutation of the input → the same output.
5. **Shared use:** `dedupe()` over two candidates with the same ISBN-13 and conflicting placements keeps two, and keeps blanks out, whatever the input order.
6. **`collapse()`**: two Works dated 2016 and 2019 with different placements aren't merged by the Work key (they would be under D22 as it stands).
7. **Regression:** CBO-68's fixture tests. Cragside, Berwick, Belsay and both Infirmary files stay strong and write the same placement on every configuration (§3.1 predicts no change).
8. **Documented limit:** a series-name conflict with equal numbers grades medium (§3.3), asserted so the behaviour is deliberate.

---

## Appendix A: probe source (sandbox `scratch/`, deleted afterwards)

`probe68.py` is `research-cbo-68-probe.py` from this folder, unchanged. Below are the CBO-65 rule functions, word for word, and a description of the harness around them. That's enough to rebuild the probe. The full harness was deleted with the sandbox, because this folder only takes Markdown.

### A.1 The rule, as simulated (`scratch/probe65.py`)

```python
from dataclasses import replace
import probe68 as P   # work_key, completeness, total_order, transports, population
from colophon.matching import band_of, dedupe, _identity

def norm_pos(v):
    if v is None: return None
    try: return f"{float(v):g}"
    except (TypeError, ValueError): return str(v).strip().casefold() or None

def placement(c):
    """Series Placement as one pair; None when the candidate states neither half."""
    if not c.series and not c.series_number: return None
    return ((c.series or "").strip().casefold(), norm_pos(c.series_number))

def split(group):
    """One part per stated placement. Blanks join the only part, or are dropped
    when the group states two or more (Q9)."""
    order = []
    for c in group:
        p = placement(c)
        if p is not None and p not in order: order.append(p)
    if len(order) <= 1: return [list(group)]
    return [[c for c in group if placement(c) == p] for p in order]

def conflicting(group):
    return len({placement(c) for c in group} - {None}) > 1

def source_rank(pool):                     # D15: where a source's first candidate sits
    rank_of = {}
    for c in pool: rank_of.setdefault(c.source, len(rank_of))
    return rank_of

def standard_edition(group, rank_of):      # D15/D16
    return min(group, key=lambda c: (c.date or "￿", rank_of[c.source],
                                     -P.completeness(c), P.total_order(c)))

FLAGGED = set()                            # mode D only

def collapse(cands, mode):                 # CBO-68 build brief §1, plus the CBO-65 modes
    rank_of = source_rank(cands)
    groups, order = {}, []
    for c in cands:
        k = P.work_key(c)
        if k not in groups: groups[k] = []; order.append(k)
        groups[k].append(c)
    out = []
    for k in order:
        g = groups[k]
        if mode == "A":
            out += [standard_edition(part, rank_of) for part in split(g)]
        elif mode == "B" and conflicting(g):
            continue
        elif mode == "C" and conflicting(g):
            out.append(replace(standard_edition(g, rank_of),
                               series=None, series_number=None, series_id=None))
        else:
            s = standard_edition(g, rank_of)
            if mode == "D" and conflicting(g): FLAGGED.add(id(s))
            out.append(s)
    return out

def dedupe_split(cands):                   # dedupe() with the same split (Q10)
    groups, order, loose = {}, [], []
    for i, c in enumerate(cands):
        k = _identity(c)
        if k is None: order.append(("loose", i)); loose.append(c); continue
        if k not in groups: groups[k] = []; order.append(("key", k))
        groups[k].append(c)
    out, li = [], 0
    for kind, k in order:
        if kind == "loose": out.append(loose[li]); li += 1
        else: out += [part[0] for part in split(groups[k])]
    return tuple(out)

def merge(pool, mode):                     # replaces correction.py:706's one line
    if mode == "main": return dedupe(pool)
    if mode == "mainA": return dedupe_split(pool)
    c = collapse(pool, mode)
    return dedupe_split(c) if mode == "A" else dedupe(c)

def band(ranked, bands):                   # band_of, with mode D's cap
    b = band_of(ranked, bands)
    if b == "strong" and ranked.leader is not None and id(ranked.leader.candidate) in FLAGGED:
        return "medium"
    return b
```

### A.2 The harness, described

* **`Sim(Corrector)`** copies `_gather`'s body (`correction.py:676-722`), replacing `dedupe([*pool, *candidates])` with `merge([*pool, *candidates], self.mode)` and `band_of` with `band`. `correction.band_of` is swapped for `band` for the length of each call, so `_by_title` grades with the same function. The corrector is built as session 1b's was: `dry_run=True`, `llm=None`, `fetch` raising, and a temporary `Backups`.
* **Modes `c68`, A, B, C, D** run inside `P.hardcover_hands_up_every_edition()` (D12).
* **Fixture walk (§3.1):** `P.population()` × `P.CONFIGS` × the 7 modes, using `P.sources_for(names, shuffle=random.Random(65))` for 50 shuffled replays. A cell records band, pool size, the written placement (the leader's placement when `outcome.matched`) and the number of distinct (band, written placement, `P._payload`) results.
* **Two-Work sweep (§3.3):**
  * `hc(num, date, isbn, series)` builds a Hardcover `Candidate("Cragside", ("L.J. Ross",), …)`, with a publisher and blurb that differ per Work.
  * `gb(date, isbn)` builds a Google `Candidate("Cragside", ("L. J. Ross",), …)` with no placement.
  * The file is an EPUB with a `dc:title` of `Cragside` plus an optional `(<series> Book <n>)`, a `dc:creator` of `L. J. Ross`, and an optional `dc:date`.
  * The sources are fakes with `name` and `by_title` returning a fixed list.
  * Dimensions are as listed in §3.3, and each scenario is run with Hardcover's list in both orders.
  * Classification: *correct* if the written placement equals the claimed Work's; *wrong* if the file claims #6 or #11 and another placement is written, or it claims #3 and any placement is written; *unsupported guess* if there's no claim and a placement is written.
* **Placement-plus-blank sweep (§3.4):** Hardcover #6 dated 2017-07-07, plus a Google Edition, over the dimensions in §3.4. It records the pooled size and band from `rank(FileBook(...), merge(pool))`, and the walk's band and written placement.
* **Census (§2.1):** every `tests/fixtures/{hardcover,googlebooks}/**/*.json`, read through `hardcover._candidate` / `googlebooks._candidate`. Each reply is grouped alone, and each Ross title is also pooled with its partner, under `_identity` and `P.work_key`. Groups with more than one distinct (series, number) pair, or mixing a placement with a blank, are counted.
