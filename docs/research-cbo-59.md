# CBO-59 — wiring the pooled gather-then-grade flow: research

Session 1, research only. Branch `main` at `e5ea994` (CBO-50 merged). Nothing
tracked was changed; probes live in `scratch/` and are gitignored.

Sources read, and the correction to the ticket's own reading list: **there is no
`docs/pr-cbo-58.md`.** The review findings this ticket inherited are the
untracked root-level `pr-cbo-58.md` (gitignored by `pr-*.md`), and the design
spec behind the §-references is `docs/research/cbo-58.md`. The ticket cites
sections "of CBO-33's design spec"; CBO-33 is the Linear issue, and the sections
as numbered (§1.2, §4.1, §4.2, §4.3, §4.5, §5.1, §5.2) exist only in
`docs/research/cbo-58.md`. Read that, not the ticket.

---

## 0. What I probed, and what it showed

Three throwaway scripts under `scratch/`, run against the real code with the
real fixtures (`tests/sources.py`, `tests/samplebooks.py`), never against a
model of it. They are not committed and are not part of the deliverable.

| Probe | Question | What it showed |
| --- | --- | --- |
| `scratch/probe_walk.py` | What does the walk do today with two sources offering one edition? | Source one's pool wins at 0.89 and the walk returns; source two is never asked (`second.asked_titles == []`). Pooling both and deduping gives **one** candidate at 1.0 → `strong`. Pooling without deduping gives two at 1.0 and gap 0.0 → `medium`. **Dedupe, not pooling, is what makes the ticket's headline test pass.** |
| `scratch/probe_walk.py` | What does `dedupe()` lose, and can the kept record be the poorer one? | Yes. With a bare Google record in front of a rich Hardcover record, the kept candidate has `description`, `publisher`, `date`, `series`, `series_number`, `cover` and `genres` all `None` where the discarded one carried them. Grouping without an ISBN is title + first author + **year**, so a differing year gives two candidates; no title or no author is never grouped at all. |
| `scratch/probe_walk.py` | Do `rank()` and `top_candidates()` really score twice? | `rank(file_book, pool)` calls `score_candidate` 3 times for 3 candidates; `rank(...)` then `top_candidates(...)` calls it **6** times. Confirmed. `top_candidates` also calls `rank` internally (`matching.py:553`), which the `rank(...).leader` call at `correction.py:574` has just done. |
| `scratch/probe_isbn_path.py` | What does an errored source do on the ISBN path? | `_by_isbn` returns at `correction.py:510` and the second source is never asked (`second.asked == []`). The outcome has `problem` set, `waiting`/`unverified` False — and **`relay.py:150` only holds on `waiting`, so the relay moves that book to output and deletes it from ingest.** The book is delivered, never retried, and never tagged. |
| `scratch/probe_isbn_path.py` | Does `dedupe()` keep the priority source? | Yes, entirely by input order: `dedupe([rich, poor])[0].source == "hardcover"`, `dedupe([poor, rich])[0].source == "google_books"`. First-wins *is* priority order if and only if the pool is built source by source in config order. |
| `scratch/probe_bands.py` | Which scores are actually reachable under the shipped weights, and in which band? | 1071 field/score combinations → 500 distinct scores. **71 distinct scores land in [0.89, 0.95)**, every one of them with the author agreeing. The medium band is reachable (thousands of low-band scores and 180-odd medium ones between 0.8008 and 0.9488). Highest score below the singleton bar: 0.9488. |

Two numbers worth carrying out of that last probe, because they decide the real
cost of this ticket:

* **Today the walk writes every score ≥ 0.89.** After banding, a **singleton**
  pool writes only ≥ 0.95. Every score in [0.89, 0.95) — 71 of them, including
  §2.1 row 4's 0.9070 and the year-contradiction case at 0.9302 — moves from
  *written* to *medium* (asked, or unverified with no LLM).
* The scores in that window are not near-miss noise. They are **the right book
  with one field contradicting**: an exact title and an exact author with a
  disagreeing year (0.9302) or a disagreeing series position (0.9070). This is
  §4.1 working as designed — the singleton bar exists to demand that one witness
  be near-exact — but it is a user-visible behaviour change and it belongs in
  the PR body, not just in the tests.

A correction to my own first reading, kept because it is the trap in this
ticket: I initially reasoned that no score could land in (0.8584, 0.9070) and
that the medium band was therefore unreachable. **That is false.** §4.1's
"window" is the set of *clean* scores at denominator 2.15 with everything else
exact; it is not the set of reachable scores. Author similarities between the
0.5 gate and 1.0 (0.8308, 0.8533, 0.8815…) fill that window densely, and a
*title* similarity between 0.8167 and 0.9488 walks the score down through 0.89
without any field contradicting at all. The medium band is populated and the
singleton bar is load-bearing. Anyone re-deriving §4.1 for session 2 should run
`scratch/probe_bands.py` rather than trust the table.

---

## 1. The CBO-43 dependency

### Options

**A. CBO-59 introduces the state itself.** A held outcome, distinct from both
`unverified` and `waiting`, that the relay honours by not delivering.
**B. CBO-59 reuses the existing `waiting` plumbing.** The relay already has the
exact behaviour the rule needs, reached by one flag with a free-text note.
**C. CBO-59 stubs a seam and does nothing observable** — compute "half asked",
put it on the walk result, and leave the behaviour to CBO-43.
**D. Resequence CBO-59 behind CBO-43.** CBO-43 is blocked by `CBO-50` (done),
`CBO-39` (done) and `CBO-35` (done), so nothing is actually in its way.

### Evidence

* **`Outcome.problem` is not a hold, and the relay proves it.** `relay.py:150`
  gates delivery on `outcome.waiting` alone; `_failed` (`correction.py:708`)
  returns `Outcome(problem=...)` without it, so the book is copied to output and
  unlinked from ingest (`relay.py:186`, `relay.py:205`). CBO-43 asks for a
  5m/15m/1h/3h retry window on temporary errors; **today an outage destroys the
  retry surface for every book it touches.** That is a live bug, not a design
  question, and it is on the ISBN path as much as the title path (probe 4).
* **The relay's `waiting` branch is word-for-word what the rule needs**:
  `relay.py:150-156` returns before `_mark`, before `_destination_for`, before
  the copy, before `path.unlink()`, and before `_remember`. The book stays in
  ingest, unmarked, unre-written, with nothing recorded against it. The relay
  docstring at `correction.py:180-184` already states the reason the rule wants:
  a hold "must not deliver it".
* **`waiting` is documented as LLM-only, and its fragment says so.**
  `Outcome.waiting`'s comment (`correction.py:180-183`) is entirely about the
  model, and `fragment()` returns `"[left in the ingest folder: {note}; trying
  again tomorrow]"` (`correction.py:207`) — which happens to be true of a source
  outage too, and is why no new machinery is needed.
* **CBO-43's shape does not collide.** Its acceptance criteria are per-source
  health, a retry schedule, `colophon:source-unavailable`,
  `colophon:cover-unavailable`, key rejection → unhealthy, and a webhook. None
  of it touches `matching.py`, `band_of`, the pool, or the walk's shape. Its
  "retry state is per source, not per book" decision *supersedes* the per-book
  `_waiting` dict — and supersedes it either way, since that dict already exists
  for the LLM. Building the hold now costs CBO-43 one reimplementation of where
  the hold is decided, and nothing it has to unpick.
* **CBO-61 is the ticket that would collide, and it is already downstream.**
  CBO-61 (blocked by CBO-59) wants post-match gap fill from a strong-band donor
  candidate. That is the answer to the merge question in §2, and building it
  here would be building CBO-61 early.

### Recommendation

**B, with A's naming.** CBO-59 builds the hold itself, by generalising what
`waiting` means rather than adding a second flag:

* `waiting` stops meaning "the LLM could not be asked" and starts meaning "the
  pass did not finish, so the book is not the library's yet". `note` already
  carries the reason and is already logged, so nothing else changes shape.
* `_failed` returns that outcome instead of `Outcome(problem=...)`, on **both**
  paths — the ISBN path at `correction.py:510` and the title path at
  `correction.py:567`. That is a second behaviour change the ticket does not
  name, and it is the same rule: sources are pooled and the trust order is a
  config value, so "somebody the user configured was never reached" is not a
  title-path-only fact.
* `self._waiting[path]` keeps its job (do not re-ask today), so a source that is
  down is still asked about each book once per day rather than once per scan.
  CBO-43 replaces where that is decided; it does not need the dict to move.
* The four existing tests that assert `outcome.waiting` for the LLM
  (`tests/test_llm.py:990,1013,1029`) keep passing unchanged, because the flag
  keeps meaning "held". The two that assert `_failed`'s problem fragment
  (`tests/test_correction.py:2320`, `:2777`, `:3125`) change to assert the hold.

**Not C.** A seam with no behaviour is not testable as the rule the ticket's own
acceptance criteria name ("a completed walk with an errored source does not
write, whatever the band") and would leave the outage bug live for another
ticket. **Not D.** CBO-59 is not blocked by CBO-43 — the reverse is true
relationally (`relatedTo`), and resequencing would stall the pooling refactor on
retry scheduling it does not need.

### Cost

Three touched lines in `_failed`, one docstring on `Outcome.waiting`, five test
assertions updated, and one pytest-scale decision: **the dry run now says
nothing about a held book** (the relay's `waiting` branch returns before its
dry-run branch). The `WARNING` from `_failed` is still logged, so an outage is
not silent — but a dry-runner sees no per-book line for a book that was held.
Move the log into the relay's `waiting` branch if that matters, and it is one
line.

---

## 2. Merge vs first-wins

### Options

**A. Keep first-wins and change nothing.** Document that the first candidate of
a group is the highest-priority source that offered the record.
**B. Merge non-`None` fields into the first candidate, keeping its `source`.**
**C. Merge and record provenance per field** — a `sources` tuple on `Candidate`
or a per-field `Change.source`.

### Evidence

* **The lost field is real, and the probe names it.** `dedupe` groups by ISBN-13
  first (`matching.py:733-743`), so the same edition from two sources groups even
  when the two records are nothing alike in coverage. A bare Google record
  (title, author, language, isbn — which is what Google returns) in front of the
  rich Hardcover record gives a kept candidate missing `description`,
  `publisher`, `date`, `series`, `series_number`, `cover` and `genres`. The
  second group, with no ISBN, is title + first author + year, and there a
  differing year keeps both candidates, which is the safe direction.
* **What is lost *today* is nothing at all, because nothing is thrown away in
  silence** — but for a reason that will not survive pooling. `_identity` returns
  `None` for a candidate with no title or no author, so those are never grouped
  and never dropped. So the only discarded candidates today are ones a *single*
  source offered twice in one reply, which is the same record with the same
  fields.
* **Attribution is a candidate-level property, and the log reads it from the
  candidate.** `_write` does `credited = COLOPHON if unverified else
  found.source` (`correction.py:758`), and `Change.source` follows it. Option B
  therefore does not just lose the donor's name — it **credits the donor's value
  to the winner**, which is a false statement in the one log line the design
  cares most about. Option C fixes that and is the only truthful version of
  merging, which makes it a logging change, not a dedupe change.
* **CBO-61 is already the answer.** It exists to "replace per-field source
  fall-through with post-match gap fill", with the acceptance criteria "fields
  it is missing *entirely* are filled from other candidates", "a populated field
  on the winning record is never overwritten", "a donor must itself be
  strong-band", and "the log still shows which source supplied each value".
  Every one of those is a requirement option B or C would have to invent here
  and CBO-61 would then re-invent.

### Recommendation

**A.** Keep first-wins, and make the priority guarantee explicit rather than
incidental: build the pool source by source in config order, so `dedupe`'s
first-wins *is* the trust order (the probe confirms it is). One comment in
`_by_title` saying so, because the property currently depends on a loop's
iteration order three functions away. Field merging belongs to CBO-61, which
already owns the donor rule, the donor threshold and the per-field log.

### Cost

Zero code. The loss is that a donor field still does not reach a book, and the
log line still cannot say a donor supplied a value — both of which are CBO-61's
deliverable, and both of which are visible rather than silent (a field that is
not written is a field the log does not list).

---

## 3. The three orphan config keys

### Confirmed, not trusted

Read rather than assumed: **all three are parsed and none of them is read.**

* `config.py:211-215` parses all three through the same `_to_threshold` /
  `_to_bool`.
* `strong_score` has one reader: `config.strong_score` → `Corrector.strong_score`
  (`config.py:153` → `correction.py:375` → `correction.py:439`), used at
  `correction.py:581` and `correction.py:650`.
* `singleton_score` and `medium_score` are read by nothing outside
  `tests/test_config.py`. `band_of` compares `SINGLETON_STRONG`, `STRONG_SCORE`,
  `MEDIUM_SCORE` and `BAND_GAP` from `matching.py` (`matching.py:517-526`).
* `llm_full_scan` is read by nothing at all, tests included beyond an
  `assertFalse` on the default.
* `config.example.toml:120-134` documents all three as the thresholds that
  "turn that number into a band", including the action per band — a documented
  effect no code produces.
* The defaults agree (`config.py:57-59` vs `matching.py:73-75`), which is exactly
  what hides it: a user who sets `singleton_score = 0.99` gets 0.95 and no
  warning.

### Options

**A. Thread all three from the caller into `band_of`.**
**B. Drop `singleton_score`, `medium_score` and `llm_full_scan` from `config.py`,
   the example config and §4.5.**
**C. Keep the keys and mark them unhonoured in the example config** — honest, and
   the worst of both.
**D. Thread `singleton_score` and `medium_score`; decide `llm_full_scan`
   separately on its own merits.**

### Evidence

* A user's config is refused, not reinterpreted, for an unknown key
  (`config.py:232-238`), so dropping the keys breaks every config that sets one
  with `ConfigError: unknown setting`. §4.5 calls the `confidence` → `strong_score`
  rename a breaking change it is willing to take *once*, pre-1.0 — but it takes
  it to fix a name collision, not to remove capability.
* §4.4's whole tuning procedure (steps 1, 3, 6) is written around moving
  `medium_score` against a real library, and §4.1 says `medium_score` "ship[s] as
  a config key with this default and then measure". Dropping it deletes the knob
  the design's own tuning session needs.
* `band_of` is pure today in the strong sense: it reads `ranked` and four module
  constants, and reads nothing else. A threshold argument keeps that property —
  the function still reads only its arguments — while removing the hidden
  dependency on four module constants, which is *more* pure, not less.
* The signature change is avoidable: an optional parameter with the module
  constants as its default leaves every existing `band_of(ranked)` call in
  `tests/test_matching.py` working.

### Recommendation

**D.** Thread the two thresholds as one value object; decide `llm_full_scan`
under §3b.

```python
@dataclass(frozen=True)
class Bands:
    # The three thresholds the bands are drawn from, as one value. `gap` is
    # internal calibration (§4.5) and never comes from config, so it is a field
    # with a default rather than a fourth key.
    strong: float = STRONG_SCORE
    singleton: float = SINGLETON_STRONG
    medium: float = MEDIUM_SCORE
    gap: float = BAND_GAP


BANDS = Bands()  # what a caller that has no config means


def band_of(ranked, bands=BANDS):
    # unchanged below: `bands.strong` in place of STRONG_SCORE, and so on
```

* **Purity survives, on the reading §5.2 states it.** `band_of` still reads only
  its arguments and calls nothing; it no longer reads mutable module state that
  a caller cannot see. The constraint §5.2 defends is "the matcher does not read
  config" — a passed-in value is not a config read.
* **The walk passes `self.bands`.** `Corrector.__init__` gains
  `singleton_score=DEFAULT_SINGLETON_SCORE` and
  `medium_score=DEFAULT_MEDIUM_SCORE`, `from_config` passes
  `config.singleton_score` / `config.medium_score`, and `self.bands` is built
  once. No config import reaches `matching.py`.
* **`Ranked.band` becomes a trap and should go** (or stop being used).
  `Ranked.band` (`matching.py:265-267`) calls `band_of(self)` with no bands, so a
  caller that has a `Ranked` built by the walk and asks it for its band gets the
  *module defaults*, silently. The walk must call `band_of(ranked, self.bands)`.
  Deleting the property is the smallest correct thing; keeping it is a pending
  wrong answer for a config that moved. (Flagged: §5.1 lists `band` as
  `Ranked`'s content, so deleting it amends the design note. See open question 3.)
* **One invariant needs saying out loud**: `singleton_score` must not be below
  `strong_score`, or a one-witness pool becomes *easier* to write than a
  corroborated one, which inverts §1.2. The pipeline asserts it once where
  `Bands` is built, and `config.py` refuses the pair. No new config key, no new
  validation vocabulary.
* An optional `bands` parameter is not "config for a value that never changes" —
  it is the seam the ticket exists to close, and it is the only way the walk's
  two new numbers can reach a decision.

### Cost

One small dataclass, one optional parameter, one constructor argument pair, a
config pair, and one new refusal in `config.py` (~25 lines). Tests: two or three
new ones in `test_matching.py` proving a passed threshold changes a band, two in
`test_config.py` for the refusal, and existing `band_of(ranked)` calls unchanged.
The alternative costs a `ConfigError` for every user who has already set either
key, plus an amendment to §4.4's tuning procedure.

### 3b. `llm_full_scan`

### Evidence

* Nothing reads it. The walk asks the LLM for **any** non-empty pool the rules
  did not write from (`correction.py:600-604`); the condition is "not strong and
  something was offered", not a band.
* §4.3 defines it as "ask whenever the band is *not* strong and the pool is
  non-empty… the flag widens the *population*, not the decision", with the flag
  **off** still asking for medium-band books.
* So the design's default (`false`) is *narrower* than today: it asks for the
  medium band only. Turning the flag on reproduces today's behaviour for low and
  none as well. The key is not "off by default = current behaviour"; **on**
  is current behaviour, and the flag's real job is to make the low/none calls a
  choice.
* `tests/test_llm.py:1049` ("the LLM is asked even when there is only one
  candidate", a Berwick-against-Belsay low-band pool) and `:1067`
  (`strong_score=0.3`, capped at 0.7, low band) both pin today's "ask anything"
  behaviour and will fail under the default flag with LLM configured.
* With **one** configured source, `llm_full_scan` still does nothing: low/none
  means every source was asked and nothing was found, which is the no-match case
  and is already final. The flag only bites when pooling lets a walk end in
  low/none with a source never reached by early exit — a multi-source
  configuration. That is worth a line in the config comment.

### Recommendation

Read it, in the walk, at the one place the LLM is gated:

```
ask = walk.ranked.leader is not None and (
    band == "medium" or self.llm_full_scan
)
```

* `strong` never asks (the walk wrote and stopped, or the half-asked rule
  stopped it).
* `medium` always asks, flag or no flag — §4.3's "the flag widens the
  population, not the decision".
* `low` and `none` ask only with the flag.
* The LLM's own pick gate stays `self.strong_score` at `correction.py:650`, not
  the band: §4.3 has the model's confidence compared against the strong
  threshold, and this is the one number that must **not** become
  `singleton_score` — a model picking one of two near-identical candidates has
  answered the question the gap could not, so requiring 0.95 of it would require
  the rules to have succeeded where they failed.

`Corrector.__init__` gains `llm_full_scan=False` to match the config default,
and the two `test_llm.py` tests above move to `llm_full_scan=True` (or gain an
explicit assertion that the flag is what admits them). That is a decision worth
reviewing rather than a mechanical fix: those two tests currently document
"anything the rules could not use goes to the model", and the design narrows
that to medium. Encode the design.

### Cost

One constructor argument, one config pass-through, one condition, and ~8 new
tests. The two rewritten `test_llm.py` tests are the reviewable part.

---

## 4. Where the reached/errored record lives

### Options

**A. A new frozen dataclass beside `Outcome` in `correction.py`** (the ticket's
placement).
**B. Fields on `Outcome`.**
**C. Inside `Ranked`.** §4.2 rules this out and the ticket repeats it.

### Evidence

* **The placement is right, and for a reason the ticket does not give.**
  `matching.py` is pure by §5.2 and by its own module docstring
  (`matching.py:12-15`); the gather is the impure part and it is the part that
  knows which sources answered. Putting reach/error on `Ranked` would make the
  matcher's return type carry network facts, which is the impurity §5.2 forbids
  in the one place it can be enforced by a signature.
* **`Outcome` is the wrong home** because `Outcome` is per-book and final
  (`fragment()`, `kept`, `changed`), while the walk result is consumed *inside*
  `_by_title` and never leaves it. The band decisions all happen between the
  gather and the return.
* **The distinction half-asked turns on is "did we stop on purpose".** §4.2:
  "exiting is a decision the design made, and the later source was never going
  to be asked for that book". A `Ranked` cannot know that; only the loop can.
* `Outcome.waiting` already has a `note` field doing free-text duty, so the new
  type needs no message field of its own for the hold — the walk can build the
  note from its own errors.

### Proposed shape

```python
@dataclass(frozen=True)
class Walk:
    """What one book's title walk gathered, and how it stopped.

    `asked` is the sources that answered, in priority order, which is also the
    sources whose candidates are in the pool. `errored` is `(source, reason)`
    for each source that could not be asked - a walk that errored is not one
    that finished, and a book graded against a pool missing a configured source
    is not a book the rules refused. `exited` says the walk stopped on purpose,
    because the pool as it then stood graded strong: a source that was never
    reached by a decision is not a source that failed.
    """

    asked: tuple = ()
    errored: tuple = ()
    exited: bool = False
    ranked: Ranked | None = None
```

* **Who constructs it**: `_by_title`, one per book, after the gather loop. It is
  the only thing that knows all four facts, and it already builds `tried`.
* **Who reads it**: `_by_title` for the decision (half-asked first, then the
  band), `Outcome.tried` for the log line (`tuple(walk.asked)`), and the tests.
  Nothing else, and nothing outside `correction.py`.
* **Where the band comes from**: `band_of(walk.ranked, self.bands)`, computed
  once in the walk and used for the action. Not read from `Ranked.band`, for the
  threshold reason in §3.
* **The summary's name is `Walk`, not `Gather`,** because `errored`/`exited`
  are facts about a walk and not about a pool. It is a fresh name in
  `correction.py` even though `_by_title`'s docstring calls the thing a walk;
  if that reads badly, `Attempt` is the alternative and the shape is unchanged.

### Early exit vs completed walk

* **`exited=True` is set at the one `break`** that follows
  `band_of(ranked, self.bands) == "strong"`. There is no other exit: `errored`
  does **not** break the loop any more (that is the whole point of pooling), and
  running out of sources is the fall-through.
* **Half-asked is `bool(walk.errored) and not walk.exited`** — one expression, no
  third state, and it is the acceptance criterion's own wording ("a walk that
  *completed* with a source erroring is half-asked"). A walk that exited early
  while a *later* source would have errored is not half-asked, and correctly so:
  the later source was never going to be asked.
* **The gather loop must record the error and continue**, not return. That is the
  single behavioural instruction the whole ticket rests on, and it inverts the
  current `return self._failed(...)` at `correction.py:567`.
* **`Outcome.tried` keeps its meaning and gains nothing.** It is `walk.asked`,
  which for a completed walk is every configured source and for an early exit is
  a prefix. `_among()` (`correction.py:251-260`) is unchanged, so the existing
  "no source among hardcover, google_books…" assertions still read correctly.
* A held book does not need the walk result to survive: `_failed`'s replacement
  writes the note into `self._waiting[path]` and returns. The `Walk` is a local.

### Cost

~25 lines including docstring, one `break`, one new `Outcome` field (or a
generalised `waiting`), and the correction to `_by_title`'s docstring, which
currently promises the opposite behaviour ("a source that cannot answer stops the
walk rather than being passed over", `correction.py:531`). That sentence has to
go: it is the rule this ticket reverses.

---

## 5. Folding `rank()` and `top_candidates()`

### Options

**A. Fold them in CBO-59**: `top_candidates` takes the ranked pool instead of
re-ranking it.
**B. Fold them in a follow-up** and leave the double scoring in the restructure.
**C. Leave both and fold nothing.**

### Evidence

* Measured, not estimated: 3 candidates → 3 `score_candidate` calls for one
  `rank`, and **6** for `rank` followed by `top_candidates`.
* The double call is unavoidable in the *current* walk because the two calls
  serve two different sources (`rank` per source at `correction.py:573`,
  `top_candidates` per source at `:587`). **The pooling restructure removes that
  reason**: after CBO-59 the pool is ranked once, so re-ranking inside
  `top_candidates` is scoring a pool that was just scored.
* Doing it as a follow-up means the walk is written with a redundant scoring pass
  and then rewritten, in the same file, in the next ticket.
* The risk of folding is the **per-source cap**, which is a documented property
  with a test class behind it (`tests/test_llm.py:1230-1323`): the cap is per
  source, and a cap over the merged list would let one source's long tail bury
  another's best record. That is not lost by folding, but it *is* lost by
  folding naively into "the best five of the pool".

### Recommendation

**A, in this ticket, as the last step**, with the cap made explicit:

```python
def top_candidates(ranked):
    """The already-ranked pool, at most CANDIDATES_PER_SOURCE per source, best first."""
    kept, seen = [], {}
    for match in ranked.matches:
        source = match.candidate.source
        if seen.get(source, 0) >= CANDIDATES_PER_SOURCE:
            continue
        seen[source] = seen.get(source, 0) + 1
        kept.append(match.candidate)
    return kept
```

* Takes the `Ranked` the walk already has, so the signature carries the fact that
  the pool is ranked and deduped: `top_candidates(ranked)`.
* Preserves per-source representation, re-sorts nothing, scores nothing.
* Order within the prompt becomes global rank order rather than source order.
  Today it is source order (source one's five, then source two's five). Both are
  "best first" for a given source; global order is the better list to number for
  a model, and the prompt numbers candidates by position, so the numbering the
  model reasons about becomes the project's own ranking. **This is a decision to
  review**, and the test at `test_llm.py:1314` (`prompt.count("title=") == 10`)
  is the one that pins it.

**Not B.** The "changes when things are computed" objection in
`pr-cbo-58.md`'s Ponytail item 4 is precisely the change CBO-59 makes; deferring
it leaves the redundant pass in the diff the reviewer of *this* ticket reads.

### Cost

One function body and its docstring, one call site, ~10 test updates
(`TheCandidateCapTests`, `test_the_llm_is_asked_even_when_there_is_only_one_candidate`,
`test_a_candidate_the_rules_could_not_use_is_offered_to_the_llm`, and the two
per-source-cap prompt-order assertions). Saves one `score_candidate` per
candidate per book — on a 10-candidate pool, five `SequenceMatcher` runs per
book, which is the single largest per-book cost after the network.

---

## 6. What I think is wrong in the ticket

1. **The band table contradicts the notes that follow it.** The table puts
   "strong → writes, stops the walk" with no exception; the half-asked bullet
   directly below says a completed walk that graded **strong** with a source
   erroring "does **not** get written from a pool that is missing a configured
   source". The table needs the exception, or the acceptance criterion "a
   completed walk with an errored source does not write, whatever the band"
   reads as contradicting the row above it. §4.2 makes the bullet the rule, and
   §4.2's own history says the strong-band exemption was deliberately narrowed.
2. **"`rank()` and `top_candidates()` score the same pool twice per source per
   book" is true, and the pooling change makes it worse before it makes it
   better** — pooling moves ranking out of the per-source loop, so the fold is
   not optional tidying but the thing that stops the walk scoring the pooled
   candidates once per source. Worth stating in the ticket, because "fold or
   defer" reads as a style question and it is not.
3. **"`dedupe()` … so only the first record's values are written and per-source
   logging loses the second" understates the second half.** Per-source logging
   does not lose the second record; it never had it. `Change.source` is
   candidate-level (`correction.py:758`), so the log can only ever name the
   winner, and any merge that is not per-field-provenance credits the donor's
   value to the winner. The ticket invites a merge that would put a false
   attribution in the log line the design cares most about.
4. **The acceptance criterion "two sources returning the same edition produce one
   candidate and a strong grade, not medium" does not test the singleton bar it
   looks like it tests.** It passes because the *edition scores 1.0*, and any
   score of 1.0 is strong in either pool shape. The criterion that has teeth is
   §4.1's real consequence: a pooled, deduped singleton scoring **0.9070** (row
   4) now grades **medium**, where today the walk writes it. Session 2 should
   test *that*, or the headline number in the PR will not be the interesting one.
5. **The ticket's reading list names `docs/pr-cbo-58.md`, which does not exist** —
   it is the untracked root-level `pr-cbo-58.md`, and the §-references are
   `docs/research/cbo-58.md`. Anyone starting session 2 from the ticket will not
   find the sections it cites.
6. **Nothing in the ticket says the relay has to change.** Two of the acceptance
   criteria are unreachable without it: `relay.py:150` holds a book on `waiting`
   and delivers it otherwise, so a "half-asked" outcome that is not a hold is
   delivered, marked-free, and never retried. The ticket should name
   `relay.py`'s `_deliver` as in scope.
7. **The three config keys are one defect with two different fixes, and the
   ticket treats them as one list.** `singleton_score` and `medium_score` have a
   designed home and a documented meaning (§4.5, §4.4); `llm_full_scan` has a
   designed meaning that *narrows* today's behaviour. Threading the first two and
   reading the third are separate decisions with separate costs.

---

## 7. Open questions

1. **Do you accept the book-not-delivered behaviour change?** Today a book whose
   source is down is delivered to output with the problem in the log line and is
   never retried; under the half-asked rule it stays in ingest until tomorrow.
   The design says the second; the shipped behaviour is the first, and **no test
   pins the first**, so this is a choice rather than a bug fix. It is also a
   change a user notices: books stop appearing while a source is down.
2. **Does the half-asked rule apply to the ISBN path?** §4.2 is written about the
   pooled title walk, and there is no pooling on the ISBN path. I recommend yes
   (uniform, and it fixes the same outage bug), but it is a wider change than the
   ticket's wording covers and it changes `_by_isbn`'s fall-through.
3. **May `Ranked.band` go?** §5.1 lists `band` as `Ranked`'s content, but a
   property that calls `band_of` with no thresholds is a wrong answer the moment
   a user sets `singleton_score`. Deleting it amends the design note; keeping it
   and never using it leaves the trap.
4. **Does the prompt's candidate order matter to you?** Folding `top_candidates`
   onto the ranked pool makes the list global-rank-ordered and numbers the model
   by the project's own ranking, instead of source-by-source. Same candidate set,
   different order.
5. **`llm_full_scan = false` cuts LLM calls that the shipped walk makes today.**
   With the default and an LLM configured, a low/none-band book goes straight to
   unverified instead of to the model. That is §4.3's design, and it is a
   behaviour change users will see as "the model stopped being asked about some
   books". Confirm that is wanted rather than assumed from a flag's name.
6. **Should `config.py` refuse `singleton_score < strong_score`?** I recommend it,
   because the alternative is a config that inverts §1.2 silently, but it is a
   new startup refusal and it is your call.

---

## 8. Build order for session 2

Each step is green on its own. Steps 1-2 are pure additions; steps 3-7 change
behaviour and each names the existing tests it must rewrite. Test-first: the
behaviour is the unit, so the list is behaviours, not files.

**1. A caller's thresholds decide the band.**
`Bands` with defaults; `band_of(ranked, bands=BANDS)`; `Ranked.band` removed or
unused. Behaviour: the same `Ranked` grades `medium` under the default bands and
`strong` under `Bands(singleton=0.90)`; a `Ranked` built by hand and one built by
`rank()` band identically. *Existing tests: none change (optional parameter).*

**2. The two thresholds come from the config.**
`Corrector(singleton_score=…, medium_score=…)`, `from_config` passes them, and
`Bands` is built once. Behaviour: two `Corrector`s differing only in
`singleton_score` reach different bands, and `config.py` refuses
`singleton_score < strong_score`. *Existing tests: `test_config.py` gains the
refusal; nothing else changes yet.*

**3. An errored source is recorded, not fatal — and half-asked beats the band.**
`Walk(asked, errored, exited, ranked)`; the gather loop catches `SourceError`,
appends, and continues. Behaviour: a source that errors does not stop the walk;
`exited` is True only for the strong break; half-asked is
`errored and not exited`. *Rewrites `tests/test_correction.py:2751`, `:2765`,
`:2777`, `:2787` (the four "a source that is down stops the walk" tests) into
"the walk carries on and the book is half-asked".*

**4. The pool is deduped, then graded once.**
`rank(dedupe(pool))` over every source's candidates. Behaviour: two sources both
get asked; the same edition from two sources is one candidate; two genuinely
different editions of one work are two candidates; the pool is graded once, with
the gap. *Rewrites `tests/test_correction.py:2585` (`second.asked == []`) and
`:2660`; `test_llm.py:1049` may move here or to step 6.*

**5. The band decides the action, and early exit stops the walk.**
strong → `_write` and break; medium → the LLM, or unverified with none
configured; low/none → unverified. Behaviour: each of the four bands takes its
action; a singleton at 0.9070 is **medium**, not written (the behaviour change
from §0); a strong pool stops before the next source is asked, and that exit is
not half-asked. *Rewrites `tests/test_correction.py:1757`, `:1862`, `:1915`,
`:1925` and `:1805`. `test_the_top_of_the_range_is_one_and_one_is_a_usable_setting`
(`:1805`) carries a second loop at `:1839` — `((1.0, False), (0.85, True))`
against a 0.91 near miss — whose `(0.85, True)` case now fails on the singleton
bar. Every one of these drives `strong_score`; each now needs `singleton_score`
to say what it means.*

**6. `llm_full_scan` decides whether low and none reach the model.**
Behaviour: medium always asks; low and none ask only with the flag; strong never
asks; the model's pick is still gated on `strong_score`. *Rewrites
`tests/test_llm.py:1049` and `:1067` to pass the flag, plus one new test that
each band asks (or does not ask) as specified.*

**7. A book that could not be asked is held, not delivered.**
`_failed` (both paths) returns the held outcome; `relay.py`'s `waiting` branch
already carries it; the next scan of the same day does not re-ask, and the next
day does. Behaviour: a half-asked book stays in ingest, is not marked, is not
backed up, and is asked again tomorrow. *Rewrites `tests/test_correction.py:2320`
and `:3125`; adds a relay-level test that the book is still in ingest and absent
from output.*

**8. One ranking per book, with the per-source cap preserved.**
`top_candidates(ranked)`. Behaviour: `score_candidate` is called once per
candidate per book (measurable with a `mock.patch.object` count, as the probe
does); the model still sees at most five per source; a second source's best
record is still shown when the first source offered a long tail. *Rewrites
`TheCandidateCapTests` and the two prompt-shape assertions.*

Steps 1-2 can land as one commit, 3-5 cannot be separated in practice (the walk
is one function), and 6-8 are each independent of one another once 5 is in.

---

# Follow-up: does the scorer use the fields Colophon is there to repair?

Session 1's follow-up probe, extending §0's finding and nothing else. The five
decisions above are unchanged; this section reweights nothing and revises none of
them. Probes: `scratch/probe_payload.py` (the population, three scorings),
`scratch/probe_f2.py` (the window attribution, on one basis),
`scratch/probe_risk.py` (the 4,950-pair band-move census),
`scratch/probe_identity_window.py`, `scratch/probe_count.py` and
`scratch/probe_window.py` (the counts that reconciled the ladder sensitivity).
No production file, test or tracked file was touched; `matching.py` was never
edited, only monkeypatched in process.

**Verdict in one line: the premise does not hold.** The window is not built out
of payload fields — 53 of its 70 scores have a reading in which no payload field
disagrees at all. It is built out of *graded titles*, and the payload fields are
what push the strongest correct matches **down into** it. Removing them moves 882
bands up and 4 down, and the 4 are wrong-author books — while making two editions
of one work indistinguishable to the scorer.

## F1. Every field that contributes, and whether it identifies or describes

Read from `score_candidate` (`matching.py:395-453`), not from the design note.

| Field | Weight | Counted when | Side | Verdict |
| --- | --- | --- | --- | --- |
| Title | `TITLE_WEIGHT` 1.00 | both sides have one | file `dc:title` vs candidate `title`, one form per side (§3.3) | **IDENTITY** |
| Author | `AUTHOR_WEIGHT` 0.80 | the file names a creator **and** the best match against the record's authors reaches `AUTHOR_AGREES` 0.5 | file `dc:creator`(s) vs candidate `authors` | **IDENTITY**, and effectively a gate: a non-agreeing author's weight leaves the denominator and the score is capped at `NO_AGREEMENT_CEILING` 0.7 |
| Series position | `SERIES_WEIGHT` 0.20 | *both* sides state one | **file**: the series number parsed out of the file's own title bracket by `_parts_of`. **candidate**: the source's `series_number` | **IDENTITY** — see below |
| Year | `YEAR_WEIGHT` 0.15 | both sides carry a four-digit year | file `dc:date` vs candidate `date` | **BOTH**, and it is the one that falls on the payload side — see below |
| ISBN | 0.00 | never | — | **IDENTITY** with a weight of zero. `Candidate.isbn` exists, is carried into the file, and reaches no `counted.append` |
| Publisher | 0.00 | never | — | **PAYLOAD**, weight zero and not even on `FileBook` |
| Language | no weight | — | — | **IDENTITY**, handled as a hard drop in `rank` (`_same_language`), not as distance |
| Description, cover, genres | no weight | never compared | — | **PAYLOAD**, never scored. `MAX_TITLE_CHARS`' docstring says descriptions are "never compared" |

So the payload that is actually in the distance is **series 0.20 and year 0.15 out
of a 2.15 total — 16.3% of the scale, and only when both sides state the field.**
Everything else Colophon writes is already at weight zero or absent.

**Why series falls on IDENTITY, and the file side is the reason.** The field
Colophon *writes back* is `series`/`series_number` — a source's string, written
under `overwrite`. But the field the *comparison* reads on the file side is not a
written value at all: it is `_parts_of`'s capture of the number in the file's own
title, `(The DCI Ryan Mysteries Book 6)`. Nothing Colophon has ever written puts
it there; it is the download's own claim about which book this is, and it is
independent of the record. The comparison therefore asks "does the record agree
with the identity the file's title asserts?", which is identity evidence. The
design says the same thing in `cbo-58.md:267-278`, and it is conditional
two-sided precisely because a record with no series data is not evidence of a
mismatch — which is the normal state of a Google Books record.

**Why year falls on PAYLOAD, and the design already says so.** `cbo-58.md:312-322`
calls year "the field most polluted by the thing it is being asked to measure",
records that the same book "legitimately arrives as 1937 in one record and 2012 in
another", and assigns it the job of *breaking a tie between two records that
agree on title and author* — a novel and its reissue, an omnibus. A field whose
intended job is to separate editions is a field whose disagreement is expected
between two correct records. Both sides of this comparison are payload: the
file's `dc:date` is written by the `fill` rule, and the record's `date` is
written by the same rule. **This is the half of the user's premise that holds.**

**The price of the split, stated once.** The scorer compares an identity claim
extracted from the file's title (series) and a payload value the file carries
(year), and both are legitimately expected to disagree when the source describes
a different impression. That is a real measurement problem, not a coding mistake,
and §4.4's tuning pass is the procedure the design nominated for it.

## F2. Re-run: the same population with payload contributing nothing

Method. `matching.py` untouched. Two reweightings, and a check that turned out to
matter:

* **zero-weight** — `SERIES_WEIGHT = YEAR_WEIGHT = 0.0`, monkeypatched in
  process. I expected this to differ from removing the fields, on the strength of
  `cbo-58.md:338-339` ("a zero weight means the field is not in the denominator at
  all, while a small [weight is]"). **It does not differ.** A zero weight is still
  appended to `counted`, but `sum(weight for weight, _ in counted)` then adds
  **0.0**, so the denominator falls to 1.8 exactly as it would if the fields were
  absent — `matching.py:436-437`. Measured: 0.8372 (as shipped) → **1.0000** (both
  weights zero) and **0.9999** (both weights 0.0001). The note's distinction is
  about a *small* weight versus none, not zero versus none, and my first reading
  of it was wrong.
* **identity-only** — series and year absent from the candidate before scoring, so
  they are neither compared nor in the denominator. **Numerically identical to
  zero-weight**, and that equivalence is worth knowing: a weight change to zero is
  a removal, not a de-emphasis.

Every number below is on **one basis**: session 1's own sweep structure
(`scratch/probe_f2.py`) — the 17-value title ladder, 7 author similarities, 3
series states × 3 year states = **1,071 rows**, 70 distinct scores in
[0.89, 0.95).

### The window, and where each score comes from

| Reachable by | Distinct scores in the window |
| --- | --- |
| a graded title **only** (no payload disagreeing in any reading) | **49** |
| a contradicting payload **and** a graded title | **16** |
| a contradicting payload **only** | **1** (0.9000) |
| neither — an author similarity under 1.0 and nothing else | **4** |
| **total** | **70** |

Two summaries of the same table, and both matter:

* **A contradicting payload is in at least one reading of 17 of the 70** — the
  upper bound on how much of the window the payload can account for. Those 17 are
  0.9302, 0.9293, 0.9231, 0.9230, 0.9221, 0.9220, 0.9194, 0.9111, 0.9070, 0.9069,
  0.9060, 0.9000, 0.8990, 0.8978, 0.8977, 0.8974, 0.8961.
* **53 of the 70 have at least one reading in which no payload field disagrees at
  all.** That is not a bound in the other direction — it is the stronger fact: you
  can produce 53 of these 70 scores with the file and the record agreeing on
  everything except the title.

Only **one** value (0.9000, series alone at denominator 2.00, no year on the file)
is produced *exclusively* by a payload disagreement. The other 16 need a graded
title as well, or are producible without any payload disagreement.

**So the premise does not hold as stated.** The window is mostly built by graded
titles: 49 of 70 exclusively, 53 of 70 in a reading with no payload disagreement.
The payload's distinctive contribution is 17 values at the very top of the window
(0.8961-0.9302) and it is concentrated in the hundredth above the strong bar. The
title comparison — which no part of this proposal touches — is the dominant cause
of "the right book lands in [0.89, 0.95)", and the payload fields are what push
the *strongest* correct matches down into it.

### A correction to session 1's §0

§0 says "71 distinct scores land in [0.89, 0.95)". **On this probe's basis the
answer is 70, and on a shorter ladder it is 71** — the count is an artefact of
which title similarities the enumeration ladder contains, and is not a fact about
the scorer. Session 1's own `probe_bands.py` printed a different figure again
(500 distinct scores overall, which its own sweep structure does not reproduce).
The defensible statement, and the one to carry into session 2, is the one above:
**the window is ~50-55 values caused by graded titles and ~17 reachable by a
contradicting payload, in a 1071-row sweep.** I have left §0's "71" in place
rather than revise a section this follow-up was told not to touch, and this
paragraph is the correction.

### Do the two named cases move?

Both move straight to **1.0000 → strong**, and so does every other correct-but-
contradicted book:

| Case | now | band now | identity-only | band after |
| --- | --- | --- | --- | --- |
| right book, series contradicts (#11 vs #6) | 0.9070 | medium | **1.0000** | **strong** |
| right book, year contradicts (1999 vs 2017) | 0.9302 | medium | **1.0000** | **strong** |
| right book, series **and** year contradict | 0.8372 | medium | **1.0000** | **strong** |
| right book, series contradicts, no year on the file | 0.9000 | medium | **1.0000** | **strong** |
| right book, year contradicts, no series position stated | 0.9231 | medium | **1.0000** | **strong** |

The user's instinct is confirmed at the case level: a file whose series and year
are both wrong — exactly the file Colophon exists to repair — is graded **medium**
today on a perfect title and a perfect author, and identity-only would grade it
**strong**. That is 0.1628 of scale, the whole of the deduction.

**What one contradicting payload field costs, by what the file actually states:**

| Fields in play | Denominator | Agreeing | Contradicting | Cost |
| --- | --- | --- | --- | --- |
| title, author | 1.80 | 1.0000 | 1.0000 | **0.0000** |
| title, author, series | 2.00 | 1.0000 | 0.9000 | 0.1000 |
| title, author, year | 1.95 | 1.0000 | 0.9231 | 0.0769 |
| title, author, series, year | 2.15 | 1.0000 | 0.8372 | 0.1628 |

A file with no year and no bracket pays **nothing** — the fields are not compared
at all. The cost is entirely borne by files that state both.

### What new behaviour appears — the risk direction

Measured over 4,950 candidate/file pairs (`probe_risk.py`: 3 files × 11 titles ×
6 author spellings × 5 series positions × 5 dates):

| | count |
| --- | --- |
| band unchanged | 4,064 |
| band moves **UP** | **882** |
| band moves **DOWN** | **4** |

**Nothing that graded strong moves down. Not one case.** The only four down-moves
are `medium → low` at 0.8084 → 0.7711, and all four are the **same wrong-author
book**: title `Cragside: A DCI Ryan Mysteries` with author `L. J. Riss` or
`L. K. Ross` (#6, 2017). Those clear the 0.5 author gate at 0.6814 — §6 item 3's
known sharp edge — and the payload's 0.0373 is what carries them over
`medium_score`. Losing that is a gain in the strong direction and a loss only in
that such a book would skip the LLM: it would be marked unverified with no call,
where today it is put to the model.

The up-moves are the whole point of the change and they are all one shape: a
correct title and a correct author with a contradicting series and/or year going
to **strong** — meaning *written*, and written **from that record's payload over
the file's**. See F5.

**One caveat on the census, stated so the number is not over-read.** It is taken
on a *singleton* pool, because the fixture set is one source. In a pool of two or
more the strong bar is 0.89 rather than the singleton bar, so a candidate at
0.9070 is already **strong** today and the up-moves there are only the ones under
0.89. The 882 is the right order of magnitude for the "one source returned one
record" case, which §1.2 records as the common one, and it is not a projection for
a pooled library.

### Is the medium band still reachable?

**Yes, and it is still populated** — 882 of the up-moves start there. With
payload absent the score *is* the title-and-author score, so the boundaries become
exact and legible:

| Boundary | title similarity needed (author exact) |
| --- | --- |
| medium (`medium_score` 0.80) | ≥ 0.80 |
| strong, singleton bar 0.95 | ≥ 0.95 |
| strong, multi-candidate 0.89 | ≥ 0.89 |

Medium is the whole band 0.80 ≤ title < 0.95. It does not empty, and it is still
where the interesting books are — on this arithmetic the medium band is not a
queue for the LLM's judgement of *which* record, but for its judgement of whether
a title spelling is the same book.

**But the harmful interaction is in the other direction**, and it is the one case
where the payload does real damage:

> A book whose title similarity is **below 0.92** and whose series **and** year
> both contradict scores **under 0.80** — so it does not even reach the LLM. It is
> marked `colophon:unverified` with no model call.

The boundary is exact: title 0.92 with series and year both contradicting gives
0.8000, the first value that reaches medium; 0.91 gives 0.7940 and is lost. With
payload removed, that same book needs only title ≥ 0.80 to reach the model. **That
is the strongest form of the user's argument, and I do not think it was the form
they made** — the harm is not "correct matches are refused", it is "correct
matches fall out of the LLM's reach and are marked without ever being asked".

## F3. The confusability check: what dropping payload costs

This is the argument against the change, and it is stronger than the case for it.

**Where identity ends, and it ends exactly at the multi-edition problem.** Payload
is the only thing that separates two records that agree on title and author. Two
editions of one work, two printings, a novel and its reissue — all identical to
title and author, all different to series and year. With payload at zero the
identity-only score for both is **1.0000**, the **gap is 0.0000**, and the leader
is whichever the source happened to list first. §1.2 exists to refuse exactly
that: "a pipeline that writes the leader anyway is writing whichever of two
near-identical numbers happened to sort first."

Measured, on three pairs the fixtures hold:

| Pair | now | gap now | identity-only | gap after |
| --- | --- | --- | --- | --- |
| two editions, #6/2017 vs #11/2017 | 1.0000 vs — | — | 1.0000 vs — | — |
| two editions, #6/2017 vs #6/2018 | 1.0000 vs 0.9302 | **0.0698** | 1.0000 vs **1.0000** | **0.0000** |
| two editions, #6/2017 vs #11/1999 | 1.0000 vs 0.8372 | **0.1628** | 1.0000 vs **1.0000** | **0.0000** |
| right book vs a different book by the same author | 1.0000 vs 0.3721 | 0.6279 | 1.0000 vs 0.4444 | 0.5556 |

Two further facts make this worse rather than better:

1. **The first row is not a tie at all, and it is the scariest one.** `dedupe`
   groups by title + first author + **year** (`matching.py:733-743`), so two
   records differing *only* in series position **collapse into one candidate
   before ranking**. The scorer never compares them. The kept one is whichever
   came first, and Colophon then writes its series number, and its series name,
   over the file's — so a file that says Book 6 can silently have a record's
   Book 11 written onto it. Verified: same-title, same-author, same-year, series
   6 vs 11 → `dedupe` returns **1** candidate. **This hole is present today and
   payload does not close it**; identity-only widens it from "series is not
   compared when the year agrees" to "series is never compared at all".
2. **Discrimination against wrong *books* is unaffected** — the last row shows
   identity-only still separating a different title by the same author
   (0.5556 gap). The loss is confined to pairs that agree on title and author,
   which is precisely the pair set the design built the series weight for
   (`cbo-58.md:267-271`, naming Belsay #23, Berwick #24 and The Infirmary #11 as
   the fixtures).

The asymmetry, stated plainly: **identity-only cannot tell two editions apart, and
its failure mode is to write one edition's payload onto another edition's file.
Payload cannot tell a wrong-but-explainable year from a wrong record, and its
failure mode is to send a correct book to a human or a model.** The design's own
§4.1 already makes that trade in the payload's favour on purpose: "a miss is
visible, and a wrong write is not."

## F4. Scope call

**This is CBO-58's, not CBO-59's, and it should not block CBO-59's session 2.**

* CBO-59's whole content is the *flow*: gather, dedupe, grade once, act on the
  band. It changes no weight and adds no field to the distance. Reweighting is a
  change to `matching.py`'s scoring model, whose numbers, tests and design note
  are CBO-58's.
* **Blocking CBO-59 would make the symptom worse, not better.** Today's walk
  ignores the bands entirely and writes anything ≥ 0.89; CBO-59 is what *exposes*
  the 0.9070 and 0.9302 correct books as medium at all. Holding CBO-59 keeps
  silently writing those books from a record whose series contradicts the file —
  the same wrong write, without the review step. The downgrade is the design
  becoming visible, not the design breaking.
* If it does become a ticket, it is **not** "drop the payload from the distance".
  Every number in it is invalidated by a weight change: `cbo-58.md` §2.1, §2.2,
  §4.1's windows and tables, the singleton bar's "≈ 0.89 at denominator 2.15"
  justification, `BAND_GAP` = 0.08 (calibrated as "about half the year weight"),
  and the literal expectations in `test_matching.py` (rows 1-11, the gaps, the
  graded-title sweep). A weight change is a re-derivation of four sections and a
  rewrite of those assertions, not a config edit.
* The one **cheap and bounded** version of it, if the medium-band downgrade rate
  is judged too high, is the year alone: its stated job is tie-breaking, not
  match-blocking, and one disagreeing year currently costs a *perfect-identity*
  book 0.0698, which is enough on its own to drop a 1.0000 to 0.9302 and out of
  the singleton bar. Either the weight comes down until the cost is under 0.05
  (≤ 0.1075 at denominator 2.15), or year joins publisher and ISBN at weight zero
  — at which point the tie between two records agreeing on title, author and
  series is left standing and goes to medium, which is what
  `cbo-58.md:331-334` already decided for publisher. Both want §4.4's labelled
  tuning set, and neither belongs in CBO-59.
* The genuinely separate question this probe turned up is the one from F2's last
  paragraph — that a book under title 0.92 with both payload fields contradicting
  is marked **with no model call**, and the "review queue" is therefore the LLM or
  nothing. On a default install with no LLM configured there is no queue at all.
  That was CBO-59 §7's open question 5 and it is now a measured rate rather than
  a worry.

**What a CBO-58-scoped ticket would contain, if you want one:** the labelled
tuning set §4.4 step 1 already specifies; a decision on whether year is scored at
all; the re-derivation of §2.1, §4.1 and `BAND_GAP` under whichever weights are
chosen; the `test_matching.py` rewrite that follows; and the measured
medium-with-no-LLM rate before and after. It blocks nothing in session 2.

## F5. Recommendation

**Path (a): leave scoring alone, and accept that medium-band books go to the
review queue as §5.2 specifies.**

* The premise was worth testing and it is **half right**: year is payload, and one
  contradicting year does cost a correct book 0.0769 or 0.0698 — enough to put a
  perfect-identity book in medium. Series is not payload; the file's series claim
  comes out of the file's own title, and the design argues for it explicitly.
* The window is **not** payload-built: of its 70 distinct scores, 49 need nothing
  but a graded title in any reading, 53 have a reading with no payload
  disagreement at all, and only 17 are reachable by a contradicting payload.
  Session 1 §0's framing — "the right book with one field contradicting" — is
  true of 17 of them and false of the other 53.
* The intervention **does not have the property it was proposed for**. It moves
  882 bands up and 4 down, and it buys that by making two editions of one work
  indistinguishable to the scorer: gap 0.0000, leader = whatever the source listed
  first, written over the file. §1.2's "high score with a small gap is evidence
  that the metric is saturated" is exactly what identity-only produces for the
  pair set the series weight exists for.
* The payload is not evidence Colophon invented. It is the file's own claim
  (series, from its title) and the source's own claim (year), compared against
  each other. Colophon writing those fields back afterwards is what makes the
  comparison *about the thing being repaired*, which is uncomfortable, but it is
  also what stops a repair being made from a record that contradicts the file.

### Cost of (a)

* **The measured harm stands.** A file whose series and year both contradict — the
  file Colophon exists to repair — is graded medium on a perfect title and author.
  Under CBO-59 that is one LLM call, or `colophon:unverified` on a default
  install.
* **The sub-0.80 case is worse and is not fixed by either path as scoped.** Title
  similarity under 0.92 with both payload fields contradicting falls below
  `medium_score` and is marked with no model call. Only reweighting or a lower
  `medium_score` reaches it. `medium_score` is a config key, so a user who wants
  it can set it today — and after CBO-59 sets it *working*, which it does not
  today.
* Nothing in CBO-59's build order changes. Steps 1-8 stand as written.
* One line of the §4.5 config comment becomes a lie if this is left alone
  forever: it says the three thresholds "turn that number into a band", which
  after CBO-59 is true, but it does not tell a user that the number includes two
  fields Colophon is going to overwrite. Worth one sentence in the comment,
  either way.

### Cost of (b), if you would rather take it

Session 2 grows a step **0** that must land before step 1, and it is not a
one-liner:

* decide between zeroing year, halving it, or a window comparison (which
  `cbo-58.md` §6 item 6 already names as settled-in-principle and open in value);
* re-derive `cbo-58.md` §2.1 (rows 1-11), §2.2, §4.1's singletons table and both
  windows, `BAND_GAP` (its 0.08 is justified against the year weight), and the
  singleton bar's "≈ 0.89 at denominator 2.15";
* rewrite every literal in those tables' tests: `test_matching.py`'s rows 1-11,
  the four gap assertions, the graded-title and every-denominator sweeps, and
  `test_correction.py`'s `A_NEAR_MISS` (0.9070 today, and four tests quote
  "confidence 0.90");
* accept the 4 measured down-moves (wrong authors skipping the LLM) and the
  widened dedupe hole in F3 row 1;
* and re-run §4.4's tuning set, which does not exist yet.

That is a ticket of its own. It is not a session-2 step.

### The one change I would take now, and it is not a weight change

**Make the falling-out-of-the-LLM's-reach case impossible rather than rarer.**
`medium_score` is user-facing and CBO-59 is the ticket that makes it work. If a
book with a correct identity and a contradicting payload must reach the model,
the cheapest correct way is to let the walk ask whenever the band is low and
`llm_full_scan` is on — which is *already in CBO-59's step 6 and already the
documented meaning of that flag* (§4.3). Turning `llm_full_scan` on is the
existing, zero-new-code answer to F2's boundary case, and it is worth saying so
in the config comment next to the key rather than adding a weight change to
compensate for a comparison the user can already widen.

Which is the point to end on: **the design already has a knob for this, and it is
`llm_full_scan`, not the weights.**

