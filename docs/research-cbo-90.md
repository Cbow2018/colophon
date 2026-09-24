# CBO-90: the title path can write an Audio Edition's ISBN, publisher, date and cover into an EPUB

Research only, 2026-09-24. Grilled with Callum (`grill-with-docs`: grilling +
domain-modeling), Q1–Q15. Measured against `main` at **`22f456b`** (CBO-74 merged),
read from a throwaway clone of `Cbow2018/colophon` in a scratch directory outside
the repo; nothing in any working tree was changed. CBO-68's session 1b material
(`research-cbo-68.md` §0, `cbo-68-build-brief.md` D15–D24,
`adr-draft-standard-edition.md`, `context-additions-cbo-68.md`) was read from this
folder, because PR #18 on GitHub is still at `728c7ea` and does not carry it.

Vocabulary: **Work**, **Edition**, **Standard Edition** (CBO-68) and **Reading
Format**, **Audio Edition** (this session, `cbo-90-context-draft.md`).

## Answers, in the order asked

| # | Question | Answer |
| -- | -- | -- |
| 1 | How often is a format present on Hardcover title-path replies? | **0 of 13** title-path Editions in the committed fixtures (0 of 32 across every Hardcover fixture), because no shipped query has ever asked for one. The live rate is **deferred to the build session** (Q1 = d), behind a gate (§5). |
| 2 | The rule | **Audio Editions are excluded before D15 chooses the Standard Edition.** D15's order is untouched; print Editions stay eligible. The signal is `reading_format_id` = 2, not `edition_format`. |
| 3 | Does the ISBN path's title fallback carry the risk? | **For the ISBN, not under the default rule; for publisher, date and cover, yes.** And a direct ISBN hit on an Audio Edition carries it too (§3). Both are closed by the same rule. A separate `isbn = "overwrite"` gap is raised as **CBO-92**. |
| 4 | CBO-65, CBO-91 | Notes only (§4). |

---

## 1. What the code does today

**The Edition supplies four written fields, not three.** `hardcover.py:_candidate`
(`:276`) takes `isbn`, `publisher` and `date` from the Edition, and
`cover=_image(edition) or _image(book)` (`:314`) — so the **cover** is the
Edition's too. The ticket names three; an audiobook's cover is square, and it is
added under the default "add only if the book has none" rule.

**`main` writes the Audio Edition for *The Infirmary* today.** `_candidates`
(`:351`) keeps the first Edition per `book.id` in reply order. In
`hardcover/by-title-the-infirmary.json` the first Edition of work 1198266 is:

| Edition | Publisher | `release_date` | Work |
| -- | -- | -- | -- |
| `9781799729945` | Audible Studios on Brilliance | 2019-02-10 | 1198266 |
| `9781912310111` | Dark Skies Publishing | 2019-02-10 | 1198266 |
| `9781792780844` | Independently Published | 2019-01-01 | 1198266 |
| `9781408733363` | Hachette UK | 2025-10-09 | 2284109 (Reagon) |

The query has no `order_by`, so which of the three is written varies (CBO-68 §0.3:
3 distinct outcomes in 100 shuffles). D12 + D15 make it `9781792780844` every time
— **by luck of dates**, as the build brief §6 says.

**`fill` does not protect a file that has no value.** `isbn`, `publisher` and
`date` default to `fill` (`config.py:67–77`); a title-path file carries no ISBN by
definition, so the Standard Edition's ISBN is written.

**The repo itself treats the audiobook ISBN as *The Infirmary*'s ISBN.**
`tests/recordings.py:54` `THE_INFIRMARY_ISBN = "9781799729945"`, used by
`by-isbn-9781799729945-genres.json` (read by
`test_hardcover.py:651`, CBO-42) and `by-isbn-the-infirmary-authors.json` (read by
no test; CBO-41's README). That is the real-world shape of the risk: an ISBN
lifted from a lookup and carried into ebook metadata.

## 2. Hardcover's format fields (documented, not yet observed)

From Hardcover's own schema docs
(`hardcover-docs/src/content/docs/api/GraphQL/Schemas/Editions.mdx` and
`Books.mdx`, fetched raw from GitHub this session):

| Field | Type | Documented values |
| -- | -- | -- |
| `editions.reading_format_id` | **`Int!`** (never null) | 1 = Physical, 2 = Audio, 3 = Both, 4 = Ebook |
| `editions.reading_format` | `reading_formats` | `format: String!` |
| `editions.edition_format` | `String` (nullable) | "hardcover, paperback, ebook, audiobook" |
| `editions.physical_format` | `String` | free text |
| `editions.audio_seconds` | `Int` | audiobook duration |
| `books.default_ebook_edition_id` / `default_audio_edition_id` / `default_physical_edition_id` | `Int` | curated per Work |

**Why `reading_format_id` and not `edition_format` (Q2).** It is non-null and an
enumeration, where `edition_format` is a nullable free string whose documented four
values are not a guarantee. The one risk of a non-null field is a default: an
unknown Edition may be stored as 1. So **only a positive 2 (Audio) is acted on**;
1 is read as "not stated", never as "proven print". `default_ebook_edition_id` was
not chosen: it is curated, may be null, and would replace D15 rather than filter
its input.

`docs/research/hardcover-api.md` records `edition_format` only (`:275`, `:483`);
it should gain `reading_format_id` when the build session touches it.

## 3. The ISBN path

**Direct hit (Q10).** `_by_isbn` (`correction.py:539`) writes the first source's
Edition for the file's ISBN (`:576`). A file carrying `9781799729945` today gets
`Audible Studios on Brilliance`, `2019-02-10` and the square cover wherever it has
none. The ISBN itself is not rewritten (`fill`, the file has one).

**Title fallback (the ticket's question).** When no source has the ISBN, the path
returns `replace(self._by_title(path, book), carried_isbn=book.isbn)` (`:585`). The
docstring says the match "keeps the ISBN the file came with" (`:556`), and under
the default it does — but only because `_edits` skips a `fill` field the file
already carries (`:1204`). Publisher, date and cover are still filled from the
title path's Standard Edition, so **the fallback inherits the whole title-path
risk except the ISBN**. Because it goes through `_by_title`, the title-path rule
closes it with no code of its own.

**`isbn = "overwrite"` (Q4 → CBO-92).** With that rule, `_write(path,
match.candidate, …)` (`:643`) passes no held ISBN, and `epub._set_isbn`
(`epub.py:375`) replaces the file's ISBN element. The docstring's promise is not
enforced. Out of CBO-90's scope; raised as
[CBO-92](https://linear.app/cbow/issue/CBO-92) (Backlog, Bug, parent CBO-33,
related to CBO-90 and CBO-64).

**Google on the ISBN path.** After Hardcover answers "not found" for an Audio
Edition, the walk asks Google by ISBN. `googlebooks/README.md:179` records
`isbn:9781799729945` answering with no item; no general claim is made.

## 4. Interactions — noted, not solved

* **CBO-68 (blocker).** The rule sits on D12 (Hardcover hands up every Edition)
  and D15 (earliest → source order → completeness → payload). It removes Audio
  Editions from D15's input and changes nothing in D15's order. The ADR draft's
  CBO-90 consequence is amended in `cbo-90-adr-draft.md`. **Open in CBO-68's
  review:** PR #18 does not yet carry session 1b; D12 is not built. Neither
  contradicts CBO-90, but CBO-90 cannot start until D12 lands.
* **CBO-65.** No interaction: the exclusion runs in the client, before the Work key
  exists. Series position is a Work field on Hardcover, so an Audio Edition never
  carries a different one.
* **CBO-61.** Audio Editions never enter the pool, so post-match gap fill can never
  use one as a donor. This is a reason Q8 put the guard in the client.
* **CBO-91.** If audiobook support is built, the guard becomes "Editions of the
  file's own Reading Format" rather than "not Audio". Nothing here blocks that;
  `Candidate` carries no format today (Q8), which CBO-91 would add if it needs it.
* **CBO-64.** Closes one known wrong-metadata path; CBO-92 records another.

## 5. Probes run, and what came back

| # | Where | What | Result |
| -- | -- | -- | -- |
| P1 | cloud sandbox | `curl -X POST https://api.hardcover.app/v1/graphql -d '{"query":"{__typename}"}'` | `CONNECT tunnel failed, response 403` — egress policy, before any token |
| P2 | Mac VM shell | the same | `Received HTTP code 403 from proxy after CONNECT` |
| P3 | cloud sandbox | `curl https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/{Editions,Books,ReadingFormats}.mdx` | fetched; §2's table |
| P4 | cloud sandbox, over every `tests/fixtures/hardcover/{by-*,hand-made/*}.json` | count Editions carrying `edition_format`, `reading_format_id`, `reading_format`, `audio_seconds`, `physical_format` | title-path: **13 Editions, 0 carry any**; all fixtures: **32 Editions, 0 carry any** |
| P5 | Linear uploads | download CBO-68's attachments | 403 from both sandboxes; Callum placed them in this folder |

P4's script, for re-running:

```python
import json, glob
keys = ("edition_format", "reading_format_id", "reading_format", "audio_seconds", "physical_format")
total, hits = 0, dict.fromkeys(keys, 0)
for f in glob.glob("tests/fixtures/hardcover/by-title-*.json"):
    for e in json.load(open(f))["data"]["editions"]:
        total += 1
        for k in keys:
            hits[k] += k in e
print(total, hits)   # 13 {…: 0}
```

**The live measurement (Q1 = d, Q12) is the build session's first step**, in this
order:

1. Add `reading_format_id` to the shipped title query (`_TITLE_QUERY`) and ISBN
   query (`QUERY`). Nothing else.
2. A one-off, uncommitted probe for the fields not chosen, so the rejection of
   `edition_format` rests on counts:

   ```graphql
   query {
     editions(where: {
       book: {title: {_in: ["The Infirmary", "Cragside", "Berwick", "Belsay"]}}
       language: {code2: {_eq: "en"}}
     }) {
       isbn_13 reading_format_id edition_format audio_seconds physical_format
       book { id }
     }
   }
   ```

   Report: Editions returned; how many carry each field non-null; the
   distribution of `reading_format_id` (1/2/3/4); and every `edition_format` value
   seen.
3. Callum re-records every Hardcover row the changed queries produce (the CBO-74
   guard will name them).
4. **Gate.** If `9781799729945` does not come back as `reading_format_id: 2`, or
   Hardcover refuses the field, stop and bring it back before building. Also
   report how many Editions come back as 3 (Both) (Q11).

## 6. Decisions from the grilling

| # | Decision |
| -- | -- |
| Q1 | The live presence rate is measured by the build session, not here (§5). |
| Q2 | Signal: `reading_format_id`. Only a stated **Audio (2)** acts. `edition_format` rejected; measured once for the record. |
| Q3 | **Exclude Audio Editions before D15.** Not an ebook-first reorder of D15; not ISBN-only suppression. Print Editions stay eligible, as they are on the ISBN path. |
| Q4 | The fallback's `isbn = "overwrite"` gap is not CBO-90's (→ Q14). |
| Q5 | Google Books: no change. It states no Reading Format; recorded as a limit. |
| Q6 | CBO-68's session 1b files read from this folder. |
| Q7 | Glossary: **Reading Format**, **Audio Edition** (`cbo-90-context-draft.md`). |
| Q8 | The guard lives in the Hardcover client (`_candidates`), not in `collapse()`. `Candidate` gets no new field. |
| Q9 | A Work whose every Edition is an Audio Edition drops out of Hardcover's reply: next source, or `colophon:unverified`. A missed match, never a wrong write. |
| Q10 | The same guard in `by_isbn`: an Audio Edition is "not found", so the title fallback runs and keeps the file's ISBN. |
| Q11 | Only 2 is excluded; 3 (Both) stays eligible, and its count is reported. |
| Q12 | Build order and gate as §5. |
| Q13 | Live *Infirmary* assertion plus a hand-made fixture where the Audio Edition is the earliest. |
| Q14 | CBO-92 created in Linear (Callum's explicit exception to the no-Linear-writes rule). |
| Q15 | No new ADR: an amendment to the Standard Edition ADR draft (`cbo-90-adr-draft.md`). |

Defaults taken without a question, confirmed in the summary: the skip is
**silent** (`hardcover.py` does no logging by design, and no new log wording is
added); the spec text goes to CBO-33 beside CBO-68's rule.

## 7. Open questions

1. **The gate (§5 step 4).** Everything here assumes Hardcover states Audio for
   `9781799729945`. Documented, not observed.
2. **How common is "Both" (3)?** Q11 keeps it eligible pending a count.
3. **CBO-92**: whether `overwrite` should be honoured on the fallback or the
   docstring is wrong.
4. **`docs/research/hardcover-api.md`** should record `reading_format_id` alongside
   `edition_format` when the build touches it.
5. **CBO-68 housekeeping.** PR #18 is at `728c7ea` and lacks session 1b; the
   build brief says it wins over the note. Push before CBO-90's build reads it.

## 8. Test plan for the build session (TDD, `llm=None` throughout)

Written in the order a red-green session would take them. Every corrector is built
with `llm=None`: a default install with no LLM configured.

**Before any test:** §5 steps 1–4, including the gate.

1. **Client, title path: an Audio Edition is not offered.**
   New hand-made fixture `hardcover/hand-made/audio-edition-earliest.json` (README
   row: CBO-90): *The Infirmary*'s three Work 1198266 Editions with
   `reading_format_id` set, the Audio Edition `9781799729945` dated **earliest**
   (e.g. `2018-12-01`) so D15 would pick it. `by_title(["The Infirmary"], "en")`
   offers no candidate with ISBN `9781799729945`. *Red on D12's code, which hands
   it up.*
2. **End to end: the rule changes what D15 writes.** Same fixture, Hardcover only,
   file with no ISBN: the written ISBN is `9781792780844`, and the publisher, date
   and cover are that Edition's, never `Audible Studios on Brilliance`. Repeat with
   the reply shuffled and with both source orders (D10's bar).
3. **Live: the acceptance criterion.** Re-recorded
   `hardcover/by-title-the-infirmary.json` (carrying `reading_format_id`): no
   candidate carries `9781799729945`. This is the "live recording" the ticket asks
   for.
4. **Only Audio Editions.** Hand-made reply where every Edition of the Work is
   Audio: `by_title` returns `[]`; with Hardcover only, the book ends
   `colophon:unverified` and nothing is written.
5. **Not stated, and "Both".** An Edition with `reading_format_id` 1, 3 or 4, and a
   pre-CBO-90 shape with no such key (an existing hand-made fixture), stays a
   candidate.
6. **ISBN path, direct hit.** Re-recorded `by-isbn-9781799729945-genres.json`:
   `by_isbn("9781799729945")` returns `None`. The corrector then takes the title
   fallback: the file's ISBN is kept, and no field is written from the Audio
   Edition.
7. **Tests that become false and must be changed, not deleted blindly:**
   `test_hardcover.py:651`
   `test_a_second_book_of_the_same_kind_adds_only_its_new_genre` reads *The
   Infirmary*'s genres through `by_isbn("9781799729945")`, which now returns
   `None`. Move it to a non-audio *Infirmary* Edition's recording (for example
   `9781792780844`), which needs a new `recordings.py` row and Callum recording it.
   `tests/recordings.py:54` `THE_INFIRMARY_ISBN` should stop naming the
   audiobook. `by-isbn-the-infirmary-authors.json` is read by no test; re-record it
   against the new constant or retire it.
8. **No regression.** CBO-68's no-regression list (Cragside, Berwick, Belsay, *The
   Infirmary* Ross and Reagon) keeps its bands on every configuration.
