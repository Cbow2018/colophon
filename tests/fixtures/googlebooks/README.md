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

## What these replies do **not** contain

**No usable series data.** `seriesInfo` is absent from every novel here, and
from every novel in the probe — it is a comics-and-collected-editions structure
that appeared once in roughly a hundred volumes examined. Where the word
"series" appears at all it is prose inside `description`. So a book matched from
Google Books gets its title and authors corrected and **no series written**,
because there is no series to write. See
`docs/research/cbo-37-google-books.md`.

**No `items` key when nothing matched.** `by-isbn-no-edition.json` and
`by-title-nothing.json` are both 53 bytes:
`{"kind": "books#volumes", "totalItems": 0}`. Reading `items` without a default
would crash on the most ordinary outcome there is.

## Failures

| File | Status | What it is |
| --- | --- | --- |
| `error-key-rejected.json` | 400 | a wrong key: `reason: badRequest`, "API key not valid." |
| `error-missing-query.json` | 400 | no `q`: `reason: required` |
| `error-max-results-too-high.json` | 400 | `maxResults=100`: `reason: invalidParameter` |

All three are 400, and only the first is about the key — which is why the client
reads the message rather than the status alone. A `reason: required` from our own
malformed query must not be mistaken for a key the user has to go and fix.
