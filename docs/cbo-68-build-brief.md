# CBO-68 — build brief (session 2)

What to build, settled. The evidence is `research-cbo-68.md` §0 (session 1b,
measured at `22f456b`), attached to CBO-68 with this brief. This brief is the
decisions and the work, not the argument. Where they disagree, this brief wins and
the disagreement is a bug to report.

Vocabulary: **Work**, **Edition** and **Standard Edition** as defined in
`context-additions-cbo-68.md`. Merge those into `CONTEXT.md` and use them in code
comments, test names and the PR. Google calls an Edition a "volume"; use that word
only when naming Google's API field. The rationale is in `adr-draft-standard-edition.md`.
Number that ADR next to CBO-48's.

**Build test-first. Do not change the scoring weights, `BAND_GAP` or any
threshold.** A default install with **no LLM configured** (`llm=None`) is the case
every new test exercises.

## 1. The rule: goes into the design spec (CBO-33) as written

> **The Standard Edition (title path).** A title search returns Editions, not
> Works. Before a pool is ranked, its candidates are grouped by Work: two candidates
> belong to the same Work when their titles have the same head, as the scorer
> normalises it, and their authors are the same letters once each name has been
> through the scorer's name normalisation. So `L. J. Ross`, `LJ Ross` and
> `Ross, L. J.` are one author, and `L. K. Ross` or `Edgar Allen Poe` is another.
> Each Work keeps one candidate, its Standard Edition: the one with the **earliest
> date** (dates compared as ISO prefixes; an undated candidate comes last); among
> equal dates, the one from the source **highest in the user's source list**; then
> the one carrying **more of the ten payload fields**; and last, the candidates'
> payloads compared field by field, so two candidates can only tie when they would
> write the same thing. This runs on the pooled candidates each time a source's
> reply joins the pool, before `dedupe` and `rank`, so every source hands up every
> Edition and the choice is made in one place. A title-path match therefore comes
> out the same whatever order a source lists its reply in. The Standard Edition is
> the earliest *listed* Edition, not necessarily the first published, and nothing
> Colophon writes or logs may call it the first edition.

These limits also go into the spec:

* **Dated files.** A year alone can't separate two Editions (0.15 / 1.95 =
  0.0769, under `BAND_GAP` 0.08). Once a Work's Editions are grouped, the Work is a
  pool of one, graded against `singleton_score` 0.95. A file whose `dc:date` isn't
  its Work's earliest Edition's year scores 0.9231 and stays medium without an LLM.
  Accepted (D18).
* **The Work key is synthesized.** Two Hardcover Works with the same title head
  and the same author letters are two `book.id`s but one key. No fixture has one.
  Accepted (D23).
* **Every format is an Edition.** The Standard Edition can be an audiobook or a
  hardback, and its ISBN, publisher and date are written to a file that has none.
  Tracked as CBO-90 (D24).

## 2. Decisions in force

D1–D14 are in the CBO-68 Linear comments. Session 1b's review settled these on top:

| # | Decision |
| -- | -- |
| D15 | Standard Edition order: earliest date → **user's source order** → payload completeness → payload compared field by field. **Amends D3** (source order goes before completeness). |
| D16 | The last-resort key is the payload itself, not the ISBN (Belsay's Hardcover Edition has none; Google's `wwLYDwAAQBAJ` has only an EAN). This meets D10's third criterion. |
| D17 | The author part of the key is `matching._name(author)`, then letters only. Refines D11. |
| D18 | The dated-file singleton consequence is accepted and documented, not fixed here. Its figures are on CBO-76. |
| D19 | The Hardcover Poe fixture row is declared in **this session's first commit** (§4). |
| D20 | `docs/research-cbo-68-probe.py` lives in the repo as a snapshot measured at `22f456b`. This session re-runs it **once** for the "after" figures. |
| D21 | Preferring the file's own year is **not** built. The evidence is on CBO-71. |
| D22 | Series position is **not** part of the Work key. CBO-65 gets scoped against this key afterwards. |
| D23 | `Candidate` does **not** carry `book.id`. |
| D24 | Every format is an Edition of the Work. The non-ebook ISBN risk is CBO-90 (High, blocked by this ticket). Audiobook support is CBO-91 (Low, after v1.0.0). |

Carried from D12/D13: Hardcover's `_candidates` stops keeping the first Edition per
Work and hands up every Edition; `most_complete` is not a config key; `earliest` is
hard-coded.

## 3. The work

1. **First commit: declare the Hardcover Poe row** in `tests/recordings.py`, beside
   the Google Poe row, then **stop and ask Callum to record it** (§4). Don't write
   the fixture by hand.
2. **Add `collapse(candidates)` to `matching.py`**, pure like the rest of the
   module. It groups by the §1 key, keeps each Work's Standard Edition by D15/D16,
   and preserves the order in which Works are first seen.
   - D15's source rank is the position at which that **source's** first candidate
     appears in the pool. The pool is built source by source in the user's order,
     so this gives the user's list with no argument passed in.
   - It must never be the candidate's own position. That is reply order, which D10
     forbids.
3. **Change one line in `correction.py:_gather`**:
   `pool = dedupe(collapse([*pool, *candidates]))`.
4. **Make `hardcover.py:_candidates` (`:351`) hand up every Edition** (D12). Remove
   its docstring line "a second edition would only offer the same book twice".
5. **Design spec:** put §1's rule and limits into CBO-33.
6. **Re-run the probe** (`python docs/research-cbo-68-probe.py --shuffle 100`) and
   put the before/after table in the PR, per configuration, as information. D10
   moved the rate criterion to CBO-76. The probe's option 1 predates D15, so on the
   reversed source order its Standard Edition for the dated Cragside rows is
   Hardcover's. Under D15 it's Google's. The bands are the same either way.

## 4. The recording step (Callum, after commit 1)

In PowerShell, from `A:\Documents\GitHub\colophon`, run one command per step:

1. `git pull`
2. `$env:COLOPHON_HARDCOVER_TOKEN = "paste-the-hardcover-token-here"`
3. `$env:COLOPHON_GOOGLE_BOOKS_KEY = "paste-the-google-key-here"` (the recorder
   needs this even for a Hardcover-only row)
4. `python tools\record-fixtures.py --list`, then check the output has this line:
   `hardcover/by-title-poe.json  Hardcover {"titles": ["The Masque of the Red Death"], "language": "en"}`
5. `python tools\record-fixtures.py hardcover/by-title-poe.json`
6. `python -m unittest -q`

The row to declare:

```python
    {
        "source": "hardcover",
        "fixture": "by-title-poe.json",
        "lookup": "title",
        "book": POE,
    },
```

## 5. Tests, mapped to the acceptance criteria

| Criterion | Test |
| -- | -- |
| Rule stated in the design spec | Review that §1's text is in CBO-33 |
| Medium rate before/after → CBO-76 (D10) | Probe table in the PR, not a test |
| Default install, no LLM | Build every new corrector with `llm=None` |
| Same result every run. D10: shuffled reply, **both source orders** | Shuffle `googlebooks/by-title-cragside.json`, `hardcover/by-title-berwick.json`, `hardcover/by-title-the-infirmary.json` and `googlebooks/hand-made/poe-core-cases.json`. Assert the same band **and the same written ISBN, publisher and date**, with the sources in both orders |
| D10 third criterion / D16 | Synthetic: two candidates equal on date, source and completeness, differing only in cover URL, fed in both orders → the same Standard Edition |
| D13 tiebreak | Recorded: in `hardcover/by-title-berwick.json` both Editions are dated `2026-02-26`, and `9781529978940` (`Century`) wins on completeness |
| D15 source order | Cragside file with `dc:date` 2019, Google listed first: the pool's leader is Google's `RASDtAEACAAJ`, not Hardcover's `2017-07-07` Edition. The band is medium, so assert on the ranked pool, not on a write |
| D11/D17 key | `L. J. Ross` = `LJ Ross` = `Ross, L. J.`; `L. K. Ross` ≠ `L. J. Ross`; The Infirmary's Ross and Reagon Works stay two; live Poe stays **medium**, with `Q8jPsgEACAAJ` (`Edgar Allen Poe`) as runner-up |
| No strong book regresses | Cragside, Berwick, Belsay, The Infirmary (Ross) and The Infirmary (Reagon) stay strong on every configuration they're strong on today |

These tests become false and must be changed, not deleted blindly:

* `test_hardcover.py:263` `test_one_work_comes_back_once_however_many_editions_it_has`:
  D12 makes it return two candidates. The one-per-Work guarantee now belongs to
  `collapse()` and is tested there.
* `test_hardcover.py:307` `test_a_work_with_no_id_of_its_own_is_not_mistaken_for_another`:
  `book.id` no longer groups anything in the client, so check whether it still
  asserts anything true.

## 6. Say in the PR

* **Written values change.** The Infirmary (Ross) via Hardcover now writes
  `9781792780844` (`Independently Published`, 2019-01-01). Before, it wrote
  whichever of three Editions arrived first, one of which is `9781799729945`, the
  `Audible Studios on Brilliance` Edition. Berwick always writes `9781529978940`.
* **Earliest is not ebook-only.** It avoids the audiobook here by luck, not by
  rule. CBO-90 will fix that.
* **Poe stays medium** (D11) and is CBO-69's acceptance case, on the frozen
  `hand-made/poe-core-cases.json`. The live reply's Standard Edition is
  `0uZ6IaW21DQC` (2008-10-02), not `du6sYyygMgIC`.
* The dated-file limit (§1) goes in the user-facing docs as well as the spec.

## 7. Out of scope

* Thresholds and weights (CBO-76)
* The file-year preference (CBO-71)
* Series position in the key (CBO-65)
* An ebook preference or `edition_format` (CBO-90)
* Audiobook support (CBO-91)
* Google `subtitle` (CBO-75): the field mask doesn't fetch it, and if it is ever
  joined onto the title, the key must stay on the head
* Title spelling on write (CBO-69)
