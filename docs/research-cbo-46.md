# CBO-46 research: AI-guess mode

Research only. Nothing was built, committed or pushed, and no file was written into the repo.

- **Commit read:** `main` at `593f14a0e620b9bba782c283be15caa09685f0e2` (2026-09-22, "Merge pull request #17 from Cbow2018/dsh/cbo-73-title-query-isbn").
- **Where:** this session wasn't linked to your computer, so I couldn't reach `A:\Documents\GitHub\colophon`. I read a fresh clone of `Cbow2018/colophon` in the cloud workspace instead (`git switch main && git pull` reported "Already up to date"). `git status` is clean there. Your local checkout wasn't touched.
- **Tickets read:** CBO-46 (plus its one comment), CBO-40, CBO-39, CBO-43, CBO-79, CBO-82, CBO-55, CBO-61, CBO-62, CBO-53, CBO-54, CBO-45 and CBO-85.
- **Live calls:** none.

The design below assumes the combined build: CBO-43 (with 10.2 and 10.5), CBO-61 and CBO-45 have landed. CBO-55 is optional. CBO-62 is post-v1.

---

## 1. What CBO-40 already gives you

**The client (`colophon/llm.py`).** It has one `Llm` class with two questions: `choose()` (the chooser) and `map_genre()` (CBO-42). Both do the same four things:

1. `_spend()` checks the daily counter.
2. `_post_json()` sends the request.
3. `_refuse()` turns a non-2xx status into a failure.
4. `_content()` reads the reply, returning `None` for anything that isn't a JSON object, including `finish_reason: "length"`.

Each question builds its own payload: `model`, `messages`, `response_format: json_object` and `max_tokens: 256`. The payload has **no `temperature`**, and that's deliberate (see §4).

**The presets.** There are seven. Only DeepSeek (`deepseek-flash`) has ever been called:

- Gemini (`gemini-3.8-flash`) and Groq (`openai/gpt-oss-120b`) are reasoning models. They may truncate at 256 tokens. That's CBO-53, unmeasured.
- Anthropic ignores `response_format`, and OpenAI, OpenRouter and Ollama are unconfirmed. That's CBO-54.

**The prompt structure.** The system prompt holds the contract, and it says **"Never invent metadata."** The user message is the file's title, its filename and a numbered candidate list (`_describe`: title, author, series, position, year, publisher, isbn, language). The candidate list is declared to be data, not instructions. The reply is `{"pick", "confidence", "reason"}`, and anything else counts as null. There's no fence-stripping.

**`llm_full_scan`** (default on) only widens *which non-strong books* reach the chooser: low and none as well as medium. A strong pool, or an ISBN hit, never calls the LLM (`correction.py:374-392`).

**The daily limit.** `llm_daily_limit`, default 200, is kept in one durable counter file, `/backups/.colophon-llm.json`. It's spent **before** each request, and failed requests count too. The chooser and genre mapping already share it.

### Can the guess ride on the chooser call?

**No. It needs its own call.** There are four reasons:

1. **The chooser mostly doesn't run on the books that need guessing.** Strong books and ISBN hits are most matched books, and they never call the chooser. A piggy-backed guess would only ever reach LLM-picked books.
2. **The chooser runs too early.** It runs before a winner exists, so before CBO-61's gap fill, and "missing" can't be known yet (§2). The model would have to guess for whichever candidate it picks, before gap fill has had its turn.
3. **The contracts conflict.** The chooser's prompt forbids inventing metadata. The guess prompt asks for it. Merging them weakens the one guard that keeps the chooser honest.
4. **One failure would cost both answers.** A bigger reply raises the CBO-53 truncation risk, and `_content()` nulls the whole object. A bad guess would then cost the book its *pick*, which means a matched book lands unverified.

**Size and cost.** Guessing is one extra call per eligible book, and only when a guessable field is actually missing after gap fill. With the field list recommended in §2, that's rare:

- Hardcover usually carries series positions, and Google Books has no series at all, so a number isn't asked for there.
- Most records carry a date.

So the typical run spends very few guess calls. The eligibility check (§2 and §3) is pure and free, so a book with no gap costs nothing.

---

## 2. What "missing" means, and which fields are guessable

### Definition

A field is **missing** when all four of these hold:

1. its `[fields]` rule isn't `skip`;
2. **every configured source has answered for this book**;
3. after CBO-61's gap fill, the winning record still has no value;
4. the file carries no value of its own. A value that is itself a previous guess counts as none (§5).

Condition 2 is stricter than it looks. **Two paths on `main` stop before every source has answered:**

- **The ISBN path** stops at the first source that has the edition (`_by_isbn`, `correction.py:304-313`).
- **The title path exits early** on a strong pool (`_gather`, `exited`, `correction.py:445-452`).

So a Hardcover hit that has no date has never been checked against Google Books, which usually does have one. Guessing there would mean guessing a value a source *does* supply.

**Proposal:** when the winner has a guessable gap, the gap-fill step first asks the sources that weren't reached, by ISBN on the ISBN path and by title on the title path. Their replies are used only as CBO-61 donors (strong-band, fill-only), so the winner doesn't change and the matcher and scoring aren't touched. This extends CBO-61's scope, so it's flagged as decision D4. It costs a source query only on books that have a guessable gap.

### Every field in `FIELD_DEFAULTS`

| Field | Default rule | Guessable? | Why |
|---|---|---|---|
| `title` | overwrite | **No** | This is identity. A match always has one, and guessing it would be CBO-55's job. |
| `authors` | overwrite | **No** | This is identity, and it feeds the author gate and the record's standards (CBO-41). |
| `series` | overwrite | **Yes (decided)** | Absence is often the *correct* answer, because standalone books have no series, so abstaining matters most here. Settled rule: check the record first. A guess matching a known series (by `normalise`d name) is written in the library's spelling. A new name is written as given but **never saved to the record**, so an invented series can't become a library-wide spelling. |
| `series_number` | overwrite | **Yes, conditionally** | Only when the book's *resulting* series is non-empty (from a source, or from the file when the series is `skip`). A number without its series is meaningless (`_series_consistent`), so the model is never asked for one on its own. |
| `description` | fill | **No** | A guessed blurb is invented prose, not a missing fact. |
| `publisher` | fill | **Yes (decided)** | Edition-specific: the model tends to answer with the original publisher. Accepted with shape validation only (§4). The record holds nothing for publishers, so nothing can check it. |
| `date` | fill | **Yes, as a year only** | Ask for `YYYY` and write `YYYY` (a valid `dc:date`). Month and day are where invention is worst, and FB2 keeps only the year anyway (CBO-46 comment, CBO-45 §2). Caveat: the model's year means first publication, while a source's date may be this edition's. |
| `isbn` | fill | **Never** | It's an identifier: checkable, and a key for matching and the record (`book_key`). |
| `language` | fill | **Never** | It's checkable from the text itself, which is deterministic and needs no LLM. The file almost always has one. |
| cover (`add_cover`) | n/a | **Never** | This is binary, and the model can't supply it anyway. |
| genres (`allowed_genres`) | n/a | **Out of scope** | CBO-42 already maps them. Not a gap to guess. |

**Decided guessable list: `series`, `series_number` (with a series from a source or from the same guess), `date` (year only) and `publisher`.** When the series is guessed, its number is asked for in the same call. If the number comes back null, the series is still written, with no position.

---

## 3. Which books are eligible

A book is eligible only if it is **written from a match, and every source answered for it**. That covers:

| Book | Eligible? | Notes |
|---|---|---|
| Strong, by the rules (title path) | **Yes** | After the §2 top-up if it exited early. |
| Exact ISBN hit | **Yes** | After the §2 top-up. |
| Medium, then an LLM pick at or above `strong_score` | **Yes** | The medium book is written only because of the pick. This stacks two LLM judgements, but the pick already passed the same gate. |
| Medium, then no pick or a pick below the gate | No | It takes the unverified path. |
| **Unverified** (CBO-39) | **No new guess** | See below. |
| Held (CBO-43 temporary, `llm_retry`, rejected key or config, CBO-81) | No | Nothing is written. |
| Passed through `colophon:source-unavailable` (CBO-80) | **No new guess** | Written with its original metadata. There's no match. |
| Written by the fallback, `colophon:incomplete` (CBO-82) | **No new guess** | By definition not every source answered. The missing source may well have the value, and Hardcover's series is exactly what's missing from a Google fallback. Guessing here would fill the very gap the tag exists to flag, and the next full match would then have to undo it. |

**Guessing on an unverified book.** There's no matched record, so the only basis would be the file's own claims. Those are exactly the claims Colophon just failed to verify. A guess would build a guessed value on an unconfirmed identity: a series number for a book nobody has identified. Nothing checks it, and nothing would ever remove it, because no source will ever supply the field for a book no source recognises. **Recommendation: never.** If an unmatched book should get help from the LLM, that's CBO-55's job: identify it first, and then it can become eligible.

**Combinations.** No path proposed here *creates* `ai-guess` alongside `unverified` or `incomplete`. Both combinations can still arise from **carry-forward** (§5): a book guessed earlier and then re-dropped keeps its guessed values in the file, whatever this pass concludes. If this pass ends unverified or incomplete, the guess mark must stay. Dropping it would launder the guess. What each combination means:

- **`ai-guess` + `unverified`:** "Colophon couldn't verify this book this time, and fields listed as guessed are left over from an earlier guess." Rare, and honest. It tells you not to trust those fields twice over.
- **`ai-guess` + `incomplete`:** "Written from partial sources during an outage, and it still carries earlier guesses." The next full match either confirms the fields (the guess is removed) or leaves them missing (the guess is kept).
- The user doesn't need to learn a new meaning: each tag keeps its own meaning independently.

---

## 4. Hallucination controls (design only)

### Input

- **The winning record after gap fill:** title, authors, the resulting series, and the fields already present (year, publisher, ISBN, language), in `_describe`'s format.
- **The winning record's description, capped at about 1,000 characters.** Blurbs often say "the third book in…". Take any Colophon note off it first (`unmarked`), and declare it data, not instructions, the same way the candidate list is.
- **The list of fields to fill.** Only the missing guessable ones.
- **Not** the other candidates. Choosing values from them is CBO-62's job (§7), and CBO-61 has already refused medium donors on purpose.
- **Not** the filename, and not the file's own metadata. The winner is what was verified.

### Abstention is required and is the default

The prompt says null is the expected answer whenever the model doesn't *know*. It also says that a standalone book has no series number, and that a plausible value is worse than null. CBO-40 measured self-reported confidence clustering at 0.98 to 1.0 across all 14 runs (CBO-40 note §3). The confidence gate therefore barely discriminates, and **null is the real control**, not the number.

### Contract

The reply is one object:

```json
{"series": "<name>" or null, "series_number": <number or null>, "date": "<YYYY>" or null, "publisher": "<name>" or null, "confidence": <0-1>, "reason": "<short>"}
```

It contains only the keys that were asked for, and one confidence covers the whole reply. The confidence gate is `strong_score`, the same bar the chooser's pick is held to (CBO-40 Q4/Q5). There's no new setting.

### Validation per field (anything else counts as null for that field)

- **`series_number`:**
  - an int, or a string matching `^\d{1,3}(\.\d{1,2})?$`;
  - `bool` is refused, the same guard `_choice` uses;
  - range 0 to 999 (0 allows prequels);
  - written through `epub._position`;
  - never accepted when no resulting series was sent.
- **`date`:**
  - a string matching `^\d{4}$` only, so a full date is refused rather than truncated;
  - a year from 1450 to the current UTC year.
- **`series`:**
  - a trimmed string of 1 to 200 characters, with no line breaks;
  - resolved against the record's series names first (known name → the library's spelling), otherwise written as given;
  - never filed as a record standard.
- **`publisher`:**
  - a trimmed string of 2 to 100 characters, with no URLs and no line breaks;
  - not a placeholder ("Unknown", "N/A", "Self-published" and the like);
  - not resolved against the record, and never saved to it.
- **Keys and shape:**
  - a key that wasn't asked for is ignored;
  - a key that was asked for but is absent counts as null;
  - a malformed body or a reply wrapped in prose or fences counts as null for everything (no fence-stripping, as in CBO-40).

### Determinism

- **Send no `temperature`, and no `seed` or `top_p` either.** CBO-40 Q21 omitted `temperature` because a reasoning model that rejects it returns a configuration 400. Under CBO-43 that is now *held like a rejected key* (CBO-81): **every book held and the container unhealthy.** The measurement also showed `temperature: 0` didn't stabilise the reply. The same argument is stronger now.
- **Determinism comes from asking once instead.** A guess is asked for once per book and then carried forward in the file (§5). It is never re-asked while the mark stands.
- **What remains:** two separate drops of the same *original* file can still get different guesses. That breaks the byte-equality duplicate detection that cbo-58 §3.6 calls a hard requirement. The chooser already accepted the same trade-off (CBO-40 Q6), and this mode is opt-in. Flagged as D14.

### Known behaviour by preset (CBO-53 and CBO-54, all unmeasured)

The guess reply is a little larger than the chooser's (which took 29 to 86 tokens).

- **Gemini and Groq:** reasoning tokens may exhaust `max_tokens: 256`, giving `finish_reason: length`, which counts as null. The guess is silently lost; it's safe, but it doesn't work.
- **Anthropic:** may wrap the reply in prose or fences, which counts as null.
- **Ollama `llama3.1`:** JSON mode is unconfirmed, and it's the model most likely to invent a value that looks plausible.
- **The ask:** CBO-53 and CBO-54's probes should also send the guess prompt, not just the chooser's.

---

## 5. The guess on the next run

### Could a guess be laundered? Yes, on `main` as it stands.

- **`date` feeds matching.** `FileBook.date` is the file's `dc:date` (`correction.py:363`), and `score_candidate` compares years at `YEAR_WEIGHT` 0.15 (`matching.py:430-432`).
  - A wrong guessed year takes about 0.077 off the true record. A perfect 1.0 drops to 0.923, and with any imperfection in the title it slips out of the strong band.
  - A matching guessed year dilutes the other penalties, which can also lift a lookalike.
- **`date` blocks the source's value.** Its rule defaults to `fill`, and `_edits` skips a `fill` field the file already carries (`correction.py:1204-1205`). A guessed date therefore stops any source from ever writing the real one. **That's the laundering.**
- **`series_number` doesn't feed scoring.** The file's position is read only from a bracket in the title (`_parts_of`), never from `calibre:series_index`. It does feed `_series_consistent`, and under a `fill` rule it would block the source's number in the same way. Under the default `overwrite`, the source wins when it has a value.
- **The record** (`record.py`) never reads a metadata value, and its docstring rules out "a series number anywhere". Guesses must stay out of it, so the record can't be where the provenance lives.

**Rule:** when a field is marked as guessed, it is **treated as absent everywhere the file's own value is read**:

- it's left out of `FileBook` (so it isn't matched on);
- it counts as empty for `fill`;
- it's ignored as "the file's number" in `_series_consistent`.

This follows the same pattern CBO-39 used for the note, where `unmarked()` runs *before* the rules.

### Where the record of guessed fields lives

It has to be **in the file**. The file is what comes back on a re-drop, often as a copy exported from Calibre or CWA. The SQLite record is keyed by `book_key`, which comes from the file's *original* title and authors (`_decision`), so the key goes stale once a book is corrected. The record is also optional, and it's forbidden from holding values. There are three ways to carry the list in the file:

| Carrier | Survives a Calibre round trip? | Readable by people? | FB2 |
|---|---|---|---|
| **A. Tag plus a description note**, e.g. `Colophon's AI guessed: series number, publication year.`, built from a fixed vocabulary so it can be parsed | Yes. Tags and comments are what Calibre keeps. | Yes. It mirrors CBO-39's "find it without reading logs". | Needs an `<annotation>` sentence. **This reopens CBO-45's decision of "no description sentence" for `ai-guess`.** |
| B. The tag plus per-field tags (`colophon:ai-guess:date`) | Yes | Cluttered | Fits CBO-45's rule unchanged |
| C. The tag plus an OPF `<meta>` / FB2 `<custom-info>` | **Probably not.** Calibre regenerates the OPF from its database. Unmeasured. | No | Custom-info |

**Recommendation: A.** This is D6.

### Removal, mirroring CBO-39

CBO-39's mark is **recomputed every pass, not remembered**. The guess mark keeps that rule, with this recomputation:

> guessed set = (fields previously marked as guessed that are still in the file **and** that no source supplied this pass) ∪ (new guesses this pass)

The tag and the note are written if and only if that set isn't empty. The note is rewritten to list exactly that set.

When a source supplies a guessed field, it writes its value regardless of `fill`, because the guess counted as empty. The field then leaves the set, the note shrinks, and when the last field goes, the tag and the note come off together.

**A field still missing is carried forward, not re-asked.** That costs no call, and a drop reproduces the same bytes.

### Where CBO-39's logic doesn't fit

1. **The mark carries data, not just on or off.** The note's text changes as the set changes, so it needs a parser and a formatter, not just `_NOTES` matching at the end of the description.
2. **Removal is per field.** It isn't "any successful match". A full match with the field still missing keeps the mark.
3. **The unverified path has to carry the mark.** `_write(found=None)` writes only the unverified mark today, and here the guess mark has to survive it too (§3).
4. **What each half means on its own.** CBO-39 says either half is enough to count as a mark. For guesses, the *note* is the list. A tag without a note (a person or a tool deleted the note) should count as **every guessable field present in the file** being guessed. That's conservative, and the note is written back on the next write. A note without a tag (the user deleted the tag) is the harder case. Recommendation: the note alone still counts as the mark, so it's consistent with CBO-39. To accept a guess, the user deletes both. This is D7.
5. **Two notes on one description.** CBO-39 requires the unverified note to be **at the end**. When both are present, the guess note goes before it. Stripping takes the unverified note off first, then the guess note.
6. **A user correction looks like a guess.** If the user fixes a guessed value in their library but leaves the mark, Colophon still reads it as a guess, and a later source value replaces it. That's documented behaviour: to accept or fix a value, remove the mark.

---

## 6. The daily limit

- **One budget.** A guess spends the same `_spend()` counter as the chooser and genre mapping, as the ticket requires. It isn't counted separately.
- **Order within a book:** walk, then chooser, then gap fill, then guess, then write. A book's own chooser call always comes before its guess, so a guess can't starve its own book.
- **The limit is hit during a book's walk:**
  - If the **chooser** call is the one refused: this is unchanged, and the book waits (and under CBO-43 it goes to `llm_retry`).
  - If the **guess** call is refused: **write the book without the guess.** No `ai-guess` tag, and nothing is recorded. This follows `_map_genres`'s precedent (`correction.py:1024-1033`): "a tag on a book the rules already resolved is not worth holding that book for a day". It's a matched book waiting on optional enrichment.
- **A 402 under `llm_retry`.** CBO-79 and CBO-82 scope `llm_retry` to books *waiting on the LLM*, meaning the chooser. A book that only needs a guess is **written without the guess**, not held. Holding a verified book for up to 24 hours for a series number is the wrong trade.
  - The cost: the book reaches the library without a guess, and it only gets one if it's re-dropped.
  - A rejected key or a configuration 4xx is different. CBO-81 holds every book anyway, and the guess payload has the chooser's shape (no extra parameters), so it can't trigger that class of failure on its own.
- **Starving other books.** Guesses can spend calls that a *later* book's chooser needed. That book then waits a day, which is recoverable. A skipped guess isn't recoverable. **No reserve in v1** (D11). Revisit it if the logs show guesses crowding out chooser calls.
- **Dry run:** no guess call (the genre precedent). The line says "would ask the LLM to guess: date".

---

## 7. Scope boundaries

| | Book state | What the LLM supplies | Where the values come from |
|---|---|---|---|
| **CBO-55** | **Unmatched** (before the unverified path) | A **search query** | Sources, through the normal matching |
| **CBO-62** (post-v1) | Matched, several candidates | A **choice per field** among candidates' values | Some source that published it, as a composite |
| **CBO-46** | **Matched**, every source answered, after gap fill | **A value no source has** | Nobody. It's marked as a guess. |

The line between them: **55 finds the book, 62 picks between published values, 46 invents what nobody published.** Each has its own tag or no tag.

**Things more than one ticket needs:**

- **A generic `Llm._ask(system, user) -> dict | None`** that does spend, post, refuse and `_content`. `choose` and `map_genre` already duplicate the payload building, and 46 and 55 would make it four copies. Whichever lands first builds it (D16).
- **Blurb-as-data framing plus a cap:** 46 sends the winner's blurb, and 55 sends the file's. Same helper. Strip Colophon's notes first, in both.
- **Per-field provenance.** CBO-61 needs it to log donors. CBO-46 needs it to credit `date="1998"<-ai-guess`. CBO-62 names it as its prerequisite. **CBO-61 should own a per-field provenance map on the merged record.** CBO-46 then only adds one more value.
- **Opt-in experimental flags** follow the same pattern in 46 and 55.

**What should move:**

- **Topping up sources that weren't asked before a guess (§2)** belongs in **CBO-61's** gap fill, not in 46.
- **Guessing a series *name*** stays in 46 (decided). The guard that keeps it from becoming identification is the record check with no write-back.
- **Using medium candidates' values** belongs to **CBO-62**. Keep other candidates out of 46's prompt, or 46 quietly becomes 62 without the provenance that 62 insists on.
- **CBO-55's open question** about its own tag: a book it identifies becomes eligible for 46 like any match. If 55 adds a tag, it combines with `ai-guess` independently.

---

## 8. The tag across formats

- **EPUB/KEPUB:** `colophon:ai-guess` fits the existing rule **unchanged**.
  - It's one `dc:subject` with exactly the tag as its text, added after the book's own subjects, never duplicated, and every exact copy removed on the way off.
  - `_own_subjects` already filters the `colophon:` prefix out of `Book.subjects`, so genres never see it. CBO-85 stops an allowed genre from colliding with it.
  - Build: generalise `_set_unverified_tag` / `_unverified_subjects` to take the tag as an argument.
- **FB2 (CBO-45):** the *tag* also fits unchanged. It's a `<genre>`, and the CBO-46 comment already records that. It's schema-invalid (the genre enum is closed), but Calibre round-trips it, the same as for `unverified`.
  - **Resolved:** carrier A was chosen (D6), so FB2 also carries the guessed-fields sentence in `<annotation>`. This is added to CBO-45's acceptance criteria, and the earlier "no description sentence" comment is superseded. The FB2 side isn't designed here.

---

## Decisions (grilled 2026-09-23)

| # | Decision | Settled |
|---|---|---|
| D1 | Own call or ride the chooser | **Its own call**, only when a guessable gap exists after gap fill. |
| D2/D3 | Guessable fields | **`series`, `series_number`, `date` (year only), `publisher`.** Never: title, authors, ISBN, language, cover, description, genres. |
| D2a | Checking a guessed series | **Record first, then as given.** A known name is written in the library's spelling. A new name is written as the model gave it and never saved to the record. Accepted knock-on: two books guessed into one *new* series may get two spellings until a source supplies it. |
| D2b | A series and its number | **One call.** The series is written even if the number is null. |
| D2c | Publisher validation | **Shape only**: 2 to 100 characters, no URLs or line breaks, no placeholders. Not saved to the record. |
| D4 | Every source asked before guessing | **Yes.** Done inside CBO-61's gap fill: when a guessable gap remains after the ISBN path or an early exit, the sources not yet asked are queried, and their answers are used only to fill gaps (the donor rule). |
| D5 | Eligibility | **Books written from a match with every source answered** (strong, ISBN, LLM pick). Never unverified, incomplete, source-unavailable or held. Existing marks are carried whatever the outcome. |
| D6 | Where the list of guessed fields lives | **The tag plus a description note that Colophon can parse.** For FB2 this means a sentence in `<annotation>`, which is added to CBO-45 (still in Backlog). |
| D7 | What each half of the mark means on its own | **Tag without note: every guessable field present counts as guessed. Note without tag: still counts as the mark.** To accept a guess, remove both. |
| D8 | The next run | **Carry the guess forward with no new call.** It's removed field by field when a source supplies the value. The tag and the note come off when the list is empty. |
| D9 | Mode turned off | **No new guesses**, but existing marks are still carried and removed. |
| D10 | Limit, outage or 402 during the guess | **Write the book without the guess.** No hold, and not put under `llm_retry`. The chooser's own wait is unchanged. |
| D11 | Budget reserve for the chooser | **None in v1.** |
| D12 | Confidence gate | **`strong_score`.** No new setting. |
| D13 | Prompt input | **The winner after gap fill, the resulting series and a capped blurb with the notes stripped.** No other candidates, no filename, no file metadata. |
| D14 | Determinism | **No `temperature`, `seed` or `top_p`.** Accept that separate drops aren't deterministic. |
| D15 | Dry run | **No call.** It logs "would ask". |
| D16 | Shared pieces | **`Llm._ask`** is built by whichever of 46 and 55 lands first. **Per-field provenance** is owned by CBO-61. |
| D17 | Log credit | **`field="x"<-ai-guess`**. |
| D18 | Setting | **`ai_guess = false`** / `COLOPHON_AI_GUESS`, marked experimental. |

## Build tickets (created 2026-09-23)

- **CBO-86** 13.1: the `colophon:ai-guess` mark, tag and field note in EPUB/KEPUB. Not blocked.
- **CBO-87** 13.2: guessed fields count as empty; carry forward and per-field removal. Blocked by CBO-86.
- **CBO-88** 13.3: the guess question in `llm.py`, with its contract and per-field validation. Not blocked.
- **CBO-89** 13.4: wire AI-guess mode into the correction pass. Blocked by CBO-86, CBO-87, CBO-88, CBO-61 and CBO-82.

Linear also updated: the decisions were added to CBO-46; the FB2 `<annotation>` sentence was added to CBO-45's acceptance criteria; comments went on CBO-61 (the source top-up and per-field provenance), CBO-53 and CBO-54 (probe the guess prompt too), and the earlier FB2 comment on CBO-46 (now superseded in part).
