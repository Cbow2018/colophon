# CBO-58: modelling the matcher on distance scoring and confidence grading

**For the session that builds CBO-58** (session 2), and for CBO-59/60/61/62 which
hang off the same design.

Written 2026-09-21, revised in session 1c after the numbers were checked against
the real `colophon/matching.py`. Read with `../AGENTS.md` and the ticket
[CBO-58](https://linear.app/cbow/issue/CBO-58/model-the-matcher-on-beets-distance-scoring-and-confidence-grading),
whose parent is the design spec
[CBO-33](https://linear.app/cbow/issue/CBO-33/colophon-ebook-metadata-relay-design-spec-v1).

**Every number in this note is computed, not estimated.** The script that produces
them is `scratch/cbo-58-calibration.py` (uncommitted, gitignored); its output is
`scratch/cbo-58-output.txt` and the reasoning behind each figure is in
`scratch/cbo-58-findings.md`. Session 2 should re-run the script rather than trust
a table in prose.

## Provenance: what this note is, and what it is not

beets' source was **not read, fetched or quoted** while writing this. Everything
below about how beets works is taken from CBO-58's own prose description of the
mechanism, plus the descriptions in `cbo-36-title-matching.md`. Where the ticket
names a beets file and a behaviour, this note describes that behaviour in Colophon's
own terms and re-derives it for Colophon's domain — it does not transcribe anything.

Consequences, stated plainly so session 2 is not misled:

- **The exact normalisation formula is not in this note**, because it is not in the
  ticket. §1 says what the mechanism must achieve arithmetically and what choices
  fall out of it. §6 lists what could not be settled without the source as open
  questions rather than guesses.
- The numbers proposed here are **Colophon's own**, computed against the fixture rows
  (§2.1) and checkable by re-running the script. They are not values copied from
  anything. Title and author are the only two that are derived; the rest are defaults
  (§2).
- Session 2 builds from this note. If beets source is ever pasted into a session and
  adapted, the output is derivative and the attribution in CBO-58's "Attribution and
  provenance" section applies — file header, `THIRD-PARTY.md`, exact copyright line
  read from beets' own `LICENSE`. If session 2 works from this note instead, the
  acknowledgement is courtesy rather than obligation. That is the maintainer's call,
  and it is worth making before the module is written rather than after.

## Where the work sits

The matcher is **already one module**: `colophon/matching.py`. It holds title
cleaning, the comparison normalisation, the confidence rule, and the `Candidate` /
`FileBook` / `Match` types that both sources (`hardcover.py`, `googlebooks.py`) and
the pipeline (`correction.py`) pass around. CBO-57's extraction review is therefore
already satisfied in shape; this ticket changes what is inside the module, not where
it lives.

What exists today, and what this ticket replaces:

| Today (`matching.py`) | CBO-58 |
| --- | --- |
| Title compared in three hard tiers: exact 1.0, whole-word contained 0.9, else 0.0 | A penalty per field, graded by similarity |
| Author compared as all-or-nothing: any creator matches any author → 1.0, else 0.0 | A graded author penalty, plus an agreement floor (§1.3) |
| `confidence = 0.6·title + 0.4·author + series nudge` | `score = 1 − Σ(weight·penalty) / Σweights` |
| Only `cleaned.search` is scored; `also` is for querying only | Both title forms are for querying; **one** form per side is scored (§3.3) |
| One number, compared against one `confidence` key (0.85) | A number **and** a runner-up gap, resolving to four bands |
| `nearest_candidate()` returns the single best | `rank()` returns the whole ordered field, bands resolve from it |
| Two outcomes: matched, or unverified | Four bands, three of which reach the same unverified outcome (§4.1) |
| Language is the query's business and is not re-checked (`matching.py:274-279`) | Language stays the query's business — decided, not moved (§3.5) |
| `correction.py` scores one source's reply at a time and returns on the first that clears | The pool is scored as a whole, then deduped, then banded |
| `normalise()` is both the comparison helper and the record's durable key | Split: a frozen key function, and a new comparison-only pipeline (§3.6) |

Branch: `dsh/cbo-58`. Linear suggests
`callumbowden111/cbo-58-model-the-matcher-on-beets-distance-scoring-and-confidence`;
the standing rule in `~/.dsh/AGENTS.md` is `dsh/<short-topic>`, so the shorter one won.

---

## 1. The mechanism

### 1.1 A weighted penalty accumulator

Each field of a candidate is compared against the corresponding field of the file,
and the comparison produces a **penalty** between 0 and 1: 0 when the two agree
completely, 1 when they have nothing in common. The penalties are multiplied by a
per-field **weight** — how much that field's disagreement should count towards the
verdict — and summed. The sum is divided by the total weight of the fields that were
actually compared, which puts the result on a 0–1 scale no matter which fields were
available. The score is that fraction, inverted:

```
counted = every field both sides supply, except author when the author gate fails
score   = 1 − ( Σ weight_f × penalty_f ) / ( Σ weight_f )        over `counted`
```

The inversion is what makes it a *score* rather than a *distance*: 1.0 is a record
that agrees with the file on everything, 0.0 is a record that agrees on nothing, and
every field's contribution is a subtraction from a perfect start.

Penalties rather than rewards, and this is the part worth keeping from beets rather
than reinventing as a bonus table: a reward model has to be defended against a
candidate winning by accumulating many weak agreements, because two mediocre
matches can outscore one strong one. A penalty model cannot be gamed that way. The
only way to score highly is to have nothing wrong with you. The metric's shape
encodes the project's asymmetry — a false accept is much worse than a false reject —
rather than relying on a threshold to enforce it.

Normalising by the weight of the fields compared is what lets one number serve every
book. Books differ in what the file says about them: a file with a title, an author
and a year, and a file with only a title, both have to produce a number the same
threshold can read. Dividing by the weight actually applied makes "everything I
could check agreed" equal 1.0 in both cases; dividing by a fixed total instead would
mean a sparse file could never score well, which punishes the file for its own
silence rather than for anything the candidate got wrong.

One consequence needs handling and does not fall out on its own: **a perfect match
must be exactly 1.0.** Not 0.997. `difflib` ratios are noisy near the top — an
uncalibrated ratio on two identical strings can still land a hair under 1.0 — so the
penalty curve needs a dead band in which "so close that nothing meaningful separates
them" is rounded to a clean zero penalty. The same applies to floating-point
accumulation: 1.0 is a number a user reads in a log line and a test asserts on.

### 1.2 Why grading needs the gap to the runner-up

The top score answers "does this record look like this book?". It cannot answer "is
this record *the* book?", and those are different questions.

A score is a lossy summary of two messy records. It is high both when the right
record is present and the comparison captured it, and when the wrong record happens
to look right — a different book by the same author in the same series, a reissue
whose title the source spells differently, a lookalike whose title contains the
file's as a prefix. The score alone cannot tell those apart, because in both cases
the wrong record's similarity is high *for the same reasons the right one's would
be*. The gap to the runner-up is the only part of the measurement that distinguishes
them: if a second record explains the file almost as well, the comparison has not
actually discriminated between them, and a pipeline that writes the leader anyway is
writing whichever of two near-identical numbers happened to sort first.

Equivalently: a high score with a large gap is evidence that the metric is
*discriminating*. A high score with a small gap is evidence that the metric is
saturated — that it is responding to something shared by every candidate in the pool
rather than to what makes this book this book. Saturation is the failure mode that no
absolute threshold can catch, because raising the threshold does not separate two
numbers that are close to each other; it only rejects both of them, including the
right one.

This is also what gives the LLM a coherent job. A book where the rules scored
something meaningfully above "nothing" but could not separate the leader from the
runner-up is a genuine question with a small, well-formed set of possible answers,
which is precisely a thing worth spending a call on. A book where the rules are
confident is not a question at all, and a book where the rules scored nothing is not
one either. So the banding, not the score, is the trigger condition for the LLM
tiebreaker, and the gap is the part of the banding that makes the trigger mean
"undecided" rather than merely "not good enough".

**Early exit, settled.** CBO-58 says to stop querying once a candidate scores in the
strong band. The reading this note takes, and the only one consistent with §4:
**the walk stops as soon as the pool as it then stands grades strong**, gap
included. A later source can only add candidates, so a pool that is already decisive
is not made less decisive by new arrivals unless they tie, and that is the accepted
rare loss the ticket names.

**Early exit is rare, which is worth knowing before optimising it.** A singleton
pool is the common case: `cbo-36` §1 records that a cleaned title returns two
editions of *one work*, so the candidate list is one record. A singleton can only be
strong at 0.95 (§4.2), which requires everything the file says to agree. So for most
books the walk runs to completion and the gap rule is the exception rather than the
mechanism. Early exit is a saving on the minority of books that return several
works, not on the library.

### 1.3 The author gate

The shipped module protects one case absolutely: `Match.agrees` is
`title_score > 0 and author_score > 0`, `NO_AGREEMENT_CEILING` caps everything else
at 0.7 against a 0.85 threshold, and a file naming no author returns `NO_AUTHOR` and
can never match. That is deliberate — CBO-36's whole weight scheme exists to make
"a title match alone is not a match" hold arithmetically — and the graded design has
to preserve it rather than assume the arithmetic still does.

It does not. With `date` added to `FileBook`, a file that names no author but whose
title and year agree compares two fields, scores 1.0000, and would grade strong
(§2.1, row 10). "At least two fields compared" is therefore **not** the rule. The rule
is:

**A candidate agrees only if the file names at least one creator, the record names at
least one, and the best file creator reaches `AUTHOR_AGREES = 0.5` calibrated
similarity against some record author.** When it does not agree:

- the **author weight leaves the denominator**, so the score is computed on the
  reduced title/series/year scale rather than being diluted toward zero by a field
  that is not being counted; and
- the result is capped at `NO_AGREEMENT_CEILING = 0.7`, **kept at the shipped value**
  so the number in the log stays comparable with what the pipeline logs today.

A capped candidate can never reach the strong band at either band threshold (§4),
which is the property the shipped ceiling provided and this preserves.

**What "agrees" means for a graded similarity, and the honest limit of it.** The
floor is a policy choice, not a measurement, because the metric cannot separate the
cases it is being asked to separate:

| Pair | Similarity | Truth |
| --- | --- | --- |
| `L. J. Ross` / `L. J. Riss` | 0.6814 | same person, one letter wrong |
| `L. J. Ross` / `L. K. Ross` | 0.6814 | **a different person** |

Identical to four decimal places. Both are one character in the same position of a
six-character key, and a character ratio has no way to tell a typo from a wrong
name. **No value of the floor separates them.** What 0.5 does buy is the cases that
matter in bulk: `L.J. Ross`, `LJ Ross`, `Ross, L. J.`, `Le Guin, Ursula K.` and
`J. R. R. Tolkien` all score 1.0000 and agree; `Ursula Le Guin` 0.8533 and
`L. J. Ros` 0.8308 agree; `M.J. Porter` 0.0200, `Carly Reagon` 0.0568,
`M. J. Ross-Smith` 0.2200, `Ross, Carly` 0.3806, `L. J. Roth` 0.3957 and `John Ross`
0.4600 do not.

Two sit above the floor together and a reader has to be told which is which:
`L. J. Riss` at 0.6814 is the same person misspelt, and `L. K. Ross` at 0.6814 is
**a different person, and the gate passes it**. Nothing in this section refuses it;
`strong_score` does, and §6 item 3 is where that is worked through.

So the floor's error runs one way, which is the direction this project prefers — it
admits a wrong author who shares initials and a surname rather than refusing a real
variant. One exception, recorded in §3.4: a bare transposition (`LJ Ross` against
`Ross LJ`, 0.1914) is genuinely the same name and is refused, because only the comma
form is reversed before comparison and an uncommaed one falls below the floor.

---

## 2. Field weights

| Field | Weight | Compared when |
| --- | --- | --- |
| Title | **1.00** | both sides have one |
| Author | **0.80** | the file names at least one creator — and only counted when it agrees (§1.3) |
| Series position | **0.20** | *both* sides state one |
| Year | **0.15** | both sides carry a four-digit year |
| ISBN | **0.00** | never scored — see below |
| Language | — | not a weight; the guarantee stays in the source query (§3.5) |

With every field available the denominator is **2.15**. The weights are **relative**;
only their ratios reach the score. Both facts matter for tuning: changing every
weight by the same factor changes nothing, and adding a field changes every existing
book's score slightly because the denominator moved.

**These numbers were swept in session 1c and corrected in 1d, not derived.** Sweeping
series ∈ {0.15…0.35} × year ∈ {0.15…0.30} against the target verdicts for the fixture
rows leaves 18 of 20 combinations working, so **the targets do not pin the weights
tightly** — they are a region, not a point, and the region is what §4.4's tuning pass
narrows. Nothing in the fixture set selects 0.20 and 0.15 from inside that region, and
session 1d removed the argument that used to: see the series note below. **`year` at
0.15 and `series` at 0.20 are unjustified defaults**, kept because there is no evidence
to move them and because their *ordering* — title ≫ author > series ≥ year > publisher
— is what the design actually argues for. Only title's 1.00 and author's 0.80 are
derived, and the author's is derived from §1.3's gate rather than from the sweep.

**Title heaviest (1.00).** It is the only field that names the book rather than
describing its circumstances. Author says who wrote *a* book, year says when *an
edition* of it appeared, a series position says where it sits in a run — none of them
identifies which book this is on its own, and for a prolific author in a long series
none of them narrows it much. It is also the field the search itself is built on, so
the title agreeing is partly a statement about the query having worked, which is the
thing most likely to have silently gone wrong.

**Author next (0.80).** The strongest available corroboration, and the field that
carries the most weight in practice because it is the one that is *usually*
available and *usually* differs between lookalikes. It is close to the title rather
than far below it deliberately: a title-only agreement is not a match, so the author
has to be able to drag a score down substantially on its own. Note that with the
gate in §1.3 the author is effectively a **gate plus a small adjustment**: a
non-agreeing author removes 0.80 from a 2.15 denominator (37% of the scale) and caps
the result, so the field's real power is the gate, not the weight.

**Series position third (0.20), conditional.** The file's own title frequently
carries its position in a series — `(The DCI Ryan Mysteries Book 6)` — and that is
the one fact about the book the title has that a source keeps elsewhere. It is a
genuinely strong discriminator between books *in the same series*, which is the
commonest hard case: Belsay #23, Berwick #24, and *The Infirmary* #11 are four
records this project has real fixtures for (`cbo-36` §1). It is conditional rather
than always-on because most files carry no bracket at all, and a field that is
absent from most books should not sit in every denominator diluting the fields that
are present. Note the two-sided requirement: it is compared only when *both* sides
state a position. A file that says Book 6 against a record that says nothing about
series is not evidence of a mismatch — the record may simply not carry series data,
which is the normal state of a Google Books record (`cbo-37`).

**The series weight is bounded above, and unconstrained below.** Session 1c justified
0.20 by saying it lands row 4 on 0.9070, which is CBO-36's own 0.90 for that case.
Session 1d established that this is dead: row 4 is **no longer written** at 0.9070 — it
is medium (§2.1, §6 item 4) — so landing on CBO-36's number no longer preserves
CBO-36's outcome.

Session 1d then overcorrected, claiming the sweep changed no row's band and calling 0.20
"unjustified". **That is false at the top of the swept range.** Row 3 sits close enough
to `medium_score = 0.80` that raising the series weight pushes it out of the medium band
and out of the LLM's reach:

| Series weight | Denominator | Row 3 | Band |
| --- | --- | --- | --- |
| 0.15 | 2.10 | 0.8571 | medium |
| 0.20 | 2.15 | 0.8372 | medium |
| 0.25 | 2.20 | 0.8182 | medium |
| 0.30 | 2.25 | **0.8000** | medium (exactly on the boundary) |
| 0.35 | 2.30 | **0.7826** | **low** |

So the sweep does constrain the weight: **series is bounded above by row 3 staying in
medium**, which puts the ceiling at 0.30 — and 0.30 only survives by landing on
`medium_score` exactly, with no margin, so the practical bound is below it. Below 0.30
the sweep finds nothing: every value from 0.15 to 0.28 leaves every row in its band, so
the weight is **unconstrained in that direction**.

**0.20 remains the default and §4.4 sets it.** The position it holds is ordinal and
nothing more: a series position is richer evidence than a release date (it says where
the book sits, not when a copy was printed), so series ≥ year; and it cannot outweigh a
title and an author that agree, so series ≪ author. That puts it between 0.15 and 0.30
and specifies no value inside that range — which is the honest statement, and narrower
than "unjustified".

**Year third (0.15), and deliberately weak.** Year is the field most polluted by the
thing it is being asked to measure. A source's `date` may be the edition's release
date or the work's first publication, and which one a given record carries is not
observable from the record itself (`cbo-38`). The same book legitimately arrives as
1937 in one record and 2012 in another. So the year's real job is not to confirm a
match but to *break a tie* between two records that agree on title and author — a
novel and its reissue, an omnibus, a same-titled book by a prolific author. That job
needs a weight small enough that a wrong-but-explainable year never blocks a match,
which is what 0.15 buys: it costs 0.070 of an otherwise perfect score. §6 records
that this is a window comparison rather than an equality, precisely because the
field's data is this imprecise.

**Publisher is not scored at all, and is not on `FileBook`.** The ticket puts
publisher "near zero" because it is inconsistent between sources and adds noise. The
weight that would express "near zero" honestly is zero: at 0.05 it can only ever move
a near-tie, and a field whose whole contribution is deciding near-ties decides them
with the noisiest evidence in the set. A tie-broken-by-noise is worse than a tie left
standing, because the tie is the signal that the rules could not decide — which is
exactly what the medium band and the LLM are for. So publisher is dropped, and with
it the `FileBook.publisher` field and its plumbing. Note what this costs: two
candidates identical on title, author, series and year are now genuinely
indistinguishable to the scorer, and the banding will grade them medium rather than
pick one.

**ISBN contributes nothing, and is not a penalty.** CBO-58 settles that a conflicting
ISBN contributes no penalty because stale and print-edition ISBNs are common. This
note takes that at its word and gives it a weight of exactly zero rather than a small
one: a zero weight means the field is not in the denominator at all, while a small
weight would score a contradictory ISBN down slightly, which is the penalty the
ticket forbids. The consequence the ticket does not state is that **an agreeing ISBN
is no longer evidence either** — two candidates identical on every scored field but
carrying different ISBNs are indistinguishable to the scorer. Today a matching ISBN
is a short-circuit and therefore decisive (`correction.py:513`); after this it is
context, passed to the LLM in the medium band and read by nothing else. This makes
CBO-60's "demote from short-circuit to scored field" a slightly different change
than its title suggests: the field is demoted to *context*, not to a small penalty.

### 2.1 The weights against the real cases

Computed by `scratch/cbo-58-calibration.py`, not estimated. One file fixture for
every row labelled "Cragside (messy)" —
`Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)` — and the two bare
files where the row says so. `sim` is the calibrated similarity (`1 − penalty`).

**Every row is a singleton pool, and the band column is the singleton reading.**
Session 1c printed this table with rows 4 and 5 marked strong, which was wrong: the
rows are one candidate each, so §4.1's raised singleton bar of 0.95 applies and not
`strong_score`. Both score 0.9070 and both are **medium**. The numbers below are taken
from `scratch/cbo-58-output.txt`, which was right; §6 item 4 records what that
correction means.

| # | File | Candidate | title raw | title sim | auth sim | denom | **score** | band |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | messy, #6 | Cragside, L.J. Ross #6 | 1.0000 | 1.0000 | 1.0000 | 2.15 | **1.0000** | strong |
| 2 | messy | Cragside, L.J. Ross #6 | 1.0000 | 1.0000 | 1.0000 | 2.00 | **1.0000** | strong |
| 3 | messy, #6 | Cragside, L.J. Ross #11 (year differs) | 1.0000 | 1.0000 | 1.0000 | 2.15 | **0.8372** | medium |
| 4 | messy, #6 | Cragside, L.J. Ross #11 | 1.0000 | 1.0000 | 1.0000 | 2.15 | **0.9070** | medium |
| 5 | messy, #6 | *Cragside: A DCI Ryan Mystery*, L.J. Ross #11 | 1.0000 | 1.0000 | 1.0000 | 2.15 | **0.9070** | medium |
| 6 | messy | Cragside, **L. J. Ross** (spacing only) | 1.0000 | 1.0000 | 1.0000 | 1.80 | **1.0000** | strong |
| 7 | messy | *Cragside: A DCI Ryan Mystery*, M.J. Porter | 1.0000 | 1.0000 | 0.0200 | 1.00 | **0.7000** | low |
| 8 | messy | The Infirmary, L.J. Ross #11 | 0.1905 | 0.0000 | 1.0000 | 1.80 | **0.4444** | low |
| 9 | messy | The Infirmary, Carly Reagon | 0.1905 | 0.0000 | 0.0568 | 1.00 | **0.0000** | none |
| 10 | messy, no author | Cragside, L.J. Ross #6 | 1.0000 | 1.0000 | n/a | 1.35 | **0.7000** | low |
| 11 | messy | *Cragside: A 1930s murder mystery*, M.J. Porter | 0.7241 | 0.4134 | 0.0200 | 1.00 | **0.4134** | low |

The rows to read carefully:

- **Rows 7, 9 and 11 have a denominator of 1.00.** The author does not agree, so
  §1.3 takes its weight out of the denominator entirely and the score is computed on
  the title alone, then capped at 0.7. That is why row 7 scores 0.7000 with an
  *exact* title: the title is all that is left, and the cap is what refuses it.
- **Row 10 is the case §1.3 exists for.** Three fields compare, the score without
  the gate would be 1.0000, and the gate holds it at 0.7000 — low band. Session 1's
  "at least 2 fields compared" rule would have graded this strong and written a book
  whose author is unknown.
- **Rows 4 and 5 are the two rows that changed band in this session.** Both score
  0.9070 — the arithmetic is right and the band was wrong. An exact title, an exact
  author and one contradicting field is not enough for a pool of one, because a pool
  of one has no runner-up to corroborate it. Both go to medium, and in a default
  install with no LLM configured that means both are marked unverified rather than
  written. §6 item 4 is the decision and its cost.
- **Row 4 is CBO-36's own case, and CBO-36 wrote it.** Note the arithmetic: the title
  similarity is 1.0000, so the whole 0.093 of deduction is the series disagreement
  (0.20 / 2.15). CBO-36 decided this case at 0.90 and treated that as a pass. Under
  this design 0.9070 is a pass for a *multi-candidate* pool and a fail for a
  singleton, so CBO-36's verdict no longer means "written" — it means "offered to the
  tiebreaker".
- **Row 3 is the second row the new design refuses and the shipped code writes** — see
  item 4.
- **Row 5 is the case the one-form rule was shaped for.** Both sides carry the
  subtitle, they are identical, and the title scores 1.0000. The earlier draft
  assumed 0.95.
- **Rows 7 and 11 differ by what the title can see.** Row 11's Porter record has a
  *different* subtitle, so the title scores 0.4134 and contributes real evidence
  against it. Row 7's Porter record has the *same* subtitle as the file, so the title
  scores 1.0000 and is silent — only the author gate refuses it (§6 item 11).

### 2.2 Regression against the shipped rule

Shipped = `matching.py` as it stands (title 1.0 exact / 0.9 contained / 0.0;
author 1.0 or 0.0; weights 0.6/0.4; series ±; ceiling 0.7) at its `confidence`
default of 0.85. New = the settled design, graded as a singleton pool at 0.95.

| # | shipped | shipped verdict | new | new band | author agrees | flag |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 1.0000 | writes | 1.0000 | strong | yes | |
| 2 | 1.0000 | writes | 1.0000 | strong | yes | |
| 3 | 0.9000 | writes | 0.8372 | medium | yes | **new refuses** |
| 4 | 0.9000 | writes | 0.9070 | medium | yes | **new refuses** |
| 5 | 0.8400 | refuses | 0.9070 | medium | yes | |
| 6 | 1.0000 | writes | 1.0000 | strong | yes | |
| 7 | 0.5400 | refuses | 0.7000 | low | **no** | |
| 8 | 0.4000 | refuses | 0.4444 | low | yes | |
| 9 | 0.0000 | refuses | 0.0000 | none | **no** | |
| 10 | 0.6500 | refuses | 0.7000 | low | **no** | |
| 11 | 0.5400 | refuses | 0.4134 | low | **no** | |

**No book the shipped code refuses is written by the new design.** Rows 1, 2 and 6
are written by both. Rows 7–11 are refused by both. Row 5's score rises across the
rules — 0.8400 to 0.9070 — and it still does not write, because 0.9070 is under the
singleton bar; it moves from "refused outright" to "offered to the tiebreaker", which
is a change in what happens next rather than in what is written. Row 9 stays at
0.0000 because neither its title nor its author agrees.

**Two rows are behaviour losses, and both are named as such.** Rows 3 and 4 were
written by the shipped rule at 0.9000 each and are now in the medium band:

- **Row 3** (series *and* year contradict) scores 0.8372. It loses because two fields
  disagree, which is the design working as intended.
- **Row 4** (series contradicts, nothing else) scores 0.9070. **This is the row the
  series weight was chosen to preserve**, and the design as it stands refuses what it
  was tuned to accept. It is not an accident of the weights: 0.9070 is a correct
  score, and the refusal comes from §4.1's singleton bar, which is doing exactly what
  §6 item 4 decided it should. The alternative — lowering the bar to admit 0.9070 —
  would also admit a wrong author at 0.8584 (item 4), which is why the bar does not
  move.

Both rows land in the medium band, so in an install with an LLM configured they go to
the tiebreaker and are resolved there. In a default install, with no LLM, they are
marked `colophon:unverified`: visible in the library, and recoverable by dropping the
book in again. That trade is the whole of item 4's reasoning, and the two rows are
where it is paid.

---

## 3. String normalisation

### 3.1 One pipeline, standard library only

Titles, author names and series names all go through the same text normalisation
before any comparison. Field-specific handling sits on top of it (§3.3 on titles,
§3.4 on names); the base pipeline is shared. Every step is `stdlib`:

| Step | What it does | Why |
| --- | --- | --- |
| 1. Decompose | `unicodedata.normalize("NFKD", text)` | Splits `é` into `e` + a combining acute, and normalises the compatibility characters that differ between sources (`ﬁ` → `fi`, full-width digits → ASCII). A source that stores `Brontë` should agree with a file that stores `Bronte`. |
| 2. Strip marks | `"".join(c for c in text if not unicodedata.combining(c))` | The second half of step 1: NFKD left the accents as separate characters, and this drops them. Doing this instead of transliterating means no table is needed and no assumption is made about which language's accents matter. |
| 3. Case fold | `text.casefold()` | Not `.lower()`. `casefold()` is the Unicode-correct operation for caseless comparison and handles cases `lower()` does not — the German `ß` folds to `ss`. |
| 4. Ampersand | Replace `&` with the word `and` | `The Wind & the Willows` and `The Wind and the Willows` are one title. Replacing the *symbol* rather than the *word* is what lets a bare `&` between two spaces normalise to a word without a special case, and a single-character non-alphanumeric token would otherwise be deleted by step 5. |
| 5. Punctuation | Every character that is not alphanumeric becomes a space; collapse runs of whitespace | `The Waste Land` = `The Waste Land.` = `The Waste-Land`. Runs collapse to a single space so that removal does not change token boundaries in ways the similarity measure would notice. This is the step that makes `don't` compare as `don t`. |
| 6. Articles | Drop a leading `the`, `a`, `an` from titles only | A file's title often keeps the article the record dropped. Titles only — an author named `A. Smith` is not an article. Guarded: the token is dropped **only when at least two tokens remain**, so `The Infirmary` keeps its article (dropping it leaves one token) and a book titled *A* keeps its title. |
| 7. Strip | `text.strip()` | The result is a comparison key, and a leading space from step 5 would make two equal titles unequal by string comparison. |

Steps 3–7 are pure string work on one side. Nothing here reaches the network, which
is what makes the whole matcher unit-testable without a source — the property
`matching.py` already has and which this ticket must not lose.

**No `unidecode`.** The NFKD-plus-combining-strip route covers the case that matters,
which is accented Latin text, with no dependency and no 100 kB of transliteration
tables. What it does *not* do is transliterate writing systems whose characters do
not decompose — a Cyrillic or CJK title stays as it is. That is correct behaviour
here rather than a gap: those titles are compared against records in the same script,
where exact Unicode equality does the job. Worth a note in the module's docstring so
the next reader does not add `unidecode` to "fix" it.

### 3.2 Similarity: `difflib`, calibrated

Comparisons use `difflib.SequenceMatcher(None, a, b).ratio()` from the standard
library, applied to the **normalised comparison key as a whitespace-joined string**.
This is stated rather than left open because the two readings differ materially:

- **Character ratio on the joined key** (chosen). `SequenceMatcher` sees the key's
  characters, so a single-letter difference in a surname costs a little and a wholly
  different name costs a lot.
- **Element-wise over the token list** (rejected). `SequenceMatcher` sees each token
  as one indivisible element, so *no* token in common is a ratio of exactly 0.0000.
  Session 1b measured this: every wrong author in the fixture set scored 0.0000,
  because `['mj','porter']` and `['lj','ross']` share no *token* — and, worse, a
  surname typo scores 0.0000 too, which is precisely the case §3.4 says the graded
  similarity exists to handle.

Tokens remain the unit the normalisation works on (the article rule and the initials
join both need them). They are not the unit difflib compares.

The character ratio is noisier on long titles, and that is what the calibration
curve exists to absorb. Three things have to be true of the mapping from `ratio()` to
a penalty, and none of them is true of the raw ratio:

1. **Identical input must be exactly 1.0.** Handled by the dead band below rather than
   by trusting the ratio to return 1.0.
2. **`ratio()` is over-generous on short strings.** Two four-character titles sharing
   three characters score 0.75, so the raw ratio would give almost every candidate a
   plausible-looking score and the bands would lose their meaning.
3. **`ratio()` rewards shared characters, not shared words.** This is the cost of the
   character reading, and the floor plus the steep calibration are the mitigation.

So the penalty curve is: a **dead band** at the top (ratio ≥ 0.97 → penalty 0), a
**floor** at the bottom (ratio < 0.35 → penalty 1, so a wholly different title is a
clean 1 rather than 0.65), and a monotone stretch in between that steepens the
middle. The starting stretch, expressed as penalty for a given raw ratio:

| Raw ratio | 1.00 | 0.90 | 0.80 | 0.70 | 0.60 | 0.50 | 0.35 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Penalty | 0.00 | 0.22 | 0.45 | 0.63 | 0.78 | 0.88 | 1.00 |

"Interpolated between" means straight lines between adjacent anchors — the plain
reading of the table, and the one the script implements. Read as scores: two
candidates that share 80% of their characters score 0.55 on that field, and one that
shares 60% scores 0.22. That is harsh, deliberately. These numbers are the single
most important thing to tune against a real library (§4.4), because they set how
quickly a partly wrong title stops looking like a candidate at all.

### 3.3 Titles: **one form per side**, chosen by whether both sides subtitle

This is the decision session 1c settled, and it replaces both "max over every form"
and "score the cleaned search title".

**The bug in max-over-forms.** The shipped `clean_title` produces `search` (the
subtitle stripped when it is generic) and `also` (the same title with the subtitle
left on), and CBO-36 used `search` for scoring and `also` for querying. An earlier
draft of this note scored *both* forms and took the better. That makes any two titles
that strip to the same head match at 1.0000 — which is how `Cragside: A 1930s murder
mystery` scored an exact title against a `Cragside: A DCI Ryan Mystery` file. It is
not a match; the subtitles say they are different books.

**The rule.** Two stages, and the stage is chosen by whether *both* sides carry a
subtitle:

| Both sides subtitle | One side bare |
| --- | --- |
| Compare the **full titles**. The subtitle is where the discriminating words are. | Compare the **heads** only. One identifier and one longer identifier are not two conflicting identifiers. |

Measured against the messy Cragside file:

| Candidate | Rule | Raw | Similarity |
| --- | --- | --- | --- |
| `Cragside` | head-containment | 1.0000 | **1.0000** |
| `Cragside: A DCI Ryan Mystery` | full-vs-full | 1.0000 | **1.0000** |
| `Cragside: A 1930s murder mystery` | full-vs-full | 0.7241 | **0.4134** |
| `The Infirmary` | head-containment | 0.1905 | **0.0000** |

**What it costs.** A record that keeps a subtitle the file dropped costs **nothing** —
that is the head-containment stage, and it is the "spelt longer" case this note was
built around. What is given up is subtitle-vs-subtitle discrimination when the
record's subtitle happens to be *identical* to the file's: row 7's Porter record
carries `Cragside: A DCI Ryan Mystery`, so its title scores 1.0000 and the title
field is **silent** about it. Only the author gate refuses that book. That is worth
stating plainly rather than implying the title is a second opinion on every
candidate; on this one it is not.

**The series bracket is extracted from the title and removed, and the subtitle is
not.** `matching.py`'s `_SERIES_BRACKET` is the right shape and stays:
`(The DCI Ryan Mysteries Book 6)` yields the series name and the number `6`. The
number is kept as a separate signal (§2), and a bracket naming a series without a
position is removed and contributes nothing. The split has to happen on the **raw**
title, before normalisation destroys the colon — session 1b's script got this wrong
and silently read the full title as a head.

**Subtitle handling at the source boundary.** A source may hand back the subtitle as
a separate field (Google: `title` "Mistborn", `subtitle` "The Final Empire" —
`cbo-37:156-157") or folded into one string (Hardcover). The two must not reach the
matcher as different shapes, or every Google candidate is scored against a bare head
while every Hardcover one is scored in full. §5.3 says where the join happens; from
the matcher's side, `Candidate.title` always means "the title as the source writes
it, subtitle included if the source has one".

**`_SUBTITLE` and `_GENERIC_SUBTITLE` remain, and remain the query's business.** They
decide which *forms get asked about* (`search_forms`), not which form is scored.
Noting the real helper so session 2 does not re-derive it wrongly:
`_GENERIC_SUBTITLE` matches `mystery|mysteries|novel|thriller|story|stories|romance|crime|saga|detective`
— **`murder` is not in the list** — and `_generic()` also returns true for any
subtitle starting `a ` or `an `. `A 1930s murder mystery` strips on `mystery` and on
the `a ` rule, not on `murder`.

### 3.4 Names: order and the multi-creator rule

Author names get the sharpest treatment in the pipeline, because `cbo-36`'s strongest
existing result is that `L. J. Ross`, `L.J. Ross`, `LJ Ross` and `Ross, L. J.` are one
author. A graded similarity is *worse* at that than the existing join-everything
comparison, so the order is:

1. **Reverse a `Surname, Given` form at the first comma** — the existing `_name()`
   behaviour (line 417), kept, because a file and a source disagreeing about which way
   round a name goes is a formatting difference and must not be scored as a difference
   in substance.
2. **Normalise through the base pipeline**, with the joining step: a run of one-letter
   tokens is joined into a single token, so `J. R. R.` becomes `jrr` and agrees with
   `JRR`. This is the existing `_join_initials` rule and it is preserved exactly,
   including its distinction between a run of initials and a one-letter *word* —
   `Ursula K. Le Guin` must not become `ursulakleguin`. That logic is subtle, tested,
   and has no reason to change.
3. **Then** compare with the calibrated character ratio (§3.2).

Step 2 before step 3 is the rule that keeps the change safe: everything the current
normalisation already collapses must be collapsed *before* the similarity is asked,
so the similarity only judges differences the normalisation could not remove. Session
1c measured what that buys and what it does not:

| Case | Pair | Shipped `_name` | Raw | Similarity | Agrees |
| --- | --- | --- | --- | --- | --- |
| surname typo | `L. J. Ross` / `L. J. Ros` | False | 0.9231 | 0.8308 | yes |
| one-letter typo | `L. J. Ross` / `L. J. Riss` | False | 0.8571 | 0.6814 | yes |
| transposed, **no comma** | `LJ Ross` / `Ross LJ` | False | 0.5714 | **0.1914** | **no** |
| transposed, with comma | `Ross, L. J.` / `L. J. Ross` | True | 1.0000 | 1.0000 | yes |
| spacing only | `L.J. Ross` / `L. J. Ross` | True | 1.0000 | 1.0000 | yes |

So the graded similarity's real gain is **typos**, which the shipped rule refuses
outright. It does **not** gain the bare transposition: `LJ Ross` vs `Ross LJ` scores
0.1914, below the floor, and the comma form the note used to cite as evidence was
never broken — `_name` already reversed it. Session 2 should not repeat the claim
that graded similarity handles transposition.

**Multiple authors: calibrate per creator, then average.** For each creator the file
names, take the calibrated similarity of its best match against any author the record
names, then average those calibrated values. Calibrating *after* averaging the raw
ratios is wrong, and an earlier draft of the script did it: the curve is a judgement,
and averaging judgements is what "the author agrees" means when a file names several
creators. Averaging raw ratios first lets one very wrong creator be diluted by one
very right one before the judgement is applied.

### 3.5 Language: the guarantee stays in the source query

`primary_language()` strips the region subtag and nothing else:

```
en -> 'en'    eng -> 'eng'    en-GB -> 'en'    EN -> 'en'    de -> 'de'    ger -> 'ger'
```

Its docstring is right that the 639-1/639-2 equivalence is carried by the *query*: a
two-letter tag is asked on `code2`, a three-letter one on `code3`, and every row in
Hardcover's `languages` table carries both. An earlier draft of this note moved the
guarantee into the matcher and reused `primary_language` to enforce it, which cannot
work — a file tagged `eng` against a record carrying `en` is the same language and
would have been dropped.

**Decision: the guarantee stays in the source query, and the matcher only removes what
it can prove.** The matcher drops a candidate when the file states a language, the
candidate states one, both are given in the **same form** (two-letter or three-letter)
and the codes differ. A two-letter code against a three-letter one is **kept** and
unflagged, because the matcher cannot decide it and a wrong drop costs a book.

This matters more than it did, because Google's `langRestrict` is accepted and ignored
(`cbo-37:118-127`) — asking for `fr` and `eng` returned the same English volumes, and
an unfiltered search put a Korean and a Portuguese volume in the top six. So the
Hardcover query's filter is a real guarantee and Google's is not, and under the pooled
flow a single candidate list mixes the two. The narrow rule above is what the matcher
can honestly contribute; **the rest is a source-side problem.**

**The code change this implies belongs to a separate ticket, not CBO-58.** Carrying
639-1/639-2 equivalence in the matcher needs a mapping table — a data file or a
dependency that this ticket should not introduce. CBO-58 records the decision; the
ticket that wants the mapping files it.

### 3.6 Determinism and cost

Two constraints from elsewhere in the repo, both of which this design satisfies:

- **Every correction must be reproducible**, because file-level duplicate detection is
  a byte comparison of the corrected book (`cbo-38:178-195`). That makes determinism a
  hard requirement of the matcher, not a nicety. Everything in §3 is a pure function
  of the input strings; there is no locale dependence (`casefold` is not
  locale-sensitive, unlike `str.lower()` under some settings), no clock, no
  randomness, and no dictionary iteration order. Ties are broken by input order, which
  is stable.
- **Cost is bounded.** `SequenceMatcher` is quadratic in input length, so every
  comparison caps its inputs — a title at 200 characters, a name at 100. Combined with
  a per-source reply cap, scoring a pool is tens of comparisons of short strings,
  which is nothing against a network round trip. Worth stating because a "just compare
  the descriptions too" change would break this instantly: descriptions are thousands
  of characters.

### 3.7 `normalise()` is split, not changed

`matching.py:normalise` is currently **two things at once**: the comparison helper, and
the durable key that `record.py` uses to decide that two spellings are one author or
one series (`config.example.toml:221-236`, and the docstring at `matching.py:319-320`
says so). `record.py`'s key is *written into a library and kept* — CBO-41's whole
point is that the first spelling to match an author fixes that author's spelling for
every later book.

Changing the normalisation therefore does not just change matching; it silently
re-keys every existing record, and an author whose stored key no longer matches will
have a second, different spelling written alongside the first. That is precisely the
failure CBO-41 exists to prevent, arriving as a side effect of a matcher ticket.

So: **`normalise()` is frozen as the record's key, with a comment saying so**, and the
new pipeline in §3.1 is added under a separate name for comparison only. The two will
differ — the new one strips accents and articles, the frozen one does not — and that
is correct: a durable key should be conservative and stable, a comparison key should
be aggressive. `record.py` needs no change, and no migration is needed. A golden test
pins the frozen output (§5.1).

---

## 4. Band boundaries

### 4.1 The bands

| Band | Condition | What happens |
| --- | --- | --- |
| **strong** | one candidate: `score ≥ 0.95`; two or more: `score ≥ 0.89` **and** `gap ≥ 0.08`; either way the author must agree (§1.3) | Applied automatically. Ends the walk. |
| **medium** | the author agrees, and `score ≥ 0.80` | LLM if the pool is non-empty and a tiebreaker is configured; otherwise unverified. |
| **low** | the author agrees and `score > 0.0`, or the author does not agree at all | Unverified. |
| **none** | nothing scored, or no candidates at all | Unverified. |

Starting numbers: `strong_score = 0.89` (**provisional**, §4.1), `singleton_score = 0.95`,
`medium_score = 0.80` (**provisional**, §4.4), `gap = 0.08`.

**`strong_score = 0.89`, and it is provisional like `medium_score`.** The value comes
from its position in a window, not from the shipped pipeline — session 1c's "it matches
the shipped threshold" reasoning is withdrawn, both because the scale changed and
because it was wrong about the number. The window is set by the two scores either side
of it:

| Score | What it is | At `strong_score = 0.89` |
| --- | --- | --- |
| 1.0000 | nothing the file states contradicts | strong |
| 0.9302 | the year contradicts, nothing else | strong |
| 0.9070 | the series position contradicts, nothing else | strong |
| 0.8584 | a wrong author who clears the 0.5 gate (§6 item 3) | **not strong** |
| 0.8372 | the series position *and* the year contradict | **not strong** |

**The window is (0.8584, 0.9070]**, and 0.89 sits inside it with margin on both sides.
The lower bound is the important one: **0.8584 is a wrong author clearing the gate, and
it must not grade strong.** The upper bound is the other half of the policy — a single
contradicting signal (0.9070) must still grade strong. Anything in the window does both;
0.85 does not, because 0.85 < 0.8584, and an earlier draft of this section set 0.85 and
then claimed it "sits in the safe half of that window". It did not sit in the window at
all, and the table directly above the claim showed the wrong author grading strong at
it. **0.89 is the value inside the window**, and it remains **provisional** — §4.4's
tuning pass is what moves it, exactly like `medium_score`.

**`singleton_score = 0.95`, and what it actually does.** A pool of one has no runner-up,
so the gap cannot corroborate the leader and the only check available is the file's own
fields. The bar's real job is a **minimum title similarity** for a singleton whose other
fields all agree:

| Denominator | Fields | Title similarity needed for 0.95 |
| --- | --- | --- |
| 2.15 | title, author, series, year | **≈ 0.89** |
| 1.80 | title, author | **≈ 0.91** |

| Score | What it is | At `singleton_score` |
| --- | --- | --- |
| 1.0000 | nothing contradicts | **strong** |
| 0.9302 | the year contradicts | medium |
| 0.9070 | the series position contradicts | medium (rows 4 and 5) |
| 0.8584 | a wrong author clearing the 0.5 gate (§6 item 3) | medium |
| 0.8372 | series *and* year contradict | medium |

**An earlier draft justified 0.95 by saying it fell in an "empty gap" between 1.0000 and
0.9302. There is no empty gap, and that justification is withdrawn.** The gap looks
empty only because the table above flips series and year as binaries while holding title
and author exact. Once the title is graded — which is the point of this ticket — the
range fills continuously:

| Title similarity (denom 2.15) | Score |
| --- | --- |
| 0.80 | 0.9070 |
| 0.85 | 0.9302 |
| 0.90 | 0.9535 |
| 0.95 | 0.9767 |
| 1.00 | 1.0000 |

So 0.95 is not sitting in a gap; it is setting a floor on one field, and that is a
better justification than the one it replaces because it says what a user gets: a
singleton is written only when the title is a near-exact match and nothing else
contradicts.

**What moving it would change.** Two candidate moves, and both are refused for a reason
that survives the corrected derivation:

- **0.93** would admit a singleton whose *year* contradicts while still refusing a
  series contradiction (0.9070). That is incoherent: year is the field §2 calls the
  weakest and least reliable of the three, so this would make it the one field a single
  witness is allowed to get wrong. (An earlier draft argued this from 0.9302 clearing
  0.93 by two ten-thousandths. That is not a margin and the argument does not rest on
  it: under a graded title the 0.93 line is crossed by title similarity, not only by
  the year case, so the objection is about *which field is forgiven*, not about the
  distance between two numbers.)
- **0.91** would admit the series contradiction too, which is row 4 — the case §6 item
  4 decided must go to the tiebreaker.
- **0.97** would refuse more than 0.95 does, not the same thing: with a graded title,
  a candidate at 0.9767 clears 0.95 and fails 0.97. So the earlier claim that 0.97
  "refuses exactly what 0.95 refuses" was an artefact of the binary table and is
  withdrawn.

**`medium_score = 0.80` is provisional and session 2 must not treat it as tuned.**
It is chosen to put rows 3 and 4 (0.8372 and 0.9070) in medium while leaving rows 7–11
(≤ 0.7000) below it, and to give the band table a boundary between medium and low —
the earlier draft left those two with no boundary at all, so the table could not be
implemented as written. The right value depends on how large a candidate pool a real
library produces, which is an empirical question §4.4's probe answers and this note
cannot. Ship it as a config key with this default and then measure.

**`gap = 0.08`.** The gap is `leader.score − runner_up.score` over the deduped pool.
0.08 is chosen to be *visible but modest*: about half the year weight, or a tenth of
the title weight, so it is crossed only by a real difference in evidence rather than
by noise in the similarity curve. It is deliberately below `strong_score`'s own margin
because the gap and the score threshold measure different things and neither should be
a proxy for the other. On a warm pool the gap is easy to clear — the same-book
runner-up in §2.1 sits 0.44 below the leader. The gap earns its keep on the cold pool:
two records that are genuinely alike, which is the case it exists for.

**"Unverified" is the outcome, and there is no skip queue.** The ticket says a miss
"belongs in the skip queue", which is a useful way to say *do not write metadata* but
is not a mechanism this repo has. `cbo-39` settles what actually happens: the book
keeps the metadata it came with, gains the `colophon:unverified` `dc:subject` tag and
"Metadata could not be verified by Colophon." at the end of its description, and is
then **backed up and delivered to `output_dir` like any other book** — it is not moved
aside, held back or deleted (`cbo-39:158`, `cbo-39:195`). A dry run writes nothing and
logs `would mark colophon:unverified` instead (`cbo-39:193-195`).

That matters here in two ways, and both are arguments for the conservative reading of
every threshold:

- **A miss is visible, and a wrong write is not.** The tag and the note are how a
  person finds an uncertain book *"without reading logs"* (`cbo-39:185`), and the mark
  is recomputed on every pass (`cbo-39:202-206`). Wrong metadata has no such recovery
  path. The asymmetry the whole design leans on is therefore real in this codebase,
  not rhetorical.
- **Three bands reach it, so "unverified" is not one condition.** `cbo-39:103-111`
  already distinguishes the two shapes that reach it today, and `Outcome.passed_over`
  already logs the second with a reason. The bands refine an existing mechanism rather
  than adding one. Low and none should be distinguishable in the log from medium,
  because a book in the medium band was an LLM's call that could not be made or was
  declined, while a book in low or none was never a candidate at all.

### 4.2 A pool that was only half asked

`cbo-39:147-151` draws a line this design has to keep: "'nobody could ask' is not 'we
asked and could not be sure'". Only the second earns `colophon:unverified`; a source
that could not be reached keeps its own state, and `colophon:source-unavailable` and
the retry window are CBO-43's. Today the walk returns the moment a source fails
(`correction.py:565-566`), so no book is ever graded against a pool a reachable source
was missing from. **Pooling removes that guarantee**, and that is a new failure mode
rather than a preserved behaviour.

**The rule, narrowed in session 1c.** An earlier draft exempted the strong band,
reasoning that early exit meant the later source was never going to be asked. That
reasoning does not cover the case the ticket actually has: **a walk that completes and
grades strong with a source that errored.** Under the draft's rule that book is
written, and a source the user configured was never consulted.

So the exemption is narrowed to what it can defend:

- **A walk that exited early is not half-asked.** Exiting is a decision the design
  made, the later source was never going to be asked for that book, and the strong
  band is not exempted so much as inapplicable.
- **A walk that completed with a source erroring is half-asked, whatever it graded.**
  If the band is strong, the book does **not** take the unverified outcome and does
  **not** get written from a pool that is missing a configured source: it takes
  CBO-43's "could not ask" state.

The two cases are distinguishable because early exit is a decision the walk made and an
error is not. The outcome therefore has to carry which sources were reached, which
errored, and whether the walk exited early — that belongs on the walk's result in
`correction.py`, not inside `Ranked`, because the matcher grades a pool and cannot
know how the pool was gathered.

**The rule above is written about the pooled title walk.** Whether it reaches the
non-pooled ISBN path is open, and CBO-67 settles it — see §6 item 18.

### 4.3 The LLM's gate, and the two thresholds that must not be confused

The LLM's own self-reported confidence is compared against the strong threshold, not
against the gap. Those are different questions: the gap asks "could the rules
distinguish the leader?", the LLM gate asks "is the model sure?". A model that
confidently picks one of two near-identical candidates has answered the question the
gap could not, so requiring a gap on that path would be requiring the rules to have
succeeded where they had already failed.

**Which books the LLM sees, under the flag.** The walk asks the LLM whenever the band
is *not* strong and the pool is non-empty. That includes low and none, not just
medium — and that is the population `llm_full_scan` exists for: a book whose *right*
record scored badly because the query was bad, which is a low or none-band book, not a
medium-band one. Defining the flag as "ask whenever the pool is non-empty, whatever
the band" would instead pay for calls on books the rules already graded strong, against
a 200/day limit. With the flag off, the walk still asks for medium-band books; the flag
widens the *population*, not the decision.

**The flag ships `true`, and the default is part of the design rather than a convenience.**
The walk this replaces asked the model for *any* non-empty pool the rules did not write
from, which is every non-strong band — so `true` is the reach Colophon already had, and
shipping `false` would have silently narrowed the model's population to the medium band
while reading as the conservative default. **`off` is the deliberate narrowing, and a
user asks for it**; it is not what a fresh install gets. The flag still only widens the
population: it never changes the decision, it does not disable early exit, and a book the
rules already graded strong never spends a call either way.

**And the two numbers must be named as different quantities in the log.** The
rule-based number and the model's self-reported number are on different scales —
`llm.py:173-175` already warns about this — and adding bands makes it worse. See §4.5's
naming decision.

### 4.4 Tuning against a real library

**What is and is not derived, before the procedure.** `singleton_score = 0.95` is
derived from the fixture rows (§4.1). `medium_score`, `strong_score`, `series = 0.20`
and `year = 0.15` are **all provisional defaults** — the fixture set does not select
them, and §2 and §4.1 say so at each. The step below is what turns them into tuned
values, and until it has run they should not be treated as findings.

1. **Build a labelled tuning set.** 20–50 books is enough to move the numbers, a few
   hundred makes them trustworthy. Each entry is a real file plus the identifiers of
   the record that *is* the same book from each configured source — recorded by hand
   against the actual source replies, not by trusting the matcher's current answer.
   Include the hard cases deliberately: books that are the same work in two editions,
   a file title carrying a series bracket, two same-named records by different
   authors, a file with no author, and at least one case where the right record is
   absent from the sources entirely.
1a. **Record the pool size per book while doing it**, because that is the number
   `medium_score` depends on. The distribution to expect from `cbo-36`'s recordings
   is one or two — but against Hardcover's exact-title filter. The pooled design adds
   Google's much noisier title search, and Google's `intitle:` returns 300 items for
   a bare title (`cbo-37:190-193`). Nobody has measured the pool size the two sources
   produce *together*, and that measurement is what sets the medium boundary. This is
   the probe session 2 should run before the first tuning pass.
2. **Measure two error rates separately, and weight them by what they cost.** A false
   accept is a candidate graded strong that is not the right book: wrong metadata
   written silently and permanently. A false reject is a right book graded below
   strong: a book delivered with the `colophon:unverified` tag, visible in the library
   and recoverable by dropping it in again. **The false-accept count is the
   constraint, not a metric to trade off: it must be zero on the tuning set.** If it
   cannot be made zero by moving thresholds, the similarity calibration in §3.2 is
   wrong, and that is what needs fixing — tightening a threshold cannot separate a
   wrong record from a right one when the calibration has made them the same number.
3. **Then put the thresholds at the loose end of the safe range**, as far as possible
   from the nearest labelled case on each side, so ordinary variation in a real
   library does not cross them. Tuning to the exact boundary is how a threshold that
   measures well on 40 books fails on the 41st.
4. **Plot the gap on its own.** Sort the tuning set by `leader − runner_up` and look at
   whether the correct books cluster above the incorrect ones. If they do not separate
   at all, the gap is not carrying information for this data and `gap = 0` is the
   honest setting — a legitimate outcome, and better than keeping a number that is
   contributing noise. Then measure the same set with the gap rule disabled and
   compare: if nothing changes, the rule is scaffolding.
5. **Instrument the bands in the log, permanently.** Count books per band and name the
   ones nearest each boundary, with the near-misses already logged by
   `correction.py`'s `passed_over`. This makes a later retune a decision about one
   number instead of another research ticket.
6. **Re-measure on a different set before believing any of it.** A threshold tuned and
   validated on the same 40 books is fitted to those 40 books.

**What "conservative" means operationally:** when a choice is between admitting a
candidate that might be wrong and rejecting one that might be right, reject.
Concretely — thresholds at the tight end of the safe range (step 3), a raised bar for a
singleton pool (§4.1), the author gate (§1.3), and a `medium` band that is a *queue*
rather than a decision (§4.3). An unverified book announces itself in the library;
wrong metadata does not.

### 4.5 Exposed or internal

**The key is renamed, not reused.** The existing key is `confidence`, and the settled
design has two different things called confidence in it — the rule-based score and the
LLM's self-reported figure — which `llm.py:173-175` already has to warn about in prose.
Keeping the user-facing key as `confidence` would preserve exactly the collision the
rename exists to remove. **Colophon has not shipped v1.0.0**, so renaming the key now
costs a config-comment rewrite and will never cost so little again.

| Name | Surface | Key |
| --- | --- | --- |
| Strong threshold | `config.toml` | `strong_score`, default `0.89` (replaces `confidence`, whose old default was 0.85) |
| Singleton threshold | `config.toml` | `singleton_score`, default `0.95` |
| Medium threshold | `config.toml` | `medium_score`, default `0.80`, **provisional** (§4.4) |
| Full-scan flag | `config.toml` | `llm_full_scan`, default `true` — see §4.3 |
| Author agreement floor | internal constant | `0.5` — a property of the metric, not a preference |
| Runner-up gap | internal constant | `0.08` |
| Field weights | internal constants | — |
| Similarity calibration | internal constants | — |
| The LLM's own figure | not config | stays `confidence` in `llm.py` and the log |

Renaming `confidence` is a **breaking config change** and needs saying in the PR body
and in the config comment: an existing `confidence = 0.9` in someone's `config.toml`
will stop being read. Accept the break rather than aliasing it, because the old value
does not mean the same thing on the new scale and silently reinterpreting it is worse
than refusing it — and pre-1.0 is the only time this is free.

**`singleton_score` and `medium_score` reach the decision without the matcher reading
config.** §5.2 requires `band_of` to read only its arguments, so the two keys cannot be
fetched from where the decision is made: they travel as a frozen `Bands` value object
(`strong`, `singleton`, `medium`, and the internal `gap`) built by the caller and passed
in, `band_of(ranked, bands=BANDS)`. The module constants are then only what a caller
with no config means, and the thresholds that decide a real library's bands are the
user's. This is *more* pure than reading four module globals, not less: the function's
answer is a function of its arguments alone, and the hidden dependency is gone.

**`singleton_score` below `strong_score` is refused at startup.** Each threshold is a
setting on its own, so only the pair can catch the inversion — and an inverted pair makes
a pool of one, which nothing corroborates, *easier* to write from than a corroborated
one, which is §1.2 backwards. `load_config` raises a `ConfigError` naming both numbers
rather than letting the pair through, the way the defaults would hide it.

**Why the gap, the singleton bar, the author floor and the weights stay internal**:
they are not preferences, they are the metric's calibration. A user who lowers the
gap is saying "let the leader win ties"; one who raises the author weight is
re-weighting a similarity scale whose other numbers they cannot see; one who lowers
the author floor is saying "a different person may count as the same author"; and one
who lowers the singleton bar is making one witness count as two. All four make the
bands mean something different from what the documentation, the tests and the fixtures
describe. The thresholds are different in kind: they are policy — how cautious the
user wants their own library corrected.

**One thing to fix while the key is being documented.** `config.example.toml:122-131`
currently tells the user what a `confidence` of 1.0 does, and names a series-position
disagreement scoring 0.9 and a series position being absent scoring 1.0. Those
sentences describe the *old* arithmetic and will be wrong whichever way this ticket
goes, so the block needs rewriting in terms of bands rather than one score — and in
this ticket rather than after, because a config comment describing a scoring model the
code no longer implements is worse than no comment.

---

## 5. Module boundary

**Everything stays in `colophon/matching.py`.** CBO-58 is explicit that the adapted
work lives in one module — it makes the provenance boundary obvious, and it keeps the
blast radius of CBO-50's later repo-wide reformat to one file. The module already
holds more than the ticket assumes (title cleaning and the shared `Candidate` type as
well as scoring), so this section audits what is inside rather than proposing a move.

### 5.1 Public surface

| Name | Why it is public |
| --- | --- |
| `Candidate` | The shared record shape. `hardcover.py`, `googlebooks.py`, `llm.py` and `correction.py` all import it from here, which is what stops two sources' records drifting apart. |
| `FileBook` | What the matcher knows about the file. **Gains `date` only** — already read by `epub.read()` (`epub.py:190`) and currently dropped. Publisher is not added, because publisher is not scored (§2). |
| `Match` | One candidate measured: the candidate, its `score`, per-field penalties and similarities, whether the author agreed, and the reasons. **`confidence` is renamed to `score`** (§4.5). |
| `Ranked` (new) | The ordered pool: `matches`, with `leader`, `runner_up` and `gap` derived from it. What a caller needs to act and to log, so a caller never recomputes the ordering or the gap. |
| `CleanedTitle` | Unchanged. The cleaning result, carrying the series position. |

| Function | Status |
| --- | --- |
| `clean_title()`, `search_title()`, `search_titles()` | Unchanged. What gets asked about — a query concern that happens to live here. |
| `primary_language()` | Unchanged, and **not** the language guarantee (§3.5). |
| `score_candidate()` | Rewritten as the accumulator with the author gate. Same name, same "one candidate against the file" job. |
| `rank()` (new) | Replaces `nearest_candidate()`. Returns the whole ordered pool — the gap needs the second entry, and the LLM needs the ranked list. |
| `band_of()` (new) | The grading, as a pure function of the ranked pool **and the bands it is asked about**: `band_of(ranked, bands=BANDS)`. See §5.2. |
| `dedupe()` (new) | Merges candidates describing one record (§6, item 4). |
| `normalise()` | **Frozen** — the record's durable key (§3.7), pinned by a golden test below. |
| `comparison_text()` (new) | The §3.1 pipeline, for comparison only. |

Explicitly **private**: the similarity calibration, the penalty functions per field,
the article and parenthetical handling, `_name`, `_join_initials`, `_words`,
`_series_adjustment`. The tests reach them through `score_candidate` and `band_of`,
which is what keeps the tests honest about the public behaviour.

**`Ranked` does not carry the band, and it used to.** `band` was a property on `Ranked`,
and it was deleted rather than moved: it called `band_of(self)` with no thresholds, so it
answered from the module defaults for any caller whose config had moved — a wrong answer
with nothing in the call site to show it. The band is `band_of(ranked, bands)`, computed
by the caller from the thresholds it actually holds (§4.5), and `Ranked` carries only
`matches`. The deletion is deliberate, not an omission.

**`top_candidates()` moves here from `correction.py`** (line 1160). It is "the best few
candidates by score", it is pure, and it sits in the pipeline module only because it
was written there. Moving it removes `CANDIDATES_PER_SOURCE` from `correction.py`'s
constants and gives the LLM's candidate list one owner.

**A golden test pins `normalise()`'s output.** §3.7 freezes it as the record's durable
key, which is a promise that has to be enforced rather than documented: the failure
mode is somebody later "tidying" the normalisation, changing every stored key, and
producing a second spelling of every author in a library — silently, and only on books
processed after the change. The test states the current output for a fixed list of
inputs as literals — `L. J. Ross`, `Ross, L. J.`, `Ursula K. Le Guin`,
`J.R.R. Tolkien`, an accented name, a title with a series bracket — and fails on any
change. It is deliberately a characterisation test rather than a specification: its
job is to stop `normalise()` changing without someone deciding to change it.

### 5.2 The band decision lives in the matcher, and the matcher does not act on it

`band_of(ranked)` returns which band a pool falls in **and nothing else**. The matcher
never calls the LLM, never writes a file, never decides a book's fate. This is what
keeps the module testable without a source, a model or a filesystem — the property
`matching.py` has today, and the reason `cbo-57` has nothing to extract.

**Every function in the module is pure: pool in, result out.** That includes
`dedupe()` and `band_of()`, and it is a constraint rather than a description. The
impure part of this design is the *walk* in `correction.py` that fills the pool — it
does network I/O, it can fail partway, and it decides when to stop — and that is where
impurity belongs.

The three band actions belong to `correction.py`, because each is a different kind of
decision:

| Band | `correction.py` does | Existing seam |
| --- | --- | --- |
| strong | Writes, ends the walk | `_write()`, `correction.py:732` |
| medium | Asks the LLM if configured, else `_unverified()` | `_ask_llm()`, `correction.py:624` |
| low / none | `_unverified()` | `_unverified()`, `correction.py:682` |

The medium, low and none rows are conditional on §4.2: a walk that **completed** with a
configured source erroring sends the book to CBO-43's state instead, whatever the band.
Only an early exit is exempt, because only an early exit was a decision.

This maps onto work that **already exists** — `_ask_llm` is already the medium-band
path and `_unverified` is already the mark-and-deliver path — so the banding names the
mechanism that is there and gives it a second input (the gap) and a fourth case (low,
which today is indistinguishable from none). That is the strongest argument that this
is a change of *measurement* rather than of *flow*.

### 5.3 What changes outside the module

- **`correction.py`'s `_by_title` becomes gather-then-grade.** Today it scores one
  source's reply at a time and returns on the first candidate that clears the threshold
  (`correction.py:558-598`). The settled design gathers every source's candidates into
  a pool, dedupes, then grades once — and the *gather* is the only impure part (§5.2).
  The walk stops as soon as the pool grades strong (§1.2).
- **`FileBook` construction gains one argument** (`correction.py:552`), from
  `book.date`. Publisher is not passed, because it is not scored.
- **The walk records which sources answered, which errored, and whether it exited
  early**, for §4.2. That result type belongs beside `Outcome` in `correction.py`.
- **`googlebooks._candidate()` joins title and subtitle** (§3.3).
- **`record.py`'s `confidence` column is renamed and its tie-break questioned** — see
  §6, item 8. A schema change, so it wants a `PRAGMA user_version` bump.
- **`llm.py`'s prompt is unchanged**, and deliberately: it takes a list of candidates
  and numbers them, and under `llm_full_scan` it takes more. It does not need the score
  — and should not get it, since showing the model this project's own confidence would
  invite it to agree with the rules rather than look at the records.
- **The scope of two other tickets moves.** CBO-59 ("dedupe candidates across sources
  before confidence grading") cannot implement dedupe if CBO-58's banding depends on a
  deduped pool — they are one change to one module. **CBO-58 takes `dedupe()`; CBO-59
  keeps the flow wiring.** CBO-60 ("demote exact ISBN match from short-circuit to
  scored field") is consumed: the demotion is a weight of zero in §2's table. **Both
  tickets need editing in Linear before session 2 starts**, or session 2 will build
  against a plan describing two overlapping implementations of the same thing.

---

## 6. Open questions, and what I think is wrong

**This section is what remains open after session 1c.** Everything the two sessions
resolved is in the body above.

### Decided across sessions 1, 1c and 1d

| Decision | Where |
| --- | --- |
| The walk stops as soon as the pool grades strong, gap included — one rule, not two. | §1.2 |
| Early exit is rare: a singleton pool is the common case, so most walks run to completion. | §1.2 |
| A candidate agrees only if the author reaches a 0.5 floor; a non-agreeing author leaves the denominator and the score is capped at 0.7. | §1.3 |
| The title is **one form per side**: full-vs-full when both sides subtitle, heads only when one is bare. No max-over-forms. | §3.3 |
| Similarity is the character ratio on the normalised key; element-wise token comparison is rejected. | §3.2 |
| Author evaluation calibrates each creator then averages; it does not average raw ratios then calibrate. | §3.4 |
| The language guarantee stays in the source query; the matcher only drops differing codes of the same form. The code change is a separate ticket. | §3.5 |
| Weights: title 1.00, author 0.80, series 0.20, year 0.15, ISBN 0.00, publisher dropped. **Only title and author are derived**; series and year are unjustified defaults awaiting §4.4. | §2 |
| `singleton_score = 0.95` — a singleton is strong only when nothing the file states contradicts. | §4.1 |
| `strong_score = 0.89` and `medium_score = 0.80`, **both provisional**. | §4.1, §4.4 |
| The singleton bar stays at 0.95 and row 4 (series contradicts, 0.9070) goes to the medium band, so CBO-36's 0.90 verdict now means "sent to the tiebreaker", not "written". | §6 item 4 |
| A completed walk that graded strong with a source erroring is half-asked and does not write. | §4.2 |
| `llm_full_scan` means "ask whenever the band is not strong and the pool is non-empty", and it ships `true` — `false` is the narrowing. | §4.3 |
| `dedupe()` and `band_of()` are pure and live in the matcher; only the walk is impure. | §5.2 |
| `normalise()` is frozen as the record's key and pinned by a golden test. | §3.7, §5.1 |
| The `confidence` config key is renamed `strong_score`; `confidence` is the LLM's own figure. | §4.5 |
| `record.matches.confidence` is renamed and re-scaled; a match stored before this lands is unknown-scale and always replaced. | item 8 |
| `dedupe()` moves out of CBO-59 into this ticket; the ISBN demotion is CBO-60's whole content. | §5.3 |

### Blocking: cannot be settled from the ticket

1. **The exact normalisation formula.** §1.1 states the arithmetic the mechanism must
   satisfy and the property that falls out of it (a perfect match is exactly 1.0).
   What is *not* in the ticket is how beets divides — by the total possible weight, by
   the weight of the fields compared, or by something else — and the choice changes
   which books are affected by a sparse file. This note divides by the compared weight
   and fixes the consequence at the banding layer, which is a self-consistent design,
   but it is a re-derivation and is labelled as one. **If the maintainer wants the exact
   formula, it has to come from the source, and then the provenance position changes** —
   see the header.
2. **Whether the score carries a "missing field" term at all.** The ticket says
   weights, penalties and 0–1 normalisation, and nothing about how silence is priced.
   §1.1's answer is one of at least three defensible designs; the others are a fixed
   penalty per missing field, and a coverage multiplier on the final score. This is the
   single decision that most changes which books are matched.

### Where I think the settled design is wrong or under-specified

3. **The author floor admits a wrong author who shares initials and a surname, and
   nothing in this design can stop it.** §1.3: `L. J. Ross` / `L. K. Ross` scores
   0.6814 and agrees, exactly the similarity of the true typo `L. J. Ross` /
   `L. J. Riss`. No value of the floor separates them, because both are one character
   in the same position of a six-character key and `_join_initials` has already
   discarded the structure that told them apart. A metric that separates them needs
   positional structure the normalisation throws away — a design question, not a
   tuning one, and out of scope for this ticket. It is the sharpest edge in the design
   and it should be named as one in `docs/`.

   **This is contained by `strong_score`, in both pool shapes, and it was not before
   session 1e.** A file whose title is `Cragside` and whose author is not stated,
   against a record titled `Cragside` by `L. K. Ross`: the author gate passes at
   0.6814, the title is exact, and there are no other comparable fields, so the
   candidate scores **0.8584** — nothing detected the wrong author.

   The earlier draft said the singleton bar refused it. That was true **only for a
   singleton pool**, and it understated the exposure:

   | Pool | Which threshold governs 0.8584 | Verdict |
   | --- | --- | --- |
   | one candidate | `singleton_score = 0.95` | refused (0.8584 < 0.95) |
   | two or more, at `strong_score = 0.85` | `strong_score`, then the gap | **written** |
   | two or more, at `strong_score = 0.89` | `strong_score`, then the gap | refused |

   In a pool of two or more the singleton bar is not consulted at all, `strong_score`
   governs, and at 0.85 the wrong author cleared it — and any runner-up scoring below
   0.7784 satisfies the `gap ≥ 0.08` rule as well, so the candidate would have been
   **written automatically**, with nothing in the pipeline having noticed. A
   one-character difference in a middle initial was enough.

   **At 0.89 the case is refused in both pool shapes**, and that is the work
   `strong_score` is doing rather than the singleton bar alone. It is the second,
   independent reason the two thresholds do not move: lowering `strong_score` to admit
   row 4's 0.9070 would also have to refuse 0.8584, and the window (0.8584, 0.9070] is
   exactly that constraint. Worth stating plainly, because a future change that moves
   either threshold for an unrelated reason would silently start writing wrong authors,
   and the author gate would report that it had agreed.

   **The mitigation, which the earlier draft omitted.** 0.8584 is above
   `medium_score = 0.80`, so with an LLM configured the candidate lands in the medium
   band and goes to the tiebreaker with both records in front of it — a model shown
   `Cragside` by `L. J. Ross` and `Cragside` by `L. K. Ross` is being asked exactly the
   question the rules cannot answer, and is likely to answer it correctly. **So the
   exposure is narrower than "wrong author written": it is a default install with no
   LLM configured**, where the medium band becomes `colophon:unverified` instead. That
   is the shape of the risk — not a silent wrong write on a configured system, but a
   visible unverified book on an unconfigured one. It is still a failure, and it is
   still the reason the thresholds do not move; it is just a failure the design already
   has a path for.

   **And the containment margin is thinner than §4.1's window implies, because the
   window holds at one denominator only.** 0.8584 is the wrong author's score at
   denominator 1.80 — title and author, nothing else comparable. The author's penalty
   is divided by whatever weight the file actually supplies, so the *same* wrong author
   scores **0.8814** at denominator 2.15, when an agreeing series position and year are
   compared too. That is 0.0086 under `strong_score`, not the 0.0316 the window's lower
   margin suggests. Solved forward: a wrong author reaching **0.705** similarity grades
   strong at denominator 2.15, and **0.725** at 2.00, against `L. K. Ross`'s observed
   0.6814 — a real margin of about 0.023 of author similarity rather than 0.03 of
   score.

   The direction is backwards, and that is the part worth fixing eventually: more
   agreeing fields should make a wrong author *harder* to write, not easier, and here
   each additional agreeing field dilutes the one field that disagrees. This is not a
   blocker for session 2 — nothing in the fixture set reaches 0.705 — but §4.1's stated
   margin does not generalise, and §4.4's tuning pass should measure the wrong-author
   score at every denominator a real library produces rather than at 1.80 alone.
4. **Rows 3 and 4 are behaviour losses against the shipped code, and the decision on
   row 4 is settled.** §2.2's regression: the shipped rule writes both at 0.9000; the
   new design grades both medium. Row 3 (series *and* year contradict, 0.8372) loses
   because two fields disagree, which is the design working as intended. Row 4 (series
   contradicts, nothing else, 0.9070) is the case CBO-36 decided at 0.90 and the case
   the series weight was chosen around — so the design as it stands refuses what it was
   tuned to accept.

   **Settled: the singleton bar stays at 0.95 and row 4 goes to the medium band, where
   the LLM resolves it.** The reasoning, recorded rather than re-derived: an unverified
   tag is visible in the library and recoverable by dropping the book in again, while a
   wrong write is neither; and lowering the bar to rescue row 4 would also admit the
   `L. K. Ross` case at 0.8584 (item 3), which is a different person rather than a
   different edition.

   **What this costs, said plainly: CBO-36's 0.90 verdict no longer means "written".**
   It means "sent to the tiebreaker". A file with a series position in its title,
   matched to a record with a different position, went from being corrected silently to
   being marked unverified on a default install with no LLM configured. That is a real
   change in what users see, it affects every series book whose numbering a source
   disagrees about, and it should be in the PR body rather than discovered later.
   Both rows are the ones to re-check against the tuning set before shipping.
5. **Dedupe's grouping rule is now the load-bearing unknown, and it is in this
   ticket.** The ticket anticipates duplicates narrowing the gap, and dedupe is the
   fix — but dedupe also *reduces the pool to one* for most well-behaved books, which
   is the case §4.1 grades differently. The two are entangled: how dedupe groups
   records determines how often the singleton bar applies. Settle and implement the
   grouping rule **before** validating the bar, in that order. The ticket's rule
   (ISBN-13 equality, then normalised title + first author + year) reads as right.
   Note that dedupe's fallback key is *not* the same as `record.py`'s `book_key`
   (item 7), even though both are "title plus author" — worth not accidentally
   unifying them.
6. **The year window's width, decided in principle and open in value.** §2 settles that
   year is compared as a **window** rather than an equality, because `cbo-38` records
   that which release date a Hardcover candidate carries is not observable and the same
   book may differ by decades. What is not settled is N — an empirical question about
   the data, belonging to whoever owns §4.4's tuning set.
7. **The consistency DB and the matcher normalise differently, on purpose — and that
   needs a note in the code.** §3.7 freezes `record.py`'s key and adds a separate
   comparison pipeline. Two titles the matcher considers the same can have different
   record keys, and two it considers different can share one. In v1 this is invisible,
   because the consistency DB does not feed scoring. It stops being invisible the day
   someone builds the "prior matches bias scoring" idea the ticket defers. `record.py`
   needs a comment saying the duplication is deliberate, or a future reader will "fix"
   it.
8. **The record's `confidence` column changes scale, and the fix is to refuse to
   compare across the change.** `record.matches` stores a `confidence`, and
   `cbo-41:488-502` decides a repeat lookup by it: a higher confidence replaces the
   stored match, a lower one is history, and an **exact tie** goes to the configured
   `sources` order. A stored 0.95 written by the old rule is not comparable to a new
   0.83. **The decision: a match stored before this lands is treated as unknown-scale
   and is always replaced**, so the mixed-scale window never exists. A
   `PRAGMA user_version` bump is the mechanism; the column is renamed in the same
   change (§4.5, §5.3).
   The exact-tie rule mostly stops firing: it was designed for a scheme with a handful
   of discrete outcomes, where ties were common. A graded score makes exact ties rare,
   which is **the right outcome** — it is the same principle as "source priority
   carries no weight in the score": which source answered should not decide a match.
9. **The lookalike volume that pooling creates is a real cost.** `cbo-37` records that
   Google's `intitle:` search returns 300 noise items with `maxResults` capped at 40.
   Pooling every source's candidates means a Google result set can flood the pool, and
   a flood is not neutral: a long tail of near-identical noise *narrows the gap*, which
   downgrades a confident match to medium, which spends an LLM call. The pool cap is
   therefore load-bearing for the banding, and under §4.1 it is load-bearing for the
   singleton rule too. The ticket does not mention a cap. Keep the existing
   `CANDIDATES_PER_SOURCE = 5` (`correction.py:71`), per source, before dedupe and
   before scoring, and make the cap's effect on banding explicit in the docs.
10. **`llm_full_scan`'s definition is settled, and its name is now wrong.** §4.3 defines
    it as "ask whenever the band is not strong and the pool is non-empty", which is the
    population it exists for. But "full scan" reads as "scan everything", and what the
    flag does is remove the medium-band restriction on *which* uncertain books reach the
    model. A name like `llm_ask_when_unsure` is honest; whatever it is called, the
    config comment has to say what it does **not** do — it does not disable early exit.
11. **The title field is silent on the case the design most needs it to catch.** §3.3:
    row 7's Porter record carries a subtitle identical to the file's, so its title
    scores 1.0000 and only the author gate refuses it. That is acceptable — the
    candidate still lands at 0.7000, below every threshold — but it means the title
    field is not a second opinion there, and a future change that weakens the author
    gate would not be caught by the title. Worth a fixture whose lookalike differs in
    its *subtitle* rather than its head.
18. **The ISBN path stops at a failed source while the title path pools, and that
    asymmetry is not settled.** §4.2's half-asked rule is written about the pooled title
    walk, and this note does not say whether it reaches the ISBN path, which is not
    pooled: an ISBN identifies one edition, so the first source that knows it is as good
    as any other and there is no pool to build. **CBO-59 took the narrow reading** — a
    source that fails on the ISBN path still ends the walk for that book, which is held
    for tomorrow by the same rule, and the sources below it are not asked. That reading
    is defensible and it fixes the same outage bug on both paths, but it means one
    question has two answers and the difference is visible in behaviour rather than only
    in the code: a book with an ISBN stops at the first failing source, a book without
    one carries on. **This is left open deliberately. CBO-67 settles it** — whether the
    ISBN path pools, falls through, or keeps its stop — and until it does, the asymmetry
    is a settled *implementation* rather than a settled rule, and should not be read as
    one.

### Smaller, and settleable while building

12. **`normalise()`'s docstring will be wrong the moment §3.1 lands.** It explains a
    single normalisation used for both purposes. That docstring and `record.py:282`'s
    "the title score is computed from the file and the candidate record" comment both
    need to name which function is which.
13. **`primary_language()`'s docstring is already right and should not be "fixed".** It
    says the 639-1/639-2 equivalence is the query's business. §3.5 agrees. The risk is a
    later reader seeing a language filter in the matcher and "completing" the function.
14. **Where the tuned numbers live.** §4.4 produces thresholds and a calibration from a
    real library. A tuning set built from real books cannot be committed whole — it is
    somebody's library. A committed fixture subset plus a non-committed local set is the
    shape to expect, and the committed subset needs the labels or it is not a tuning
    set.
15. **`docs/` is named in the ticket and not written by it.** The ticket says the
    exposed and internal knobs are all documented in `docs/`, with the internal ones
    stating why they are not user-tunable. §4.5 gives the wording; where the file goes
    is a CBO-63 question.
16. **Determinism has a test that does not exist yet.** `cbo-38`'s finding that file
    duplicate detection is a byte comparison of the corrected book makes determinism a
    correctness requirement, and it deserves a test that scores the same pool twice and
    asserts an identical ordering and identical band — not just that `score()` is pure.
17. **Two tickets in Linear now contradict this note and need editing before session
    2.** CBO-59 is written as the ticket that adds dedupe (CBO-58 now owns it), and
    CBO-60 is written as the ticket that demotes the ISBN short-circuit (that demotion
    is a weight of zero in §2). Left as they are, session 2 finds three tickets
    describing overlapping work on one module.

---

## Fixtures this design needs

- **Same book, two editions** — the year-disagreement case, and the case the 0.15 year
  weight is justified by.
- **A same-title, different-author pair** — *The Infirmary* by Carly Reagon against
  *The Infirmary* by L.J. Ross already exists as two recorded works (`cbo-36`).
- **A singleton pool** and **a two-candidate pool** as separate fixtures, because §4.1
  grades them differently.
- **A pool where dedupe fires** — one record from both sources. `cbo-38` found
  Cragside's description byte-identical across the two sources, which makes Cragside
  the obvious pair.
- **A wrong-language candidate** with a two-letter file tag against a three-letter
  record (and the reverse), for §3.5's narrow rule.
- **A file with no author** and **a file with no year**.
- **A higher-degree author pair** — one correct and one held back — to test the
  multi-creator calibration order in §3.4.
- **A lookalike that differs in its subtitle**, for open question 11.

---

## Changelog — session 1c

What moved in session 1c, and why. Session 2 should read both changelogs before
trusting any table in the body.

| Change | Why |
| --- | --- |
| §1.3 added: the author gate (0.5 floor, denominator removal, 0.7 cap) | Session 1's "≥ 2 fields compared" rule did not preserve `Match.agrees`: with `date` on `FileBook`, row 10 compared two fields and scored 1.0000 |
| §1.2 rewritten: one rule for early exit, and it is rare | §1.2 said the gap was read once after the walk; §4.1 said a strong band ends the walk. Contradiction resolved to the §4.1 reading, with the singleton-pool consequence stated |
| §3.2 rewritten: the token mode is now stated, not left open | "Whole-word token lists" had two readings; element mode scores a surname typo at 0.0000, defeating the reason §3.4 says graded similarity exists |
| §3.3 rewritten: **one form per side**, not max-over-forms | Max-over-forms made any two titles that strip to the same head match at 1.0000, which read a different book's subtitle as an exact title match |
| §3.3's split now happens on the raw title | Session 1b's script normalised first, destroying the colon, so every title was silently read as a head |
| §3.4: calibrate per creator, then average | Session 1b's script averaged raw ratios and calibrated once, which is the opposite of what §3.4 said |
| §3.5 rewritten: the language guarantee stays in the source query | §2 moved it into the matcher and reused `primary_language`, which returns `eng` for `eng` and `en` for `en` and so would have dropped correct candidates |
| §2: weights swept; publisher dropped | 1d corrected *why*: the sweep found a region, not a value, and the series weight's old justification is dead. **Superseded by 1e**: the sweep does bound series above |
| §4.1: `strong_score` 0.90 → 0.85, marked provisional in 1d | At 0.90 rows 3 and 4 straddled the band wrongly; 1d removed the "matches the shipped threshold" reason and left it provisional. **Superseded by 1e**: 0.85 is outside its own window and became 0.89 |
| §4.1: `medium_score` given **0.80**, provisional | The table left medium and low with no boundary, so it could not be implemented as written |
| §4.2: the strong-band exemption from the half-asked rule **narrowed** | It covered early exit but also silently covered a *completed* walk that graded strong with a source erroring |
| §2: new §2.1 table and §2.2 regression table, both computed | The old table's similarities were not produced by the pipeline; 1c's are, and the script is in `scratch/` for re-running |
| Every section: figures replaced with computed ones | Session 1b found the note's own similarity column disagreed with its pipeline |

## Changelog — session 1d

Corrections. Session 1d changed no mechanism; it fixed numbers the note had got wrong
and the conclusions resting on them.

| Change | Why |
| --- | --- |
| Note moved `notes/` → `docs/research/cbo-58.md` | The repo keeps research in `docs/research/`, as every other CBO note does |
| §2.1: rows 4 and 5 moved from **strong to medium** | Every row is a singleton pool, so §4.1's 0.95 bar applies and not `strong_score`. 0.9070 is under 0.95. The script's output was right and the note's table was wrong |
| §2.2: row 4 → **new refuses**; row 5's flag removed | The regression table said "new writes" for row 5 while the paragraph below said no refused book is written. Row 5's score rises but its band does not change to strong, so nothing is written |
| §2.2: **row 4 named as a second behaviour loss** | The shipped rule writes it at 0.9000 and the new design grades it medium. It is the row the series weight was tuned around, so it must be visible rather than absorbed |
| §4.1: `singleton_score = 0.95` **derived** | It was an internal constant with no numbers behind it. Now shown as the score a singleton reaches when nothing the file states contradicts, with the 0.93 / 0.91 / 0.97 alternatives and what each would admit. **Superseded by 1e**: the "empty gap" derivation was wrong and the justification is replaced |
| §4.1: `strong_score = 0.85` marked **provisional** | Session 1c justified it by matching the shipped threshold — the same reasoning §4.1 rejected when it moved off 0.85. Replaced with the window it has to sit in, on the new scale. **Superseded by 1e**: 0.85 was named as inside the window and is not |
| §6 item 3: the `L. K. Ross` case recorded as **contained by the singleton bar by accident** | At an exact title and no other comparable fields it scores 0.8584 and passes the author gate; only the 0.95 bar refuses it. A second reason the bar does not move. **Superseded by 1e**: true for a singleton only, and false for a multi-candidate pool at 0.85 |
| §6 item 4: row 4's outcome recorded as **settled** | The bar stays at 0.95, row 4 goes to the medium band, and CBO-36's 0.90 verdict now means "sent to the tiebreaker" rather than "written" |
| §2: the **series weight's justification withdrawn** | It rested on landing row 4 on CBO-36's 0.90, and row 4 is no longer written there. Sweeping series 0.15–0.35 changes no row's band, so 0.20 is an unjustified default awaiting §4.4. **Part-corrected by 1e**: the sweep does change a band at 0.30 and above, so series is bounded above rather than unjustified |
| §2: year 0.15 also marked an unjustified default | Same sweep, same reason: the fixture set does not select it. **Stands** |

## Changelog — session 1e

Two corrections, and nothing else. No decision listed as settled was reopened, and no
number outside the four below was re-derived or re-swept.

| Change | Why |
| --- | --- |
| §4.1: **`strong_score` 0.85 → 0.89** | 0.85 is outside the window the same paragraph derived. The window is (0.8584, 0.9070] and 0.85 is below its lower bound, so a wrong author clearing the gate graded strong — the note's own table said so. 0.89 sits inside with margin on both sides. The "matches the shipped threshold" reasoning is removed, and the "0.85 sits in the safe half of that window" sentence with it |
| §6 item 3: the `L. K. Ross` containment claim **corrected** | "The singleton bar refuses it" was true only for a singleton pool. In a pool of two or more, `strong_score` governs and at 0.85 a score of 0.8584 cleared it, with any runner-up below 0.7784 satisfying the gap rule — a wrong author written automatically. At 0.89 it is refused in both pool shapes, and `strong_score` is doing that work |
| §6 item 3: the **mitigation added** | 0.8584 is above `medium_score`, so on a configured system it goes to the LLM tiebreaker with both records in front of it. The exposure is a default install with no LLM, where medium becomes `colophon:unverified`. That is the shape of the risk and it was missing |
| §4.1: the **"empty gap" derivation of `singleton_score = 0.95` replaced** | The gap between 1.0000 and 0.9302 is empty only because the fixture cases flip series and year as binaries with title and author held exact. Once the title is graded the range fills continuously — 0.90 scores 0.9535 and 0.95 scores 0.9767 at denominator 2.15. There is no gap. Replaced with what the bar actually does: it sets the minimum title similarity a singleton needs when everything else agrees, ≈ 0.89 at denominator 2.15 and ≈ 0.91 at 1.80 |
| §4.1: the **0.97 and 0.93 arguments corrected** | 0.97 does not refuse "exactly what 0.95 refuses" — under a graded title it refuses more. And the 0.93 objection no longer rests on 0.9302 clearing it by two ten-thousandths, which is not a margin |
| §2: the series weight **restated as bounded rather than unjustified** | Session 1d's "no row's band changes" is false at the top of the range: at series 0.35 the denominator is 2.30 and row 3 scores 0.7826, below `medium_score = 0.80`, moving out of the LLM's reach; at 0.30 it lands on 0.8000 exactly. So series is bounded above by row 3 staying in medium, and unconstrained below within the swept range. 0.20 remains the default |

## Changelog — session 1f

Three corrections to the note, made by hand rather than by a session. No number was
re-derived, no threshold moved, and no decision listed as settled was reopened.

| Change | Why |
| --- | --- |
| §1.3: `L. K. Ross` **moved to the agreeing side** of the floor's worked list | It was listed at 0.6814 among the names that do not agree. 0.6814 clears the 0.5 gate, so it does agree — which is the premise of §6 item 3's whole containment argument, and of §4.1's window. The table two paragraphs above already said so, and §1.3 contradicted it |
| §1.3: the claim that the floor **"refuses nothing that is genuinely the same name" removed** | False, and §3.4 holds the counterexample: a bare transposition (`LJ Ross` / `Ross LJ`, 0.1914) is the same name and is refused, because only the comma form is reversed before comparison. Replaced with the qualified statement |
| §6 item 3: the **denominator-dependence of the containment margin** added as an open point | The window's lower bound of 0.8584 is the wrong author's score at denominator 1.80. At 2.15 the same author scores 0.8814 — 0.0086 under `strong_score`, not 0.0316. A wrong author at 0.705 similarity grades strong at 2.15, and at 0.725 at 2.00. Not a blocker; nothing in the fixture set reaches it. Flagged for §4.4 rather than fixed here, because fixing it means moving a threshold |
