# CBO-41: Colophon's own record and name standard

**For the session that builds CBO-41.** Written 2026-09-19, after probing
Hardcover, Google Books and DeepSeek with the project's own keys. Everything
under "Verified against the live APIs" is a captured reply, not a reconstruction.
The probe scripts and their raw replies were in `.tmp/` (excluded, not
committed); the recordings the claims rest on are committed as fixtures, and the
few replies that are neither are quoted here in full.

Read with `../../AGENTS.md`, `../agents/issue-tracker.md` and the ticket
[CBO-41](https://linear.app/cbow/issue/CBO-41/08-colophons-own-record-and-name-standard),
whose parent is the design spec
[CBO-33](https://linear.app/cbow/issue/CBO-33/colophon-ebook-metadata-relay-design-spec-v1).

## Where the work sits

CBO-41's only listed blocker is **CBO-36**, and it is **Done** (PR #6, merged),
verified 2026-09-19 against Linear. CBO-36's own blocker, CBO-35, is Done too.
CBO-37, CBO-38, CBO-39 and CBO-40 are all Done, so `main` at the time of writing
carries the ISBN path, the title path, the field rules, the unverified path and
the LLM chooser. Nothing blocks this ticket.

Branch: `dsh/cbo-41-record-and-name-standard`. Linear suggests
`callumbowden111/cbo-41-08-colophons-own-record-and-name-standard`; the standing
rule in `~/.dsh/AGENTS.md` is `dsh/<short-topic>`, so the shorter one won. Say so
in the PR description.

### What the ticket asks for, in the code's terms

| Acceptance criterion | Where it lands |
| --- | --- |
| SQLite record (standard library) storing author spellings, series names, tags and previous matches | a new module, `colophon/record.py`, built on `sqlite3` |
| Author already recorded → the same spelling is reused; new author → the top-priority source's spelling becomes the standard | the resolve-then-write step in the correction pass |
| `[authors]` overrides always win | read from the config, applied last, never written back |
| Never used to work out series numbers | the record has no series-number column at all |
| Duplicates: looked up again, higher-confidence match wins; spellings still follow the record and overrides | the stored match, and the resolve step |
| Never cleared automatically; a reset command wipes it | no call to `expire()`; a `--reset-record` flag on `__main__` |
| Tests: LJ Ross vs L.J. Ross consistency, override precedence, duplicate re-lookup | see "Tests this note implies" |

## Verified against the live APIs

Probed 2026-09-19. Raw replies were written to `.tmp/cbo41/`; the ones the claims
depend on are committed under `tests/fixtures/`, and both READMEs there say which
is which and that no test reads the new ones yet.

### 1. Neither source writes an author's name; both write an identifier for it

Hardcover's `authors` table (asked of the schema, not the docs) has exactly the
fields this ticket needs:

```
alias, alias_id, alternate_names, bio, books_count, born_date, born_year,
cached_image, canonical, canonical_id, contributions, contributions_aggregate,
creator, death_date, death_year, gender_id, id, identifiers, image, image_id,
is_bipoc, is_lgbtq, links, location, locked, name, name_personal, object_type,
slug, state, title, updated_at, user_id, users_count
```

The row behind the three whole books this project already tests
(`tests/fixtures/hardcover/author-lj-ross.json`):

```json
{"id": 318638, "name": "L.J. Ross", "slug": "lj-ross", "name_personal": null,
 "alternate_names": [], "canonical_id": null, "alias_id": null, "books_count": 39,
 "canonical": null, "alias": []}
```

So `alternate_names` is an **empty array**, `canonical_id` and `alias_id` are
**null**, and `alias` is **empty** — for the author this ticket's own test names.
The columns exist and are populated for nobody here.

`_ilike` is refused on this root field, exactly as CBO-36 found it refused on
titles:

```
=== authors-named-ross: HTTP 403, 74 bytes ===
{"error":"ilike and related operations are not permitted on this server."}
```

`_eq` and `_in` on `authors.name` both work. **There is therefore no way to ask
Hardcover for "the other rows whose name resembles this one"** — a search for a
spelling variant is not available, only a lookup of a spelling already guessed.

Google Books has no author identity at all. Its `volumeInfo.authors` is a list of
display strings and nothing else, and its `fields` mask in `googlebooks.FIELDS`
asks for no more.

### 2. The id resolves the same id under two spellings, and nothing else

Three DCI Ryan books, each recorded by ISBN with the id asked for
(`by-isbn-{cragside,berwick,the-infirmary}-authors.json`):

| Book | ISBN | author | series |
| --- | --- | --- | --- |
| *Cragside* | 9781521748831 | id 318638 `L.J. Ross` | id 23832 `DCI Ryan Mysteries`, featured, position 6 |
| *Berwick* | 9781529978940 | id 318638 `L.J. Ross` | id 23832, featured, position 24 |
| *The Infirmary* | 9781799729945 | id 318638 `L.J. Ross` | id 23832, featured, position 11 |

Same author id, same series id, three books. That is what an id buys: **when a
record's author id is the one already recorded, the spelling is reused even if
the string differs.** The case that needs it
(`tests/fixtures/hardcover/works-good-omens-authors.json`):

```
work 2955939  "Good Omens"  → 1566154 "Terry David John Pratchett"
work 315038   "Good Omens"  → 227859  "Terry Pratchett", 106235 "Neil Gaiman"
work 438096   "Good Omens"  → 227859  "Terry Pratchett"
```

One source, one title, and the name of its author spelt two ways on two records —
plus a third record crediting only one of the two authors, and the two credited in
a different order on the second. **Comparing the strings cannot resolve that;
comparing ids can** (227859 is 227859).

**What the id does not do — the residual case, and it is not hypothetical.** One
human is three rows:

```
exact:  [{"id": 350235, "name": "LJ Ross", "slug": "lj-ross-9c7bfe5a-…"}]
spaced: [{"id": 350233, "name": "L. J. Ross", "slug": "l-j-ross"}]
plain:  [{"id": 806228, "name": "Ross", "slug": "ross"}]
many:   [350233 "L. J. Ross", 318638 "L.J. Ross", 350235 "LJ Ross"]
```

(committed as `authors-spelling-variants.json`; the fourth row is one `_in`
query, which is the only way to get more than one at once). Every DCI Ryan book
carries 318638. Nothing in the API ties 318638 to 350233 or 350235: no
`canonical_id`, no `alias_id`, no `alternate_names`, no link of any kind. So an id
**does not merge those three**, and no amount of asking the same source will.

**That residual case is what `[authors]` is for**, and CBO-41's test must say so
rather than implying the id solved it. The two mechanisms answer two different
questions:

| Question | Answered by |
| --- | --- |
| Is this the same author record I recorded before, spelt differently? | the source's own id |
| Are these two *rows* one person? | `[authors]`, the user's override — nothing else |

An earlier cut of this note proposed using the LLM for the second question. It is
dropped; §5 is why.

### 3. The two sources spell the same author differently, and each is stable

Google Books, asked about the same author three ways
(`by-isbn-cragside-authors.json`, and the two title searches that were recorded
and then deliberately not kept — see `fixtures/googlebooks/README.md`):

| Query | Volume | Title | Authors |
| --- | --- | --- | --- |
| `isbn:9781521748831` | `RASDtAEACAAJ` | *Cragside* | **`L. J. Ross`** |
| `intitle:"Cragside" inauthor:"L.J. Ross"` | `7kMMzgEACAAJ`, `RASDtAEACAAJ` | *Cragside* ×2 | `L. J. Ross` |
| `intitle:"Cragside" inauthor:"LJ Ross"` | `7kMMzgEACAAJ`, `RASDtAEACAAJ` | *Cragside* ×2 | `L. J. Ross` |
| `inauthor:"L.J. Ross"` (40 volumes) | eight volumes | *Heavenfield*, *Holy Island*, *Cragside*, … | `L. J. Ross` on every one |

So Google **normalises the punctuation server-side** — `LJ Ross` and `L.J. Ross`
both find the same volumes, which is what `googlebooks.py` already relies on —
and its own spelling is `L. J. Ross`, stably, across a whole author's catalogue.
Hardcover's is `L.J. Ross`, stably, across the same catalogue.

**Neither is wrong and neither is more correct. The library has to pick one, and
that is the whole point of the standard.** A book first matched from Hardcover
gets `L.J. Ross` and every later book by that author gets it too, including books
matched from Google Books, because the record is what decides.

Ordering is a second thing the sources disagree about, and the record must not
try to fix it: the same title by the same two authors comes back
`[Terry Pratchett, Neil Gaiman]` on one Hardcover record and `[Neil Gaiman, Terry
Pratchett]` on another (`works-good-omens-authors.json` covers one source; the
Google Books *Good Omens* probe showed the same disagreement between volumes of
one work, and no recording of it was kept). The authors a match writes keep **the
order the matched source's record gives them**.

### 4. Series identity, and tags

Series is the same shape as authors, on Hardcover:

```
=== works-authors (four DCI Ryan works) ===
1198994 "Cragside"      → series 23832 "DCI Ryan Mysteries" (featured, 6)
2379453 "Berwick"       → series 23832 (featured, 24)
1647114 "Belsay"        → series 23832 (featured, 23)
1198266 "The Infirmary" → series 23832 (featured, 11)
```

A series has an `id`, and the four books share it. **Google Books has no series
data at all** — `cbo-37-google-books.md` records that `seriesInfo` never appeared
for a novel — so there is nothing to give a series an id from that source. A
series standard therefore resolves by id where the source has one and by the
remembered spelling otherwise, and a book matched from Google Books never
introduces a series name.

Neither shipped query asks for `series.id` or `authors.id` today, which is a
query change this ticket needs (§"The query change").

**Tags are not on the wire in any shape this ticket should read.** The one place
Hardcover keeps them is `books.cached_tags`, recorded here because the ticket
names tags and the answer is not obvious:

```
=== cached-columns: HTTP 200 ===
{"id": 1198994, "title": "Cragside",
 "cached_tags": {"Tag": [],
                 "Mood": [{"tag": "dark", …}, {"tag": "fast-paced", …},
                          {"tag": "mysterious", …}, {"tag": "tense", …}],
                 "Genre": [{"tag": "Murder", …}, {"tag": "Crime", …},
                           {"tag": "Thriller", …}, {"tag": "Mystery", …}],
                 "Content Warning": []},
 "taggings": [{"tag": {"tag": "Murder"}}, {"tag": {"tag": "Crime"}}, …]}
```

It is a `jsonb` cache of community tags, not the source's own taxonomy, and it is
reachable only from a work. It is **not** the allowed-genres list the spec
describes, which comes from the user's config and from Colophon's own record. The
shipped queries do not ask for it and this ticket does not read it. See Q7.

### 5. The LLM name job does not fit in the client it would have to reuse

The spec lists "recognising the same author spelt differently" as an LLM job, so
it was probed. Same key, same endpoint, same request shape `colophon/llm.py`
sends (`deepseek-flash`, `response_format: {"type": "json_object"}`, no
`temperature`, `max_tokens: 256`), model reported as `deepseek-flash` on every
reply, 19 calls.

| Pair asked about | completion | reasoning | `finish_reason` | content |
| --- | --- | --- | --- | --- |
| `L.J. Ross` / `LJ Ross` | 70 | 42 | `stop` | `{"same": true, "confidence": 0.99, …}` |
| `L.J. Ross` / `L. J. Ross` | 86 | 59 | `stop` | `{"same": true, "confidence": 0.99, …}` |
| `L.J. Ross` / `Ross, L. J.` | 75 | 46 | `stop` | `{"same": true, "confidence": 1.0, …}` |
| `Ursula K. Le Guin` / `Ursula LeGuin` | 73 | 36 | `stop` | `{"same": true, "confidence": 0.99, …}` |
| `L.J. Ross` / `Carly Reagon` (**the answer is "no"**) | **256** | **256** | **`length`** | **empty string** |
| `LJ Ross` / `Ross` (a bare surname) | **256** | **256** | **`length`** | **empty string** |
| the same bare-surname pair at `max_tokens: 2000` | **2000** | **2000** | **`length`** | **empty string** |
| `L.J. Ross` / `Carly Reagon` at `max_tokens: 2000` | 434 | 407 | `stop` | `{"same": false, "confidence": 0.99, …}` |

Two things fall out.

**`deepseek-flash` always reasons first.** `usage.completion_tokens_details.
reasoning_tokens` is populated on every reply in this probe — including the
chooser's own job, which took 29–58 reasoning tokens across five runs. CBO-40's
note sizes `MAX_TOKENS` at 256 for exactly one small object and attributes the
"reasons first" risk to Gemini's and Groq's presets alone; DeepSeek's own preset
carries it too, and here it is **measured rather than documented**. Recorded as a
comment on CBO-40, where the budget was chosen. The chooser itself is unaffected:
its worst run was 101 completion tokens, and a truncated reply is already a
`null`.

**A name verdict the model finds hard spends the budget on thinking and answers
nothing.** The two cases that matter most are the two that return an empty
string: "these are different people", and a name too vague to decide. Under
CBO-40's Q3 a truncated reply is a `null`, so on the shipped 256-token request
those books would silently keep the spelling the record already had — every day,
for ever, with no log line saying the model had been asked and had produced
nothing. Raising the cap is not a fix either: 2000 was not enough.

## The grilling

Every question below was put to the maintainer before any code was written, with
the answers as given. They are decisions, and the ones that override what the
ticket's wording implies are flagged.

### Round 1 — author identity

**Q1. How does the record decide two author spellings are the same person?** →
**Source id within a source, remembered spelling across sources — with a
correction the maintainer added:** "Be clear in the note about what the id
actually buys: it resolves *same id, different spelling* (the Pratchett case). It
does not merge 318638 / 350233 / 350235, because those are three separate records
for one human. That residual case is what `[authors]` is for, and the test should
say so rather than implying the id solves it."

So the resolution order is: **the source's own id first, then the spelling the
record already has, then the source's spelling as a new standard.** The id makes
the first step exact where a source supplies one, which is the Pratchett case;
the remembered spelling carries the standard to a source that has no ids, which is
every Google Books match; and the residual one-human-three-rows case is answered
by nothing but `[authors]`. This is written into §2 as a table because it is the
single most misreadable part of the design.

**Q2. Does the LLM recognise name variants?** → **No, dropped from this
ticket.** The maintainer's reason is stronger than the token measurement and is
the one to record: "a wrong 'same person' verdict writes a permanent merge into a
store that is never cleared automatically. Bad trade for the least reliable path
in the ticket." The finding is also filed on CBO-53/CBO-54.

*This is a deliberate narrowing of the spec*, which lists the job among the LLM's
three. It is narrowed on evidence rather than on preference: the job does not fit
the request the client already sends, and its failure mode is a permanent wrong
merge rather than a wrong answer about one book.

### Round 2 — the override, and the duplicate

**Q3. Which way does `[authors]` read, and is an override recorded?** → **key =
any spelling seen, value = what is written; never recorded.** So
`[authors]` `"LJ Ross" = "L.J. Ross"` means a book whose author arrives as
`LJ Ross`, `L.J. Ross` or `L. J. Ross` is written `L.J. Ross`. Two rules were
added:

- **One hop, no chaining.** If a value happens to also appear as a key, it is not
  followed. `"A" = "B"`, `"B" = "C"` writes `B`, not `C`. A chain is a
  configuration nobody can read back off the page, and the second hop is always
  the user's to write if they want it.
- **Both sides are normalised at load time**, because TOML keys are literal
  strings and `"L.J. Ross"` and `"L. J. Ross"` are two keys to TOML and one name
  to this project. `matching.normalise` is already the one place that says what
  "the same name" means for comparison, so the table is keyed by its output.

An override is applied **last**, after the id lookup and after the remembered
spelling, and is never written into the record: editing the config back restores
the recorded spelling, which is what "overrides always win" has to mean if the
override is a layer rather than a value.

**Q4. What is "a book already recorded", and what does the higher-confidence
match update?** → **Keyed on ISBN, else on the normalised title and author.** The
record keeps the source and the confidence of the match that produced it; a
re-lookup whose confidence is higher replaces the stored match **and can raise a
standard**; a lower one is history and changes neither. Two caveats were added:

- **Tie-break on the configured source priority**, added by the maintainer
  "only if confidence is comparable across sources". It is: `CONFIDENCE = 1.0` on
  the ISBN path is a constant, and on the title path `score_candidate` is
  computed from the *file* and the *candidate record* — never from which source
  offered it. Two sources offering the same record score it identically. So
  confidence is comparable, and an exact tie is broken by the user's
  `sources` order, which already exists. In a single pass the walk's
  first-match-wins already does this; the tie-break is for the duplicate case,
  where an old match and a new one are compared.
- **Two editions of one book have different ISBNs and key separately.** Recorded
  in the note and to be said in the ticket rather than discovered later.
  Acceptable for v1: the consequence is that a paperback and a hardback of one
  book can each set a spelling, and then the record has two standards for one
  author — which is the case `[authors]` exists for.

**Q5. Which corrections may teach the record a standard?** → **Only one that was
actually applied, and only once the output file has landed** — so a crash
mid-write cannot teach a standard for a book that never arrived. A dry run
teaches nothing (it writes nothing, which is the one thing `dry_run` means), a
book nothing matched has no source spelling to teach, and a correction that
failed after matching — a backup that could not be written, a cover the file
refused — leaves the record alone.

This puts the record write in the **relay**, after `copy_into_place`, and not in
the corrector: the corrector decides what the correction *is*, and the relay is
what knows whether it landed. See "Where the record write goes".

### Round 3 — where it lives, and what else is in it

**Q6. Where does the SQLite file go?** → **A `record_path` setting, default
`/backups/.colophon.db`.** `docker-compose.example.yml` mounts `/config` as `:ro`
and `read_only: true` is on the container, so the record cannot live beside
`config.toml`. CBO-40 already put its daily counter at
`/backups/.colophon-llm.json` for exactly this reason and explicitly left "where
durable state lives" to this ticket (its Q13); this is that ticket's answer, and
it reuses the folder rather than adding a mount. Three additions:

- **`.colophon.db-wal` and `.colophon.db-shm` appear beside it** in SQLite's
  default journal mode. Both begin with a dot, so `Backups.expire()`'s existing
  skip still protects them, and a test must assert that rather than assume it.
- **`record_path` should be documented as local disk.** On an SMB or NFS share
  SQLite's locking is unreliable, and `backup_dir` is a plausible thing for a
  user to point at a NAS.
- **A `record_path` setting rather than a constant**, so the path follows the
  same shape as every other one, and so a user who wants it elsewhere can say so.

**Q7. Does CBO-41 store tags?** → **Yes, a table, unwritten by this ticket** —
which exposed a gap worth more than the answer: **schema migration.** "CBO-41
creates the database, and CBO-42, CBO-47 and anything after will want columns it
doesn't have. Without a `user_version` pragma and a migration step, the only
options later are wipe-and-rebuild or ad-hoc `ALTER TABLE` scattered across
tickets. Add it here." With migrations in place an unwritten tag table is free,
and CBO-42 can extend it without touching this ticket's schema.

So: `PRAGMA user_version` is set when the file is created, **an older version is
migrated forward** by steps that live beside the schema, and **a file whose
version is newer than the build knows is refused** with a clear message rather
than read: an older Colophon writing a newer database is how a table someone else
added gets dropped. The version is bumped by whichever ticket first changes the
schema, and this is builder work rather than a user-visible setting.

## Decisions taken by me, for review

These are the calls I made rather than asked about. Each is here so it can be
overturned in review.

1. **The record is `colophon/record.py`, and it owns the SQLite.** One module
   with the schema, the migrations, the resolve-then-record step and the reset.
   No ORM, no dependency — `sqlite3` is in the standard library and the spec says
   standard library only.
2. **The record stores a match, not a book.** A row is the source, the confidence
   and the identity the source matched it under. It is not a cache of the book's
   metadata and is never read to *write* a field: every value written still comes
   from the matched source's record, which is the spec's pipeline step 6 and what
   keeps the record "for consistency only".
3. **The record has no series-number column**, which is how "never used to work
   out series numbers" is enforced structurally rather than by discipline. A
   column that is written and then ignored is a column someone will read.
4. **A standard is carried under two keys per name**, the source's own id and the
   normalised spelling, both holding the same `standard`, so the lookup can start
   with the strongest identity available and fall back to the name. Resolution is
   therefore one table and two queries, not a table per source.
5. **The reset is a flag, not a subcommand**: `python -m colophon
   --reset-record`, which is what `__main__` already is. No confirmation prompt —
   it is documented as the command that wipes it, and an interactive prompt in a
   container is a prompt nobody can answer. **It wipes the record only.** Books
   already in the library keep the spellings they were given; rewriting them is
   the "fixing an existing library" the design spec puts out of scope for v1, and
   a reset that silently rewrote a library would be a much bigger command than
   the ticket asks for. This needs `main()` to parse an argument it does not
   parse today, and the config must be loaded first because `record_path` is
   where the file is.
6. **Overrides are validated loudly.** A `[authors]` value that is empty, or a
   key that is not a string, is a `ConfigError` at startup like every other
   setting — a table that silently does nothing is the failure mode this project
   refuses elsewhere.
7. **`config.py` learns the `[authors]` table.** `_read_file` refuses unknown
   top-level settings, so `[authors]` is a `ConfigError` today. It becomes a
   field on `Config`, normalised and checked, like `fields`.
8. **The record is opened once and passed down**, from `Relay` to `Corrector`,
   the way `Backups` already is. Two connections to one SQLite file is how
   `database is locked` starts.
9. **The record write is the relay's, after the file lands** (Q5). The correction
   returns a small record-ready value on the `Outcome` — the match's confidence
   and source, and each name written with the keys it resolved under — and the
   relay persists it on the one path where `copy_into_place` succeeded. The relay
   stores the decision; it does not re-derive it.
10. **`record_path` is a top-level config key**, so `COLOPHON_RECORD_PATH` works
    like every other setting.

## The build shape

### The schema

Three tables and a version. Names and shapes are a proposal; the columns are the
ticket's.

```sql
-- The user's config is not a table. Read at startup, applied last, never written.

CREATE TABLE names (
    kind     TEXT NOT NULL,   -- 'author' or 'series'
    source   TEXT NOT NULL,   -- which source's identity key this row is under
    key      TEXT NOT NULL,   -- that source's own id, or the normalised spelling
    standard TEXT NOT NULL,   -- the one spelling every later book is given
    seen     TEXT NOT NULL,   -- the spelling this row was built from
    PRIMARY KEY (kind, source, key)
);

CREATE TABLE matches (
    book_key   TEXT PRIMARY KEY, -- the ISBN, else normalised title + author
    source     TEXT NOT NULL,    -- who matched it
    confidence REAL NOT NULL,    -- the match's own confidence
    matched_at TEXT NOT NULL,
    -- The identity the source matched it under, so a re-lookup can find the
    -- same records: the source's own id for the book, or its ISBN when the
    -- source has no work id (Google Books).
    matched_as TEXT NOT NULL
);

CREATE TABLE genres (
    genre      TEXT PRIMARY KEY  -- written by CBO-42, created here and unused
);
```

**There is no `source_id` column, and that is the point.** A source's own id is
the strongest key available, but it is only meaningful to that source: Google
Books has no author ids, so a Google Books match could never find a row keyed by
Hardcover's 318638, and the standard would not carry across — which is the whole
of what this ticket is for. So a name is looked up **twice**: under the source's
own identity (`source='hardcover', key='318638'`), and under the name itself
(`source='', key=normalise('L. J. Ross')`). The first answers "the same record,
spelt differently"; the second is what a source with no ids has, and what every
source falls back to. Both land on **one `standard` per name**, so the first
source to match an author fixes the spelling every later source reuses.

The rows are written together: the id row and the spelling row for one author
carry the same `standard`, so whichever lookup finds it gives the same answer.

### Resolving one name

```
for each author the match names, in the matched record's order:
    1. override    config [authors], keyed by normalise(name)              -> wins
    2. the id      names(kind='author', source=<who matched>, key=<the id>) -> reuse
    3. the name    names(kind='author', source='', key=normalise(name))     -> reuse
    4. nothing     the source's spelling becomes the standard, recorded
                   under both keys
```

Step 4 records only on a correction that was applied and delivered (Q5). The
order is the ticket's own: overrides always win, a recorded author's spelling is
reused, and a new author takes the top-priority source's spelling — which is step
4 reached by the first source, in priority order, that matched the book. Step 2
fires only when the source supplies an id and the record already has that id,
which is the Pratchett case; step 3 is what makes the standard follow an author
from Hardcover to Google Books.

Series is the same shape with `kind='series'` and one difference: Google Books
has no series at all, so it reaches step 4 with nothing and can never introduce a
series name.

**Step 3 is also where the residual case is visible.** `matching.normalise` keeps
the words and drops everything between them, so an initial pairs with its stop and
`L.J. Ross` normalises to `l j ross`. That is exactly the same key as
`L. J. Ross` (checked against the function, not assumed) — so those two spellings
**do** reach one standard by name. The third spelling, `LJ Ross`, is the odd one
out: `lj ross` is a different key, so it stays its own standard until `[authors]`
says otherwise. A bare `Ross` is a third key again (`ross`).

So of the three rows §2 found for one human, name resolution merges two and
leaves one — and **the source id merges none of them**, because they are three
rows with three ids. `[authors]` is the only thing that merges all three, which is
what the ticket's test has to demonstrate.

### The query change

`hardcover.QUERY` and `hardcover.TITLE_QUERY` gain two fields:

```
contributions { contribution, author { id name } }
book_series    { featured, position, series { id name } }
```

**This is a stated change to fixtures**, the way CBO-36's note stated its own:
the eleven recordings made before this ask for no id, and `_candidate` must treat
a missing id as absent rather than as a bug. New recordings
(`by-isbn-*-authors.json`) carry it. Google Books needs no change — it has no ids
to ask for.

`matching.Candidate` gains two fields that are **not values to write and are
never written into a book**: the ids of the authors the record names, and the id
of the series it puts them in. They belong on the candidate because that is what
the source returned and what the corrector already passes around — a second
parallel type carrying the same record's ids would be a second thing to keep in
step — and because a candidate is already "a book a source offered", of which its
ids are a part. `_candidate`, `_authors` and `_series` in `hardcover.py` are the
one place each is read, so the two lookups cannot disagree about which id belongs
to which name. Every `Candidate` field a rule may write stays exactly as it is:
the ids are carried, not applied.

Google Books supplies neither, so both default to empty and the resolution falls
through to the remembered spelling — which is the whole of why that step exists.

### Where the record write goes

`Corrector._write` already knows `found` (the candidate) and `path`, and it is the
only place that knows which names were resolved and under which keys. `Outcome`
gains one optional field carrying that, and `Relay._deliver` persists it **after**
`copy_into_place` returns, on the one path where the book actually arrived. A dry
run returns before that point, so it needs no second guard. This is decision 9 in
the list above; it is repeated here because it is the only change outside
`colophon/record.py` that the ticket forces.

### Tests this note implies

The ticket's three, plus the ones the probes make worth pinning:

- **Consistency across sources, which is the ticket's own LJ/L.J. test.** A book
  matched from Hardcover records `L.J. Ross`; a later book by the same author
  matched from Google Books arrives as `L. J. Ross` and is written `L.J. Ross`,
  resolved at step 3 of the next section. The first half is
  `by-isbn-cragside-authors.json` or `by-isbn-berwick-authors.json`, the second is
  `googlebooks/by-isbn-cragside-authors.json`.
- **Consistency by id, which is the step name resolution cannot do.** A record
  carrying author id 227859 and a spelling the record has never seen still reuses
  that author's standard, because the id matches. Driven by
  `works-good-omens-authors.json`, where 227859 is spelt `Terry Pratchett` on both
  works while 1566154 is a different row for the same human.
- **Override precedence.** An `[authors]` entry beats a recorded standard; the
  record is unchanged afterwards; a two-hop chain resolves one hop only; a
  differently-punctuated key matches.
- **Duplicate re-lookup.** A recorded book, re-matched at a higher confidence,
  takes the new match and can raise a standard; at an equal confidence the
  configured source priority decides; at a lower one nothing changes.
- **The residual case, as the maintainer asked for it.** `LJ Ross` (id 350235)
  does not merge with `L.J. Ross` (id 318638) through the id or through the name
  key — `lj ross` and `l j ross` are different keys — and `[authors]` is what
  merges them. The test asserts the non-merge first, so a later change that
  "helpfully" starts merging them fails rather than passing silently.
- **`normalise` is what decides a key.** A test pins `L.J. Ross` and
  `L. J. Ross` to `l j ross` and `LJ Ross` to `lj ross`, because the whole
  cross-source behaviour rests on that and it is not obvious from reading the
  function.
- **The record has no series number.** Asserted against the schema, so a later
  ticket cannot add one quietly.
- **`Backups.expire()` never deletes the record, its `-wal` or its `-shm`.**
- **A record a build does not know the version of is refused**, not upgraded.
- **The reset wipes it**, and the next book starts a fresh standard.
- **Nothing is recorded on a dry run, on an unmatched book, or on a correction
  the relay never delivered.**

## Fixtures this session recorded

Committed, with the two READMEs saying which are read by a test and which are
not. No test reads any of them yet.

| Fixture | What it pins |
| --- | --- |
| `hardcover/by-isbn-{cragside,berwick,the-infirmary}-authors.json` | same author id, same series id, three books |
| `hardcover/author-lj-ross.json` | the row itself: no alternate names, no canonical, no alias |
| `hardcover/authors-spelling-variants.json` | one human, three rows, unrelated to each other |
| `hardcover/works-good-omens-authors.json` | one id under two spellings, and authors in two orders |
| `googlebooks/by-isbn-cragside-authors.json` | Google's own spelling, `L. J. Ross` |

Two Google Books title recordings — the same Cragside search with `LJ Ross` and
with `L.J. Ross` — were made and **not kept**: both answers are
`by-title-cragside.json` again with a different `etag`, and that README already
states the property they would show. The replies the LLM section rests on are
**not** committed either, because no test would read them; the numbers are in §5
and on CBO-53/CBO-54.

## What this ticket does not build

CBO-42's genre mapping and the allowed-genres list itself; CBO-43's retry window
and rejected-key hold; CBO-46's AI-guess mode; and the LLM name job (Q2). The
`genres` table is created empty on purpose so CBO-42 has somewhere to put its
list without changing this ticket's schema.
