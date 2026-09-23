# CBO-74: fixtures drifted from their queries — how far, and which ones are evidence

Session 1 of 3, research only. Branch `dsh/cbo-74-fixture-drift` off `origin/main`
at `593f14a` — "Merge pull request #17 from Cbow2018/dsh/cbo-73-title-query-isbn",
the merge of CBO-73. Nothing was recorded (no token), no fixture was edited, added
or deleted, and `matching.py`, the scoring weights and the thresholds were not
touched. The only file this session produces is this one.

Read with the ticket [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re-record-and-guard)
and CBO-73's merged PR description (PR #17).

**Two corrections to the reading list before anything else.**

* **`docs/research-cbo-68.md` is not on `main`.** It is committed on the unmerged
  branch `dsh/cbo-68-standard-edition-rule`
  (`git show dsh/cbo-68-standard-edition-rule:docs/research-cbo-68.md`). CBO-74's
  description cites its §3.1 as though it were a repository document. Every
  citation of it below is to that branch, and it is 2026-09-22 work.
* **CBO-74 has no comments.** Item 3 of the ticket says "a working script exists
  in this ticket's comments from the 2026-09-22 session". `list_comments` on
  CBO-74 returns `[]`. The nearest thing that exists is
  `.tmp/record_cbo38_hardcover.py` and `.tmp/record_cbo38.py`, both from
  2026-09-19 and both gitignored. §4 below is written from those and from the
  shipped queries, not from a ticket comment.

### Session 2 corrections, 2026-09-23

Two measurements in this note were re-taken against the scorer, and one of them
was wrong in a way worth recording rather than quietly fixing.

1. **The five Poe volumes score 0.9231, not 1.0000.** §3.2, §4.2 and the ticket
   all say the tied group scores 1.0000, and they do not: measured by running
   `matching.rank` over the real Gutenberg EPUB and the real fixture, the top
   five score **0.9231** and the sixth scores **0.8629**. The reason is
   `1 - YEAR_WEIGHT / (TITLE_WEIGHT + AUTHOR_WEIGHT + YEAR_WEIGHT)` — the file
   carries `2010-06-06` and none of the five matches it — so the score was never
   going to be 1.0 for a file that carries a year. **Nothing in §4's argument
   depends on the absolute value: the finding is the gap, and the gap is still
   0.0000.** The five-member set is `[0, 1, 3, 4, 6]`, exactly as §4.2 predicted.
2. **The tie survived the re-record, but not as predicted.** §3.2 and the block
   below say a re-record "will return up to 40 volumes, not 10". It returned
   **20**, with `totalItems` still 300: Google honours `maxResults` as a ceiling
   and answers with what it has that is relevant. The frozen cases are still the
   right call — the reply changed completely — but the arithmetic of "the extra
   30" was a guess about a source this note had not asked.

Corrections 1 and 2 are also stated where they bite: `hand-made/README.md` for
the score, and `docs/recording-fixtures.md`'s *Unguarded* section for
`maxResults`. The body of this note is otherwise left as session 1 wrote it,
because it is a record of what was measured on 2026-09-22.

### On the evidence in this note

Every fixture measurement below was taken this session, twice, by two independent
methods (read tool and a `ConvertFrom-Json` property dump) that agree on all 45
JSON fixtures. Where a number is quoted from a prior note, the note and **the date
it was measured** are named. Fixture recording dates come from `git log
--diff-filter=A`, and are the dates the *files* were committed, which is the same
day the API answered.

## 1. What CBO-73 already gives you — and whether this is an afternoon

**It is not an afternoon. It is closer to one and a half sessions than three, and
the reason is not the scanner — it is the fixture mapping.** The honest split:

| Piece | Cost | Why |
| --- | --- | --- |
| Reuse `selection_set()` to get a query's field names | **free** | It already exists, on `main`, as `tests/test_hardcover.py:680`, and it already strips arguments — the thing that made CBO-73's first attempt wrong. |
| Compare a fixture's key set to a query's | **a few lines**, if that is all it is | `ASKED_FOR` + `set` comparison, literally. |
| Compare a fixture's key set to a query's *nested* selection | **new — the real work** | See below. |
| Know which query made a given fixture | **new — the real work** | See below. |
| Decide what "match" means where a reply legitimately lacks a key | **new, and it is a judgement call, not code** | See below. |
| Make the guard green | **blocked** | 26 of 27 Hardcover fixtures and 15 of 18 Google fixtures fail a field-set check against the shipped queries today. See §2. |

### 1.1 The cheap half is real

`selection_set(query)` returns the query's outer selection as a *string* of field
names with arguments removed:

```
editions(...) { isbn_13 isbn_10 title publisher { name } release_date ... }
```

For `QUERY` that string is a **flat** list of edition-level names plus `book`. So a
top-level edition-key check is `set(fixture_edition_keys) == {names in
selection_set(QUERY)}` — genuinely a handful of lines, reusing the exact scanner
the review already hardened. `ASKED_FOR` is not the right operand (it is the nine
*written payload* fields, not the query's fields), but it is the right precedent:
the mapping is a plain dict, and CBO-73 already argued that a dict beats a
substring check.

### 1.2 Three things genuinely new, in increasing cost

**(a) Nested selection.** The fields that actually drifted are not top-level. The
`release_date`/`publisher`/`image` gap is at *edition* level (easy), but
`cached_tags` and `book.id` are under `book`, and `contributions{author{id name}}`
and `book_series{series{id name}}` are two levels down with a *filter and an
order_by* attached. `selection_set()` handles one level: it returns at the first
unmatched `}`. A nested version is a small recursive/brace-stack parser — maybe
40–60 lines, plus a dict describing the shape. `ASKED_FOR`'s nine entries cannot be
reused for this because they name only written payload fields, and `image`,
`cached_tags`, `id` are fetched-but-unwritten by design.

**(b) Which query made this fixture.** There is no machine-readable record. What
exists is the filename prefix (`by-title-` / `by-isbn-`), a test-local constant
(`test_hardcover.py:39` defaults `Replay(name="by-isbn-found.json")`), and the
README's prose table. A guard needs this to be data. See §6.

**(c) The semantics, which are the part that decides whether the guard is honest.**
Three classes of legitimate-looking mismatch all appear in the committed set:

* **A key the query selects but the reply lacks, because the source had nothing.**
  `by-title-belsay.json` carries `isbn_13: null` and `isbn_10: null`;
  `by-title-berwick.json` record [1] does too. `by-title-berwick.json` (Google) has
  **no `authors`, `description` or `publishedDate` key at all** — all three are in
  the shipped mask, and Google simply has nothing for that volume. A strict
  equality check fails on all three. This is not drift.
* **A key the fixture has and the query does not select, because the query used to
  select it.** `by-title-cragside.json` (Hardcover) has the ISBNs and today's title
  query does select them — but only since CBO-73. The reverse case is
  `by-title-cragside-other-fields.json`, which has no ISBN key at all. Both are
  drift and both must fail.
* **A fixture legitimately recorded off-spec.** `by-isbn-two-series.json` was
  recorded *without* the query's `order_by`, and the Hardcover README says so
  (`:199-202`), because the point of it is the order Hardcover returns naturally.
  `by-isbn-cragside-authors.json` and `by-isbn-berwick-authors.json` lack
  `language`, which `QUERY` selects. A guard that does not know about these turns
  a documented choice into a red suite.

**The estimate.** If the guard is "top-level edition keys only", it is an
afternoon and it catches roughly the CBO-38 widening and the CBO-73 ISBN
regression. If the guard is meant to catch the drift the ticket actually describes
— `cached_tags`, `book.id`, `authors.id`, `series.id`, and Google's whole mask —
it needs (a), (b) and (c), and (c) is a conversation with you, not a coding task.
**Recommendation: do not rescope CBO-74 to an afternoon.** The narrow guard would
be green on a fixture set that is still 26/27 drifted, which is worse than no
guard because it reports coverage it does not have. Build the nested guard and
accept that session 2 is a build session with a real design decision in it.

## 2. The drift inventory

Sources of truth, read from `colophon/hardcover.py:40-125` and
`colophon/googlebooks.py:52-58` at `593f14a`:

**Hardcover `QUERY` (ISBN path) selects** — edition: `isbn_13`, `isbn_10`,
`title`, `publisher`, `release_date`, `image`, `language`, `book`; under `book`:
`title`, `description`, `release_date`, `image`, `cached_tags`, `contributions`,
`book_series`.

**Hardcover `_TITLE_QUERY` (title path) selects** the same nine edition fields
*plus* `book.id`.

**Google** sends a `fields` mask, which is an enumeration — anything outside it is
not returned. Mask: `totalItems`, `items/id`, `items/volumeInfo/{title, authors,
language, industryIdentifiers, description, publishedDate, publisher, imageLinks,
categories}`. So `kind`, `etag`, `selfLink`, `accessInfo`, `searchInfo`,
`pageCount`, `subtitle`, `seriesInfo`, `previewLink`, `infoLink`,
`canonicalVolumeLink`, `averageRating`, `ratingsCount`, `maturityRating`,
`contentVersion`, `printability`, `panelizationSummary`, `readingModes`,
`printType` and `allowAnonLogging` are all **outside the mask**.

### 2.1 Hardcover — title path (6 fixtures incl. the untracked one)

Legend: `—` present, `✗` absent, `+x` extra key the query does not select.

| Fixture | Era | Edition keys | Missing vs today's `_TITLE_QUERY` | Extra |
| --- | --- | --- | --- | --- |
| `by-title-cragside.json` | pre-CBO-38 | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `by-title-belsay.json` | pre-CBO-38 | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `by-title-berwick.json` (2 recs) | pre-CBO-38 | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `by-title-the-infirmary.json` (4 recs) | pre-CBO-38 | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `by-title-cragside-other-fields.json` | CBO-38 | title, publisher, release_date, image, language, book | **isbn_13, isbn_10** | — |
| `by-title-the-infirmary-other-fields.json` **(untracked)** | 2026-09-22 live | title, publisher, release_date, image, language, book | **isbn_13, isbn_10** | — |

Nested drift is uniform across the four pre-CBO-38 files: `book` carries
`id, title, contributions, book_series` and lacks `description`, `release_date`,
`image`, `cached_tags`. `contributions[].author` carries `name` only
(**no `id`**), and `book_series[].series` carries `name` only (**no `id`**). All
four are missing every CBO-38 field and every CBO-41/CBO-42 id.

**`by-title-the-infirmary-other-fields.json` is the only title fixture whose
`book` key set matches today's `_TITLE_QUERY` exactly** — `id, title, description,
release_date, image, cached_tags, contributions, book_series` — with `author.id`
and `series.id` present. Its only drift is the absent ISBN pair (see §3.1).

### 2.2 Hardcover — ISBN path (21 fixtures)

| Fixture | Era | Edition keys | Missing vs `QUERY` | Extra |
| --- | --- | --- | --- | --- |
| `by-isbn-found.json` | 09-19 am | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `by-isbn-no-series.json` | 09-19 am | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `by-isbn-edition-title.json` | 09-19 am | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `by-isbn-two-series.json` | 09-19 am | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `nothing-found.json` | 09-19 am | *(0 records)* | — | — |
| `hand-made-work-without-title.json` | hand-made | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `hand-made-wider-than-the-question.json` | hand-made | title, isbn_13, isbn_10, language, book | publisher, release_date, image | — |
| `by-isbn-cragside-edition.json` | CBO-38 | title, isbn_13, isbn_10, publisher, release_date, image, language, book | — | — |
| `by-isbn-9781521748831-genres.json` | CBO-42 | same 8 as above | — | — |
| `by-isbn-9781799729945-genres.json` | CBO-42 | same 8 | — | — |
| `by-isbn-9781529978940-genres.json` | CBO-42 | same 8 | — | — |
| `by-isbn-9780575064843-packed-genres.json` | CBO-42 | same 8 | — | — |
| `by-isbn-9781529196382-packed-genres.json` | CBO-42 | same 8 | — | — |
| `by-isbn-9781473225374-genres.json` | CBO-42 | *(0 records)* | — | — |
| `by-isbn-cragside-authors.json` | CBO-41 | title, isbn_13, isbn_10, book | publisher, release_date, image, **language** | — |
| `by-isbn-berwick-authors.json` | CBO-41 | title, isbn_13, isbn_10, book | publisher, release_date, image, **language** | — |
| `by-isbn-the-infirmary-authors.json` | CBO-41 | title, isbn_13, isbn_10, book | publisher, release_date, image, **language** | — |
| `author-lj-ross.json` | CBO-41 | *`data.authors`, not an edition reply* | n/a | n/a |
| `authors-spelling-variants.json` | CBO-41 | *four aliased roots, not an edition reply* | n/a | n/a |
| `works-good-omens-authors.json` | CBO-41 | *`data.books`, not an edition reply* | n/a | n/a |

**The five `*-genres.json` files and `by-isbn-cragside-edition.json` are the only
Hardcover fixtures whose top-level edition key set matches the shipped `QUERY`.**
They still drift underneath: none carries `book.id` (correct — `QUERY` does not
select it), but the four `*-authors.json` files and the three non-edition files
carry `author.id`/`series.id` where `QUERY`'s `by-isbn-found`-era siblings do not.
`by-isbn-cragside-edition.json` is the one ISBN fixture with `publisher` and
`release_date` and **no `author.id` or `series.id`** — so a nested guard fails it,
trivially.

### 2.3 Google Books — 18 fixtures

Two distinct drifts, and they are not the same drift.

**(a) The `fields` mask drift.** The mask is an enumeration, so a conformant reply
has top level exactly `{totalItems, items}`, item keys exactly `{id, volumeInfo}`,
and a `volumeInfo` drawn from the mask's nine. **Only three fixtures are
conformant:**

| Fixture | volumeInfo keys | Verdict |
| --- | --- | --- |
| `isbn-cragside-categories.json` | title, authors, publishedDate, description, industryIdentifiers, categories, language | **mask-conformant** — 8 of the mask's 9; `imageLinks` absent because the volume has none |
| `by-isbn-cragside-other-fields.json` | title, authors, publishedDate, description, industryIdentifiers, language | **mask-conformant** — 6 of 9, `publisher`/`imageLinks` absent |
| `by-title-cragside-other-fields.json` | *(2 volumes, differ)* title, authors, publisher/–, publishedDate, description, industryIdentifiers, imageLinks/–, language | **mask-conformant** |

Conformance is a *maximality* claim, not an equality one: a field the mask selects
and the volume has nothing for is legitimately absent (`publisher` and `imageLinks`
on the two `isbn` files above; `imageLinks` on the second Cragside volume). What
makes a fixture non-conformant is a key the mask **cannot** return.

The other **10** non-error files are non-conformant at the byte level: top level
carries `kind: "books#volumes"` and items carry all eight keys
(`accessInfo, etag, id, kind, saleInfo, searchInfo, selfLink, volumeInfo`). The mask
begins at `totalItems` and never names `kind`, `etag`, `selfLink`, `saleInfo`,
`accessInfo` or `searchInfo`, so **their presence is proof these were recorded
unmasked** — not with an older mask, but with no projection at all. Inside
`volumeInfo` they carry up to 21 keys including `pageCount`, `previewLink`,
`infoLink`, `canonicalVolumeLink`, `readingModes`, `printType`, `maturityRating`,
`contentVersion`, `panelizationSummary`, `allowAnonLogging`, `averageRating` and
`ratingsCount`. The two `nothing` and three `error` fixtures are empty and error
shapes and are unaffected.

The one `volumeInfo` key the corpus disagrees with itself about and the mask cannot
return is `subtitle`; `panelizationSummary` is the only mask-adjacent key that
varies *within* a file (`by-title-poe.json`, absent only on volume [5]).

A useful side effect of the mask: for the 10 unmasked files the original query
**survives verbatim** in `volumeInfo.previewLink`'s `dq=` parameter. The Poe file's
ten volumes all carry `dq=intitle:"The Masque of the Red Death" inauthor:"Edgar
Allan Poe"`, matching `TITLE_ASKED` at `tests/test_correction.py:130` exactly. The
three conformant files have no `previewLink` and so no recorded query. This is
directly relevant to §6.

**(b) The `subtitle` drift, which is a subset of (a).** Measured this session:
**11 volumes across 4 fixtures** carry `volumeInfo.subtitle` —
`by-title-poe.json` (6), `by-isbn-cragside.json` (1), `by-isbn-cragside-authors.json`
(1), `by-isbn-one-digit-off.json` (1), `by-title-cragside.json` (1),
`by-title-the-infirmary-reagon.json` (1).

The ticket says "8 of 18 recorded volumes". **CBO-68 §6.2 (2026-09-22) already
said 8 of 18**, and both counts are now wrong: the fixture set holds **26 volumes
across 14 non-empty files**, and 11 of them carry a subtitle. The discrepancy is
consistent with the count having been taken over a different volume population
(§3.1 of CBO-68 quotes 18 volumes for its *date* measurement, over "the 7
non-empty `by-title-*` recordings", which excludes every ISBN-path file). Either
way, **no committed fixture was recorded with the shipped mask and also carries a
subtitle**, so re-recording removes the field from every file that has it — which
is the whole of CBO-75's fixture evidence.

**`isbn-cragside-categories.json` is the fixture that proves the mask changed, and
the `googlebooks/README.md` was stale about it.** `:139-154` said the shipped
`FIELDS` does not carry `items/volumeInfo/categories` and that "CBO-42 appends it to
the mask". Read at `593f14a`, `FIELDS` (`colophon/googlebooks.py:52-58`) **already
ends with `"items/volumeInfo/categories"`** — CBO-42's addition is in the tree. So
the fixture is conformant, not drifted, and the README sentence is a documentation
defect rather than a code one. §7 therefore has no decision to make about the mask.

*(Session 2 fixed the README, and the re-record made the fixture ordinary: it was
recorded with that field appended to a mask that lacked it, and now answers the
shipped mask like every other ISBN recording. The `mask_selection` guard test reads
`FIELDS` itself, so the README and the mask cannot drift apart again without
something failing.)*

### 2.4 So how many instances?

The ticket asks whether there are twelve. **Twelve is a severe undercount, and it
is an undercount in an unhelpful direction.** Against the shipped queries today:

* **26 of 27 Hardcover fixtures fail a field-set check** (25 by edition keys, plus
  `by-isbn-cragside-edition.json` and the four `*-genres.json` files only if the
  check is nested; the three non-edition files fail by shape).
* **13 of 18 Google fixtures fail** — all 10 unmasked recordings, plus the two
  `nothing` files and three `error` files if the guard does not special-case empty
  and error shapes.
* **Two named instances in the ticket; ~39 fixtures in fact.**

That is not 12 drift instances — it is a fixture corpus built across five recording
eras (09-19 am, 09-19 pm CBO-38, 09-19 pm CBO-39, 09-20 CBO-41, 09-20 CBO-42),
only the last two of which match anything shipped. The ticket's framing ("a fixture
is recorded once, the query changes, and nothing fails") is exactly right; the
scale is the whole directory, not two files.

## 3. Which fixtures are load-bearing evidence for an open ticket

Ticket status read from Linear this session: open and fixture-dependent are
**CBO-68**, **CBO-69**, **CBO-65**, **CBO-75**, **CBO-66**, **CBO-70**, **CBO-76**.

### 3.1 The load-bearing table

| Fixture | Depends on it | What precisely rests on it | If a re-record returns something different |
| --- | --- | --- | --- |
| `googlebooks/by-title-poe.json` | **CBO-68** (§4), **CBO-69** (its whole reproduction), **CBO-75** | The only large multi-edition reply in the suite: 10 volumes, 5 tied at ~~1.0000~~ **0.9231** (session 2), gap 0.0000. CBO-68 §4's central finding (collapse by head+author still leaves Poe **medium**, gap 0.0602) is computed off it. CBO-69's bug is **candidate [4]**, `du6sYyygMgIC`, `'The Masque Of The Red Death'` (capital `Of`), `2013-01-29`. | **Catastrophic.** Loses CBO-69's reproduction outright if the casing changes; loses CBO-68's §4 headline if the volume drops or Google re-cases it. **Preserve the case before re-recording.** See §3.2. |
| `hardcover/by-title-the-infirmary.json` | **CBO-65**, CBO-68 §1/§3, CBO-66 | 4 editions → 2 works under `book.id`; the 3 L.J. Ross editions carry ISBNs `9781799729945`/`9781912310111`/`9781792780844`, all `position=11`, identical on every payload field except ISBN. This is CBO-65's premise (position is *uniform* here, so the collapse it describes is between editions of *one* work), and CBO-68 §3.1's evidence that Hardcover title replies carry no date (0/4). | **Degrading but not fatal for CBO-65**; **fatal for CBO-68 §3.1's "unproven"** — the replacement will carry `release_date`, which is the point of the re-record. ISBN variability across the three editions could change too. |
| `hardcover/by-title-cragside.json` | **CBO-68** §1, **CBO-68** §2.1 population, CBO-65 | One of 4 title recordings proving `books.id` exists on every edition; one of the 8 file fixtures in CBO-68 §2.2's 9-row population. | Low. One work, one edition, one `book.id`. Re-recorded, it grows a date and a publisher — which *changes* CBO-68 §2.2's completeness inputs. |
| `hardcover/by-title-berwick.json` | **CBO-68** §1 (2 editions → 1 work) | The reply proving multi-edition collapse already ships. | Low-ish. If Hardcover collapses Berwick's two printings, `_candidates` returns 1 either way. |
| `hardcover/by-title-belsay.json` | CBO-68 §2.1 population | Population row; also the only fixture with `isbn_13: null` **and** `isbn_10: null` present-but-empty. | Low for the population, **high as a guard specimen** — see §5. |
| `googlebooks/by-title-cragside.json` + `-other-fields.json` | **CBO-68** §2.2/§4, **CBO-75**, CBO-68 §3.1 | The "two printings of one work, both 1.0000, gap 0.0000" case — 2 of the 3 medium rows in the Google-only configuration. Both dated (`2021-03`, `2017-07-07`). Also 1 of the 11 subtitle volumes. | **Moderate.** This case is robust (two real Cragside printings), but note the two files are near-duplicates: `-other-fields.json` exists only because the mask widened. A re-record makes them *more* similar, and the pair could rationally collapse to one file. |
| `googlebooks/by-title-the-infirmary-reagon.json` | CBO-68 §4 (the refused head-only key), CBO-75 | The lookalike pair's second half. CBO-68's proof that a head-only collapse key **must be refused** (head-only gives `low`). | **Moderate.** If Google stops returning Reagon's volume, the lookalike case disappears and the head-only variant has no counterexample. |
| `hardcover/by-title-cragside-other-fields.json`, `googlebooks/by-isbn-cragside-other-fields.json`, `isbn-cragside-categories.json` | CBO-75, CBO-68 §6 | The mask-conformant trio; `isbn-cragside-categories.json` is the only Google fixture carrying `categories`. | Low for behaviour, **high for the guard's calibration** — these three are the only fixtures a strict guard can pass today. |
| `hardcover/by-title-the-infirmary-other-fields.json` **(untracked)** | **CBO-68 decision 4 ("Hardcover's dates")** | The live 2026-09-22 recording that **settles CBO-68's open question 4**: 4 of 4 editions carry `release_date`, so Hardcover *does* populate it and D3's primary key is not degenerate. §3.1 below. | It is already the answer, not a question. It is untracked, so it is currently one `git clean` from gone. |
| The 5 `*-genres.json` ISBN files | CBO-42 (merged) | Genre mapping evidence. | Low structurally, but they are among the 6 Hardcover files that match `QUERY`'s top level. |

**Fixtures in the set that no open ticket rests on and no test reads** (measured:
zero references in `tests/*.py`): `author-lj-ross.json`,
`authors-spelling-variants.json`, `by-isbn-berwick-authors.json`,
`by-isbn-the-infirmary-authors.json`, `works-good-omens-authors.json`. The
Hardcover README already says this at `:85` ("No test reads these six yet"). They
are CBO-41 planning artefacts. They are the cheapest candidates for deletion if
the re-record becomes large — but that is CBO-41's call, not this ticket's, and
`authors-spelling-variants.json` holds a row (`id 806228 'Ross'`) the README never
mentions.

### 3.2 The one you flagged: `by-title-poe.json`, and the general question

Verified this session against the recording:

```
[4] id=du6sYyygMgIC title='The Masque Of The Red Death' sub='Short Story'
    date=2013-01-29 authors='Edgar Allan Poe' pub='Harper Collins'
```

That is CBO-69's candidate [4] exactly — same id, same casing, same date — and
`2013-01-29` is the **earliest** date in the reply, so under any `earliest` rule it
is also the survivor. The case is doubly load-bearing: CBO-69's bug and CBO-68's
D3 leader are the same volume.

**Why re-recording is genuinely unsafe here.** `totalItems` for this query is
**300** and the fixture keeps the first 10. Nothing about the recording is
Colophon's choice: the set, the order, the dates and the casing are Google's
inventory on 2026-09-19. Google re-cases titles (it is a search engine, not a
catalogue — `cbo-37-google-books.md`, 2026-09-19, records `isbn:` behaving as a
relevance query). A re-record can therefore legitimately return `The Masque of the
Red Death` for that volume, at which point:

* CBO-69's reproduction is gone and its acceptance criterion ("Test: the Poe
  fixture's casing variant does not overwrite a correct file title") becomes
  untestable against the live file;
* CBO-68 §4's gap arithmetic changes, because the five-member tied group's
  membership changes;
* and nothing fails, because a re-record is indistinguishable from a fix.

**And the largest risk is not the casing — it is that the reply gets four times
bigger.** The title path asks for `maxResults=MAX_RESULTS`, which is **40**
(`colophon/googlebooks.py:68`, sent at `:148`). The Poe fixture holds **10** items.
Ten is Google's *default* page size, so the recording was made without the
parameter — and **no test asserts `maxResults`, and `ReplayByQuery` matches on `q`
alone** (`tests/test_googlebooks.py:45-67`). A re-record of this file will
therefore return **up to 40 volumes, not 10**, and the extra 30 are more printings
of the same story. Every number CBO-68 §4 derives from this file — ten volumes,
five tied at ~~1.0000~~ **0.9231** (session 2), gap 0.0000, the 0.0602 post-collapse
gap — is computed off a
reply the current client cannot obtain, and the replacement will not be a
like-for-like measurement.

**Session 2, after the re-record:** it returned **20** volumes, not "up to 40",
with `totalItems` still 300 — Google treats `maxResults` as a ceiling and answers
with what it has. The reply changed completely, so freezing the cases first was
still the right call, but the "extra 30" above was a guess about a source this
note had not asked. The five-member tied set survived, and is frozen in
`hand-made/poe-core-cases.json`.

This is the ticket's own theme one level below the key set: **the fixture is a
10-item reply to a request the client now makes asking for 40.** A field-set guard
would not notice, because the key sets are identical. It is the strongest argument
in this note for treating the Poe recording as evidence to be frozen rather than
replaced.

**The answer to the general question is yes, the fixture set should distinguish
the two jobs — and it currently does not, in any form, by naming or by
directory.** Today the only signal is the word "hand-made" in two Hardcover
filenames. Google has none.

**Recommended shape (do not build it this ticket): a `hand-made/` directory beside
the live recordings, with a README stating the rule.**

```
tests/fixtures/googlebooks/by-title-poe.json          ← the API's reply, re-recordable
tests/fixtures/googlebooks/hand-made/poe-core-cases.json  ← the cases, frozen
```

Why a directory rather than a name suffix: the distinction is a *different reason
to exist*, not a different kind of file, and a directory is the only form that
cannot be forgotten when someone adds the next one. It also matches what the repo
already does for the two hand-made Hardcover files — those are named, but they sit
in the live directory, which is precisely the ambiguity to remove. The rule to
write down:

> A **live** recording is re-recordable at will; nothing asserts its values, only
> its shape. A **hand-made** fixture exists to freeze one case a ticket rests on;
> it is never re-recorded, and it says which ticket and which case in the
> directory README.

**The concrete instruction for the Poe file.** Before the live file is replaced,
freeze the volumes the two tickets actually rest on into
`hand-made/poe-core-cases.json`: **volume [4]** (`du6sYyygMgIC`,
`'The Masque Of The Red Death'`, `2013-01-29` — CBO-69's casing and CBO-68's
`earliest` survivor) and **the four other volumes of the ~~1.0000~~ 0.9231 tie**,
since
CBO-68 §4's gap of 0.0000 *is* that five-member group. Keep `totalItems: 300`.
Then note in that README which ticket reads which volume. **This is a session-2
deliverable, and it is the first thing CBO-74 should build, before the guard** —
because the guard is worthless if the evidence it protects has already been
overwritten by the re-record the guard was supposed to make safe.

### 3.3 CBO-68's open question 4 is already answered by the untracked recording

`tests/fixtures/hardcover/by-title-the-infirmary-other-fields.json`, recorded
2026-09-22 14:51 (SHA-256
`FF2473CFD3304C1BAA616925D4FFCD77F11C66A582BA4AD0AEECCC040829C27C`, 10,712
bytes), carries **4 editions, all 4 with a `release_date`**: `2019-02-10`,
`2019-02-10`, `2019-01-01`, `2025-10-09`. Publishers are `Audible Studios on
Brilliance`, `Dark Skies Publishing`, `Independently Published`, `Hachette UK`.

CBO-68 §3.1 ("Hardcover: unproven — 0 of 8 editions carry a date") and its
decision 4 are therefore **already resolved in the affirmative**, by a recording
that exists on disk and is untracked. Two consequences worth acting on:

1. **It should be committed** (session 2), or CBO-68's decision 4 gets re-litigated
   from the same stale 0/8 number the ticket was raised to correct.
2. **It is also drifted**: its edition records have **no `isbn_13`/`isbn_10` key at
   all**. So the 2026-09-22 live recording was made with a title query that did
   *not* ask for the ISBNs — i.e. CBO-73's bug was still live when it was taken,
   three hours before PR #17 merged at 15:23. It is a second, independent
   confirmation of CBO-73's defect, and it means **the re-record must be redone
   after CBO-73**, which is what CBO-74 item 1 says.

There is a third thing in it: `book.cached_tags` is present with keys `Tag, Mood,
Genre, Content Warning`. So the live title reply carries `cached_tags` — which the
committed pre-CBO-38 title fixtures lack — and the query asks for it.

### 3.3.1 Session 2: the Hardcover numbers, re-taken (2026-09-23)

The recording above is committed, and the whole corpus is re-recorded. Re-measured
against the replacement, **every Hardcover title-path edition in the corpus is
dated — 13 of 13**, and every Hardcover fixture in the corpus is dated 1/1.

| Fixture | Editions | Dated | Dates |
| -- | -- | -- | -- |
| `by-title-cragside.json` | 1 | 1 | `2017-07-07` |
| `by-title-cragside-other-fields.json` | 1 | 1 | `2017-07-07` |
| `by-title-berwick.json` | 2 | 2 | `2026-02-26` (both) |
| `by-title-belsay.json` | 1 | 1 | `2025-01-31` |
| `by-title-the-infirmary.json` | 4 | 4 | `2019-02-10`, `2019-02-10`, `2019-01-01`, `2025-10-09` |
| `by-title-the-infirmary-other-fields.json` | 4 | 4 | the same four |

**CBO-68's decision 4 is answered in the affirmative**: Hardcover populates
`release_date` on title replies, so D3's primary key is not degenerate on
Hardcover and the Infirmary's three L.J. Ross editions can be ordered by it.

Three things fall out of the re-record that the old fixtures could not show:

1. **The Infirmary's four editions are two works, not one.** The reply carries two
   distinct `book.id`s — 1198266 for the three L.J. Ross editions, 2284109 for the
   fourth — so the collapse CBO-65 and §1 describe is now visible in a fixture and
   not only argued from one.
2. **The tiebreak is not idle.** `by-title-berwick.json`'s two editions carry the
   **same** date, `2026-02-26`. §3.1's first consequence (that a date-less
   Hardcover degenerates D3 to its tiebreak) no longer holds, but two editions of
   one work agreeing on a date is exactly the case the tiebreak exists for.
3. **§4's Poe numbers are dead.** They were computed off a 10-item reply to a
   request the client no longer makes; the re-record returned 20 volumes. The
   frozen `hand-made/poe-core-cases.json` preserves the five-volume tie and the
   gap of 0.0000, and that is all of §4 that survives.

**CBO-68 must not re-quote the 0-of-8.** It was a recording-era gap, not a source
gap, and the fixtures now prove the opposite.

## 4. The recording matrix

Ordered by what unblocks CBO-68 first, then CBO-69, then the rest. **Do not run
any of this in this session's branch state without reading the warning under the
table first.**

Constraints that shaped the order:

* Every command records against the query that is **shipped at `593f14a`**, read
  from the module rather than retyped, so nothing here re-encodes a query by hand.
* Nothing overwrites an existing filename. A re-record of a file a test reads is a
  change to what a test asserts, which is a separate decision; this matrix writes
  new files and leaves the promotion to §5's follow-up.
* Callum records by hand with a token. `.tmp/` is gitignored, so the script below
  lives there and never reaches a commit.

### 4.0 The one-time harness (write `.tmp\record-cbo74.py`, do not commit)

```python
"""Record the replies CBO-74's re-record needs. Shipped queries only."""

import json, sys, urllib.error, urllib.parse, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from colophon.hardcover import QUERY, TITLE_QUERY  # noqa: E402
from colophon.googlebooks import FIELDS  # noqa: E402

TOKEN = (
    Path(r"C:\Users\Callum\secrets\hardcover_token").read_text(encoding="utf-8").strip()
)
KEY = (
    Path(r"C:\Users\Callum\secrets\google_books_key")
    .read_text(encoding="utf-8")
    .strip()
)
UA = "Colophon (+https://github.com/Cbow2018/colophon)"
HC_OUT = ROOT / "tests" / "fixtures" / "hardcover"
GB_OUT = ROOT / "tests" / "fixtures" / "googlebooks"


def hardcover(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.hardcover.app/v1/graphql",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def google(params):
    url = "https://www.googleapis.com/books/v1/volumes?" + urllib.parse.urlencode(
        params
    )
    request = urllib.request.Request(
        url, method="GET", headers={"Accept": "application/json", "User-Agent": UA}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def save(folder, name, status, body):
    payload = json.loads(body)
    if status != 200 or payload.get("errors") or payload.get("error"):
        print(f"REFUSING {name}: HTTP {status} {body[:300]!r}")
        return
    (folder / name).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {name}")


if __name__ == "__main__":
    which = sys.argv[1]
    if which == "hc-title":
        title, slug = sys.argv[2], sys.argv[3]
        save(
            HC_OUT,
            f"by-title-{slug}-current.json",
            *hardcover(TITLE_QUERY, {"titles": [title], "language": "en"}),
        )
    elif which == "hc-isbn":
        isbn, slug = sys.argv[2], sys.argv[3]
        save(HC_OUT, f"by-isbn-{isbn}-current.json", *hardcover(QUERY, {"isbn": isbn}))
    elif which == "gb-title":
        titles, author, slug = sys.argv[2], sys.argv[3], sys.argv[4]
        q = " OR ".join(f'intitle:"{t}"' for t in titles.split("|"))
        if author:
            q += f' inauthor:"{author}"'
        save(
            GB_OUT,
            f"by-title-{slug}-current.json",
            *google(
                {
                    "q": q,
                    "fields": FIELDS,
                    "maxResults": 40,
                    "langRestrict": "en",
                    "key": KEY,
                }
            ),
        )
    elif which == "gb-isbn":
        isbn, slug = sys.argv[2], sys.argv[3]
        save(
            GB_OUT,
            f"by-isbn-{slug}-current.json",
            *google({"q": f"isbn:{isbn}", "fields": FIELDS, "key": KEY}),
        )
    else:
        raise SystemExit(f"unknown job {which!r}")
```

Run every command below from `A:\Documents\GitHub\colophon`.

### 4.1 Step 1 — unblocks CBO-68's open decision 4 (4 commands)

Hardcover title replies with a date. This is the measurement CBO-68 §3.1 could not
make and its decision 4 is waiting on.

```powershell
python .tmp\record-cbo74.py hc-title "Cragside" cragside
python .tmp\record-cbo74.py hc-title "Berwick" berwick
python .tmp\record-cbo74.py hc-title "Belsay" belsay
python .tmp\record-cbo74.py hc-title "The Infirmary" the-infirmary
```

`The Infirmary` is the one that matters most: three L.J. Ross editions of one work
with a date each is what decides whether `earliest` can order them.

**Stop here and report.** If all four come back with `release_date` populated,
CBO-68's decision 4 is answered and CBO-68 can proceed; §3.3 already suggests it
is. If they come back empty, D3's primary key really is degenerate on Hardcover
and CBO-68 needs to know before session 2 builds the rule.

### 4.2 Step 2 — protect CBO-69's reproduction, *before* re-recording Poe

Freeze volume [4] (CBO-69's casing, CBO-68's `earliest` survivor) plus the other
four members of the ~~1.0000~~ 0.9231 tie (CBO-68 §4's gap-0.0000 group). Which four those are
is determined by running the scorer, not by eye — at `593f14a` the tie is the five
volumes scoring 1.0000 against a file holding `The Masque of the Red Death` by
`Edgar Allan Poe`. The indices below are **[0, 1, 3, 4, 6]** by the fixture's own
order; **verify that against the scorer before freezing**, because it is exactly the
kind of number this ticket exists to stop taking on trust.

```powershell
$poe = Get-Content tests\fixtures\googlebooks\by-title-poe.json -Raw | ConvertFrom-Json
$keep = 0, 1, 3, 4, 6
$case = [ordered]@{
  kind       = $poe.kind
  totalItems = $poe.totalItems
  items      = @($keep | ForEach-Object { $poe.items[$_] })
}
New-Item -ItemType Directory -Force tests\fixtures\googlebooks\hand-made | Out-Null
$case | ConvertTo-Json -Depth 20 | Set-Content tests\fixtures\googlebooks\hand-made\poe-core-cases.json
```

Then write `tests/fixtures/googlebooks/hand-made/README.md` naming, per volume, the
ticket that reads it. Then re-record the live Poe file (step 3). **This command is
the one that must not be skipped**, and it is why §3.2 recommends building the
`hand-made/` directory before the guard.

**Note what this freeze preserves that a one-volume freeze would not:** the *tie*.
CBO-68 §4's finding is that five volumes score identically and the band is therefore
medium — a single frozen volume cannot reproduce that, and the re-record returned
20 volumes (session 2; the "up to 40" guess below), so the tie's membership was
exactly what was about to change.

### 4.3 Step 3 — Google title replies, mask-conformant (7 commands)

These are the ones whose fixtures currently carry a subtitle, and the books
CBO-68's population is built from.

```powershell
python .tmp\record-cbo74.py gb-title "Cragside" "L. J. Ross" cragside
python .tmp\record-cbo74.py gb-title "Berwick" "L. J. Ross" berwick
python .tmp\record-cbo74.py gb-title "Belsay" "L. J. Ross" belsay
python .tmp\record-cbo74.py gb-title "The Infirmary" "L. J. Ross" the-infirmary
python .tmp\record-cbo74.py gb-title "The Infirmary" "Carly Reagon" the-infirmary-reagon
python .tmp\record-cbo74.py gb-title "The Masque of the Red Death" "Edgar Allan Poe" poe
python .tmp\record-cbo74.py gb-title "The Cragside Compendium of Nothing" "" nothing
```

`langRestrict=en` is sent for all seven, matching what the DCI Ryan recordings were
made with (`googlebooks/README.md:31-34`). The `nothing` one needs no author
filter.

### 4.4 Step 4 — Google ISBN replies (5 commands)

```powershell
python .tmp\record-cbo74.py gb-isbn 9781521748831 cragside
python .tmp\record-cbo74.py gb-isbn 9781521748830 cragside-one-digit-off
python .tmp\record-cbo74.py gb-isbn 9780000000000 unrelated
python .tmp\record-cbo74.py gb-isbn 9789999999991 no-edition
python .tmp\record-cbo74.py gb-isbn 9781521748831 cragside-authors
```

**Nothing asks Google for genres.** `FIELDS` no longer carries
`items/volumeInfo/categories`, so a re-record cannot produce
`isbn-cragside-categories.json`'s content. Whether `categories` should go back
into the mask is CBO-42's finding and CBO-75's neighbourhood, not this ticket's —
flagged as a decision in §7.

### 4.5 Step 5 — Hardcover ISBN replies (5 commands)

```powershell
python .tmp\record-cbo74.py hc-isbn 9781521748831 cragside
python .tmp\record-cbo74.py hc-isbn 9780571334650 normal-people
python .tmp\record-cbo74.py hc-isbn 9780765311788 mistborn
python .tmp\record-cbo74.py hc-isbn 9780007458424 hobbit
python .tmp\record-cbo74.py hc-isbn 9781799729945 the-infirmary
```

Note `by-isbn-two-series.json` (Mistborn, 9780765311788) was deliberately recorded
without the query's `order_by`. A faithful re-record will now *have* the
`order_by`, which destroys the fixture's reason to exist (the featured series
coming back **last**). **Do not re-record Mistborn without deciding that first** —
it is called out in §7.

### 4.6 What is deliberately not in the matrix

* The three Hardcover non-edition files (`author-lj-ross.json`,
  `authors-spelling-variants.json`, `works-good-omens-authors.json`). They were
  recorded against **root fields the shipped queries do not contain** (`authors`,
  `books`, aliased roots); there is no query in `colophon/hardcover.py` that
  reproduces them, so "re-record against the current query" is undefined for them.
  They need a decision, not a command.
* The two Google `error-*` fixtures. They are what a rejected key and a bad
  `maxResults` return; re-recording means deliberately sending a bad key.
* The three `nothing`/`no-edition` fixtures. Their bodies are 53 bytes of
  `{"kind": ..., "totalItems": 0}`. `googlebooks/README.md:46-53` already argues
  that re-recording one would produce the same 53 bytes.

**Total: 22 recordable files; 3 need a decision first, 5 are error/empty shapes.**

## 5. What the guard cannot catch

Stated plainly, because the risk is someone reading "guarded" as "covered".

**After CBO-74 the chain is: query ↔ code (CBO-73), fixture ↔ query (CBO-74), and
nothing ↔ live source.** Neither guard ever contacts a source. Concretely, five
shapes stay invisible:

1. **A field the query selects, the fixture carries, and the source returns empty
   in every live reply.** This is the *exact* shape of Hardcover's `release_date`
   that motivated the ticket, one level down: the fixture's keys look right and the
   values are empty. **`by-title-belsay.json` is this shape already** — it carries
   `isbn_13: null` and `isbn_10: null`, so a key-set guard passes a fixture whose
   ISBN is empty, which is the same class of defect as a fixture whose ISBN is
   absent. Only a live recording distinguishes them.
2. **A field the query selects and the fixture carries, whose value shape changed.**
   `image` from `{"url": ...}` to a bare string, `book_series` from a list to an
   object, `cached_tags` gaining or losing a category key. Key-set comparison
   passes all three. (The `cached_tags` case is live: five keys in
   `by-isbn-9780575064843-packed-genres.json` — it alone carries `Group` — and four
   in every other `cached_tags` fixture.)
3. **A field the query selects, the fixture carries, that no code and no test ever
   reads.** `image` and `cached_tags` are fetched-but-unwritten by design (CBO-73's
   PR says so). A guard on the *fixture* confirms they arrived; nothing confirms
   Colophon still does the right thing with them.
4. **Drift in the source's own semantics** — a field that still returns, with
   different meaning. Google's `isbn:` relevance behaviour
   (`cbo-37-google-books.md`, 2026-09-19) is the precedent: the *shape* was fine
   and the *meaning* was not.
5. **The mask's server-side silence.** Google's `fields` is an enumeration, so a
   field Colophon wants but has not added is absent from every reply and from every
   fixture. `seriesInfo` (CBO-65, CBO-75) is in this class and has **no fixture
   evidence either way**: 0 of the 26 recorded volumes carry it, and it is not in
   `FIELDS` (`colophon/googlebooks.py:52-58`, which asks for no `seriesInfo`), so
   its 2026-09-19 measurement (`cbo-37-google-books.md:137-176`, "one volume in
   roughly a hundred") cannot be re-confirmed from the fixture set at all. Citing
   that note is citing a measurement taken **2026-09-19** whose population no longer
   exists on disk. A guard cannot tell "we stopped asking" from "the source stopped
   answering" — and no test imports `FIELDS`, so changing the mask cannot fail
   anything today.
6. **A request parameter that changed while the reply stayed valid.** This is the
   `maxResults` case of §3.2, and it is the sharpest limit of all: `by-title-poe.json`
   is a 10-item reply, the client now asks for 40, every key set matches, and
   `ReplayByQuery` matches on `q` alone. **A fixture↔query guard that compares field
   sets cannot see a parameter.** Comparing the whole request (the `fields` mask and
   `maxResults` and `langRestrict`, all of which are already in `Replay.sent` or
   `Replay.sent["url"]`) would catch it; comparing keys will not.

The one-line version: **the guard catches a query that changed under a fixture. It
cannot catch a source that changed under both.**

## 6. Should a fixture record the query that produced it?

**No — not inside the fixture. The bodies should stay the API's own bytes.** The
reason is that the repo already made this decision, deliberately, and re-opening it
costs more than it buys.

`googlebooks/README.md:5-8` states the invariant: "each body is the API's own,
re-indented so it can be read in a diff; nothing inside them is changed, including
`kind`, `etag`, `selfLink`, `accessInfo` and `searchInfo`". Wrapping a body in
`{"query": ..., "reply": ...}` breaks that for every fixture, and it breaks the
`Replay` seam: `test_hardcover.py:40` does `(RECORDED / name).read_bytes()` and
hands the bytes straight back to the client, and `test_googlebooks.py:36` does the
same. Both would need unwrapping. That is a real cost for a gain the repo can get
more cheaply.

**The gain is real, though, and the repo is already halfway to it.** `ReplayByQuery`
(`test_googlebooks.py:45-67`) *is* the "record the query" mechanism — it picks the
fixture by matching the `q` the client actually sent, and raises
`AssertionError(f"no recording for {query!r}")` otherwise. It exists for exactly one
fixture, the Poe one, and its docstring gives the reason: "a recording replayed for
the wrong query would be a test that proves nothing." **That is the whole drift
problem, already solved, in the one place a session bothered to solve it.**

**Recommended shape: keep the body pure, put the query in the test as data.** A
`RECORDINGS` dict in `tests/test_hardcover.py` / `tests/test_googlebooks.py`:

```python
RECORDINGS = {
    "by-title-cragside-current.json": ("title", {"titles": ["Cragside"], "language": "en"}),
    "by-isbn-found.json":             ("isbn",  {"isbn": "9781521748831"}),
    ...
}
```

Three properties, and they are why this beats a sidecar:

* the fixture body stays byte-faithful, so `Replay` needs no change;
* the guard reads the *same* declaration the replay does, so there is one mapping
  rather than two that can disagree — the failure mode CBO-73's review already
  found once in this area;
* a fixture added without a `RECORDINGS` entry fails, which is the enforcement the
  filename prefix cannot give.

The alternative — a `by-title-x.query` sidecar per fixture — doubles the file count
and lets the sidecar rot unread, which is the drift problem in a new costume. The
version-in-the-filename idea is already implicit (`-other-fields`, `-genres`,
`-authors`) and is worth *documenting* as the era marker, but it cannot be the
contract because it does not say which query, only that something differs.

**Do not build this in session 1.** It is the load-bearing half of §1.2(b) and it is
a session-2 shape decision.

## 7. Recommendation for session 2, and what I need decided

### Recommendation

**Session 2 is a build session with three deliverables, in this order — the order
matters, because the second protects evidence the third would otherwise destroy.**

1. **`hand-made/` for the cases, `RECORDINGS` for the queries.** Create the
   directory convention (§3.2) and the declarative fixture→query mapping (§6).
   Small, and it is the substrate both the re-record and the guard need.
2. **Freeze the load-bearing cases into `hand-made/`** — starting with
   `poe-core-cases.json` (§4.2), then whichever of §3.1's rows Callum wants
   protected. This must happen **before** any live file is replaced.
3. **The nested fixture↔query guard**, with CBO-73's `selection_set()` reused for
   the top level and a small nested parser for `book`/`contributions`/`book_series`,
   plus the explicit list of knowingly-off-spec fixtures from §1.2(c) so the guard
   is green on a *stated* set of exceptions rather than silently weakened.
   **Consider widening it from field sets to the whole request** — `Replay.sent`
   already holds `maxResults`, `langRestrict` and the `fields` mask, and §5 item 6
   shows a field-set-only guard cannot see the drift that matters most here.

**CBO-74 is three sessions, not an afternoon.** The re-record (item 1 of the
ticket) is Callum's and is a separate sitting; this ticket cannot close until it
happens and the guard is green against the result.

### What I need decided

1. **Does `by-title-poe.json` get frozen `hand-made/` cases *and* a fresh live
   recording, or does the live file stay as it is?** My recommendation is both, per
   §3.2 — but it means deliberately keeping a fixture that is known to be drifted,
   which is a policy call. **The `maxResults` finding (§3.2) makes this the urgent
   one: the live replacement holds more volumes than 10, so CBO-68 §4's numbers
   cannot survive the re-record either way.** *(Session 2 decided: both, and the
   replacement returned 20 volumes with no exemption for the live file.)*
2. **Is the guard allowed to be red on a stated exception list?** Something must
   absorb `by-isbn-two-series.json` (recorded without `order_by`, on purpose),
   `by-title-belsay.json` and the Google Berwick file (keys the query selects and
   the source has nothing for), and the three Hardcover non-edition files. My
   recommendation is an explicit `OFF_SPEC` dict with a one-line reason each,
   because the alternative is a guard loose enough to miss `release_date` again.
3. **CBO-68 decision 4 is already answered** (§3.3) by an untracked recording, and
   the answer is yes — Hardcover populates `release_date` on title replies, 4 of 4.
   Confirm, so CBO-68 can stop carrying it as open.
4. **`by-isbn-two-series.json` (Mistborn): re-record it and lose the natural-order
   case, or keep it off-spec?** §4.5. I recommend keeping it and marking it
   off-spec, because the featured-last ordering is the fixture's entire reason to
   exist.
5. **Should the guard compare the whole request rather than the field set?** §5
   item 6. `maxResults` drifted from 10 to 40 unnoticed and no field-set check can
   ever see it. My recommendation is yes — it is the same amount of code and it
   catches a strictly larger class.
6. **`isbn-cragside-categories.json` is conformant and `googlebooks/README.md:139-154`
   is stale about it** (§2.3). The README says the shipped `FIELDS` lacks
   `categories`; `colophon/googlebooks.py:57` says otherwise. Documentation fix, not
   a mask change — flagging it because a guard is about to start trusting that
   README.
7. **The five fixtures no test reads** (§3.1): delete, keep, or wire up? Not this
   ticket's decision, but the re-record is the cheapest moment to make it.

### Decisions I made myself (routine, for review)

| # | Call | Why |
| --- | --- | --- |
| 1 | Re-pointed the existing `dsh/cbo-74-fixture-drift` at `origin/main` with `git switch -C` rather than switching from it | The branch already existed on the stale `04e5585` (its reflog shows `Created from origin/main` before the fetch), and it had **no commits of its own**, so re-pointing lost nothing. `git reset`/`restore`/`clean` were not used, per the standing rule. The untracked recording survived. |
| 2 | Read `docs/research-cbo-68.md` from `dsh/cbo-68-standard-edition-rule` via `git show` into `.tmp/` | It is not on `main`; the deliverable is one file on a branch off `main`. Same call CBO-68's own session made (`research-cbo-68.md`, decision 2). |
| 3 | Measured every fixture twice, by two methods | The ticket exists because a measurement described a reply the code could not obtain. A single method would have been the same mistake in miniature. Both agree on all 45 files. |
| 4 | Counted `subtitle` across all 14 non-empty Google files rather than the 7 `by-title-*` ones | §2.3(b). The ticket's 8-of-18 and CBO-68's 8-of-18 are both population-dependent; the whole-set number is 11 of 26 and that is the one a re-record acts on. |
| 5 | Did not run the matrix's PowerShell | The session has no token and the instruction is explicit. §4.2's one-liner is the only command that neither records nor writes a fixture — it writes a *new* file in a directory that does not exist yet, so it is also not run here. |
| 6 | Recommended a directory over a filename suffix for hand-made cases | §3.2. The repo already has two named-but-not-separated hand-made files, which is the ambiguity to remove. |
| 7 | Recommended a `RECORDINGS` test constant over recording the query in the fixture | §6. `Replay` returns raw bytes and `googlebooks/README.md` states the bodies are unmodified; the query belongs where the replay already reads it. |
