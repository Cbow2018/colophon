# CBO-68: the standard edition rule — is it derivable, and is it worth it

Session 1 of 3, research only. Branch `dsh/cbo-68-standard-edition-rule` off `main`
at `e5ea994` (CBO-59 is still unmerged; §2.1 covers what that means). Nothing
tracked was changed; the probes are
`scratch/cbo68-survey.py`, `cbo68-measure.py`, `cbo68-measure2.py`,
`cbo68-measure3.py` and `cbo68-measure4.py`, all gitignored, and every number
below is computed rather than estimated.

Read with the ticket [CBO-68](https://linear.app/cbow/issue/CBO-68/title-search-returns-editions-not-works-the-medium-band-is-the-normal),
its comment *Decisions from grilling, 2026-09-22* (D1–D9, settled and not
reopened here), `docs/research/cbo-58.md` (the design spec behind every §-reference),
and `docs/pr-cbo-59.md`.

**Two corrections to the reading list, before anything else.**

* **There is no `docs/research-cbo-59.md` on `main`.** The CBO-59 research note
  and a session-2 handover are committed on the unmerged branch
  `dsh/cbo-59-pooled-walk` (`git show dsh/cbo-59-pooled-walk:docs/research-cbo-59.md`).
  Its F1–F5 follow-up is the source of this ticket, and F2 is the measurement
  this note's step 2 is asked to be comparable with.
* **CBO-59 is unmerged.** `main` has CBO-58's `rank()` / `dedupe()` / `band_of()`
  but no production caller of any of them: `correction.py:_by_title` still races
  the sources and writes anything at or above `strong_score`. So "the current
  medium-band rate" is not something `main` can be run to produce. Every band
  below is `dedupe` → `rank` → `band_of` over the recorded replies, which is
  CBO-59's `_gather` transcribed, and that is stated wherever it matters.

## Answers, in the order asked

| # | Question | Answer |
| -- | -- | -- |
| 1 | Does Hardcover expose a work-level identity? | **Yes — `books.id` — and the client already collapses on it.** CBO-70 is **not** a blocker. |
| 2 | Baseline medium rate on title-path books | **11% on the shipped source order, 33% if only Google answers.** §4.4's tuning set does not exist; the fixture population is 9 rows. |
| 3 | Is D3's rule derivable? | **Yes on Google** (dates on every multi-edition reply, earliest never tied). **Unproven on Hardcover** (0/8 recorded editions carry a date) and not yet deterministic there (no `order_by`). |
| 4 | Projected effect of D2 | **Nil on the shipped configuration.** It fixes the two Cragside rows on the Google-only path and **leaves the Poe fixture medium** — the one book the ticket exists for — unless the collapse key tolerates Google's own author spellings. No strong→weaker regression in any variant. |
| 5 | Is `most_complete` worth a config key? | **No. Hard-code `earliest`.** As a primary it ties where a date does not. |
| 6 | D6: where does edition wording live? | Hardcover: separate edition fields, already ignored. Google: a `subtitle` field Colophon **drops**, and the title on 3 of 10 Poe volumes. **The filename is read by nothing that scores** — D6's premise as written is false. |

---

## 1. Does Hardcover expose a work-level identity? Yes

`docs/research/hardcover-api.md` already records the schema split — `books` is the
work, `editions` is the printing, ISBNs live on `editions` and the work is reached
at `editions[].book` — and the fixtures carry it: **every edition in every one of
the four non-empty `hardcover/by-title-*.json` recordings has `book.id`.**

| Fixture | Editions | Distinct `book.id` | Candidates `_candidates()` returns |
| -- | -- | -- | -- |
| `by-title-cragside.json` | 1 | 1198994 | 1 |
| `by-title-berwick.json` | 2 | 2379453 | **1** |
| `by-title-belsay.json` | 1 | 1647114 | 1 |
| `by-title-the-infirmary.json` | 4 | 1198266, 2284109 | **2** |
| `by-title-cragside-other-fields.json` | 1 | 1198994 | 1 |

**The collapse is not merely available on the Hardcover side; it is shipped.**
`hardcover.py:_candidates` groups the reply by `book.id` and keeps one edition per
work, with a docstring saying exactly why ("a second edition would only offer the
same book twice"). Berwick's two printings become one candidate, and The
Infirmary's four editions become two — the two *works* that share the title, which
is the distinction CBO-36 exists to draw.

So D5 comes back **positive**, and CBO-70 is not pulled forward. The rest of this
note is about the Google side for the plain reason that **Hardcover is not the
source that produces the medium band: its reply is already one candidate per
work.**

**What is not free, and is this ticket's actual work on the Hardcover side.**

1. **The rule is arrival order, not D3.** `_candidates` keeps the *first* edition
   of each work. The surviving edition supplies the ISBN, the publisher, the cover
   and the date, so which of Berwick's two printings wins decides what gets
   written. The Infirmary's three L.J. Ross editions carry ISBNs
   `9781799729945`, `9781912310111` and `9781792780844`, and the reply picks the
   first with no reason recorded.
2. **There is no `order_by` on `editions` in the title query**, so "first" is not
   even a stated order: Hasura's row order with no sort is not a guarantee across
   requests. **This is a live determinism defect on the path the ticket's
   acceptance criterion names** ("a multi-edition reply for a popular title
   resolves the same way every run"), independent of anything Google does.
3. **The committed title recordings carry no `release_date` at all** — 0 of 8
   editions. They predate CBO-38's widening of the query, and only the widened
   `by-title-cragside-other-fields.json` has one (1/1, `2017-07-07`). The field is
   in the shipped query and in the schema (`editions.release_date`, a nullable
   `date`, plus `release_year` as a nullable `Int`), so this is a recording-era
   gap rather than a source gap — but **no committed fixture proves Hardcover
   populates it**, and D3's primary key for Hardcover therefore rests on an
   unverified assumption (§3).

## 2. Baseline: what fraction of title-path books grade medium

### 2.1 The population, and what "§4.4's tuning set" is

**§4.4's tuning set does not exist.** `docs/research/cbo-59.md` says so outright
("re-run §4.4's tuning set, which does not exist yet"), and nothing in the repo
contradicts it: there is no committed or gitignored labelled set of real books with
the identifiers of the record that *is* the same book from each source. §4.4 step 1
asks for 20–50 such books, step 1a for the pool size per book, and neither has been
built. **Steps 2, 3 and 6 cannot be run, so no threshold in this design has ever
been tuned.**

What exists instead is the fixture population: every recorded `by-title-*` reply
paired with the file book it was recorded for — **9 rows over 8 distinct file
fixtures**. Cragside is one file recorded twice (before and after CBO-38 widened
the query) plus a no-author variant, and two rows are single-source because only
one source has a recording for that book. Both facts are limitations of the
population, not choices.

Method, so the numbers can be re-run: `FileBook` from a real sample book read by
`epub.read`, candidates from the real `Hardcover`/`GoogleBooks` parsing functions
over the real recordings, pooled in the shipped `sources` order
(`("hardcover", "google_books")`, `config.py:27`), `dedupe`d, `rank`ed,
`band_of`ed, with CBO-59's early exit on a strong pool. No LLM: a default install
with no key is the case D7 names, and on that install every non-strong band is
`colophon:unverified`.

### 2.2 The band distribution, in F2's shape

F2's shape is an exclusive-category table with counts and a total. The same shape,
for the fixture population, under three source configurations:

| Configuration | strong | medium | low | none | total | **medium** |
| -- | -- | -- | -- | -- | -- | -- |
| both sources, shipped order | 6 | **1** | 1 | 1 | 9 | **11%** |
| `hardcover` only | 5 | **0** | 1 | 3 | 9 | **0%** |
| `google_books` only | 3 | **3** | 2 | 1 | 9 | **33%** |

The per-book rows, which are the ones that carry information:

| Book | both | `hardcover` only | `google_books` only |
| -- | -- | -- | -- |
| Cragside (no ISBN) | strong (pool 1) | strong (1) | **medium** (2) |
| Cragside (widened recording) | strong (1) | strong (1) | **medium** (2) |
| Belsay | strong (1) | strong (1) | strong (1) |
| Berwick | strong (1) | strong (1) | low (1) |
| The Infirmary (L.J. Ross) | strong (2) | strong (2) | strong (1) |
| The Infirmary (Carly Reagon) | strong (1) | none (no recording) | strong (1) |
| Holy Island | none (0) | none (0) | none (0) |
| The Masque of the Red Death | **medium (10)** | none (no recording) | **medium (10)** |
| Cragside (no author) | low (2) | low (1) | low (1) |

**The headline is that the shipped configuration is already at 11%, under the 20%
bar, and the collapse would not move it.** The reason is structural and worth
stating plainly: Hardcover is asked first, its exact-title query returns works
rather than printings, and one work from one title is a singleton pool that clears
`singleton_score` on an exact title and author — so the walk **exits early and
Google's multi-edition reply is never read**. Of the nine rows, only the Poe
fixture reaches the state the ticket describes, and only because Hardcover has no
Poe recording.

That makes the rate a function of which sources are configured, not a single
number, and the 33% Google-only rate is the one that matches the ticket's
complaint. Two of its three medium rows are Cragside (two printings of one work,
both scoring 1.0000, gap 0.0000), and the third is Poe (ten volumes, five tied at
0.9231, gap 0.0000).

### 2.3 The second basis: F2's own 1071-row sweep, in F2's shape

Comparability with F2 needs F2's basis: 17 title similarities × 7 author
similarities × 3 series states × 3 year states = **1071 rows, 500 distinct
scores** — reproduced here exactly, including F2's corrected count of **70**
distinct scores in `[0.89, 0.95)`.

| Band | Rows | Share | Distinct scores |
| -- | -- | -- | -- |
| strong | 58 | 5.4% | 29 |
| medium | 292 | 27.3% | 208 |
| low | 709 | 66.2% | 262 |
| none | 12 | 1.1% | 1 |
| **total** | **1071** | | **500** |

**This is a field-state distribution, not a book rate**, and the two must not be
averaged together or read as one. The fixture table says what a library does; this
one says what the scorer can reach. The 27.3% here is not "27% of a library grades
medium" — it is 27% of a synthetic enumeration of field states, weighted by a
ladder chosen for coverage rather than for frequency. What it does establish is
that the medium band is **densely populated on purpose** (208 distinct scores), so
a medium outcome cannot be dismissed as a rare edge.

## 3. Is the D3 rule derivable?

D3: the standard edition is the **earliest publication date of the work**,
tiebroken on **payload completeness**. Two questions: is a usable date present on
every candidate in a multi-edition reply, and is "payload completeness" defined
tightly enough to score.

### 3.1 The date, per source

| Source | Recordings | Candidates with a four-digit year |
| -- | -- | -- |
| `google_books` | 18 volumes across the 7 non-empty `by-title-*` recordings | **17 (94%)** |
| `hardcover` | 8 editions across 4 pre-CBO-38 title recordings | **0** |
| `hardcover` | 1 edition, the widened recording | **1** |

**Google: derivable, and stronger than the average suggests.** The one undated
volume is the single Berwick volume — a reply with nothing to choose between, so
the rule has no decision to make there. **Every multi-edition Google reply in the
fixtures is 100% dated** (Cragside 2/2, Cragside widened 2/2, Poe 10/10), and on
those the rule is decided by its primary key alone: Cragside `2021-03` against
`2017-07-07`; Poe ten distinct dates from `2013-01-29` to `2021-09-02`. **The
tiebreak never fires on any recorded reply.** Partial dates are the norm rather
than the exception (`2021-03`, `2019-02`, `2026-01-22`), and they order correctly
by plain string comparison while the forms are ISO-8601 prefixes — no parsing, no
dependency.

**Hardcover: unproven.** The schema has the field (`editions.release_date` is a
nullable `date`; `editions.release_year` a nullable `Int`; `books.release_date`
exists too, and `_candidate` already falls back to the work's), and the shipped
query asks for it. But **no committed recording shows it populated**, and this
session had no token, so it could not be recorded. Two consequences, and neither is
hypothetical:

* If Hardcover's editions carry no date in practice, D3's primary key **degenerates
  to its tiebreak for Hardcover**, and the tiebreak ties: The Infirmary's three
  L.J. Ross editions are identical on every payload field except the ISBN, so
  completeness is equal and the choice falls back to arrival order — which is the
  current behaviour, and not deterministic (§1.2).
* Even with dates, they are the *edition's* date, which is what the field means in
  the schema and what `_candidate` already prefers.

**One limitation of "earliest" that must be recorded rather than discovered later:
earliest *listed* is not first *published*.** Poe's earliest candidate is a 2013
Harper Collins reprint; the story is from 1842 and the Gutenberg file says 2010.
For any public-domain or long-reprinted work every candidate is a modern printing,
so the rule picks the oldest surviving listing. That is still deterministic and
still a defensible "standard edition", but it is not the first edition and the
diagnostic wording must not claim it is.

### 3.2 "Payload completeness" scores over these fields

The concrete set, taken from what Colophon can write rather than from the
`Candidate` dataclass, because `Candidate` also carries fields that are **not**
payload:

**`FIELD_DEFAULTS`' nine (`config.py:67`) plus the cover:**

`title`, `authors`, `series`, `series_number`, `description`, `publisher`,
`date`, `isbn`, `language`, and `cover`.

Deliberately excluded, and the reason is that they are identity or provenance
rather than something written: `source` (which source offered it), `author_ids`
and `series_id` (CBO-41's names for the same people, never written), and `genres`
(written only through CBO-42's mapping and its own setting, so counting them would
let an unmapped tag list decide which edition is standard). Nine of the ten are
greppable to `FIELD_DEFAULTS`; the cover is its own setting
(`config.py`'s `cover` rule) and is included because it is the one payload field
the file visibly gains.

### 3.3 Determinism: where it holds and where it does not

| Question | Answer |
| -- | -- |
| Is the earliest date ever tied, on a recorded reply? | **Never.** Cragside's pair and Poe's five-member group all have distinct dates. |
| Would `earliest` resolve a shuffled reply the same way? | **Yes on Google**, because the sort key is a value rather than a position — provided the final fallback is a total order on the candidate, which needs stating (see below). |
| Would it on Hardcover today? | **No.** The reply is unordered and the date is absent from every recording, so the answer is the reply's order. |

Two gaps the rule needs closed when it is built, both small:

1. **A total-order fallback.** `sorted` is stable, so two candidates tied on date
   *and* completeness keep input order — deterministic for one reply, but not
   across two replies that list the same editions differently. The honest fallback
   is a value that is already unique per candidate (the ISBN, then the normalised
   title, then the source's own edition key if CBO-70 gives one).
2. **Hardcover's `order_by`.** Adding `order_by: {release_date: asc}` to the title
   query's `editions`, or routing Hardcover's per-work collapse through the same
   rule, is what makes the Hardcover side obey D3 instead of arrival order. **It
   changes which edition's ISBN, publisher and cover get written**, so it is a
   behaviour change and not a tidy-up.

## 4. Projected effect of D2, estimated against the fixtures

Four collapse variants, same population, same source order. "Head" is the
candidate's title before its colon; "exact author" is `_name`'s normalised key;
"file-author gate" admits a candidate to a work group only when its author reaches
`AUTHOR_AGREES` against the **file's** author, the same floor `score_candidate`
gates on.

| Collapse | both sources | `google_books` only |
| -- | -- | -- |
| none (CBO-59 as shipped) | strong 6, medium 1, low 1, none 1 — **11%** | strong 3, medium 3, low 2, none 1 — **33%** |
| head + exact author | strong 6, medium 1, low 1, none 1 — **11%** | strong 5, medium 1, low 2, none 1 — **11%** |
| whole title + exact author | same as head + exact author | same as head + exact author |
| head + file-author gate | strong 7, medium 0, low 1, none 1 — **0%** | strong 6, medium 0, low 2, none 1 — **0%** |

**No variant moves any book from strong to a weaker band**, on either
configuration. D8's second half is met.

**And on the shipped configuration the collapse changes nothing at all.** That is
not a modelling artefact: the three rows it can reach are either already strong,
because Hardcover answered first and exited before Google's reply was read, or
missing a Hardcover recording entirely and left exactly where they were. The two it
does fix are the two Cragside recordings on the Google-only path. **The projected
effect is 3 books out of 9 in the most favourable configuration, and 0 out of 9 in
the shipped one.**

**The Poe fixture is the finding, and it survives the obvious fix.** Collapsing its
ten volumes by head and exact author gives six, and the band stays **medium**:

| After collapse | Score | Why |
| -- | -- | -- |
| leader: `The Masque Of The Red Death`, 2013-01-29 | 0.9231 | earliest of the five-member group; year disagrees with the file's 2010 |
| runner-up: `The Masque of the Red Death`, 2015-05-30 | 0.8629 | Google spells its author **`Edgar Allen Poe`**, so this is a *separate work* to the key, and its author similarity is 0.8533 |
| gap | **0.0602** | strong needs 0.08; every other work must score ≤ 0.8431 |

The collapse cannot reach the tie it was aimed at, because **the work key's author
component splits one work in two over a spelling Google itself disagrees with**: the
ten volumes carry `Edgar Allan Poe` (seven), `Edgar Allan Edgar Allan Poe` (one)
and `Edgar Allen Poe` (one). Merge those three spellings and the pool is four
candidates, the gap is **0.3254**, and the band is **strong**.

So the choice of author key is not a detail; it is the difference between D2
working and D2 not working on the only fixture that motivated the ticket:

| Author in the key | Poe | Risk |
| -- | -- | -- |
| exact (`_name` equality) | **medium** — gap 0.0602 | none beyond this failure |
| fuzzy (`AUTHOR_AGREES`, 0.5) | **strong** | inherits §6 item 3's sharp edge: `L. J. Ross` / `L. K. Ross` score 0.6814 and would merge two different people's books into one work |
| the file's author as the gate | **strong** | couples the collapse to the file; can never merge two works whose authors disagree with the file |

**A head with no author at all is the one variant that must be refused**, and the
fixtures show why. The Infirmary's four Hardcover editions are two books — L.J.
Ross's and Carly Reagon's — and a head-only key merges them. Measured on the
Reagon file: head + author gives `strong` (1.0000 against Reagon, 0.7000 against
Ross, gap 0.3); head only gives **`low`**, because the single surviving work is
chosen by completeness, which Ross's edition wins, so the file is offered a
different author's book with no runner-up left to catch it.

**What this means for the estimate, stated as a limit.** Nine rows over eight file
fixtures is not a library. Two of the three medium rows in the Google-only
configuration are the same book recorded twice, so the true denominator of "popular
titles that tie" here is **one**. The projection is directional: the collapse is
free (no regressions), it is nearly a no-op where Hardcover answers, and whether it
achieves D2's stated goal ("popular titles grade strong") depends entirely on a key
decision this session cannot make from 9 rows.

## 5. Is `most_complete` worth a config key?

**No. Hard-code `earliest` and do not ship the key.** D4's own instruction covers
this ("if session 1 finds nobody would set `most_complete`, drop the key and
hard-code the rule"), and there are three reasons, in order of weight:

1. **As a primary it reintroduces the tie it exists to break.** A publication date
   is nearly unique per work; payload completeness is a small integer with a heavy
   floor, so editions of one work cluster on it. Measured on the Poe group:
   completeness `[7, 9, 8, 9, 6]` — **two candidates share the maximum 9**, where the
   dates `[2020-10-06, 2021-09-02, 2020-03-19, 2013-01-29, 2021-03-09]` share
   nothing. `most_complete` therefore needs the date as its own tiebreak, which is
   `earliest` with the arguments swapped and a worse first key.
2. **As a tiebreak it never fires.** Every multi-edition reply in the fixtures has
   distinct dates, so the second half of D3's rule is dead code on the only evidence
   available. A key whose second value exercises a branch that cannot be reached
   cannot be evaluated by a user either.
3. **It is the same class of choice D3 already rejected.** "Most popular by
   ratings/count" was rejected because the signal is unstable and breaks
   determinism. "Most payload" is more stable but it is not stable *between
   sources*: across the 18 recorded Google volumes, `publisher` is absent on **10**
   and `imageLinks` on **6**, while a Hardcover edition carries both — so a
   `most_complete` pool prefers whichever source happens to fill more fields, which
   makes a source's completeness decide a match, the thing §4.4 and the "source
   priority carries no weight in the score" principle both refuse.

CBO-59's review found `singleton_score`, `medium_score` and `llm_full_scan` parsed
and read by nothing. A `standard_edition` key with a second value nobody sets, on a
branch the fixtures never reach, is the same defect written deliberately.

## 6. D6: where edition wording actually lives

### 6.1 Hardcover puts it in separate fields, and Colophon already ignores it

`editions` has its own `title`, `subtitle`, `edition_information` and
`edition_format` (documented, the last two not queried), and the work has
`books.title`. `hardcover.py:_candidate` prefers the work's title and only falls
back to the edition's, so edition wording never reaches `Candidate.title`. The
fixture shows both spellings side by side under one work:

```
work 1198266  books.title = 'The Infirmary'
              editions.title = 'The Infirmary'                     (isbn 9781799729945)
              editions.title = 'The Infirmary: A DCI Ryan Mystery'  (isbn 9781912310111)
              editions.title = 'The Infirmary: A DCI Ryan Mystery'  (isbn 9781792780844)
```

That is precisely what makes the Hardcover collapse work: the edition wording is
where the collapse can see it and the scorer cannot.

### 6.2 Google puts it in a `subtitle` field Colophon drops, and in the title often enough to matter

`volumeInfo.subtitle` is a separate field on **8 of the 18** recorded volumes, and
**`googlebooks._candidate` never reads it** — `title=_text(info.get("title"))`.
That is worth flagging beyond this ticket: `cbo-58.md:1100` records
"**`googlebooks._candidate()` joins title and subtitle**" as one of the changes
CBO-58 makes outside the matcher. It does not join them, and the docstring at
`googlebooks.py:255` says the opposite ("The subtitle is left off the title"). So a
Google candidate is scored on a head the source may never have used as the whole
title, and the difference is exactly the case §3.3's "one form per side" rule was
written for.

Google also puts edition wording **in the title** for 3 of the 10 Poe volumes —
`The Masque of the Red Death by Edgar Allan Poe Annotated`,
`The Masque of The Red Death Illustrated Edition`,
`The Masque of the Red Death (Short Story Books) (Hardcover)` — and varies the
casing on a fourth. So it is not "neither": for Google it is **both, and mostly the
field Colophon ignores**.

### 6.3 The filename is read by nothing that scores

**D6's premise — "edition words in a filename already ride in the title distance" —
is false as the code stands.** `epub.read` takes the title from the OPF
(`epub.py:184`, `_first_text(metadata, "title")`) with no filename fallback, and
`score_candidate` reads only `FileBook.title`. `path.name` has exactly two kinds of
consumer and neither scores: the LLM prompt (`correction.py:645` → `llm.py:341`,
`Filename:`), and log lines (`correction.py` ×3, `relay.py`). Measured: holding the
title at `Cragside` and changing the filename from `Cragside.epub` to
`Cragside (Large Print).epub` to `Cragside - Ulverscroft Large Print Edition.epub`
gives an identical leader (`1.0000`) and an identical band.

**What does ride in the title distance is edition wording in the file's
`dc:title`**, and the measurement is less flattering than "a small distance
penalty", because the query is affected first:

| File `dc:title` | Asked about | Leader | Band | What happened |
| -- | -- | -- | -- | -- |
| `Cragside` | `Cragside` | 1.0000 | medium | the baseline |
| `Cragside (Large Print)` | `Cragside (Large Print)` | **0.5508** | low | the bracket is not a series bracket (`_SERIES_BRACKET` needs `Book`/`Vol`), so it stays in the search string, is sent literally to both sources, and the marker is then scored against the record's bare title |
| `Cragside [Large Print]` | `Cragside [Large Print]` | **0.5508** | low | same, and the brackets are not even stripped for the query |
| `Cragside - Large Print` | `Cragside - Large Print` | **0.5508** | low | same |
| `Cragside: Large Print Edition` | `Cragside: Large Print Edition` | **1.0000** | medium | the colon makes it a subtitle; no candidate carries one, so §3.3 compares **heads** and the marker is invisible to the score |
| `Cragside (Ulverscroft Large Print)` | `Cragside (Ulverscroft Large Print)` | 0.4667 | low | same as the bracket form |

Two failure modes, and the second is the one to document:

* **The bracket form is scored and costs real evidence** (1.0000 → 0.5508), but it
  fails earlier than that: both sources filter literally (`books.title: {_in: …}`
  on Hardcover, `intitle:"…"` on Google), so a marker the source does not spell is
  a **query that returns nothing**, and the book is graded with an empty pool. The
  score above is what a pool that did come back would be worth.
* **The colon form is silently ignored by the scorer** (1.0000, because the head
  is compared) and still sent literally, so it fails at the query with no signal
  anywhere that the marker was the reason.

**And the D3 rule points the opposite way from a filename marker.** A user whose
file says *Large Print* is asking for the Ulverscroft printing
(`2021-03`, `Ulverscroft Special Collection`); `earliest` selects the original
(`2017-07-07`). Recorded in the fixture: for `Cragside` the leader is the
`Independently Published` 2017 record, not the large print. D6 asks for the filename
case to be **documented rather than built**, and this is the thing to document: the
standard-edition rule is deliberately indifferent to the user's request, and CBO-71
is where the two would have to be reconciled.

## 7. The pass bar (D8)

**D8's 20% is met before the change and cannot distinguish the change from doing
nothing**, on the fixtures, in the shipped configuration:

* shipped order: **11% medium** before, **11%** after any collapse variant;
* `google_books` only: **33%** before, **11%** (exact-author key) or **0%**
  (file-author-gated key) after.

So the bar is **trivially met** in the configuration that is supposed to be the
problem case, and **not met** in the one where the ticket's complaint actually
lives. Both halves are true at once because the medium rate is a function of
whether Hardcover answers first; the number needs a stated population before it can
be a pass bar. **Per D8 this is brought back rather than retargeted: no number is
changed in this note.**

Two further things the bar cannot currently be evaluated against, both already
stated: §4.4's tuning set does not exist, and the Google-only configuration has
**one** distinct popular title behind its three medium rows.

---

## Decisions taken in this session (routine, for review)

| # | Call | Why |
| -- | -- | -- |
| 1 | Branch `dsh/cbo-68-standard-edition-rule` off `main` at `e5ea994`, `--no-track` | The standing rule; Linear's suggested name is longer and the shorter one is the convention. |
| 2 | Read `docs/research-cbo-59.md` from `dsh/cbo-59-pooled-walk` via `git show` into `.tmp/` rather than switching branches | The note is not on `main`, and the deliverable is one file on a branch off `main`. |
| 3 | Present bands from `dedupe`/`rank`/`band_of` with CBO-59's `_gather` transcribed, not from running `correction.py` | `main` has no band caller, so there is no other way to state a current band. |
| 4 | Group D6's file-title forms under "bracket", "colon", "dash" rather than listing every variant | They are three behaviours, not six, and the table shows which is which. |
| 5 | Reuse F2's 1071-row basis verbatim, including its 70-value window count | Comparability was the instruction, and the basis reproduces exactly. |
| 6 | Report the field-state sweep and the fixture population as two separate tables that are never averaged | One is a reachability enumeration, the other is a book rate; averaging them would be a fabricated number. |
| 7 | Sketch three collapse keys and one refused variant (§4) | D2's effect is not estimable without naming a key, and the key turns out to decide the answer. |
| 8 | Take the ISBN path as out of scope without deciding anything | The ticket settles it: an ISBN identifies one edition, so the question does not arise. |
| 9 | Probes in `scratch/cbo68-*.py`, gitignored, no engine of their own beyond `matching`'s pure functions | `scratch/` is excluded and CBO-58/CBO-59 set the precedent; the numbers stay re-runnable. |

## What I need decided

1. **D8's population.** "Title-path books" is two different rates — 11% (shipped
   order) and 33% (Google only). Which one is the bar about? *This is the revision
   D8 explicitly invites, and it is the only number I am not changing myself.*
2. **§4.4's tuning set does not exist, and this ticket's headline measurement
   depends on it.** Nine fixture rows over eight file fixtures cannot support a
   rate. Do we build the labelled set first (blocking session 2), or ship the rule
   and record the limitation? My recommendation is to build it, because D8's bar and
   D4's key decision both want it and neither can be judged without it.
3. **The collapse key's author component.** Exact (Poe stays medium), fuzzy at
   `AUTHOR_AGREES` (Poe strong, but merges `L. J. Ross` with `L. K. Ross`), or gated
   on the file's own author (Poe strong, no cross-author merging). **I recommend
   the third**, and the head-only variant must not ship. This is a behaviour
   decision with a false-accept edge, so it is yours rather than mine.
4. **Hardcover's dates.** The committed title recordings carry none, so D3's
   primary key for Hardcover is unverified and, if the field really is empty,
   degenerates to a tiebreak that ties. Confirming it needs a live title recording
   with the widened query (a token — I had none). Confirm, or accept arrival order
   on the Hardcover side and say so.
5. **Hardcover's missing `order_by`.** Adding one to the title query (or routing
   `_candidates` through the D3 rule) is what makes the Hardcover side
   deterministic, and it changes which edition's ISBN/publisher/cover is written.
   In session 2, or a follow-up?
6. **D6's premise is false as written.** The filename rides in nothing but the LLM
   prompt. Does session 2 document *that* (with the `dc:title` bracket/colon
   findings above), or does D6 get restated first?

## Recommendation for session 2's scope

**Build the rule, and treat the measurement as the session's other half.**

1. **`collapse(candidates, file_book)` in `matching.py`**, pure like everything
   else there: group candidates by the work, choose the standard edition, and run
   it **before** `dedupe` and `rank` (D2). Key: the title head plus the file-author
   gate; survivor: earliest ISO date, then payload completeness over the ten fields
   in §3.2, then a total-order fallback that does not depend on reply order.
2. **Hard-code `earliest`. No new config key** (§5). Add nothing to
   `config.example.toml` that a user cannot reach.
3. **Close the Hardcover determinism hole** (§1.2, §3.3) — an `order_by` on the
   title query's editions, or the same rule applied to Hardcover's per-work
   collapse. Pending decision 5.
4. **The acceptance test the ticket names**: a multi-edition reply resolves the same
   way every run, tested by shuffling the recorded reply and asserting the same
   survivor, the same pool and the same band. That test is what pins D2's ordering
   and is worth more than any of the unit cases.
5. **Re-measure and report the before/after medium rate on the fixture population,
   per source configuration**, because §7 shows the aggregate number is the wrong
   instrument.
6. **Document the D6 findings** (§6) wherever the edition-marker behaviour belongs —
   at minimum: the filename is read by the LLM only, a bracket marker reaches the
   query verbatim, and a colon marker is invisible to the score. Building the
   grammar stays CBO-71's.
7. **Do not touch the scoring weights, `BAND_GAP` or the thresholds.** §4's estimate
   holds weights fixed, and F2's follow-up already covers why moving them is a
   re-derivation rather than a config edit.
