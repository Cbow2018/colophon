# CBO-36 starting point: title cleaning and title+author matching

**For the session that builds CBO-36.** Written 2026-09-19, after probing
Hardcover with the project's own token. Everything in "Verified against the API"
below is a captured reply, not a reconstruction. The probe scripts and their raw
replies were thrown away with `.tmp/`; the evidence is quoted here.

Read with `../../AGENTS.md`, `../agents/issue-tracker.md` and the ticket
[CBO-36](https://linear.app/cbow/issue/CBO-36/03-title-cleaning-and-titleauthor-matching).

## Where the work sits

CBO-35 is Done (PR #5, merge `9fc4499`), so nothing blocks CBO-36.

Branch: `dsh/cbo-36-title-matching`. Linear suggests
`callumbowden111/cbo-36-03-title-cleaning-and-titleauthor-matching`; the standing
rule in `~/.dsh/AGENTS.md` is `dsh/<short-topic>`, so the shorter one won. Say so
in the PR description.

### The seam

`colophon/correction.py` already has exactly the decision point this ticket
needs. `Corrector.correct()` reads the book, then:

```python
if not book.isbn:
    return Outcome(problem="no ISBN in the file, so no source was asked")
```

That early return is where CBO-36 goes. Everything downstream —
`Outcome.fragment()`, `Change`, `_edits()`, `_changes()`, `Corrector._write()` —
carries over unchanged, except that `CONFIDENCE = 1.0` is currently a module
constant and a title match has to compute a real score instead.

`Correcter._write()` calls `epub.correct(path, edits, write=False)` first to ask
the file what would move, so a book that already matches is neither backed up nor
rewritten. A title match gets that behaviour for free. Note that
`epub.correct(..., write=False)` returns the fields whose value *already*
differs — `tests/test_correction.py` has the existing examples.

### What the file gives you

`epub.read()` returns the file's title, authors, language and ISBN. Per CBO-36's
scope the clean signals are:

- `book.title` — may carry `: A … Mystery` and `(… Book N)`
- `book.authors` — the file's spelling, e.g. `L. J. Ross` where Hardcover has
  `L.J. Ross`
- `book.language` — already read, and the language to search in

Note the spacing difference between `L. J. Ross` (the file, in
`tests/samplebooks.py:AS_DOWNLOADED`) and `L.J. Ross` (Hardcover,
`tests/sources.py:MATCH`). Normalising the two to compare is explicitly in
CBO-36's criteria, and that pair is the fixture for it.

## Verified against the API

### 1. The exact-title path works, and the cleaning is load-bearing

`books.title` holds the *clean* work title — `Cragside`, not the editions'
messier titles. Matching it exactly is permitted and finds all three books:

| What was asked | editions | work | series | position |
| --- | --- | --- | --- | --- |
| `book: {title: {_eq: "Cragside"}}` | 2, one work | 1198994 | DCI Ryan Mysteries | 6.0 |
| `book: {title: {_eq: "Berwick"}}` | 2, one work | 2379453 | DCI Ryan Mysteries | 24.0 |
| `book: {title: {_eq: "Belsay"}}` | 2, one work | 1647114 | DCI Ryan Mysteries | 23.0 |

All three carry `L.J. Ross`. **Belsay needs no series number from the file** — it
is #23 on the record, which is the case CBO-36 names.

The file's title as it arrives finds nothing at all:

| What was asked | editions |
| --- | --- |
| `book: {title: {_eq: "Cragside: A DCI Ryan Mystery"}}` | 0 |
| `book: {title: {_eq: "Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)"}}` | 0 |

So a title with the subtitle or the series bracket left on it scores nothing.
That is the whole point of the ticket, and it is the strongest available
regression test for the cleaning rules.

### 2. Which operators this server actually permits

This is not in the docs, and it reshapes the design. `_ilike` — the obvious
choice for a title search — is **refused server-side**:

```
=== by-title -> HTTP 403, 74 bytes ===
{"error":"ilike and related operations are not permitted on this server."}
```

| Operator | Result |
| --- | --- |
| `_eq` on `books.title` | 200, works |
| `_ilike` | **403** `{"error":"ilike and related operations are not permitted on this server."}` |
| `_regex`, `_iregex` | **403**, same refusal |
| `_contains` | reject — not in the schema: `field '_contains' not found in type: 'String_comparison_exp'` |

There is therefore **no substring or case-insensitive title match available**.
Exact `_eq` is the only title filter that works.

This is a real recall risk worth a decision in the PR: a cleaned title that is
spelled or punctuated even slightly differently from `books.title` gets *zero*
candidates, with no fuzzy fallback. Anything that wants to soften that has to do
it by asking for candidates some other way.

### 2a. Answered when CBO-36 was built: `_in` works, and `_eq` is case-sensitive

Probed 2026-09-19 with the project's own token, with the query the client now
ships. This is the answer to the question this note left open.

```
=== _eq exact: HTTP 200 ===      2 editions, work 1198994
=== _eq lowercase: HTTP 200 ===  {"data": {"editions": []}}
=== _eq UPPERCASE: HTTP 200 ===  {"data": {"editions": []}}
=== _in three clean titles: HTTP 200 ===  Berwick 2379453, Cragside 1198994,
                                          Belsay 1647114 — six editions
=== _in with the messy title: HTTP 200 ===  work 1198994 only
=== _in plus language: HTTP 200 ===  all four en-language works
```

- **`_in` on `books.title` is permitted**, so one request can ask about a small
  set of cleaned title variants. CBO-36 sends one variant today (the cleaned
  title; the subtitle and the series bracket are both gone by then), so the list
  is a set of one — the operator is used because it is the one that is proven
  and because a later ticket can add forms without changing the caller.
- **`_eq` is case-sensitive.** `cragside` and `CRAGSIDE` both return nothing
  where `Cragside` returns the work. So a title has to be asked about exactly as
  Hardcover spells it, and the recall risk above is real rather than theoretical.
- One work comes back once per matching edition, so the client keeps the first
  edition of each `books.id` and drops the rest.

Two more facts, both needed by the client:

```
=== language null, title given: HTTP 200 ===
    [{"message": "unexpected null value for type 'String'",
      "extensions": {"path": "$.selectionSet.editions.args.where.language.code2._eq"}}]
=== language de, title given: HTTP 200 ===  0 editions
=== no titles at all: HTTP 200 ===          0 editions
```

`editions.language.code2` is not nullable, so `_eq: null` is a validation
failure rather than "match everything": a file that names no language has to be
asked about **without** the language filter, which is why the client carries two
versions of the query. A language with no editions returns an empty list, as an
ISBN that no edition carries does.

### 3. Author and language filters

```
{book: {title: {_eq: "Cragside"}, contributions: {author: {name: {_eq: "L.J. Ross"}}}}}
    -> 2 editions, work 1198994
{book: {title: {_eq: "Cragside"}, contributions: {author: {name: {_eq: "Ross"}}}}}
    -> 0 editions
{book: {title: {_eq: "Cragside"}}, language: {code2: {_eq: "en"}}}
    -> 1 edition, work 1198994
{book: {title: {_eq: "Cragside"}}, language: {code2: {_eq: "de"}}}
    -> 0 editions
```

Author `_eq` needs the **full** name as Hardcover spells it (`L.J. Ross`, not
`Ross`), so a surname-only filter silently returns nothing. That makes it a poor
server-side filter and a good reason to filter and score authors in Python
instead — which is where "normalised for comparison only" has to happen anyway.

The language filter works on the **edition**, and `editions.language.code2` is
the field. This is how "searched in their own language, nothing translated" can
be enforced: constrain the query, and score language agreement in Python.

### 4. The `search` root field is a dead end here

Worth recording, because CWA uses it and the spec's failure cases came from it.
It answers, and it does reproduce the bug:

| Query | Hits | Top hit |
| --- | --- | --- |
| `Cragside` | 2 | *Cragside* (L.J. Ross) — then *Cragside: A 1930s murder mystery* (M.J. Porter) |
| `Cragside L.J. Ross` | 1 | *Cragside*, correct |
| `Berwick L.J. Ross` | 1 | *Berwick*, correct |
| `Belsay L.J. Ross` | 1 | *Belsay*, correct |
| `Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6) LJ Ross` | 1 | **`Cragside: A 1930s murder mystery`, M.J. Porter — the wrong book** |

That last row is CWA's failure reproduced exactly: the raw title query returns
only the lookalike, which is why cleaning the query is the whole fix.

But it is not usable as Colophon's candidate source:

- **`per_page` truncates hard.** `L.J. Ross` with `per_page: 5` returned exactly
  5 hits; `per_page: 10` on the three titles returned 1–2. There is no
  candidate *set* to score — title+author queries collapse to a single hit.
- **No language filter.** The schema documents `query` as the only parameter.
- **`score` is not in the reply.** The hits carry title, authors, series, isbns,
  slug and counts, but every hit's `score` key is absent — there is nothing to
  map onto a 0.85 confidence.
- **`results` is untyped `jsonb`**, the caveat already in
  `hardcover-api.md` Unknown #10.

**Recommendation: use the typed `editions` query, not `search`.** It returns
rows the existing `_as_book()` already parses.

### 5. Two facts that make one query enough

```
search document id=1198994, title "Cragside", isbns ["1521748837","9781521748831"]
shipped ISBN query for 9781521748831 -> edition_id=31223802 work_id=1198994
editions(where: {book_id: {_eq: 1198994}}) -> edition 31403503 (lang None),
                                              edition 31223802 (lang "en")
```

`search.results.hits[].document.id` **is** `books.id` — the two agree at
1198994 — and `editions.book_id` is filterable. So a title match can be one
query against `editions` with the work constraints in the `where`, rather than
searching and then re-fetching the work. `editions.book_id` `_eq` works.

### 6. The lookalike already falls out, which weakens that criterion

The spec's lookalike is *Cragside: A 1930s murder mystery* by M.J. Porter, and
its **work title is the full messy string**. Asking for
`{title: {_eq: "Cragside"}}` therefore never returns it:

```
{book: {title: {_eq: "Cragside"}}}                        -> work 1198994 only
{book: {title: {_eq: "Cragside: A 1930s murder mystery"}}} -> work 2335610, M.J. Porter
```

So on the exact-title path the lookalike is excluded by title equality before
any scoring happens, and CBO-36's "a lookalike is not accepted" is satisfied
vacuously. **A fixture built only on Porter's book would pass even if the author
scoring did nothing.** The lookalike fixture should be a *different book by the
same author* instead — e.g. *The Infirmary* (work 1198266, DCI Ryan #11), which
also has to be rejected, and which only the author/title comparison can reject.
Ask for that explicitly when the fixture is built.

## The open question: how a title+author comparison becomes a confidence

*(Answered below. The question is kept because the answer is a decision rather
than a deduction, and this is where the evidence for it lives.)*

The threshold is settled in CBO-33 pipeline step 6 — **apply at ≥ 0.85,
adjustable**. What is *not* in the spec is how the comparison produces a number.
That is the design work for this ticket, and it is the one thing to bring back
for a decision rather than settle alone, because it changes behaviour users see.

The single candidate sets above make one thing clear: **author agreement is
load-bearing.** With exact-title querying the candidate set is usually one
work, so title similarity is near-constant and the score is effectively decided
by whether the author matches. A rule that accepts on a title match alone would
carry a 0.85 with the author never checked, which cannot be right.

Worth deciding, with evidence, before implementing:

- the title score (exact / normalised-equal / similar-but-not-equal)
- the author score, given the file may carry several creators and spellings
  differ (`L. J. Ross` vs `L.J. Ross`, and `Ross, LJ` in
  `samplebooks.TWO_CREATORS`)
- how the two combine, and what happens when the file carries **no** author
- what a missing or unmatched language does to the score

"Adjustable via config" is the *threshold*, and CBO-39 owns the unverified path
and the config key: CBO-36 produces the confidence and adds no config for it.

### The rule CBO-36 built, with the numbers behind it

Settled by the direct instruction that a title match alone must never reach the
threshold. Built as proposed, minus the edit distance:

```
confidence = 0.6 * title_score + 0.4 * author_score
title_score  = 1.0   the cleaned titles are equal after normalising
             = 0.9   one normalised title is contained in the other, whole words
             = 0.0   otherwise
author_score = 1.0   any file creator normalises to any record author, in either
                     order, so `L. J. Ross` = `L.J. Ross` = `Ross, LJ`
             = 0.0   otherwise, including when either side names nobody
```

The weights are what make the instruction hold arithmetically: a perfect title
with no author agreement scores **0.6**, and an author agreement with no title
scores **0.4**, so no single half can clear 0.85. A candidate that does not
agree on both is also refused outright (`agrees`), so the number is never the
only thing standing between a wrong book and someone's library.

A candidate in another language is left out entirely rather than scored down —
non-English books are matched in their own language and nothing is translated.
A language missing on either side is no evidence either way. The language is
also the query's filter, so this is the second line of the same defence.

Every real candidate, scored with the recorded replies, against 0.85:

| file's title | candidate | title | author | confidence | 0.85 |
| --- | --- | --- | --- | --- | --- |
| Cragside (messy) | Cragside, L.J. Ross | 1.0 | 1.0 | **1.00** | accepted |
| Berwick (messy) | Berwick, L.J. Ross | 1.0 | 1.0 | **1.00** | accepted |
| Belsay (`: A … Mystery` only) | Belsay, L.J. Ross | 1.0 | 1.0 | **1.00** | accepted |
| Cragside (messy) | The Infirmary, L.J. Ross | 0.0 | 1.0 | 0.40 | rejected |
| Cragside (messy) | The Infirmary, Carly Reagon | 0.0 | 0.0 | 0.00 | rejected |
| The Infirmary (messy) | The Infirmary, Carly Reagon | 1.0 | 0.0 | 0.60 | rejected |
| Cragside (messy), no author in the file | Cragside, L.J. Ross | 1.0 | 0.0 | 0.60 | rejected |
| Cragside (clean) | *Cragside: A DCI Ryan Mystery* on the record | 0.9 | 1.0 | **0.94** | accepted |

**The three real books clear 0.85 because the candidate set is one work and the
author then agrees** — title equality is doing no discriminating work there at
all, which is the finding this note asked for. The score earns its keep in the
other direction: it is what rejects *The Infirmary* by the same author (0.40),
what rejects the same title by another author (0.60), and what still accepts a
record that kept its subtitle (0.94).

The edit-distance decay in the proposal was dropped. With exact-title querying
it can never fire — a candidate too differently spelt to score 1.0 is never
returned — so it would be a branch no fixture could reach. A title that is
neither equal nor contained is 0.0, which is the honest answer to "the query
never found it".


## What else to know before building

*(Kept as written for the session that did the building; what actually happened
is in the "As built" section at the end.)*

- **`tests/tempdir.py`** exists (added in CBO-35) so tests can write real files.
- **Fixtures for this ticket do not exist yet.** `tests/samplebooks.py` has
  `AS_DOWNLOADED` for Cragside *with* an ISBN; CBO-36's books have **no** ISBN,
  so new metadata blocks are needed. `write_epub()` takes a metadata string, and
  `add_isbn()` is only for the ISBN path — do not use it here.
- **`tests/fixtures/hardcover/by-isbn-*.json` deliberately omit `id`**, which is
  why `_as_book()` never reads one: the point of that fixture is the nullability
  of `books.title`. Either omit `id` from the new recordings for consistency, or
  add it and state the change in the PR. Prefer omitting — CBO-36's criteria do
  not require capturing the matched edition's ISBN.
- `hardcover.py`'s `QUERY` does **not** request `subtitle`, and the research doc
  shows it exists on both `books` and `editions`. If subtitle-aware behaviour is
  wanted, that is a query change to call out in the PR.
- `tests/sources.py:FakeSource` answers `by_isbn` only. A title lookup needs its
  seam extended — that is the natural place for the new fixture wiring.
- No `CONTEXT.md` exists in this repo yet, though `AGENTS.md` says there should
  be one. Worth raising separately; out of scope for this ticket.

## As built (2026-09-19)

The slices were built in the order below; everything in this note that was a
question above is answered in place, and the rest is here.

1. **`colophon/matching.py`** — new. `clean_title()`, `title_variants()`,
   `normalise()`, `compared()`, `best_candidate()`, and the `FileBook`,
   `Candidate` and `Match` types. The cleaning and the comparison live here
   rather than in the client, so neither needs a network to test.
2. **`colophon/hardcover.py`** — a second query, `TITLE_QUERY`, and
   `by_title(titles, language)`, which returns `Candidate`s with the work's
   first edition per `books.id`. `by_isbn` is untouched.
3. **`colophon/correction.py`** — `Corrector.correct()` splits into `_by_isbn`
   and `_by_title`; the ISBN path behaves exactly as it did, including the
   confidence of 1.0. `Outcome` gained `sought`, the title a book with no ISBN
   was recognised by, because the log line said `matched ISBN None` otherwise.
   The one line per book now reads
   `hardcover matched Cragside by title and author, confidence 1.00`.
4. **Fixtures** — `by-title-{cragside,berwick,belsay,the-infirmary}.json`, real
   replies for one cleaned title each, exactly the request the client sends.
   They keep `books.id`, unlike the ISBN recordings: the client needs it to
   return one candidate per work, and that is a stated change to the fixture
   convention in `tests/fixtures/hardcover/README.md`.
5. **`tests/samplebooks.py`** — `CRAGSIDE`, `BERWICK`, `BELSAY`,
   `THE_INFIRMARY`, `WITHOUT_AUTHOR` and `WITHOUT_AUTHOR_OR_LANGUAGE`, the same
   files with no ISBN in them.
6. **Tests** — `tests/test_matching.py` (28), `TitleLookupTests` in
   `tests/test_hardcover.py`, and `BooksWithoutAnIsbnTests` in
   `tests/test_correction.py`, plus the relay's one-line log.

Two things worth knowing about what was found on the way:

- **`The Infirmary` is not a lookalike for `The Infirmary`.** Running the real
  client over a file whose title is *The Infirmary: A DCI Ryan Mystery* accepts
  it, correctly: the file names the book, and the record agrees on title and
  author. The lookalike this ticket names is the same author's *other* book, so
  the fixture that rejects is a `Cragside` file offered `The Infirmary`
  candidate, which is what `test_the_lookalike_is_not_accepted_for_any_of_them`
  does. The Porter book is rejected by title equality without any scoring, as
  §6 above said it would be.
- **`The Infirmary` also exists as a real book by Carly Reagon** (work 2284109),
  in the recording, with exactly the same title. It is the case that proves
  author agreement is what carries the comparison: same title, 0.60, rejected.

