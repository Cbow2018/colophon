# CBO-42: Genre mapping

**For the session that builds CBO-42.** Written 2026-09-20, after probing
Hardcover, Google Books and DeepSeek with the project's own keys. Everything
under "Verified against the live APIs" is a captured reply, not a reconstruction.
The probe scripts and their raw replies were in `.tmp/cbo42/` (excluded, not
committed); every claim this note rests on is committed as a fixture under
`tests/fixtures/` and named in "Fixtures this session recorded".

Read with `../../AGENTS.md`, `../agents/issue-tracker.md` and the ticket
[CBO-42](https://linear.app/cbow/issue/CBO-42/09-genre-mapping), whose parent is
the design spec
[CBO-33](https://linear.app/cbow/issue/CBO-33/colophon-ebook-metadata-relay-design-spec-v1).

## Where the work sits

CBO-42's two blockers are **CBO-40** (07 LLM fallback chooser, PR #11) and
**CBO-41** (08 Colophon's own record, PR #12), and **both are Done and merged
into `main`**, verified against Linear on 2026-09-20. Nothing blocks this ticket.

Branch: `dsh/cbo-42-genre-mapping`. Linear suggests
`callumbowden111/cbo-42-09-genre-mapping`; the standing rule in `~/.dsh/AGENTS.md`
is `dsh/<short-topic>`, so the shorter one won. Say so in the PR description.

### What the ticket asks for, in the code's terms

| Acceptance criterion | Where it lands |
| --- | --- |
| Allowed-genres list in `config.toml`, added to by Colophon's own record over time | a top-level `allowed_genres` array read by `config.py`; what the record adds over time is the **mapping** vocabulary, not the list — see Q4 |
| The LLM maps each source genre onto the allowed list (a judgement task; it doesn't supply facts) | one `Llm` call per source genre, reusing `llm.py`'s transport and `_spend()` |
| Genres that don't fit are dropped; no new tags are created | a `null` from the model, an off-list target, and a truncated reply all drop; the config's spelling is the only one ever written |
| Counts toward the daily LLM call limit | the same `_spend()` the chooser uses; no second counter |
| Tests (recorded replies): messy Hardcover genres map to the allowed list; an unmappable genre is dropped | see "Tests this note implies" |

## Verified against the live APIs

Probed 2026-09-20. Each recorded fixture is the reply to the **shipped request
shape plus the one field this ticket adds**, so a test can replay it through the
real client rather than through a hand-built stub. Bodies are the API's own,
re-indented for a diff, the way `tests/fixtures/*/README.md` requires.

### 1. Both sources carry genres, and both are messy

Hardcover keeps community tags in `books.cached_tags`, reached from a work, and
it is the only place genres exist there. The row behind *Cragside*, from
`by-isbn-9781521748831-genres.json`:

```json
{"book": {"id": 1198994, "title": "Cragside",
 "cached_tags": {
   "Tag": [],
   "Mood": [{"tag": "dark", "count": 1, "tagSlug": "dark", "category": "Mood", "categorySlug": "mood", "spoilerRatio": 0.0}, ...],
   "Genre": [{"tag": "Murder", "count": 1, "tagSlug": "murder", "category": "Genre", "categorySlug": "genre", "spoilerRatio": 0.0},
             {"tag": "Crime", ...}, {"tag": "Thriller", ...}, {"tag": "Mystery", ...}],
   "Content Warning": []}}}
```

`Tag`, `Mood` and `Content Warning` are the same shape and are **not genres**.
`categorySlug` on each entry and `tag_category_id` on each `taggings` row both
name the category, and `tag_categories` says what the numbers are:

```
=== tag-categories: HTTP 200 ===
{"tag_categories": [{"id": 1, "category": "Genre"}, {"id": 2, "category": "Tag"},
                    {"id": 3, "category": "Content Warning"}, {"id": 4, "category": "Mood"},
                    {"id": 37, "category": "Pace"}, {"id": 70, "category": "Easiness"},
                    {"id": 71, "category": "Queer"}, {"id": 72, "category": "Member"},
                    {"id": 73, "category": "note"}, {"id": 74, "category": "quote"},
                    {"id": 75, "category": "annotation"}, {"id": 76, "category": "highlight"},
                    {"id": 77, "category": "general"}, {"id": 78, "category": ""},
                    {"id": 79, "category": "Group"}]}
```

So "genre" is a real subset and not a name for all tags, and `cached_tags.Genre`
is the field to read — one key, already separated. Reading `taggings` instead
would mean filtering `tag_category_id = 1` and correcting for the community tags
the cache has not seen.

Three books, each its own recording:

| Fixture | Book | ISBN | `cached_tags.Genre` |
| --- | --- | --- | --- |
| `by-isbn-9781521748831-genres.json` | *Cragside* | 9781521748831 | `Murder`, `Crime`, `Thriller`, `Mystery` |
| `by-isbn-9781799729945-genres.json` | *The Infirmary* | 9781799729945 | `Thriller`, `Crime`, `Suspense`, `Mystery` |
| `by-isbn-9781529978940-genres.json` | *Berwick* | 9781529978940 | **`Fiction`** |

**This is the ticket's whole reason for existing, in one table.** Four genres on
*Cragside*, three of which are synonyms for one shelf label — a library that
wrote them straight would collect `Murder`, `Crime`, `Thriller` and `Mystery` as
four tags for one kind of book, and *The Infirmary* would add `Suspense` as a
fifth. And *Berwick*'s single genre is `Fiction`, which is not a genre a crime
shelf wants at all.

The mess is not limited to synonyms. `by-isbn-9780575064843-packed-genres.json`
is *Pyramids*, whose ten Genre tags are:

```
['Fantasy', 'Adventure', 'Science Fiction', 'General', 'Humor', 'Humour',
 'Fantasy:Humour', 'Satire', 'Science Fiction & Fantasy', 'Comedy & Humor']
```

Three separate problems in one real record: **a BISAC path packed into one
string** (`Fantasy:Humour`), **`Humor` and `Humour` as two entries**, and
**`Science Fiction & Fantasy` as a third spelling of two things already listed**.
`by-isbn-9781529196382-packed-genres.json` is *The Trial*, whose three are
`['Mystery', 'Thriller & Suspense:Crime Fiction', 'Fiction']` — the colon-packed
shape again, this time as a path whose leaf is a genre already present as a
separate entry.

Two more things the replies settled:

- **A book can have no genres and still exist.** Seventeen of the twenty-five
  *Good Omens* works read during this probe carried `"Genre": []`. An empty
  genre list is ordinary, not an error.
- **An ISBN Hardcover does not have** (`9781473225374`) answers with
  `{"data": {"editions": []}}`, recorded as
  `by-isbn-9781473225374-genres.json`, so "no genres" and "no book" are two
  different empties and a client must handle both.

A semicolon-packed genre (`Classics; Fantasy; Horror` as one string) was seen in
the same probe and **is not in the fixtures**: the works carrying it have no
ISBNs on their editions, and reaching one through the title query costs a
120 KB-plus reply of unrelated editions. The split rule is one line of code and
is pinned by a unit test on the string rather than by a recorded reply; this is
the one claim in this note backed by a probe log rather than by a fixture.

### 2. Google Books carries categories, but the shipped mask no longer asks

The existing `tests/fixtures/googlebooks/by-title-cragside.json` (recorded
before CBO-37 widened the mask) **already contains** `categories`, and its two
volumes are the ticket's two cases in one file:

```
7kMMzgEACAAJ '*Cragside*' -> categories: ['Finlay-Ryan, Maxwell (Fictitious character)']
RASDtAEACAAJ '*Cragside*' -> categories: ['Murder']
```

One is a library subject heading — a character, not a genre — and the live model
correctly refused it (§3). The other is a genre. **The current `FIELDS` mask
returns neither**: asked live, it comes back with `categories` absent, because
the mask enumerates fields and `items/volumeInfo/categories` is not among them.
So adding it is a real change to what Google is asked for, and it makes those two
existing values readable again. Recorded as
`googlebooks/isbn-cragside-categories.json` (the shipped ISBN request with
`items/volumeInfo/categories` appended).

Two things from the same probe that the genre path inherits rather than causes:
Google's ISBN query is a relevance search, so `isbn:9781799729945` answered with
**no item at all** (`{"totalItems": 0}`) and `isbn:9781529978940` answered with a
volume titled *Raby*. `googlebooks.by_isbn` already filters by identifier and
returns nothing when nothing carries the ISBN, so a book Google cannot confirm
has no genres to map — the existing behaviour is the correct behaviour here.

### 3. The batch prompt shape is unsafe, and it failed on real data

Probed with the project's own key, the same endpoint, and the same request shape
`llm.py` sends (`deepseek-flash`, `response_format: {"type": "json_object"}`, no
`temperature`, `max_tokens: 256`). Two prompt shapes were measured: one that
answers **all** of a book's genres in a single object, and one that answers a
**single** genre.

The single-genre shape, seven calls — every one of them `finish_reason: stop`:

| Fixture | allowed list | source genre | completion | reasoning | answer |
| --- | --- | --- | --- | --- | --- |
| `genre-mapping-murder.json` | the six-genre user list | `Murder` | 62 | 38 | `Crime` |
| `genre-mapping-case.json` | the same | `crime` | 56 | 28 | `Crime` |
| `genre-mapping-packed.json` | the same | `Fantasy:Humour` | 55 | 28 | `Fantasy` |
| `genre-mapping-fiction.json` | the same | `Fiction` | 49 | 21 | `null` |
| `genre-mapping-synagogues.json` | the same | `Synagogues` | 79 | 48 | `null` |
| `genre-mapping-unmappable.json` | the same | `Finlay-Ryan, Maxwell (Fictitious character)` | 97 | 76 | `null` |
| `genre-mapping-empty-allowed.json` | `[]` | `Murder` | 40 | 15 | `null` |

The batch shape, measured twice — and it is **unreliable at four genres, which is
one ordinary book's worth**. Five runs of the identical four-genre request:

| Run | completion | reasoning | `finish_reason` | content |
| --- | --- | --- | --- | --- |
| 1 | 179 | 68 | `stop` | all four mapped |
| 2 | **256** | **256** | **`length`** | **empty** |
| 3 | 221 | 108 | `stop` | all four mapped |
| 4 | **256** | **146** | **`length`** | partial JSON, discarded |
| 5 | 168 | 56 | `stop` | all four mapped |

And three runs of a six-genre list, which is the size *Good Omens* and *Pyramids*
actually reach: **all three hit 256 tokens and `finish_reason: length`**, one with
an empty body and two with truncated JSON.

**Two of five runs losing every genre, at four genres, is the finding.** CBO-40's
rule treats `finish_reason: length` as a `null`, which for the chooser means one
book takes the unverified path; for a batch of genres it means a book silently
gets none, with nothing in the log to say the model was asked. The recorded
`genre-mapping-batch.json` is one of those truncated replies — partial JSON with
`finish_reason: length` — and `genre-mapping-truncated.json` is the empty-content
case, which is what a list sharing no vocabulary with the allowed list produces.
This is the same failure CBO-41 measured on the name-variant job, from a
different direction.

**A correction, recorded because a number in a note is what the next session
trusts:** an earlier draft of this note quoted the four-genre batch as
"249 of 256 tokens", from a single run. A second run of the same request answered
in 128. The cost is not a fixed figure, it is a **distribution that straddles the
cap**, and the honest statement is the table above rather than one lucky sample.
The conclusion the first number supported is the right one; the number was not.

What the per-genre probes also settle: `Murder → Crime` when the allowed list
holds both `Murder` and `Crime` is the model choosing the nearer *allowed* word
rather than echoing the source — the judgement the ticket is buying, not a bug.
An **empty allowed list is a valid state** (`[]`, a fresh install) and answers
`null` rather than failing, and the unmappable cases answer `null` **confidently**
rather than inventing a nearby genre, which is what makes "no new tags are
created" achievable at all.

### 4. What the code already has, and what it does not

Checked in the tree rather than assumed:

- **`Candidate` carries `author_ids` and `series_id`** (`matching.py`), added by
  CBO-41 for the same reason: what a source returned travels beside the values it
  belongs to. `genres` joins them; no second parallel type is needed.
- **`Candidate` already carries the source name**, as `source: str | None`, and
  its own docstring says what it is for: "names where it came from, so a candidate
  can be written into a file without anything else having to remember who offered
  it." So the cache key `(source, genre)` needs **no new field** — decision 1 adds
  only `genres`, and the source half of the key is read off the candidate that
  already has it. Nothing in this ticket reads `source` for any other purpose, and
  the record's `genres.source` column is written from this same field.
- **Neither shipped query asks for genres.** `hardcover.QUERY` and
  `hardcover.TITLE_QUERY` ask for `contributions` and `book_series` but not
  `cached_tags`, and `googlebooks.FIELDS` has no `categories`. Both are query
  changes this ticket needs.
- **Nothing reads or writes a book's subjects except the unverified tag.**
  `epub.Book` has no field for them, `read()` does not collect them, and
  `_set_unverified_tag` is explicit that "the book's own subjects are not touched
  either way". Genres become the second writer of `dc:subject`, which is why
  Q5's add-only rule is load-bearing rather than tidy.
- **`record.genres` exists and nothing writes it.** CBO-41's schema has
  `CREATE TABLE genres (genre TEXT PRIMARY KEY)` and its `reset()` deletes from
  it; the column set is not what this ticket needs (§"The schema change").
- **A book nothing matched never asks the LLM.** `_ask_llm` is reached only from
  a path that had candidates, so an unmatched book has no source genres and genre
  mapping cannot run for it. Nothing has to be arranged for that.
- **`_ask_llm` already treats "cannot ask" as a wait.** `LlmError` and
  `LlmLimited` both go to `_wait`, which leaves the file untouched in the ingest
  folder for the next UTC day, and the waiting list stops the same question being
  re-asked today. Genre mapping inherits that unchanged, which is what makes
  "counts toward the daily limit" safe to reuse.

## The grilling

Every question below was put to the maintainer before any code was written, with
the answers as given. They are decisions. The ones that override what the
ticket's or the spec's wording implies are flagged.

### Round 1 — where genres come from, and what maps them

**Q1. What counts as a source genre?** → **Both sources, and the packed forms are
split.** Hardcover's `cached_tags.Genre` and Google's `categories` are both read,
and both are fetched in the shipped queries. `Fiction` is deliberately *not*
filtered out by a rule of Colophon's own — deciding what is a genre is the
judgement the LLM is being paid for, and the probe shows it answers `null`
correctly for `Fiction` and for a character heading.

**Q2. One call per book, or one per genre?** → **One call per source genre, with
a cache added by the maintainer**: "a source genre maps to the same allowed genre
every time, so store the mapping in the record ... Each distinct genre then costs
one call ever, not one per book. Your genre vocabulary saturates after a few
dozen books and the spend drops to near zero — which removes the whole objection
to per-genre calls." The batch shape was not merely more expensive; §3 shows it
failing outright.

**Q3. Dedupe, order, and an off-list target?** → **Dedupe, keep the source's
order, drop anything not on the allowed list.** With one addition: match a target
against the allowed list **case-insensitively and trimmed, and write the config's
exact spelling** — a config saying `Crime` and a model answering `crime` write
`Crime`. An off-list target is treated exactly like a `null`, which is what makes
"no new tags are created" true by construction rather than by trusting the model.

### Round 2 — the cache, and where the list lives

**Q4. Where does the allowed list come from, and may the record add to it?** →
**The config is the sole source of allowed genres; the record stores only the
source→allowed mappings.** The maintainer rejected the union this note first
proposed, and the reason is the one to record: "If the record only mirrors
config, config ∪ record is just config, so the union adds a concept that does
nothing." The spec's "added to by Colophon's own record over time" is satisfied
by what actually grows — the **mapping vocabulary**, which is what makes the
second and later books free — and the note records the rewording rather than
leaving the sentence to be re-read.

*Consequence, stated plainly so it is not discovered later:* removing a genre from
`config.toml` stops it being **written** on the next book, and does **not** rewrite
books already delivered. That is the same line CBO-41 drew for the record
("fixing an existing library" is out of scope for v1), and it is also why positive
cache rows survive a config edit — they are re-validated when read (Q7).

**Q5. Does CBO-42 write genres, and under what rule?** → **Write, add-only to
`dc:subject`, never removing the book's own subjects.** Two reasons, and the
maintainer supplied the second: the `colophon:*` tags live in `dc:subject` too,
so anything that replaced subjects would eat them. This is the **one field outside
the `skip`/`fill`/`overwrite` system**, and the example config says so. A genre
the book already carries is not written again, **compared case- and
space-insensitively** — `Crime` beside the book's own `crime` is the same
near-duplicate problem in miniature — while the spelling already in the file is
what stays: the config's spelling is what is added, and nothing rewrites an
element that is already there.

### Round 3 — the cache's failure modes

**Q6. Are `null` outcomes cached?** → **Yes, and invalidated when the allowed list
changes**, because a null is relative to the list: add `True Crime` to
`config.toml` and every source genre cached as null should be askable again, or
the config change silently does nothing for them. A positive target is not
relative in the same way — it goes through the same off-list filter a fresh
answer does (Q7).

**Q7. How is that invalidation built?** → **A fingerprint of the normalised
allowed list** (sorted, case-folded, trimmed) and nothing else, so *reordering or
re-casing* an entry does not wipe the null cache for no reason. Fingerprinting the
hits was dropped in favour of something better: **validate a positive cache hit
against the current allowed list when it is read**, and treat a target that is no
longer allowed as a *miss* and re-ask. That handles genre removal for free and
keeps the fingerprint doing one job.

**Q8. The sweep breaks a dry run** (the maintainer's correction to this note's
first Q9): "Deleting null rows on load is a database write, and the spec says a
dry run logs changes without writing anything. As written, a dry run mutates the
record. Skip the invalidation sweep when dry run is on — the fingerprint just
doesn't get rewritten, and the next real run does the sweep." Decided: the sweep
is driven by the caller, not by `Record.open`, and a dry run skips it entirely.

**Q9. A run's mappings need a memo** (the maintainer's correction to Q10):
persisting at `copy_into_place` is right, but between the call and the landing
there is no record of the mapping, so "30 books carrying 'Crime Fiction' in one
run ask 30 times, and a run where nothing lands (source unavailable, key
rejected) pays the full cost and learns nothing." Decided: **a plain dict on the
corrector's run**, checked before the cache and written to after it, so one run
asks each `(source, genre)` once whatever the database says. One dict, no new
write point.

**Q10. What a dry run reports** (the maintainer's correction to Q11): "'reports
what would be added' and 'spends no call' can't both be true. No calls means
uncached genres have no mapping to report. Don't let that surface as a book with
no genres, which reads as a bug." Decided: **a dry run uses the cache where it
hits and logs an uncached genre explicitly as not asked**, so the no-call rule
stands and the preview is honest about what it does not know.

## Decisions taken by me, for review

These are the calls I made rather than asked about. Each is here so it can be
overturned in review.

1. **Genres travel on `Candidate`** as `genres: tuple = ()`, exactly as CBO-41 put
   `author_ids` and `series_id` there: they are what the source returned, the
   corrector already passes the candidate around, and a second parallel type
   carrying the same record's other fields would be a second thing to keep in
   step. Every `Candidate` field a rule may write stays as it is — genres are
   carried, and applied by their own path.
2. **The split happens in the source modules, once.** `hardcover._genres(book)`
   reads `cached_tags.Genre` and splits each tag on `:` and `;`;
   `googlebooks` does the same to `categories`. One place per source decides what
   a genre string is, so the prompt and the cache key cannot disagree about it.
   Splitting keeps the words in order and drops empties, so `Classics; Fantasy;
  Horror` is three genres and `Fantasy:Humour` is two. **The unsplit string is
  kept for the cache's `seen` column**, and only the parts are asked about — see
  "What `seen` holds when two strings collide" for which string that is when more
  than one produces the same genre.
3. **Google's mask gains `items/volumeInfo/categories`**, and Hardcover's two
   queries gain `cached_tags` — asked whole, because a jsonb column's inner keys
   are not selectable one at a time. **This is a stated change to fixtures**, the
   way CBO-36's and CBO-41's notes stated theirs: the eleven ISBN recordings and
   the title recordings made before this ask for no genres, so `_genres` must
   treat a missing `cached_tags` as **absent rather than as a bug**. New
   recordings carry it.
4. **A `[fields]` entry for genres was rejected.** `KNOWN_FIELDS` is built from
   `FIELD_DEFAULTS` and `_edits` reads every one of them with
   `getattr(found, name, None)`, so adding `genres` there would give it a rule
   that none of `skip`/`fill`/`overwrite` can express: `fill` is judged against
   the file and a book carrying any subject would get none at all, while
   `overwrite` would eat the book's own tags and the `colophon:*` marks. Genres
   are therefore an `Edits` field of their own, like `drop_series_number` and
   `notes_taken_off`, and the example config documents it as the one field
   outside the rule system.
5. **`Epub.Book` learns the file's own subjects.** `read()` collects every
   `dc:subject` except the `colophon:*` ones, so "add only" has something to
   compare against. Without it, "the book already has this genre" is unknowable.
6. **The write is `_set_genres`, beside `_set_unverified_tag`, and it inherits
   that function's discipline**: it adds the genres that are not already there,
   in order, and reports whether anything moved, so a re-dropped file is not
   rewritten and a second pass reports nothing. It never removes an element.
7. **The prompt is the same shape as the chooser's, with this ticket's contract
   and the chooser's own data-not-instructions clause.** One system prompt is
   built once (`GENRE_SYSTEM_PROMPT`), one `Llm` method is added
   (`Llm.map_genre(allowed, source_genre)`), and it reuses `_post_json`,
   `_refuse`, `_spend` and `_without_key` unchanged. `map_genre` returns the
   target string or `None`, and **a raised `LlmError` is reserved for "could not
   be asked"** — unreachable, refused, rate-limited — which leaves the book
   waiting by CBO-40's existing rule. Every bad *answer* (a `null`, an off-list
   target, a malformed body, a truncated reply) is a plain `None`, which drops the
   genre. The distinction that matters is the log line: "the model said no" and
   "the model could not be asked" must not read the same.
8. **The daily counter is not touched.** `_spend()` is called by `map_genre` the
   same way `choose` calls it, so "counts toward the daily LLM call limit" is the
   existing mechanism rather than a second one, and `llm_daily_limit` keeps its
   shipped default of 200. With the cache and the run memo that default is no
   longer a throughput ceiling: a first pass over a library spends roughly one
   call per distinct source genre, and every later pass spends nothing.
9. **`record.genres` is rebuilt into a mapping table, and `SCHEMA_VERSION` goes
   to 2.** The table CBO-41 left is a single `genre TEXT PRIMARY KEY` column,
   which cannot hold a source, a target or a negative outcome. It is empty in
   every real database (nothing ever wrote it), so the migration is a
   `DROP TABLE IF EXISTS genres` followed by the new `CREATE`, and the version
   guard CBO-41 built is what makes that a step rather than an ad-hoc `ALTER`.
   **The `drop` is safe only because the table is provably unwritten** — assert
   that before writing the migration, and if a row ever does exist, migrate rather
   than drop.

   *Overridden when CBO-42 was built:* the migration drops the version-1 table
   unconditionally, with no row count read first. The check was for a state
   nothing could have produced — version 1 shipped `CREATE TABLE genres (genre
   TEXT PRIMARY KEY)`, `reset()` deleted from it, and no code path in any shipped
   version ever inserted into it — so the guard would have been code that can
   never run, and a `RecordError` would have refused to start on a real database
   over a table its owner never wrote. The reasoning is recorded in `record.py`
   where the migration is, next to the `DROP`.
10. **The mapping is persisted at the one existing write point.** It travels on
    `Decision` beside the match and the resolutions, and the relay persists it
    after `copy_into_place` succeeds, so a book that never landed teaches nothing
    and there is still exactly one place that writes the record. This keeps
    CBO-41's review decision intact rather than adding a second save site.
11. **The allowed list is a top-level `allowed_genres = [...]` array**, so
    `COLOPHON_ALLOWED_GENRES` works like every other setting, and it is validated
    the way `[authors]` is: a non-list, a non-string entry and an empty entry are
    a `ConfigError`, and **two entries that normalise to the same genre with
    different spellings are a `ConfigError` too** — `["Crime", "crime"]` is one
    genre with two spellings, and TOML gives no order to appeal to. This reuses
    the reasoning `_to_authors` already records.
12. **An empty `allowed_genres` is valid and is how genres are turned off**, and
    the example config says so. It is also a fresh install's state: every genre
    maps to `null`, nothing is written, and **no LLM call is made at all** — with
    no list there is no question to ask, so the mapping step returns before
    `_spend()`.

## The build shape

### The schema change

`SCHEMA_VERSION` becomes 2 and one table becomes a mapping. `names` and `matches`
are untouched.

```sql
-- What a source's genre was judged to mean.
-- The row is upserted: `mapped` is replaced with a fresh answer, `seen` is not.
CREATE TABLE genres (
    source  TEXT NOT NULL,   -- which source's vocabulary the string came from
    genre   TEXT NOT NULL,   -- the source's own string, split and trimmed
    mapped  TEXT NOT NULL,   -- the allowed genre written, or '' for "does not fit"
    seen    TEXT NOT NULL,   -- the first unsplit string this key came out of
    PRIMARY KEY (source, genre)
);

-- One row: the allowed list the nulls above were answered against.
-- The CHECK is the point: without it this table accumulates a row per sweep,
-- and "the fingerprint" stops meaning anything.
CREATE TABLE genre_list (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    fingerprint TEXT NOT NULL
);
```

**Why `mapped` is `''` and not `NULL`.** SQLite does not treat two nulls as equal
in a primary key comparison, so a null target would be both unfindable and
unwritable twice; an empty string is a real value, sorts predictably, and cannot
be confused with a genre because no genre trims to nothing (decision 11 refuses
one).

**Why `source` is in the key.** The same word can arrive from two vocabularies
and mean two things, and keying on the string alone would let one source's answer
silently answer for the other. It is one more column, filled from the
`Candidate.source` the candidate already carries (§4).

**Why `seen` exists.** It is the only record of what the source actually wrote,
the same role `names.seen` plays for a spelling: it is what a person looks at when
they wonder why their book says `Crime` and not `Murder`.

#### What `seen` holds when two strings collide

Nothing about a genre string is unique to the genre: `Fantasy` arrives on its own
from *Pyramids* and again as one half of `Fantasy:Humour` from the same record, and
**both split to the key `Fantasy`**, so `PRIMARY KEY (source, genre)` gives them
**one row**. The key is the split part, `seen` only records where it came from, and a
collision must not be allowed to mean two answers to one question.

**The first unsplit string wins; the answer is always the current one.**

```
INSERT INTO genres (source, genre, mapped, seen) VALUES (?, ?, ?, ?)
ON CONFLICT (source, genre) DO UPDATE SET mapped = excluded.mapped
```

The upsert touches **`mapped` only, never `seen`**:

- **`seen` is first-write-wins**, because it is provenance and the second string is
  not a better account of where the key came from. So a book whose only genre is
  `Fantasy` records `(hardcover, 'Fantasy', <target>, seen='Fantasy')`, and the
  `Fantasy:Humour` record's `Fantasy` half leaves `seen` as it was — while still
  adding its own `Humour` row, because that key is new. `Fantasy:Humour` is
  therefore **not** recoverable from the table afterwards, which is the deliberate
  cost of a key that has to be one genre. `Pyramids` and its packed path are what a
  test pins this with.
- **`mapped` must be updatable, and `DO NOTHING` would have been a silent bug.**
  Q7 says a positive hit whose target is no longer on the allowed list is treated as
  a **miss** and re-asked. Under `DO NOTHING` the new answer would then be thrown
  away by the very write that was supposed to store it: the row would keep the
  target that is not allowed, the next lookup would miss again, and **every later
  book carrying that genre would re-ask for the rest of the record's life**. The
  cache would be dead for that genre and nothing would say so.

  `DO UPDATE SET mapped = excluded.mapped` is what makes "re-ask and store" the
  outcome Q7 intends. It cannot resurrect a stale target either: §"Resolving one
  genre" validates every stored target against the allowed list on the way out, so a
  row is never trusted just because it exists.

The consequence worth stating, because it is the price of a single key: a row's
`seen` can name a string the current `mapped` was not answered for — the
`Fantasy:Humour` case, once `Fantasy` alone is re-asked and re-answered. `seen`
answers "where did this key first come from", not "what is this target's
provenance", and the log line is the place where a mapping's own reason is
recorded.

### The fingerprint

```
fingerprint = "\n".join(sorted(genre.casefold().strip() for genre in allowed))
```

Sorted, case-folded and trimmed, so reordering or re-casing `config.toml` is not a
change (Q7). On load, when the stored fingerprint differs from the current one
**and the relay is not in dry run**, `DELETE FROM genres WHERE mapped = ''` and
the row is rewritten. Positive rows are left as they are and are validated when
read.

**A fresh database has no `genre_list` row at all, and that is not an error.**
There is no stored fingerprint to compare against, and the table is empty by
definition, so the sweep is a no-op that simply writes the current fingerprint. It
is deliberately the same code path as a changed list rather than a special case:
`SELECT` returning `None` and the stored value differing both mean "the nulls on
file were not answered against this list", and either way the delete removes
nothing. Treating a missing row as an error would refuse the first book on a new
install, which is the one case that must work.

### Resolving one genre

```
for each (source, genre) the matched candidate carries, in order, deduped:
    1. the run memo   {(source, genre): target or None}     -> the run's own answer
    2. the record     genres(source, genre)                 -> a stored mapping,
                      a stored target no longer allowed      -> treated as a miss
    3. the model      Llm.map_genre(allowed, genre)          -> judged, then stored
    4. nothing        no list, no LLM, or a failed call      -> dropped, and said in the log
```

Then every non-`None` target is matched against the allowed list
case-insensitively, mapped onto the config's exact spelling, deduped, and added
to `dc:subject` in source order if the book does not already carry it — compared
the same way, case and surrounding space aside, because `Crime` written beside a
book's own `crime` is the pile of near-duplicate tags this ticket exists to
prevent in miniature. The book's own spelling is what stays: the config's
spelling is what is *added*, and this field has no rule that rewrites an element
already there.

**A failed call at step 4 drops the genre and nothing else, and the book lands.**
`LlmError` and `LlmLimited` out of `map_genre` are caught there and never reach
`_wait`: the genre is dropped, **no row is written for it** — it is absent rather
than decided, so dropping the file in again asks the question again — and the
book is delivered with whatever did resolve. The wait CBO-40's rule gives an
unanswerable call belongs to a *match* the model was needed for; a tag on a book
the rules already resolved is not worth holding that book for a day, and books
are dropped in on demand. The chooser's own `LlmError`/`LlmLimited` handling is
untouched and still waits, so the two paths must be pinned apart by test. The log
line is where that shows: "the model said no" is an answer, it is recorded, and
it reads differently from "could not be asked", which is not recorded and is the
only one of the two worth re-dropping the file for.

**An empty `allowed_genres` returns before step 1** (decision 12), and that is the
one ordering in this list worth stating: with no list there is nothing to map
onto, so neither a cached target nor a memo hit is a valid answer any more and
neither is worth looking up. Without the early return the memo would hand back a
target the empty list cannot accept, and the book would reach the write step with
a genre that decision 12 says cannot be written. The check belongs at the top of
the mapping step, not inside step 3.

### Files this touches

| File | Change |
| --- | --- |
| `colophon/hardcover.py` | `cached_tags` in both queries; `_genres(book)` splitting on `:` and `;`; `Candidate(genres=...)` |
| `colophon/googlebooks.py` | `categories` in `FIELDS`; the same split in `_candidate` |
| `colophon/sources.py` | `genre_parts()`, the split both sources share. **The module already existed** — CBO-37 added it for `SourceError`, `text` and `image` — so this is a function in the place the two sources' common code already lives, not a new file |
| `colophon/matching.py` | `Candidate.genres: tuple = ()` |
| `colophon/llm.py` | `GENRE_SYSTEM_PROMPT`, `Llm.map_genre()`, the allowed-list membership check |
| `colophon/config.py` | `allowed_genres`, `_to_genres()`, `Config.allowed_genres` |
| `colophon/record.py` | schema v2, the two tables, `mapping()`/`save_genres()`, the fingerprint sweep |
| `colophon/epub.py` | `Book.subjects`, `Edits.genres`, `_set_genres` |
| `colophon/correction.py` | the run memo, the mapping step, `Decision.genres`, the dry-run reporting |
| `colophon/relay.py` | persist the mappings at the existing write point |
| `config.example.toml` | `allowed_genres` and the add-only note |
| `tests/` | the tests below, plus the fixtures |

### Tests this note implies

The ticket's two, plus the ones the probes make worth pinning:

- **Messy Hardcover genres map onto the allowed list.** The four genres off
  `by-isbn-9781521748831-genres.json`, against a config list, produce the
  expected allowed genres deduped.
- **An unmappable genre is dropped.** `genre-mapping-unmappable.json` (a
  character heading) and `genre-mapping-synagogues.json` both answer `null`, and
  the book gets neither.
- **A truncated reply drops rather than writes.** `genre-mapping-batch.json` is a
  real `finish_reason: length` reply with partial content, and
  `genre-mapping-truncated.json` is the empty-body case; both are a `null`.
- **An empty allowed list costs no call.** Asserted on the transport never being
  called, not only on the outcome. This is why
  `genre-mapping-empty-allowed.json` is evidence rather than a fixture: the reply
  exists, but no request can reach it, so the test drives the state directly
  instead of replaying it.
- **A genre key that two strings collide on gets one row, and the first wins.**
  `by-isbn-9780575064843-packed-genres.json` carries `Fantasy` alone *and*
  `Fantasy:Humour`, so `Fantasy` already has a row when the packed form is split;
  the test asserts the row is unchanged, that `Humour` is still added, and that
  the whole packed string is not recoverable afterwards.
- **A book with no genres asks nothing**, and so does a recording made before
  this ticket — a missing `cached_tags` is absent, not an error.
- **The packed forms split.** `Fantasy:Humour` is two genres and
  `Classics; Fantasy; Horror` is three, asserted on the strings the transport was
  handed. The first has a recorded reply behind it
  (`by-isbn-9780575064843-packed-genres.json`); the semicolon shape does not, and
  is a unit test on the splitter.
- **The cache means one call per source genre, not per book.** Two books carrying
  `Crime` in one run spend one call; a second run spends none.
- **The run memo means one call per run.** Two books carrying `Crime` where the
  first never lands still spend one call in that run.
- **A positive cache hit that is no longer allowed is re-asked**, and a positive
  hit that is still allowed is not.
- **The re-ask is stored, and the next book pays nothing.** The same case driven
  one step further: the new target is written, the row's `seen` is unchanged, and a
  second book carrying that genre **in the same run** spends no call. This is the
  assertion that catches a `DO NOTHING` upsert, under which the row would keep the
  target that is no longer allowed and every later book would re-ask for ever —
  silently, because a re-ask that works looks exactly like a cache hit that
  works.
- **Nulls are invalidated when the allowed list changes**, and **not** when it is
  merely reordered or re-cased.
- **A dry run does not write the fingerprint and does not sweep**, asserted
  against the record's own contents, not only against the outcome.
- **A dry run logs an uncached genre as not asked** rather than reporting a book
  with no genres.
- **Add-only holds.** A book already carrying `Crime` is not rewritten for it; a
  book carrying its own subjects keeps every one of them; `colophon:unverified`
  survives a genre write.
- **The target is written as the config spells it**, matched case-insensitively:
  a config saying `Crime` writes `Crime`, and `genre-mapping-case.json` answering
  `crime` also writes `Crime`.
- **An off-list target is dropped**, so the allowed list is the only authority.
- **`["Crime", "crime"]` is a `ConfigError`**, and an empty list is not.
- **A version-1 record is carried forward to version 2**, and a newer file is
  still refused (CBO-41's test).
- **The mapping is not persisted for a book the relay never delivered.**

## Fixtures this session recorded

Committed under `tests/fixtures/`. Unlike CBO-41's seven, **these are read by
CBO-42's tests**, and each README says so.

| Fixture | What it pins |
| --- | --- |
| `hardcover/by-isbn-9781521748831-genres.json` | *Cragside*: four genres, three of them one shelf label |
| `hardcover/by-isbn-9781799729945-genres.json` | *The Infirmary*: `Suspense` added as a fifth |
| `hardcover/by-isbn-9781529978940-genres.json` | *Berwick*: `Fiction`, the only genre, and not a genre |
| `hardcover/by-isbn-9780575064843-packed-genres.json` | *Pyramids*: a BISAC colon path, `Humor` beside `Humour`, and `Science Fiction & Fantasy` as a third spelling |
| `hardcover/by-isbn-9781529196382-packed-genres.json` | *The Trial*: a colon path whose leaf is already a separate entry |
| `hardcover/by-isbn-9781473225374-genres.json` | an ISBN Hardcover has no edition of, which is a different empty from "no genres" |
| `googlebooks/isbn-cragside-categories.json` | Google's ISBN reply with `categories` asked for, which the shipped mask does not currently return |
| `llm/genre-mapping-murder.json` | one genre mapped: `Murder → Crime` |
| `llm/genre-mapping-case.json` | a lower-cased source genre, for the case-insensitive target match |
| `llm/genre-mapping-packed.json` | a packed form asked about unsplit |
| `llm/genre-mapping-fiction.json` | `Fiction` answered `null` — the drop that leaves a book with no genres |
| `llm/genre-mapping-synagogues.json` | a real Hardcover Genre tag that is not a genre, answered `null` |
| `llm/genre-mapping-unmappable.json` | Google's character heading, answered `null` |
| `llm/genre-mapping-empty-allowed.json` | an empty allowed list answered `null` rather than failing — probe evidence only, **not read by a test**: decision 12 means no call is made in that state, so no test can reach this reply |
| `llm/genre-mapping-batch.json` | the rejected shape: `finish_reason: length` with partial content, which must drop |
| `llm/genre-mapping-truncated.json` | the rejected shape at its worst: `finish_reason: length`, empty body |

`by-title-cragside.json`, already committed, is the second source's two cases in
one file and needs no new recording for the unmappable one — but its `categories`
are invisible to the shipped mask until decision 3 lands, so CBO-42's test for
Google's genres reads it through a client that asks for the field.

**All sixteen are live replies — none was reconstructed from documentation.** The
one Google recording and the six Hardcover ones are live replies to the shipped
request plus the field this ticket adds; the nine LLM ones are live replies from
DeepSeek. **Fifteen of the sixteen are read by a test**;
`genre-mapping-empty-allowed.json` is the exception, and it is kept because an
empty allowed list is the state a fresh install is in and the reply is what the
probe showed that state answers — not because anything replays it. The test for
that state asserts the transport was **never called**, which is a stronger claim
than any recorded reply could make.
