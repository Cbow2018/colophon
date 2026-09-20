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

### 2. What an author id does, and what it does not

Three DCI Ryan books, each recorded by ISBN with the id asked for
(`by-isbn-{cragside,berwick,the-infirmary}-authors.json`):

| Book | ISBN | author | series |
| --- | --- | --- | --- |
| *Cragside* | 9781521748831 | id 318638 `L.J. Ross` | id 23832 `DCI Ryan Mysteries`, featured, position 6 |
| *Berwick* | 9781529978940 | id 318638 `L.J. Ross` | id 23832, featured, position 24 |
| *The Infirmary* | 9781799729945 | id 318638 `L.J. Ross` | id 23832, featured, position 11 |

Same author id, same series id, three books, and the same spelling on all three.
The four DCI Ryan works recorded earlier say the same thing, and so does every
other full-format recording in `tests/fixtures/hardcover/`. **Checked rather than
assumed: no committed recording shows one author id carrying two spellings, and
none shows one series id carrying two names.** The same-id-different-spelling
case this section is named after is real in principle and does not appear in any
fixture CBO-41 has. §"Does step 2 earn its place" says what follows from that.

Three things about identity *are* in the fixtures, and they are three different
problems:

**One name, two rows.** Two works called *Good Omens* name `Terry Pratchett` and
neither of them is the other's author row:

```
work 2955939  "Good Omens"  → 1566154 "Terry David John Pratchett"
work 315038   "Good Omens"  → 227859  "Terry Pratchett", 106235 "Neil Gaiman"
work 438096   "Good Omens"  → 227859  "Terry Pratchett"
```

`Terry Pratchett` (227859) and `Terry David John Pratchett` (1566154) are **two
ids and two normalised keys** — `terry pratchett` and `terry david john
pratchett`. So the id does not join them either; they are separate standards
until `[authors]` joins them, exactly like the Ross rows below. A third work
credits only one of the two authors, and the two are listed in a different order
on the second, which is why the record must keep the order a record gives rather
than sorting authors.

**One human, three rows.** The case `[authors]` exists for:

```
exact:  [{"id": 350235, "name": "LJ Ross", "slug": "lj-ross-9c7bfe5a-…"}]
spaced: [{"id": 350233, "name": "L. J. Ross", "slug": "l-j-ross"}]
plain:  [{"id": 806228, "name": "Ross", "slug": "ross"}]
many:   [350233 "L. J. Ross", 318638 "L.J. Ross", 350235 "LJ Ross"]
```

(committed as `authors-spelling-variants.json`; the fourth line is one `_in`
query, which is the only way to get more than one at once). Every DCI Ryan book
carries 318638. Nothing in the API ties 318638 to 350233 or 350235: no
`canonical_id`, no `alias_id`, no `alternate_names`, no link of any kind. So the
id **does not merge those rows**, and no amount of asking the same source will.

**The name key merges all three, and that is the decision this section records.**
Grouping the committed spellings through `matching.normalise` (run over the
fixtures, not read off by eye):

| id | spelling | normalised key |
| --- | --- | --- |
| 318638 | `L.J. Ross` | `lj ross` |
| 350233 | `L. J. Ross` | `lj ross` |
| 350235 | `LJ Ross` | `lj ross` |
| 806228 | `Ross` | `ross` |
| 227859 | `Terry Pratchett` | `terry pratchett` |
| 1566154 | `Terry David John Pratchett` | `terry david john pratchett` |

Those first three keys are **one key only after the change described in "The
normaliser change" below**; before it, `normalise` gave `l j ross` for the first
two and `lj ross` for the third, so the name key merged two of the three and
`[authors]` was needed for the third. The ticket's own acceptance test —
"LJ Ross vs L.J. Ross consistency" — is what forced the change: a test that only
passes because of a config entry is testing the config, not the design.

The finding, stated exactly:

> **The name key merges spellings that differ only in punctuation and initial
> spacing. `[authors]` is the merge for spellings that differ in their words** —
> `Terry Pratchett` against `Terry David John Pratchett`, or a bare `Ross`
> against `LJ Ross`.

So the three mechanisms answer three questions:

| Question | Answered by |
| --- | --- |
| Are these two spellings the same name? | `matching.normalise`, in the name-keyed lookup |
| Are these two *rows* one person, spelt with different words? | `[authors]` — nothing else |
| Has this *source row* been seen before, whatever it was spelt as? | the source's own id |

An earlier cut of this note proposed using the LLM for the second question. It is
dropped; §5 is why.

#### Does the id-keyed read earn its place?

The resolution order has an id-keyed lookup before the name-keyed one.
**Confirmed by the maintainer: the id is both read and written.** Writing it and
never reading it was rejected — "dead data is worse than either alternative" — so
the read stays.

**No fixture reaches it.** Checked over every committed recording: none shows one
author id under two spellings, and none shows one series id under two names. The
read is therefore **not an evidence-backed path**: it is cheap insurance against
a source renaming an author under a stable id, which is a thing sources do and
which the fixtures have simply not caught yet. It is one indexed lookup on a
column that is already there, and it is what stops the id row being data nothing
reads.

This is the same shape as a finding CBO-36's review already acted on — the
edit-distance decay was dropped because *no fixture could reach it*. The
difference is that this one is one query rather than a branch of scoring logic,
and the maintainer's call is that the insurance is worth more than the tidiness.

#### The normaliser change

**Decided by the maintainer, and it is a change to `matching.normalise`, not just
to this ticket's use of it.** Today `normalise` keeps the words and drops
everything between them, so `L.J. Ross` gives `l j ross` while `LJ Ross` gives
`lj ross` — one name, two keys, and the ticket's own acceptance test would pass
only because of an `[authors]` entry. The rule becomes:

> casefold, strip punctuation, collapse whitespace, then **collapse runs of single
> letters into one token**.

Measured against the committed spellings:

| spelling | today | after the change |
| --- | --- | --- |
| `L.J. Ross` | `l j ross` | `lj ross` |
| `L. J. Ross` | `l j ross` | `lj ross` |
| `LJ Ross` | `lj ross` | `lj ross` |
| `Ross, L. J.` | `ross l j` | `ross lj` |
| `J.R.R. Tolkien` | `j r r tolkien` | `jrr tolkien` |
| `J. R. R. Tolkien` | `j r r tolkien` | `jrr tolkien` |
| `JRR Tolkien` | `jrr tolkien` | `jrr tolkien` |
| `Ursula K. Le Guin` | `ursula k le guin` | `ursula k le guin` |
| `Ursula LeGuin` | `ursula leguin` | `ursula leguin` |
| `1.0.0` | `1 0 0` | `1 0 0` |

**Blast radius, measured against `main` with the shipped function rather than
argued:** `normalise` is called on two things and only two — the file's cleaned
title and the candidate's title — so both were measured.

- **0 of 28 title keys in the fixture set move**, and **0 of 36
  file-title/candidate pairs** change their score or their `agrees` verdict. No
  match the project already makes is decided differently.
- **4 of 11 author spellings move**: `L.J. Ross` and `L. J. Ross` onto one key,
  and `J.R.R. Tolkien` and `J. R. R. Tolkien` onto `JRR Tolkien`'s. Those four
  are exactly the names the change is for.

An earlier draft of this section quoted "6 of 394 strings" from a prototype whose
word-splitting was wrong, which made the change look broader than it is and,
worse, made a version string look safe when that prototype was still gluing
`1.0.0` into `10 0`. The figure is corrected here because a number in a note is
what the next session trusts.

Two ordinary inputs that must **not** change, and are pinned by tests:

```
"Ursula K. Le Guin"       -> "ursula k le guin"      (never "ursulakleguin")
"I am here"               -> "i am here"             (never "iam here")
"1.0.0"                   -> "1 0 0"                 (never "10 0")
```

The rule that gets all three right is narrower than "join runs of single
letters", and this is the part worth reading before touching it. **This is the
rule as the code implements it, not as an earlier draft described it:**

- **A one-letter word joins the token before it only when that token is itself a
  one-letter run.** Otherwise it starts a run of its own. That one condition is
  the whole rule and it carries every case: `L. J. Ross` joins because `j` finds
  the run `l` beside it, while `Ursula K. Le Guin` does not, because the `k` has
  the word `ursula` before it and so never becomes a run for `le` to join.
- **A run is marked when it is born, not recomputed.** A token carries whether it
  is a run, so a word that merely happens to be one letter long by this point —
  `k` in `K. Le Guin` — cannot be mistaken for one and swallow the word after it.
  This is the flag `_join_initials` keeps beside each token, and it is the only
  thing that makes `ursula k le guin` and `i am here` come out as they do.
- **A full stop between two letters is part of an initial; a full stop after a
  digit is a decimal point and one after a word is a sentence ending.** Both
  others are left as separators, which is what keeps `1.0.0` a version string.

**An earlier draft of this note described a look-ahead instead** — "join only
when the next word is also one letter" — and claimed it was what stopped `I am`
becoming `Iam`. It is not, and the build exposed the draft as wrong rather than
the code: the look-ahead was implemented, measured, and **removed**, because it
changes no answer for any arrangement of one-letter and word-shaped tokens up to
five long. What actually does the work is the rule above. The note is corrected
rather than the code, because the simpler rule is the one that is right and the
simpler rule is the one to keep.

`normalise` also scores titles, so the change reaches the title half as well, and
the 36 title-and-author pairs the project tests with all score exactly what they
scored before — which follows from no title key moving. The one title-side pair
of this shape, `J.R.R. Tolkien` against a record spelling it `JRR Tolkien`,
already agrees through `_name` and is unaffected either way.

**`matching._name` already does this, more aggressively, and needs no change.**
The author half of the comparison runs names together entirely — `LJ Ross`,
`L.J. Ross` and `L. J. Ross` are all `ljross`, and `J.R.R. Tolkien` is
`jrrtolkien` — which is why the author comparison already accepts every variant
above and why the ticket's consistency problem was never about *matching*. It is
about the spelling that gets **written**, which is the name key's job, and the
name key needs a key that is stable and readable rather than a bag of characters.
The two normalisers stay separate for that reason, and the note that says so is
in `record.py` beside the key function: **`_name` is for scoring and may
over-merge; the record key is durable identity and must not.** The difference is
concrete: `Ursula LeGuin` matches `Ursula K. Le Guin` through `_name` (author
score 1.0) and would not match it through `normalise`.

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
the first step exact where a source supplies one; the remembered spelling carries
the standard to a source that has no ids, which is every Google Books match; and
the residual one-human-three-rows case is answered by nothing but `[authors]`.

**Two corrections to this answer, both verified after the fact, both recorded
because the answer above is a decision and the corrections are facts.**

1. **The Pratchett case is not a same-id case.** It is two ids — 227859 `Terry
   Pratchett` and 1566154 `Terry David John Pratchett` — with two normalised keys
   (`terry pratchett`, `terry david john pratchett`). So it demonstrates a
   `[authors]` case and not the id rule. The id rule stands; the example that was
   given for it does not, and §2 now says so.
2. **The name key is stronger than `normalise` made it.** Under the old rule
   `LJ Ross` and `L.J. Ross` were different keys, so `[authors]` was carrying the
   ticket's own consistency test — which is the acceptance criterion, not a
   design that satisfies it. The maintainer's decision is to change `normalise`
   so runs of single letters collapse into one token: **all three Ross rows then
   reach one standard on the name key alone**, and `[authors]` is left as the
   merge for spellings that differ in their words. See "The normaliser change".

Neither correction changes the order in the first paragraph. The first narrows
what the id is demonstrated to do; the second narrows what `[authors]` is
required for. No committed recording shows one author id under two spellings, so
§2 records that the id-keyed read is insurance rather than an evidence-backed
path — and the maintainer confirmed it stays, because writing an id nothing reads
is worse than either alternative.

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
it reuses the folder rather than adding a mount. Three additions, the first
corrected by the maintainer after an earlier draft of this note got it wrong:

- **The default journal mode, and therefore no `-wal` or `-shm` siblings.** The
  earlier draft assumed WAL; the maintainer's decision is not to enable it — one
  connection and one writer does not need it — so nothing appears beside the
  record except the record. The file itself begins with a dot, so
  `Backups.expire()`'s existing skip covers it, and a test asserts that.
- **`record_path` should be documented as local disk.** On an SMB or NFS share
  SQLite's locking is unreliable, and `backup_dir` is a plausible thing for a
  user to point at a NAS. The line goes in `config.example.toml` beside the key.
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
   --reset-record`, which is what `__main__` already is. **It asks for
   confirmation, and `--yes` skips it for scripted use** (the maintainer's
   amendment): the record is never cleared automatically and a typo in a
   container's command line would otherwise wipe the spelling history of a whole
   library with nothing to recover from. The prompt reads the record's path and
   what is about to be lost, so the answer is informed rather than reflexive, and
   a non-interactive stdin is treated as "no" — but `--yes` is what a script
   should pass rather than relying on that. **It wipes the record only.** Books
   already in the library keep the spellings they were given; rewriting them is
   the "fixing an existing library" the design spec puts out of scope for v1, and
   a reset that silently rewrote a library would be a much bigger command than
   the ticket asks for. This needs `main()` to parse arguments it does not parse
   today, and the config must be loaded first because `record_path` is where the
   file is.
6. **Overrides are validated loudly, in three ways.** A `[authors]` value that is
   empty, or a key that is not a string, is a `ConfigError` at startup like every
   other setting — a table that silently does nothing is the failure mode this
   project refuses elsewhere. **And two keys that normalise to the same key with
   different values are a `ConfigError`, not a silent last-wins** (added by the
   maintainer): `"LJ Ross" = "A"` beside `"L.J. Ross" = "B"` is one name with two
   answers, and TOML gives no order to appeal to, so which one wins would depend
   on the parser. The check reuses `matching.normalise`, so it catches exactly the
   collisions the resolution itself would. **The resolution rule that goes with
   the table: one hop only — an override value is never re-resolved as a key.**
   `"A" = "B"` beside `"B" = "C"` writes `B`, not `C`; the second hop is the
   user's to write if they meant it, and a chain is a config nobody can read back
   off the page.
7. **`config.py` learns the `[authors]` table.** `_read_file` refuses unknown
   top-level settings, so `[authors]` is a `ConfigError` today. It becomes a
   field on `Config`, normalised and checked, like `fields`.
8. **The record is opened once and passed down**, from `Relay` to `Corrector`,
   the way `Backups` already is. Two connections to one SQLite file is how
   `database is locked` starts. **Confirmed by reading the code, because the
   maintainer asked: the relay is single-threaded.** `scan_once` walks the ingest
   folder and corrects each book in turn on the thread that called it, and
   `__main__.run` is a plain `while` loop over it; the only `threading` in the
   package is the `threading.Event` that stops that loop. No book is corrected in
   a worker thread, so one connection on the calling thread is safe and
   `check_same_thread=False` is **not** used — turning it off would hide exactly
   the mistake worth catching. **Written into the note so nobody adds a thread
   later without noticing**: if a worker thread is ever introduced, the
   connection has to move with it or be created per thread, and the tests will
   not catch it because a single-threaded test never trips the check.
9. **The record write is the relay's, after the file lands** (Q5). The correction
   returns a small record-ready value on the `Outcome` — the match's confidence
   and source, and each name written with the keys it resolved under — and the
   relay persists it on the one path where `copy_into_place` succeeded. The relay
   stores the decision; it does not re-derive it.
10. **`record_path` is a top-level config key**, so `COLOPHON_RECORD_PATH` works
    like every other setting, and it **should be documented as local disk**:
    SQLite's locking is unreliable on SMB and NFS, and `backup_dir` is a
    plausible thing for a user to point at a NAS. The note in `config.example.toml`
    says so beside the setting.
11. **SQLite's default journal mode, not WAL** (the maintainer's decision, and it
    supersedes an earlier draft of this note). One connection and one writer needs
    nothing more, and the default mode means **no `.colophon.db-wal` or
    `.colophon.db-shm` siblings in the backups folder at all** — nothing to
    protect from `Backups.expire()` and nothing to explain to a user looking at
    their backup folder. The record file itself still begins with a dot, so the
    existing skip covers it, and that is the one thing the test asserts.
12. **The record's public surface is what production reads** (added in the review
    session, applied). `standard()`, `match()` and `genres()` were deleted because
    no caller outside the tests used them; the tests read the table directly.
    `names()` stays, because the reset command counts what it is about to wipe
    with it. The migration marker comment went with them; the `user_version` guard
    stayed, because refusing a newer file is the mechanism and not the marker.

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
(`source='', key=normalise('L.J. Ross')`). The first says "this is a source row
the record already knows"; the second is what a source with no ids has, and what
every source falls back to. Both land on **one `standard` per name**, so the
first source to match an author fixes the spelling every later source reuses.

The rows are written together: the id row and the spelling row for one author
carry the same `standard`, so whichever lookup finds it gives the same answer. A
name that resolves at step 3 under a **new** id is written as an id row too, so
the row is always there for the next book — see "The write-side rule" below.

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
4 reached by the first source, in priority order, that matched the book. Step 3 is
what makes the standard follow an author from Hardcover to Google Books, and it is
the step the fixtures exercise (§2). Step 2 fires only when the source supplies an
id the record already has; no fixture reaches it, and §2 records why it is kept
anyway.

Series is the same shape with `kind='series'` and one difference: Google Books
has no series at all, so it reaches step 4 with nothing and can never introduce a
series name.

#### The write-side rule: a new id is anchored to the standard it resolved to

Step 3 resolving a name is not the end of it. **When a book arrives under a
source id the record has never seen, and the name lookup resolves to an existing
standard, the record stores that id against that standard.** With `normalise`
collapsing single-letter runs (§2), all three Ross rows now walk like this:

```
book A  hardcover, author id 318638 "L.J. Ross"
        step 2 misses, step 3 misses, so step 4 records:  standard 'L.J. Ross'
        keys: (hardcover, 318638), ('', 'lj ross')

book B  hardcover, author id 350233 "L. J. Ross"
        step 2 misses (350233 is new)
        step 3 finds ('', 'lj ross') -> standard 'L.J. Ross'
        writes 'L.J. Ross', and records (hardcover, 350233) -> 'L.J. Ross'

book C  hardcover, author id 350235 "LJ Ross"
        step 2 misses (350235 is still new)
        step 3 finds ('', 'lj ross') -> standard 'L.J. Ross'
        writes 'L.J. Ross', and records (hardcover, 350235) -> 'L.J. Ross'
```

**All three rows reach one standard on the name key alone, and each new row is
anchored to it by id as it arrives.** That is the ticket's consistency test
passing by design rather than by config, and it is why the id-keyed read stays:
book C resolving at step 3 and being *written* at step 2 is what makes the next
book from 350235 an id lookup instead of another normalise.

The id read still changes no outcome here — step 3 would have found the same
standard — and that is the honest statement of what it is for. It is reached the
first time a book arrives from an id whose spelling has drifted from the one the
record holds, which the fixtures do not yet contain. What `[authors]` is left for
is the shape the name key cannot reach at all:

```
book D  hardcover, author id 1566154 "Terry David John Pratchett"
        step 2 misses, step 3 misses ('terry david john pratchett')
        step 4 records a *second* standard: 'Terry David John Pratchett'

book E  hardcover, author id 227859 "Terry Pratchett"
        step 2 misses, step 3 misses ('terry pratchett')
        step 4 records a *third* standard: 'Terry Pratchett'
```

`[authors]` mapping `Terry David John Pratchett` to `Terry Pratchett` is what
collapses D onto E. Nothing about the id can: they are different rows, and the
only part of the API that could say otherwise — `canonical_id`, `alias_id` — is
null on both. So of the fixtures' two shapes, the name key merges one completely
and `[authors]` is needed for the other, which is what the tests have to
demonstrate — the non-merge first, so a later change that starts merging
different-words spellings fails rather than passing silently.

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
- **All three Ross rows reach one standard through the name key, with no config.**
  `L.J. Ross` (318638), `L. J. Ross` (350233) and `LJ Ross` (350235) from
  `authors-spelling-variants.json` all give `lj ross`, so the third book is
  written `L.J. Ross` with an empty `[authors]` table. **This is the test that
  makes the acceptance criterion pass by design**, and it is the one that fails
  today.
- **A new source id is anchored to the standard it resolved to.** A book whose
  author id the record has never seen, whose spelling resolves by name, stores
  that id against the standard — and the next book from that id resolves at step
  2. `authors-spelling-variants.json` supplies 350233 for it.
- **The id read is exercised.** No fixture reaches it through a spelling
  difference, so the test drives it directly: a record holding `(hardcover,
  318638) → L.J. Ross` resolves a candidate carrying that id even when the name
  key would miss. Without this the id column is written and never read, which is
  the thing the maintainer rejected.
- **The `[authors]` case, as the maintainer asked for it.** `Terry David John
  Pratchett` (1566154) and `Terry Pratchett` (227859) do not merge through the id
  or through the name key — `terry david john pratchett` against `terry
  pratchett` — and an `[authors]` entry is what merges them. The test asserts the
  non-merge first, so a later change that "helpfully" starts merging
  different-words spellings fails rather than passing silently.
- **`normalise` is what decides a key.** A test pins `L.J. Ross`, `L. J. Ross`
  and `LJ Ross` to one key, and `J.R.R. Tolkien` and `JRR Tolkien` to another, and
  pins the words that must **not** collapse: `Ursula K. Le Guin` stays
  `ursula k le guin`, and `1.0.0` stays `1 0 0` rather than becoming `10 0`. The
  whole cross-source behaviour rests on this and it is not obvious from reading
  the function.
- **The normaliser change does not move the title scores it already had.** The 36
  file-title/candidate pairs in the committed Hardcover recordings score exactly
  what they scored before, and `J.R.R. Tolkien` against `JRR Tolkien` goes from
  0.0 to 1.0. A regression test on the 36 is cheap and it is the guard that says
  the change was surgical.
- **Override precedence.** An `[authors]` entry beats a recorded standard; the
  record is unchanged afterwards; a two-hop chain resolves one hop only; a
  differently-punctuated key matches.
- **Two override keys that normalise together with different values are a
  `ConfigError`**, not a silent last-wins.
- **Duplicate re-lookup.** A recorded book, re-matched at a higher confidence,
  takes the new match and can raise a standard; at an equal confidence the
  configured source priority decides; at a lower one nothing changes.
- **The record has no series number.** Asserted against the schema, so a later
  ticket cannot add one quietly.
- **`Backups.expire()` never deletes the record**, and the record has no `-wal`
  or `-shm` sibling to worry about because WAL is not enabled — asserted as "the
  backups folder holds exactly the record", not by naming a file that should not
  exist.
- **A record a build does not know the version of is refused**, not upgraded.
- **The reset wipes it**, and the next book starts a fresh standard.
- **The reset asks before wiping**, and `--yes` skips the question; a reset with
  no stdin and no `--yes` changes nothing.
- **Nothing is recorded on a dry run, on an unmatched book, or on a correction
  the relay never delivered.**
- **One connection on one thread.** A test that calls the record from a second
  thread is asserting nothing about production, but a test that constructs the
  record and drives a whole `Relay` passes only while `check_same_thread` stays
  at its default — which is the reminder the note asks for.

## Fixtures this session recorded

Committed, with the two READMEs saying which are read by a test and which are
not. No test reads any of them yet.

| Fixture | What it pins |
| --- | --- |
| `hardcover/by-isbn-{cragside,berwick,the-infirmary}-authors.json` | same author id, same series id, three books, and the same spelling on each |
| `hardcover/author-lj-ross.json` | the row itself: no alternate names, no canonical, no alias |
| `hardcover/authors-spelling-variants.json` | one human, three rows, unrelated to each other — and all three merging through `normalise` once it collapses single-letter runs |
| `hardcover/works-good-omens-authors.json` | two rows for one human under two keys, one of them a fuller spelling, and authors in two orders |
| `googlebooks/by-isbn-cragside-authors.json` | Google's own spelling, `L. J. Ross` |

**None of the seven is an LLM reply.** Six are Hardcover API responses and one is
a Google Books response — the only HTTP calls whose bodies were written here.
Every DeepSeek reply the LLM section rests on stayed in `.tmp/` and is **not**
committed, because no test would read it; the numbers are in §5 and on
CBO-53/CBO-54. Nothing in `tests/fixtures/` changed under `llm/`.

Two Google Books title recordings — the same Cragside search with `LJ Ross` and
with `L.J. Ross` — were made and **not kept**: both answers are
`by-title-cragside.json` again with a different `etag`, and that README already
states the property they would show.

## What this ticket does not build

CBO-42's genre mapping and the allowed-genres list itself; CBO-43's retry window
and rejected-key hold; CBO-46's AI-guess mode; and the LLM name job (Q2). The
`genres` table is created empty on purpose so CBO-42 has somewhere to put its
list without changing this ticket's schema.

## As built (2026-09-20)

Built in the order below, one commit each. Every decision in this note is in the
code; the four places the build departed from it are at the end, and each is a
smaller change than the note asked for rather than a larger one.

1. **`colophon/matching.py`** — `normalise` joins runs of initials. The rule it
   settled on is narrower than "join runs of single letters", and the note's
   "The normaliser change" section was rewritten twice: once from the built code,
   and once more when a look-ahead the first draft described was measured and
   found to change nothing. The shipped rule is the one in that section: **a
   one-letter word joins the token before it only when that token is itself a
   one-letter run**, and a token carries whether it is a run so a lone initial
   before a word cannot be mistaken for one.
2. **`colophon/record.py`** — the schema, `user_version`, `resolve`, `save`,
   `reset`, `names`, `standard`, `match`, `genres`, and `book_key`.
3. **`colophon/config.py`** — `record_path` and `[authors]`, the latter keyed by
   `normalise` and refused when two keys collide with different values.
4. **`colophon/hardcover.py`** — both queries ask for `author { id name }` and
   `series { id name }`, and `_author_rows` is the one place that decides what
   counts as an author, so the names and the ids cannot describe different
   people.
5. **`colophon/correction.py`** — `Standards` and `Decision`; `_standards`
   resolves the names and `applied_to` puts them on the candidate before
   anything is decided from it, so the log line, the backup and the book all name
   one spelling; `_decision` carries the match to the relay.
6. **`colophon/relay.py`** — `_remember`, called after `copy_into_place` and
   before the log line.
7. **`colophon/__main__.py`** — `--reset-record` and `--yes`.

Tests: 638 in the suite, 2 skipped. New files are `tests/test_record.py` (33)
and the record classes in `tests/test_correction.py`, `tests/test_relay.py`,
`tests/test_config.py`, `tests/test_main.py` and `tests/test_matching.py`.

### Three places the build is narrower than the note

- **The `genres` table is never written**, as decided (Q7); the migration
  scaffold is a `user_version` guard and a comment marking where a step goes,
  rather than an empty list of steps. A first schema needs nothing to migrate
  from, and the guard is the part that protects a user's record from an older
  build.
- **`_name` is unchanged.** It already collapsed both `LJ Ross` and
  `J.R.R. Tolkien` to one token, which is why the ticket's problem was never
  matching. `record.py`'s module docstring and `_name`'s own docstring both say
  why the two normalisers are separate and which may over-merge.
- **A per-save connection is not opened by the record.** `Record.open` is called
  once by `main` (or by a test) and the connection is passed down as the note
  says; `Relay` closes nothing, because it did not open it.

### Where the build first departed from the note, and was sent back

`book_key` was built as the ISBN else the normalised **title only**, and review
rejected it. The reasoning that produced the narrowing — "the ISBN alone makes
every ISBN-less book one row" — argues for *adding* the title, not for dropping
the author; and a title-only key collides where it matters, because *The
Infirmary* is two books by two authors and the higher-confidence rule would let
the second match silently replace the first's in a store nothing clears. It is
now **ISBN, else normalised title + author**, with a test asserting two books
sharing a title under different authors produce two rows, and another for the
book that has neither an ISBN nor a title. The note's original wording was
right and the build is what moved.

### What the note said that the build proved wrong

Two things, both now corrected in place, with the numbers the review asked for:

- **The blast radius was "6 of 394 strings"**, and that figure came from the
  broken prototype — the one whose word-splitting concatenated whole
  descriptions, and which therefore also made a version string look safe when it
  was not. **The corrected measurement, taken against `main` with the shipped
  `normalise`:**
  - **0 of 28 distinct title keys** in the fixture set move. Every cleaned title
    the fixtures contain keys exactly as it did before.
  - **0 of 36 file-title/candidate pairs** change their score or their `agrees`
    verdict. So no match the project already makes is decided differently.
  - **4 of 11 author spellings move**: `L.J. Ross` and `L. J. Ross` onto each
    other's key, and `J.R.R. Tolkien` and `J. R. R. Tolkien` onto `JRR Tolkien`'s.
    Those four moving is the entire point of the change; nothing else does.
- **The look-ahead rule the note described was dead code.** Implemented,
  measured, and removed: it changes no answer for any arrangement of one-letter
  and word-shaped tokens up to five long. The section above now states the rule
  as the code implements it.

**Where each number came from, since one of them was doubted:** the 0-of-36
figure was never the prototype's. It comes from scoring the project's own
file-title/candidate pairs with `score_candidate` under each `normalise`, which
is a measurement of the shipping comparison and not of any rewritten helper. It
has since been re-run against the built `normalise`, not the proposed one, and
still reads 0 of 36. The only number the broken prototype produced was the
"6 of 394", which is withdrawn.
