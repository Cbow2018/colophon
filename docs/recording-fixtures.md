# Recording the source fixtures

The tests never touch the network. Every reply from Hardcover and Google Books is
recorded once into `tests/fixtures/<source>/` and replayed from there. This is how
to record one again.

The fixture bodies are the API's own bytes, re-indented so they can be read in a
diff. Nothing about the *request* is written inside a fixture, because `Replay`
hands the body straight back to the client as-is. Which query produced which
fixture is declared in `tests/recordings.py` instead, and both the recorder and
the guard read that one declaration.

## Live or hand-made

> A **live** recording is re-recordable at will; nothing asserts its values, only
> its shape. A **hand-made** fixture exists to freeze one case a ticket rests on;
> it is never re-recorded, and it says which ticket and which case in the
> directory README.

A fixture directly inside `tests/fixtures/hardcover/` or
`tests/fixtures/googlebooks/` is live, and this document is about those. A fixture
inside `hand-made/` is not, and re-recording one destroys the case it exists for.
`googlebooks/hand-made/README.md` and `hardcover/hand-made/README.md` say which
ticket each one holds up.

`googlebooks/by-title-poe.json` is both, and is the case that shows why the
distinction has to be a directory. The live file **is** re-recorded, and its reply
grew from 10 volumes to 20 when it was, because `MAX_RESULTS` is 40 and the 10 was
Google's default page size from a recording made before the parameter was sent.
Twenty rather than forty because Google treats `maxResults` as a ceiling and
answers with what it has.
The tie CBO-68 §4 and CBO-69 rest on is not in the live file and must not be
asserted from it: it is frozen in `hand-made/poe-core-cases.json`, and every test
about the tie reads that instead.

## Before you start

You need two secrets, and they never go into a file in this repository:

- a **Hardcover token**, from your Hardcover account settings;
- a **Google Books API key**, from the Google Cloud console.

They are read from environment variables, so nothing secret is typed into a
command, written to a shell history, or committed.

## Recording, step by step

Every command is run from the repository root, `A:\Documents\GitHub\colophon`.
These are PowerShell; on macOS or Linux the same commands work with
`export NAME="value"` instead of `$env:NAME = "value"`.

### 1. Open a terminal in the repository

In File Explorer, open the `colophon` folder, right-click empty space, and choose
**Open in Terminal**. You should see a prompt ending in `colophon>`.

### 2. Put the two secrets in the environment

```powershell
$env:COLOPHON_HARDCOVER_TOKEN = "paste-the-hardcover-token-here"
$env:COLOPHON_GOOGLE_BOOKS_KEY = "paste-the-google-key-here"
```

Nothing is echoed back, and closing the terminal forgets both. You must do this
again in every new terminal.

### 3. Look at what would be recorded

```powershell
python tools\record-fixtures.py --list
```

This asks the API nothing. It prints every declared fixture in the order it would
be recorded, with the query each one would be sent:

```
  1. hardcover/by-title-cragside.json              Hardcover {"titles": ["Cragside"], "language": "en"}
  2. hardcover/by-title-cragside-other-fields.json Hardcover {"titles": ["Cragside"], "language": "en"}
  ...
  6. googlebooks/by-title-poe.json                 Google q='intitle:"The Masque of the Red Death" inauthor:"Edgar Allan Poe"'
                                                   {"langRestrict": "en", "maxResults": "40"}
```

The order is CBO-68's files first, because those are the ones it is waiting on.
**Read this list before recording.** Every request here is built by the shipped
client rather than typed, so if a query looks wrong the fix is in `colophon/`, not
in this script.

### 4. Record

All of them:

```powershell
python tools\record-fixtures.py
```

Or one at a time, by the fixture's name:

```powershell
python tools\record-fixtures.py by-title-poe.json
```

Both sources have files with the same name, so a bare name records every file with
it — `by-title-cragside.json` means two files, one from each. To mean exactly one,
put the source in front:

```powershell
python tools\record-fixtures.py googlebooks/by-title-poe.json
```

Or name several at once:

```powershell
python tools\record-fixtures.py hardcover/by-title-cragside.json googlebooks/by-title-poe.json
```

Each line printed is one capture, and the summary says what came back:

```
Recording 33 fixtures against the shipped queries.
Pacing Hardcover at 1.5s between requests (20 of them, about 0.5 minutes); a 429 is waited out and retried.
  hardcover/by-title-cragside.json                  1 editions, 1 dated
  googlebooks/by-title-poe.json                     20 volumes, totalItems 300
  ...

wrote tests/fixtures/hardcover/by-title-cragside.json
wrote tests/fixtures/googlebooks/by-title-poe.json
```

### Hardcover rate-limits, so the run paces itself

Hardcover's free tier limits requests per second and answers **429** with
`Try again in 1 seconds` when asked faster. The 33 declared fixtures are 20
Hardcover requests and 13 Google ones, which is enough to hit it. The recorder
therefore:

- **paces Hardcover** at `--pace` seconds between requests (default **1.5**,
  measured from the start of the previous request, not the end), so a full run
  takes about half a minute of waiting. Google is not paced: its quota is daily
  rather than per-second, and 13 requests will not reach it.
- **waits out a 429 and asks again**, for the delay the reply itself names — the
  `Retry-After` header if there is one, otherwise the number in the message. Five
  attempts, then the run stops with the reason and writes nothing.

If a run still trips the limit, raise the pace:

```powershell
python tools\record-fixtures.py --pace 3
```

### What the script will not do

- **Write a refusal.** A non-2xx status, a GraphQL `errors` body or a Google
  `error` body is reported and *nothing* is written. A fixture on disk is always
  an answer the source actually gave. A 429 that outlasts the retries is a
  refusal like any other.
- **Write a partial run.** Every capture is made before the first file is written,
  so a run that fails on fixture 20 while *asking* leaves all 33 committed
  fixtures exactly as they were. The write phase is separate and is not guarded:
  it writes one file at a time, so a failure partway through it — a full disk, a
  file another process holds open — leaves the earlier files written and the later
  ones not. Re-run to finish; nothing is corrupted, and `git status` shows exactly
  which files moved.
- **Let one source answer for the other.** The two sources reuse fixture names —
  six of them, including `by-title-cragside.json` — so a capture is kept under
  its source *and* its name, and a body is refused outright if it has the other
  source's shape. See below for why that is not hypothetical.

### The collision that got through once

The first successful re-record wrote both sources' replies to the wrong files for
all six shared names and reported success throughout. `collect` keyed its captures
on the fixture name alone, so the Google reply for `by-title-cragside.json`
overwrote the Hardcover one; `write` then looked each file up by that same bare
name and wrote whichever reply had survived, to **both** directories. Five
`hardcover/` files ended up holding Google bodies and one `googlebooks/` file a
Hardcover body, and nothing in the run said so.

The fix is `label(row)` — `source/name` — as the key in both directions, plus
`check_shape`, which refuses a body whose top level is the other source's. The
first would have prevented it; the second is what turns the next such mistake into
a stopped run rather than a corpus that lies. `tests/test_recording_tools.py`
covers both.

**Why it was caught late.** The tests that would have noticed were the ones
replaying the *clobbered* files, and they failed as `Hardcover's reply did not
contain any editions` — a client-side error message for a file that was simply the
wrong source's. The fixture↔query guard would not have caught it either: it
compares field sets against a query, and it has no way to know which *source*
produced the body. This is the strongest argument for the shape check existing
inside the recorder rather than being left to a test.

Adding `--dry-run` does the printing above without asking anything or writing
anything. It is the same output as `--list`, so it is only worth reaching for when
you want to see the plan for a subset.

### 5. Check what changed

```powershell
git status
git diff --stat tests/fixtures
```

Read the diff before committing it. A reply that changed shape tells you what the
source is doing now; a reply that changed *size* is usually a query that asks for
more than it used to.

### 6. Run the tests

```powershell
python -m unittest -q
```

A re-record changes what the tests replay, so a test that asserted a recorded
value can fail here — correctly, because the value it asserted is gone. Fix the
test to assert what is true now, or, if the value was the point, freeze it into
`hand-made/` instead. Do not restore the old fixture to make a test pass.

## Every declared fixture, and the request it is recorded with

Generated from `tests/recordings.py`; `--list` prints the same thing. The `fields`
mask is the same for every Google request and is not repeated here.

| Fixture | Source | Request |
| --- | --- | --- |
| `by-title-cragside.json` | Hardcover | `{"titles": ["Cragside"], "language": "en"}` |
| `by-title-cragside-other-fields.json` | Hardcover | `{"titles": ["Cragside"], "language": "en"}` |
| `by-title-berwick.json` | Hardcover | `{"titles": ["Berwick"], "language": "en"}` |
| `by-title-belsay.json` | Hardcover | `{"titles": ["Belsay"], "language": "en"}` |
| `by-title-the-infirmary.json` | Hardcover | `{"titles": ["The Infirmary"], "language": "en"}` |
| `by-title-poe.json` | Google | `intitle:"The Masque of the Red Death" inauthor:"Edgar Allan Poe"` `langRestrict=en` `maxResults=40` |
| `by-title-poe.json` | Hardcover | `{"titles": ["The Masque of the Red Death"], "language": "en"}` |
| `by-title-cragside.json` | Google | `intitle:"Cragside" inauthor:"L. J. Ross"` `langRestrict=en` `maxResults=40` |
| `by-title-cragside-other-fields.json` | Google | `intitle:"Cragside" inauthor:"L. J. Ross"` `langRestrict=en` `maxResults=40` |
| `by-title-berwick.json` | Google | `intitle:"Berwick" inauthor:"L. J. Ross"` `langRestrict=en` `maxResults=40` |
| `by-title-belsay.json` | Google | `intitle:"Belsay" inauthor:"L. J. Ross"` `langRestrict=en` `maxResults=40` |
| `by-title-the-infirmary.json` | Google | `intitle:"The Infirmary" inauthor:"L. J. Ross"` `langRestrict=en` `maxResults=40` |
| `by-title-the-infirmary-reagon.json` | Google | `intitle:"The Infirmary" inauthor:"Carly Reagon"` `langRestrict=en` `maxResults=40` |
| `by-title-nothing.json` | Google | `intitle:"The Cragside Compendium of Nothing"` `langRestrict=en` `maxResults=40` |
| `by-isbn-cragside.json` | Google | `isbn:9781521748831` |
| `by-isbn-cragside-other-fields.json` | Google | `isbn:9781521748831` |
| `by-isbn-cragside-authors.json` | Google | `isbn:9781521748831` |
| `isbn-cragside-categories.json` | Google | `isbn:9781521748831` |
| `by-isbn-one-digit-off.json` | Google | `isbn:9781521748830` |
| `by-isbn-unrelated.json` | Google | `isbn:9780000000000` |
| `by-isbn-no-edition.json` | Google | `isbn:9789999999991` |
| `by-isbn-found.json` | Hardcover | `{"isbn": "9781521748831"}` |
| `by-isbn-cragside-edition.json` | Hardcover | `{"isbn": "9781521748831"}` |
| `by-isbn-9781521748831-genres.json` | Hardcover | `{"isbn": "9781521748831"}` |
| `by-isbn-cragside-authors.json` | Hardcover | `{"isbn": "9781521748831"}` |
| `by-isbn-no-series.json` | Hardcover | `{"isbn": "9780571334650"}` |
| `by-isbn-two-series.json` | Hardcover | `{"isbn": "9780765311788"}` |
| `by-isbn-9780575064843-packed-genres.json` | Hardcover | `{"isbn": "9780575064843"}` |
| `by-isbn-9781529196382-packed-genres.json` | Hardcover | `{"isbn": "9781529196382"}` |
| `by-isbn-9781529978940-genres.json` | Hardcover | `{"isbn": "9781529978940"}` |
| `by-isbn-berwick-authors.json` | Hardcover | `{"isbn": "9781529978940"}` |
| `by-isbn-9781792780844-genres.json` | Hardcover | `{"isbn": "9781792780844"}` |
| `by-isbn-edition-title.json` | Hardcover | `{"isbn": "9780007458424"}` |
| `by-isbn-9781473225374-genres.json` | Hardcover | `{"isbn": "9781473225374"}` |
| `by-title-the-infirmary-other-fields.json` | Hardcover | `{"titles": ["The Infirmary"], "language": "en"}` |

**Two pairs share a request**, so a re-record writes identical bytes to both:
the Google `by-title-cragside` pair (which differ only because the mask widened
between them) and the Google `by-isbn-cragside` pair (likewise). Both files are
read by name, so neither is dropped here; whether a pair should collapse into one
file is a decision nobody has taken.

## The fixtures no shipped query produces

These have no request to be re-recorded with, and each says why in
`tests/recordings.py`. They are not "frozen evidence" and not "drifted": they are
replies to questions the client does not ask.

| Fixture | Why it has no request |
| --- | --- |
| `hardcover/author-lj-ross.json` | recorded against the `authors` root field, which no shipped query has |
| `hardcover/authors-spelling-variants.json` | recorded against the `authors` root field |
| `hardcover/works-good-omens-authors.json` | recorded against the `books` root field |
| `hardcover/nothing-found.json` | the empty reply to an ISBN no edition carries; 44 bytes either way |
| `hardcover/by-title-nothing-found.json` | the empty reply to a title Hardcover does not have; 44 bytes either way |
| `googlebooks/error-key-rejected.json` | a 400 from a deliberately wrong key |
| `googlebooks/error-max-results-too-high.json` | a 400 from a deliberately out-of-range `maxResults` |
| `googlebooks/error-missing-query.json` | a 400 from a deliberately missing `q` |
| `googlebooks/hand-made/poe-core-cases.json` | hand-made: a frozen case |
| `hardcover/hand-made/work-without-title.json` | hand-made: a frozen case |
| `hardcover/hand-made/wider-than-the-question.json` | hand-made: a frozen case |

**The two Google empty replies are the interesting pair, and they were re-recorded
with everything else.** `googlebooks/by-title-nothing.json` and
`googlebooks/by-isbn-no-edition.json` had been recorded **without a mask**, so they
were the unmasked `{"kind": "books#volumes", "totalItems": 0}`. Google's masked
empty reply is `{"totalItems": 0}` — 25 bytes as stored here, indented, and 16
without the whitespace, with no `kind` at all — so re-recording changed the file's
only two keys. No test reads `kind`, so the suite cannot tell the difference; the
`googlebooks/README.md` note that argued the old byte count was evidence the two
recordings agreed has been corrected. The change is worth knowing about because it
is the kind a field-set guard on an empty body cannot see: there is no field set
to compare.

## Unguarded

**What the guards do.** There are two, and between them they close one gap:
`query ↔ code` (CBO-73) fails when a field Colophon writes is selected by nothing,
and `fixture ↔ query` (CBO-74) fails when a committed fixture's field set is not
the one its declared query would return today. Both are static. **Neither ever
contacts a source**, so everything below is invisible to both, and "guarded"
must not be read as "covered".

**A third guard does not exist, and CBO-73's "Sequencing" line points at the wrong
ticket for it.** That line says "Fix this, re-record (CBO-76), then CBO-68 session
2". CBO-76 is a real ticket and is not about re-recording: it is *Build §4.4's
tuning set — no threshold in this design has ever been tuned*, which is 20–50
labelled books and a threshold report. The re-record it names is this document's
subject and was CBO-74's. Flagged rather than corrected in CBO-73, which is closed
and is a record of what was decided then.

### `maxResults`, and request parameters generally

The fixture guard compares the *reply's shape* against the request's selected
fields. It does not compare the rest of the request, so a parameter can change
under a fixture and nothing fails.

`by-title-poe.json` is the case that proves it matters, and it is the drift that
produced the file it is now. `MAX_RESULTS` is 40 (`colophon/googlebooks.py:68`)
and is sent on every title lookup, but that fixture held **10** volumes — Google's
default page size, so it was recorded before the parameter was sent at all. Every
key set in it matched, and `ReplayByQuery` matches on `q` alone
(`tests/test_googlebooks.py`), so the mismatch was invisible from every direction:
a 10-item reply to a request the client had stopped making.

The re-record made it a **20-volume** reply, not a 40-volume one: Google treats
`maxResults` as a *ceiling* and answers with what it has, with `totalItems` still
300. So the count is not even a function of the parameter — which is the point.
**Nothing asserts either number.** A future change to `MAX_RESULTS`, or to
`langRestrict`, or a parameter added to `_ask` later, drifts exactly as silently,
because the count is a property of the whole request and no comparison of field
sets can reach it. `Replay.sent` already holds the whole URL, so a guard comparing
the whole request would catch this; the fixture guard deliberately does not,
because that is a different claim from "the fixture matches the query that would
produce it". **Nothing currently asserts `maxResults`.**

### A field that is selected, present, and always empty

The fixture guard compares *keys*. A key the query selects, the fixture carries
and the source has nothing for passes, and the same defect one level down — a
field that arrives present-but-empty in every live reply — is invisible.
Hardcover's `release_date` was that shape and took a live recording to find.

`by-title-belsay.json` is this shape already: it carries `isbn_13: null` and
`isbn_10: null`, so the guard passes a fixture whose ISBN is empty, which is the
same class of problem as a fixture whose ISBN key is absent. Only a live recording
tells the two apart.

### A value whose shape changed

The guard compares key sets, not types. `image` going from `{"url": ...}` to a
bare string, `book_series` from a list to an object, or `cached_tags` gaining or
losing a category key all pass it. `cached_tags` is already inconsistent across
the corpus: five keys in `by-isbn-9780575064843-packed-genres.json`, four in every
other fixture that carries it.

### A field nothing reads

`image` and `cached_tags` are fetched but never written, by design. A guard on the
fixture confirms they arrived; nothing confirms Colophon still does the right
thing with them.

### A change in what the source *means*

Google's `isbn:` behaves as a relevance query rather than a lookup
(`docs/research/cbo-37-google-books.md`, 2026-09-19). The shape is fine and the
meaning is not, and no comparison of field sets can see it.

### A field the mask never asks for

Google's `fields` is an enumeration, so a field Colophon wants but has not added
to the mask is absent from every reply *and* from every fixture. `seriesInfo` is
in this class: 0 of the 26 recorded volumes carry it, it is not in `FIELDS`, and
the 2026-09-19 measurement of it ("one volume in roughly a hundred") cannot be
re-confirmed from the fixture set at all. A guard cannot tell "we stopped asking"
from "the source stopped answering", and no test imports `FIELDS`, so changing the
mask cannot fail anything today.

### The token was never here

The recorded bodies carry no key and no token: the key travels as a query
parameter and Google does not echo it, and the request is not stored in the
fixture. The recorder takes both from the environment and prints neither.
