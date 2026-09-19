# Google Books, probed live (CBO-37)

Everything here was measured against `https://www.googleapis.com/books/v1/volumes`
on 2026-09-19, with a real API key, not reconstructed from Google's documentation.
The raw replies are the recorded fixtures under `tests/fixtures/googlebooks/`.
Probe scripts: `.tmp/probe_gb.py`, `.tmp/probe_gb2.py`, `.tmp/probe_gb3.py`.

## The headline: the key is not optional after all

The ticket calls it "Google Books key (if used)". It is used, always. Every
keyless call fails:

```
GET /books/v1/volumes?q=isbn:9781521748831        (no key)
HTTP 429  Quota exceeded for quota metric 'Queries' and limit 'Queries per day'
          of service 'books.googleapis.com' for consumer 'project_number:624717413613'.
          "quota_limit_value": "0"
```

`quota_limit_value: 0` is the whole story: the anonymous consumer Google falls
back to when no key is sent is allowed **zero queries per day**. So a keyless
Colophon would fail on every single book, forever, and never once succeed.

**Decision (the user's):** Google Books requires a key whenever it appears in the
priority list. A missing or empty key file is handled exactly like a missing
Hardcover token: log it once at startup, skip Google Books for this run, carry
on with the rest of the list. Startup does not fail.

A keyless call is therefore never made at all. This is the design, not a
precaution: making one would burn neither quota nor goodwill, but it can only
ever return a 429, so there is nothing to gain and a wasted round trip to lose.

## The key itself was proven, then thrown away

The key at `C:\Users\Callum\secrets\google_books_key` (39 characters) works.
It was passed as the `key` query parameter and never logged; the failure probes
that needed the *real* key had it stripped for display as `AIzaSyCW...`.

**The parameter is `key`, not `Authorization`.** Google's own docs for the
Volumes resource list `key` as an optional query parameter
([Volumes: list](https://developers.google.com/books/docs/v1/reference/volumes/list),
[Using the API](https://developers.google.com/books/docs/v1/using)). Unlike
Hardcover there is no bearer header, so the key travels in the URL. That matters
for logging: the URL must never reach a log line, which is a stricter rule than
`colophon/hardcover.py` needed, where the token was in a header.

## A rejected key is a 400, not a 401 or a 403

```
GET /books/v1/volumes?q=isbn:9781521748831&key=AIzaSyxxxxxxx...   (wrong key)
HTTP 400  "API key not valid. Please pass a valid API key."
          reason: badRequest, domain: global
```

Same for a junk key and for a real key truncated to 20 characters. All three:
**HTTP 400, `reason: badRequest`**.

Google's documented key-failure reasons are `keyInvalid`, `keyExpired`,
`ipRefererBlocked`, `accessNotConfigured` and `dailyLimitExceeded`. A wrong key
came back as a plain `badRequest`, so the reason string is **not** a reliable
discriminator on its own. Matching on "the key is rejected" has to be done on
the *status code*: 400 and 403 mean the key. The user confirmed this reading.

So, per the user's instruction:

| What came back | What it is | What Colophon does |
| --- | --- | --- |
| HTTP 400 (any reason) | the key was refused | bad/expired key: the key-rejected path |
| HTTP 403 | the key was refused, or the API is not enabled for the project | the key-rejected path |
| HTTP 429 | this project's daily quota is spent | a **temporary** source error: the retry window, CBO-43 |
| HTTP 5xx, timeout, DNS | Google is having a bad day | a temporary source error |

This is a deliberate difference from the first draft of "if used": a 429 is not
a rejected key. A busy day at Google must not mark the container unhealthy or
hold every book, because the quota resets.

## `isbn:` is a relevance search, not a lookup

This is the finding that changes the code, and it is the one nobody would guess
from the docs. **Google returns books whose ISBN was never asked about.**

```
GET ?q=isbn:9780000000000            (a number that is no book's ISBN)
HTTP 200  totalItems=3
  "Ecos De Paris"                 ids=[ISBN_13:9780000000002, ISBN_10:0000000000]
  "A Questão da gambiarra"        ids=[ISBN_13:9780000000002, ISBN_10:0000000000]
  "애거서 크리스티 A to Z"          ids=[ISBN_13:9780000000002, ISBN_10:0000000000]
```

Not one of those carries `9780000000000`. Even sharper:

```
GET ?q=isbn:9781521748830            (real ISBN with the check digit wrong)
HTTP 200  totalItems=1
  "Cragside"  ids=[ISBN_10:1521748837, ISBN_13:9781521748831]   <- the correct ISBN
```

A one-digit-off query returned the book carrying a *different* number. Google
matched the digits, not the identifier.

**Consequence, and the reason the clause "an exact ISBN match is as certain as
metadata matching gets" cannot be carried over from Hardcover:** `by_isbn` must
read `volumeInfo.industryIdentifiers` on every returned volume and keep only the
volumes that actually carry the ISBN asked about — normalised, hyphens and
spaces removed, and checking both the ISBN-10 and the ISBN-13 entry. If none
does, there was no match, and `None` is returned even though Google sent a 200
with a full-looking reply.

Without that check Colophon would match *Cragside* on the strength of the wrong
ISBN, write another edition's ISBN into the file, and report confidence 1.00
while doing it. The ISBN path is only certain because of the check, not because
of the query.

Confirmed working the other way: `isbn:9789999999991` returns `totalItems: 0`,
so a genuinely absent ISBN can return nothing at all — the fuzzy behaviour is a
hazard, not a certainty in either direction.

## `langRestrict` does nothing, so the language filter is client-side or absent

```
GET ?q=intitle:"Cragside" inauthor:"L.J. Ross"&langRestrict=en  -> totalItems=2
GET ?q=intitle:"Cragside" inauthor:"L.J. Ross"&langRestrict=fr  -> totalItems=2   (same two, both English)
GET ?q=intitle:"Cragside" inauthor:"L.J. Ross"&langRestrict=eng -> totalItems=2   (same two)
```

`fr` returned the same two English volumes as `en`. The parameter is accepted
and ignored for these queries. A three-letter code is accepted and also ignored.

**Consequence:** Colophon cannot ask Google for English-only editions. Every
volume comes back with `volumeInfo.language` set, so the language is known
*after* the fact and can be compared client-side; but the existing design's
"ask on `code2`/`code3` and let the query keep other languages out" has no
Google equivalent. The reply for `intitle:"Cragside"` with no author filter
returned a Korean and a Portuguese volume among the top six, so this is not
hypothetical.

## `seriesInfo` exists in the schema but is useless for novels

`seriesInfo` is a real `volumeInfo` field, documented on
[Volume](https://developers.google.com/books/docs/v1/reference/volumes), but it
is a **comic and graphic-novel collected-edition** structure. It appeared in
exactly one volume out of roughly 100 examined:

```
Sapiens A Graphic History, Volume 1
  {"kind": "books#volume_series_info",
   "shortSeriesBookTitle": "Volume 1",
   "bookDisplayNumber": "1",
   "volumeSeries": [{"seriesId": "i9gsGwAAABCmwM",
                     "seriesBookType": "COLLECTED_EDITION",
                     "orderNumber": 1,
                     "issue": [{"issueDisplayNumber": "1"}]}]}
```

For every actual novel it was absent — including *Mistborn: The Final Empire*
(ISBN 9780765311788, returned with `title: "Mistborn"`, `subtitle: "The Final
Empire"`), *The Fellowship of the Ring*, and all three DCI Ryan books, several
of which are unmistakably in a series. Where the word "series" does appear for
those books it is **prose inside `description`**:

> "The twenty-fourth instalment in LJ Ross's globally bestselling DCI Ryan mystery series…"

There is no field, no `seriesId` that maps to a work, and no series number.

**Consequence for the priority list, and the most important shape change:**
Google Books cannot supply `series` or `series_number`. It supplies title,
authors, language, ISBN, publisher, publishedDate, description, categories and
pageCount. Only the first three of those are fields `epub.Edits` can currently
write at all. So a book matched from Google Books gets its **title and authors**
corrected and nothing else — in particular **no series is written**, which is
the outcome the design spec already asks for ("series only applied from a
trusted source"), arrived at here from the data rather than from policy.

The pipeline needs no special case for this: `_edits(found)` already writes only
the fields the source actually has. A candidate from Google carrying no series
simply writes none.

## What else the reply says, and the cheap wins

- **`inauthor:` is a real filter and it works across punctuation.** The cleaned
  title alone returned 300 items of noise (National Trust guidebooks, a cattle
  herdbook). Adding the author collapsed it:

  | Query | totalItems | What the top hits were |
  | --- | --- | --- |
  | `intitle:"Cragside"` | 300 | National Trust guides, Ken Smith |
  | `intitle:"Cragside" inauthor:"L.J. Ross"` | 2 | both L. J. Ross editions |
  | `intitle:"Berwick" inauthor:"L.J. Ross"` | 1 | the right book |
  | `intitle:"Belsay" inauthor:"L.J. Ross"` | 1 | the right book |
  | `intitle:"The Infirmary"` | 300 | L.J. Ross, Carly Reagon, 1834 hospital catalogues |
  | `intitle:"The Infirmary" inauthor:"L.J. Ross"` | 1 | the right book, not Carly Reagon |

  `inauthor:"L.J. Ross"` matched a record spelling the author `"L. J. Ross"` —
  the stops and the spacing did not matter to Google. That means `by_title`
  should take the file's authors and filter on them, which is also what makes
  the *The Infirmary* lookalike case cheap instead of a 300-item reply.
- **The series bracket breaks the query, exactly as it does on Hardcover.**
  `intitle:"Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)"` →
  `totalItems: 0`. The same title with the bracket off, subtitle still on →
  `totalItems: 1`. The existing `clean_title` is what makes a Google query work.
- **`maxResults` is capped at 40 and answers 400 above it.** `maxResults=100` →
  `HTTP 400 "Values must be within the range: [, value: 40]"`. `maxResults=0`
  → a valid 200 with no `items` key at all. The default is 10.
- **A reply with no matches omits `items` entirely** rather than sending an
  empty list: `{"kind": "books#volumes", "totalItems": 0}`. Reading `items`
  without a default would crash on the not-found case.
- **`totalItems` is not a count of anything reachable.** `startIndex=40` on
  `intitle:"Cragside"` returned `totalItems: 0` after `totalItems: 300`. It is
  an estimate; only `items` is real.
- **A missing or empty `q` is a 400** (`"Missing query."` / `"Required
  parameter: q"`), so no request is ever made without one.
- **The `fields` projection works** and cuts the reply down to what is read,
  which matters because `description` is 500–1800 characters per volume and
  nothing in this ticket reads it.
- **`searchInfo.textSnippet`, `accessInfo` and `saleInfo` are all present** and
  none of them is needed here.
- **Authors come back as a list**, `volumeInfo.authors`, already in the shape
  `Candidate.authors` wants. `"L. J. Ross"` — spaced, which is a *different
  spelling* from Hardcover's `"L.J. Ross"`, and is precisely the case the design
  spec's naming standard exists for.
