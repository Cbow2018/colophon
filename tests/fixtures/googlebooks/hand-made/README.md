# Hand-made fixtures: the cases a ticket rests on

> A **live** recording is re-recordable at will; nothing asserts its values, only
> its shape. A **hand-made** fixture exists to freeze one case a ticket rests on;
> it is never re-recorded, and it says which ticket and which case in the
> directory README.

This is the rule for both `fixtures/googlebooks/hand-made/` and
`fixtures/hardcover/hand-made/`. A directory rather than a filename suffix,
because the distinction is a different *reason to exist* and a directory is the
only form that cannot be forgotten when someone adds the next one.

A fixture in the parent directory is a live recording: re-record it whenever the
query changes, and let the test that reads it assert the shape rather than the
values. A fixture here is the opposite. Re-recording one destroys the case, and
there is no test that can tell that from a fix.

## `no-categories.json`

A real recording, taken from this repository's own history rather than invented:
`by-isbn-cragside-other-fields.json` as it stood before the 2026-09-23 re-record,
when the shipped mask did not yet ask for `items/volumeInfo/categories`. Recovered
with `git show <the commit before the re-record>:tests/fixtures/googlebooks/by-isbn-cragside-other-fields.json`.

It is a CBO-38-era ISBN reply: one Cragside volume carrying `title`, `authors`,
`publishedDate`, `description`, `industryIdentifiers` and `language`, and **no
`categories`**. The mask asks for categories today and the re-record returned
them, so `test_googlebooks.GenreTests.test_a_candidate_with_no_categories_carries_no_genres`
would otherwise be asserting an absence against a reply that has the field. The
case is that a volume with no categories answers no genres — absent, not a bug.

One file, one reader, and it is not the same claim as `poe-core-cases.json` below:
this one freezes a *shape* the client has to handle, that one freezes *values* two
tickets rest on.

## `poe-core-cases.json`

Five volumes out of the ten in the live `googlebooks/by-title-poe.json`, frozen
on 2026-09-23 before that file is re-recorded. `kind` and `totalItems: 300` are
carried over from the live file unchanged; the volumes are byte-identical to the
ones they were copied from.

**Why five and not one.** The five are the tie. Every one of them scores
**0.9231** against the real Gutenberg EPUB, so the gap between the leader and the
runner-up is **0.0000**, and that gap of zero is the whole of CBO-68 §4's finding:
a title reply can offer five editions that agree with the file on everything the
file states, so no rule can pick one, and the band is `medium` rather than
`strong`. One frozen volume cannot reproduce a tie. The re-record will return up
to 40 volumes, so the tie's membership is exactly what is about to change.

**The score is 0.9231, not 1.0000.** CBO-74's ticket description, its session-1
research note at §3.2 and the docstring of
`test_correction.ABookMatchedFromGoogleBooksTests.test_a_real_book_is_not_written_from_a_reply_full_of_editions`
all say the five score 1.0000. They do not. Measured 2026-09-23 by running
`matching.rank` over the real EPUB and the real fixture: the top five score
0.9231 and the sixth scores 0.8629. The 0.9231 is
`1 - YEAR_WEIGHT / (TITLE_WEIGHT + AUTHOR_WEIGHT + YEAR_WEIGHT)` — the file says
`2010-06-06` and none of the five says 2010 — so the score was never going to be
1.0 for a file that carries a year. Nothing in CBO-68 §4's argument depends on
the absolute value: the finding is the **gap of 0.0000**, and 0.9231 ties as well
as 1.0000 does.

| Volume | Index in the live file | Reads it | The case |
| --- | --- | --- | --- |
| `q6T5zQEACAAJ` | 0 | CBO-68 | one of the five members of the 0.0000 tie |
| `XcE-EAAAQBAJ` | 1 | CBO-68 | one of the five members of the 0.0000 tie |
| `_hSNzQEACAAJ` | 3 | CBO-68 | one of the five members of the 0.0000 tie |
| `du6sYyygMgIC` | **4** | **CBO-69** and **CBO-68** | **the case both tickets rest on** — see below |
| `nPByzgEACAAJ` | 6 | CBO-68 | one of the five members of the 0.0000 tie |

### `du6sYyygMgIC` — the volume two tickets rest on

`'The Masque Of The Red Death'`, `2013-01-29`, `Harper Collins`, subtitle
`Short Story`. It is load-bearing twice over:

- **CBO-69** (*a written title does not carry the record's spelling — normalised
  match, unnormalised write*). This volume is that ticket's entire reproduction.
  Its title spells the preposition with a capital `O`, where the file and the
  other nine volumes spell it `of`. The normalised comparison treats the two as
  one title, so CBO-69's bug writes Google's spelling over a correct file title.
  Without this volume the ticket has no reproduction at all.
- **CBO-68** (*title search returns editions, not works*). `2013-01-29` is the
  **earliest** `publishedDate` in the reply, so under any `earliest` rule this
  volume is the survivor of the tie. CBO-68's decision on what to do when the
  band is `medium` is a decision about *this* volume.

**Why it cannot simply be re-recorded.** Google re-cases titles: it is a search
engine, not a catalogue. A re-record can legitimately return
`The Masque of the Red Death` for `du6sYyygMgIC`, at which point CBO-69's casing
variant is gone, CBO-68's tie has different membership, and **nothing fails** —
a re-record is indistinguishable from a fix. That is what this file is for.

## `error-access-not-configured.json`

The 403 Google answers when the project behind the key may not use the Books API:
`"reason": "accessNotConfigured"`, "Books API has not been used in project
123456789 before or it is disabled." Hand-made for CBO-78, because nothing else
in the corpus is a 403 and a re-record with a working key cannot produce one.

**What it freezes is that the key is not blamed.** `_KEY_WORDS` is what decides
"key or query" from the message, and this message matches none of them, so the
failure is held without being the key's - which is the ticket's decision, and the
opposite of the pairing a status reader would guess. The envelope is Google's own
error shape and the message is the documented one, with a placeholder project
number in place of a real one and the console URL its real reply carries left
out.

`WhenGoogleRefusesTests.test_a_project_that_may_not_use_the_api_is_held_not_blamed_on_the_key`
reads it.

## Adding a fixture here

Only when re-recording would destroy the case: a ticket's evidence, or a client
behaviour a test asserts that a live file can stop demonstrating. Each one needs a
row in this README naming the ticket (or the behaviour), the case, and why the live
file cannot carry it. If a live recording would do, it belongs in the parent
directory.
