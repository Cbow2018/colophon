# Recorded Google Books replies

Real replies from `https://www.googleapis.com/books/v1/volumes`, recorded on
2026-09-19 with a real key, so the suite never needs one and never touches the
network. As with `fixtures/hardcover/`, each body is the API's own, re-indented
so it can be read in a diff; nothing inside is changed, including `kind`,
`etag`, `selfLink`, `accessInfo` and `searchInfo`, which the client does not
read.

The key is sent as the `key` query parameter, and Google never echoes it into a
reply, so the recorded bodies are key-free. The two ISBN fixtures whose point is
a *wrong* ISBN were recorded by asking about that wrong ISBN; the query is not
stored in the body, so it is named in the table below instead.

## By ISBN

| File | ISBN asked about | What came back | How |
| --- | --- | --- | --- |
| `by-isbn-cragside.json` | 9781521748831 | 1 volume, *Cragside*, L. J. Ross, carrying ISBN_13 9781521748831 | recorded |
| `by-isbn-no-edition.json` | 9789999999991 | `totalItems: 0` and **no `items` key at all** | recorded |
| `by-isbn-one-digit-off.json` | 9781521748830 | 1 volume, *Cragside*, carrying **9781521748831** — the correct ISBN | recorded |
| `by-isbn-unrelated.json` | 9780000000000 | 3 volumes, none of which carries that ISBN | recorded |

`by-isbn-one-digit-off.json` and `by-isbn-unrelated.json` are the two that
matter. Neither reply carries the ISBN that was asked about, which is why
`by_isbn` verifies `industryIdentifiers` itself instead of trusting a 200. The
probe that found this is in `docs/research/cbo-37-google-books.md`.

## By title

Every one of these was recorded with `intitle:"…" inauthor:"…"`, and the DCI
Ryan ones with `langRestrict=en` because the file says `en`. Google matched
`inauthor:"L. J. Ross"` against a record spelling the name `"L. J. Ross"`, and
against a file spelling it `LJ Ross`: the stops and the spacing do not matter.

| File | Title and author asked about | What came back | How |
| --- | --- | --- | --- |
| `by-title-cragside.json` | *Cragside*, L. J. Ross | 2 volumes: the Ulverscroft large-print edition and the original | recorded |
| `by-title-berwick.json` | *Berwick*, L. J. Ross | 1 volume, *Berwick* | recorded |
| `by-title-belsay.json` | *Belsay*, L. J. Ross | 1 volume, *Belsay* | recorded |
| `by-title-the-infirmary.json` | *The Infirmary*, L. J. Ross | 1 volume, L. J. Ross's book | recorded |
| `by-title-the-infirmary-reagon.json` | *The Infirmary*, Carly Reagon | 1 volume, Carly Reagon's book of the same name | recorded |
| `by-title-poe.json` | *The Masque of the Red Death*, Edgar Allan Poe | 10 volumes, several of them Poe's | recorded |
| `by-title-nothing.json` | a title nobody has | `totalItems: 0`, no `items` key | recorded |

`by-title-nothing.json` is CBO-39's as well as CBO-37's: the unverified path
begins when no source has the book, so the branch that reads this was asked of
the live API again with the widened `fields` mask and answered byte-identical
bytes. **That was true of the unmasked mask and is no longer true of the shipped
one.** Both empty files were re-recorded on 2026-09-23, and the shipped mask
returns `{"totalItems": 0}` — 17 bytes, with no `kind` — where the unmasked
request returned 53 bytes with `kind: "books#volumes"`. No test reads `kind`, so
the change is invisible to the suite; it is recorded here because the byte count
below used to be the evidence that the two recordings agreed.

The two `the-infirmary` recordings are the lookalike pair: two different books
share a title, and only the author separates them.

`by-title-poe.json` is the Gutenberg fixture's book. It is driven through the
whole corrector in
`test_correction.ABookMatchedFromGoogleBooksTests.test_a_real_book_is_corrected_from_a_recorded_google_books_reply`:
a real EPUB in, a real `GoogleBooks` client, this recording back, and the title
and authors written out. Its replay picks the fixture by matching the `q` the
client actually sent, so a change to the query fails the test rather than
quietly reading the wrong recording.

Every fixture here is read by a test, and nothing else is kept. Two recordings
were dropped for want of a reader: a Cragside reply with the subtitle left on,
and a duplicate of `by-title-nothing.json`.

`by-isbn-unrelated.json` is the one worth explaining: it holds three volumes,
where one would exercise the same branch, because the point of it is that the
*reply* Google gave for a nonsense ISBN was three unrelated books and not an
empty result. It is kept whole for the same reason every other body here is.

## CBO-41: the spelling Google returns

CBO-41 (Colophon's own record) has to decide what a name's standard spelling is,
and Google Books is the second source it can take one from.

| File | Query | What came back | How |
| --- | --- | --- | --- |
| `by-isbn-cragside-authors.json` | `isbn:9781521748831` | 1 volume, *Cragside*, author **`L. J. Ross`** — with a space between the initials, where Hardcover spells the same author `L.J. Ross` | recorded |

The spelling is the whole finding: **the two sources disagree about the same
author, and neither is wrong.** Google matched `inauthor:"LJ Ross"` (no stops, no
space) and `inauthor:"L.J. Ross"` to the same two volumes and answered
`"L. J. Ross"` both times, and an `inauthor:"L.J. Ross"` search across the author
returned `"L. J. Ross"` on every volume. So Google does the punctuation
normalising server-side and its own spelling is stable, exactly as CBO-37's note
records.

Two recordings of those two title searches were made and then **not kept**: both
answers repeat the same two volumes with the same fields as
`by-title-cragside.json`, and differ from it only in the `etag`, which Google
changes on every request — so keeping them would be two near-duplicate files for a
property this README already states. `by-isbn-cragside-authors.json` overlaps
`by-isbn-cragside.json` for the same reason, and is kept because CBO-41's research
note quotes its author value directly rather than through a second file.

## What these replies do **not** contain

**No usable series data.** `seriesInfo` is absent from every novel here, and
from every novel in the probe — it is a comics-and-collected-editions structure
that appeared once in roughly a hundred volumes examined. Where the word
"series" appears at all it is prose inside `description`. So a book matched from
Google Books gets its title and authors corrected and **no series written**,
because there is no series to write. See
`docs/research/cbo-37-google-books.md`.

**No `items` key when nothing matched.** `by-isbn-no-edition.json` and
`by-title-nothing.json` are both 17 bytes as of the 2026-09-23 re-record:
`{"totalItems": 0}`. Reading `items` without a default would crash on the most
ordinary outcome there is. (Before that they were the unmasked 53 bytes,
`{"kind": "books#volumes", "totalItems": 0}` — same absence, one more key.)

## The fields CBO-38's rules write

CBO-37's client asked Google for six things and none of them was a blurb, a
date, a publisher or a cover. CBO-38 widened the mask, so the same queries now
ask for all four; these two recordings are the same questions asked with the
widened mask, which is why the values in them are not in the older files.

| File | Query | What came back | How |
| --- | --- | --- | --- |
| `by-title-cragside-other-fields.json` | the same Cragside title search as `by-title-cragside.json` | 2 volumes, both with a `description` and a `publishedDate`; one with a `publisher` and `imageLinks`, one with neither | recorded |
| `by-isbn-cragside-other-fields.json` | `isbn:9781521748831` | 1 volume, with a `description` and a `publishedDate`, and **no** `publisher` and no `imageLinks` | recorded |

The two Cragside volumes disagree, which is the point of keeping both: the
Ulverscroft large-print edition has a publisher (`Ulverscroft Special
Collection`), a date of `2021-03` and a cover, and the original has no
publisher, a date of `2017-07-07` and no cover. `imageLinks` being absent is
therefore the ordinary case rather than a failure, and `by-isbn-cragside-other-fields.json`
is the one that proves it: the ISB volume carries a blurb and a date and
nothing else, because that is what Google answered.

`description` is the one new field Google has reliably: all four volumes across
the two files carry a blurb, and the 1084-character one is byte-for-byte what
Hardcover has for the same book.

## CBO-42: `categories`, which the shipped mask now asks for

CBO-42 (genre mapping) needs Google's genres, and they are `volumeInfo.categories`.
The CBO-37 recording above, `by-title-cragside.json`, was made through an older
request and **already carries them** — its two volumes are CBO-42's two cases in
one file:

```
7kMMzgEACAAJ  'Cragside'  ->  categories: ['Finlay-Ryan, Maxwell (Fictitious character)']
RASDtAEACAAJ  'Cragside'  ->  categories: ['Murder']
```

One is a library subject heading — a character, not a genre — and the other is a
genre.

**The shipped `FIELDS` mask carries `items/volumeInfo/categories`**, as its last
entry (`colophon/googlebooks.py:52-58`). This README said the opposite until
CBO-74: that the mask did not carry it and that CBO-42 appended it. CBO-42's
addition *is* the shipped mask, and had been since that ticket merged — the
sentence described the state before it. The re-record settled the question the
sentence raised: every masked reply now carries `categories` when the volume has
any, and omits the key entirely when it has none.

| File | Query | What came back | How |
| --- | --- | --- | --- |
| `isbn-cragside-categories.json` | `isbn:9781521748831`, the shipped mask | 1 volume, *Cragside*, `categories: ["Murder"]` | recorded |

That file was recorded with `items/volumeInfo/categories` *appended* to a mask that
lacked it, which is why it was once evidence of a difference between it and the
shipped mask. It is not any more: re-recorded on 2026-09-23 against the shipped
mask, it is an ordinary recording, and the mask it answers is the one the client
sends.

Two volumes disagreeing about one book's genre is not a defect to fix: the
character heading is Google's own catalogue data, and the same probe shows the
genre path is best-effort by nature. Google's ISBN query is a relevance search, so
`isbn:9781799729945` answered with no item at all and `isbn:9781529978940` answered
with a volume titled *Raby* — `by_isbn` already filters those out by identifier,
and a book Google cannot confirm simply has no genres to map.

## Failures

| File | Status | What it is |
| --- | --- | --- |
| `error-key-rejected.json` | 400 | a wrong key: `reason: badRequest`, "API key not valid." |
| `error-missing-query.json` | 400 | no `q`: `reason: required` |
| `error-max-results-too-high.json` | 400 | `maxResults=100`: `reason: invalidParameter` |

All three are 400, and only the first is about the key — which is why the client
reads the message rather than the status alone. A `reason: required` from our own
malformed query must not be mistaken for a key the user has to go and fix.
