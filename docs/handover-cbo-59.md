# CBO-59 — pooled gather-then-grade: session 2 handover

Session 2, BUILD. Branch `dsh/cbo-59-pooled-walk` off `main` at `e5ea994`.
Test-first throughout; the suite is green at every commit. Nothing pushed, no PR,
no merge.

**Suite: 804 tests (2 skipped) on `main` → 827 tests (2 skipped) on the branch.**
`ruff check .` and `ruff format --check .` both clean. Five commits, in the
research note's build order:

| Commit | Build order |
| --- | --- |
| `23a9b5b` | steps 1–2: `Bands`, `band_of(ranked, bands)`, the two thresholds from config, `Ranked.band` deleted |
| `7abf172` | steps 3–5 and 8: the pooled walk, `Walk`, the band actions, the half-asked hold, `top_candidates(ranked)` |
| `774e8e2` | steps 6–7: `llm_full_scan` read and shipping on, the relay-level hold test |
| `56ce5e4` | a pooled test reshaped so it fails on `main` (see below) |
| `75d928c` | the last two config readers pinned end to end |

`docs/research-cbo-59.md` is committed with the branch, since the code cites it
and session 3 needs it.

---

## 1. `llm_full_scan`'s default — the first task

**Read: `config.py:160` defaulted it to `False`, and nothing anywhere read it.**
Today's walk asks the model for *any* non-empty pool the rules did not write
from (`if offered:` in the old `_by_title`), which includes the low and none
bands. So `false` **would have narrowed today's reach silently**, exactly as
research §3b predicted: a low/none-band book with an LLM configured would go
straight to `colophon:unverified` without ever being put to the model.

**Shipped: `llm_full_scan = True`,** with `Corrector(..., llm_full_scan=True)`
matching it, and `config.example.toml` reworded so it no longer says "`false` is
already what Colophon does". `off` is now the deliberate narrowing, and the flag
still means what §4.3 says it means — it widens the *population*, never the
decision, and never makes a strong-band book spend a call.

This is a reversal of research §3b's proposal (`Corrector.__init__` gains
`llm_full_scan=False`) on the instruction that the default must preserve today's
reach. One consequence is worth knowing: the two `test_llm.py` tests §3b wanted
rewritten (`:1049`, `:1067`) **did not need rewriting** — they still hold under
the shipped default. The flag's effect is pinned instead by four new tests in
`WhichBandReachesTheModelTests` (strong never asks; medium asks with the flag
off; low asks only with it on; `medium_score` draws the band).

## 2. Where the build order deviated, and why

1. **Steps 3–5 landed as one slice**, as the note itself says they must ("3-5
   cannot be separated in practice (the walk is one function)"). Nothing here is
   a judgement call: the tests for all three behaviours were written first, then
   `_by_title` was rewritten once.
2. **Step 8's fold came with steps 3–5, not after them.** The pooled walk has no
   per-source raw candidate list left to hand the old
   `top_candidates(file_book, candidates)`, so the walk could not be made green
   without the fold — and calling it per source over the pooled list would have
   restored the double scoring the fold exists to remove. §5 of the note is
   explicit that this fold is not optional tidying here.
3. **Step 6's mechanism also came with step 5**, because the flag is one term in
   one condition (`band == "medium" or self.llm_full_scan`). Its default, its
   config comment and its tests landed as step 6.
4. **Step 1's "a hand-built `Ranked` and one built by `rank()` band identically"
   test was not written.** `Ranked` is only `matches`, so a hand-built one with
   the same matches *is* the same value and the assertion could not fail. The
   behaviour it was meant to protect — `band_of` reading nothing but its
   arguments — is pinned by the caller-thresholds test instead.
5. **The `exited` flag means "stopped with a source left to reach".** The note's
   expression is `errored and not exited`; left at that, a strong pool reached at
   the *last* configured source counts as an early exit, and a walk that
   completed with an errored source writes anyway — which fails the ticket's own
   acceptance criterion ("a completed walk with an errored source does not
   write, whatever the band"). `_gather` sets `exited` only when the break skips
   a source that would otherwise have been asked. **This is the reading most
   worth a second pair of eyes** (§6 below).
6. **The ISBN path holds but still stops.** Settled decision 1 says `_failed`
   returns the hold on both paths; it does not say the ISBN path continues to
   the next source, and that would change `_by_isbn`'s fall-through — research
   §7 open question 2, which was never settled. So: source errors on the ISBN
   path → the book is held for tomorrow, and the sources below are not asked
   (the old "no lower-priority source quietly stands in" rule, unchanged).

## 3. The §5.1 amendment, and three smaller design-note readings

* **`Ranked.band` is deleted** (decision 7). It called `band_of(self)` with no
  thresholds, so it would have answered from the module defaults for any caller
  whose config moved. `Ranked`'s docstring now says the band is
  `band_of(ranked, bands)` and why it is not a property. §5.1 lists `band` as
  `Ranked`'s content; that list is amended.
* **`strong_score` stays a `Corrector` attribute as well as `bands.strong`.** One
  reader, the LLM's own pick gate (`correction.py:750`), which §3b says must stay
  on `strong_score` and must not become the singleton bar. Same number, two
  names, both documented — deliberate, and the only redundancy of its kind.
* **The near miss named in an unverified line is now the best *agreeing*
  candidate in the pool**, where it used to be the best agreeing *per-source
  leader*. Same predicate, strictly more candidates considered. No test changed.
* **The prompt's candidate order is now global rank order**, not source by
  source (research §5 flags this as a decision to review). Same candidate set:
  the per-source cap is untouched. No test pinned the order — only the counts —
  so nothing failed, and the numbering the model reasons about is now this
  project's own ranking.

## 4. What a user will see, and it is the PR body's headline

* **The medium band is reachable on real replies, and it is where a real Google
  title lookup lands.** `fixtures/googlebooks/by-title-cragside.json` holds two
  Cragside editions (the Ulverscroft large print and the original) that agree
  with the file on everything it states: two candidates at 1.0, gap 0.0, so
  **medium**. The Masque of the Red Death recording is worse — five of its ten
  volumes score 1.0. On a default install with no LLM, those books are now
  `colophon:unverified` rather than corrected. That is §1.2 working as designed
  ("writing whichever of two near-identical numbers happened to sort first"), and
  it is also the largest user-visible change in the ticket: **title-path books
  from a source that returns several printings now want an LLM configured.**
  Three real-recording tests were rewritten to assert it.
* **Every score in [0.89, 0.95) that used to be written is now medium** — asked,
  or marked when no LLM is configured. §0's 0.9070 case is tested directly.
* A book whose configured source is down is **held for tomorrow rather than
  delivered** — not marked, not backed up, not retried until the day turns.
* `singleton_score` and `medium_score` now work, and **`singleton_score` below
  `strong_score` is refused at startup**. Three existing tests that set
  `strong_score` alone above 0.95 had to set `singleton_score` too; a user doing
  the same gets a `ConfigError` naming both numbers rather than a silent
  inversion of §1.2.
* A two-source outage now logs **one warning per errored source**; `main` logged
  one, because it stopped at the first.
* A dry run says nothing about a held book (the relay's `waiting` branch returns
  before its dry-run line) — true of the LLM hold on `main` too, now also of a
  source-error hold. The `WARNING` still names the source, so it is not silent.

## 5. Verification

Every acceptance criterion has a test, and each was run against `main` in a
throwaway worktree with the new test files copied in:

* fails on `main`: the pooled band tests (`a_pooled_singleton_in_the_medium_band_
  is_not_written`, `the_pool_is_what_picks_the_record_that_gets_written`), the
  half-asked pair (`a_completed_walk_with_an_errored_source_does_not_write_
  whatever_the_band`, `a_title_lookup_that_is_down_does_not_stop_the_walk`), the
  hold (`a_walk_that_could_not_be_finished_holds_the_book`,
  `the_outcome_says_which_source_could_not_be_asked`), `two_genuinely_different_
  editions_are_not_merged`, `a_source_s_reply_is_scored_once_rather_than_twice`
  (6 → 3), all four `WhichBandReachesTheModelTests`, all three relay hold tests,
  `one_edition_from_two_sources_is_one_candidate_in_the_prompt` (2 → 1), the band
  tests in `test_matching.py`, and the config refusal and default.
* **passes on `main` as well**: `two_sources_returning_the_same_edition_are_one_
  candidate_and_grade_strong` and `a_pool_that_grades_strong_stops_the_walk_
  before_the_next_source`. The first is the ticket's headline criterion and it is
  **vacuous**, exactly as research §6 item 4 said: the edition scores 1.0, the
  singleton pool grades strong, and the walk exits before the second copy of the
  record could ever become a runner-up. It is kept because the ticket names it.
  The criterion's teeth are the two tests above it.

## 6. What session 3 should look at hardest

1. **The `exited` refinement (§2.5).** It is the one place I read the note
   further than it wrote, and it decides whether a strong pool at the last
   source is a completion or an exit. Both readings pass the ticket's wording;
   only this one passes its acceptance criterion.
2. **The medium-band rate on real replies (§4).** Two fixtures now grade medium
   where `main` wrote. Decide whether that is the accepted cost or whether the
   §4.4 tuning pass (or CBO-65's dedupe key) has to come first — and note that
   on a default install the review queue is "the LLM or nothing".
3. **The ISBN path still stopping (§2.6).** Research §7 open question 2 is still
   open, and this session took the narrow reading.
4. **`llm_full_scan` shipping on.** A deliberate reversal of §3b on your
   instruction; the note's stated cost ("cuts LLM calls users see") is inverted,
   so the PR body should say so plainly.
5. **The prompt's candidate order** is now global rank order (§3). The model's
   numbering changes for multi-source books, and no test pins the order itself.
6. **The `Bands` invariant lives in two places**: a `ValueError` in
   `Bands.__post_init__` (programmer's) and a `ConfigError` in `load_config`
   (user's). Cheap to collapse if you would rather have one.
7. **Behaviour `main` had that this branch drops on purpose** — check these are
   the ones you expected: writing from a 0.89–0.95 singleton; delivering a book
   whose source was down; letting `strong_score` be raised without
   `singleton_score`; one warning for a two-source outage.

**Ponytail, so session 3 does not have to guess:** nothing was built for a second
caller. No new module, no pool object, no `Walk` in `matching.py`, no
stdlib-free dependency. Field merging is CBO-61, the dedupe key is CBO-65 and any
reweighting is CBO-66 — all three were left alone, and the code says where each
belongs.
