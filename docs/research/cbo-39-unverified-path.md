# CBO-39: the unverified path

Probed live on 2026-09-19 with the real keys, from `.tmp/probe_cbo39.py`. Raw
replies are in `.tmp/cbo39/`. Everything below is what the two APIs actually
answered, not what the documentation says they would.

This is the probe for CBO-39 (*Unverified path*), whose acceptance criteria are
that a book no source can match confidently passes through with its original
metadata, tagged `colophon:unverified`, with "Metadata could not be verified by
Colophon." added at the end of the description, as a final state, tested for
both a no-match and a below-threshold match.

## 1. Which source can even produce each case

The two cases the ticket names reach the pipeline by different routes, and the
probe shows which source produces which.

### Hardcover answers a title exactly or not at all

`TITLE_QUERY` filters with `book: {title: {_in: $titles}}`. That is an exact
match, case-sensitive, which
`docs/research/cbo-36-title-matching.md` already records. What the probe adds is
what that costs the below-threshold case:

| Title asked about | Reply |
| --- | --- |
| `The Cragside Compendium of Nothing` | `{"data": {"editions": []}}` |
| `DCI Ryan Mysteries` | `{"data": {"editions": []}}` |
| `Cragside: A DCI Ryan Mystery` | `{"data": {"editions": []}}` |
| `Holy Island` | 7 editions, all *Holy Island*, L.J. Ross, #1 |
| `Cragside` | 1 edition, *Cragside*, L.J. Ross, #6 |

So a title Hardcover does not spell exactly yields **no candidate at all**, which
is the *no match* case rather than a near miss. A near miss needs a reply whose
candidate title differs from the file's - a `contained` title - and Hardcover's
`_in` filter cannot produce one: the only titles it returns are the ones asked
about.

### So the near miss comes from a record, not from the query

The probe confirms the below-threshold case is real and scoreable, just not by
asking Hardcover a near title. Scored against the file's own title:

| File | Best candidate | confidence | agrees | Route |
| --- | --- | --- | --- | --- |
| *Cragside* (messy) | *Holy Island*, L.J. Ross | 0.60 | no | no candidate agrees on both halves |
| *Cragside* (messy) | *The Infirmary*, Carly Reagon | 0.00 | no | as above |
| *Cragside* (messy) | *Cragside: A DCI Ryan Mystery*, L.J. Ross, #11 | 0.84 | yes | **the near miss** |

The 0.84 row is the one that matters, and it is already in the suite as
`test_correction.BooksWithoutAnIsbnTests.test_a_near_miss_says_which_book_it_was_and_what_was_wrong_with_it`.
A file whose title carries a position (a real `(… Book N)`) matched against a
record that kept its subtitle and disagrees about that position scores 0.84:
contained title (0.9) and agreeing author (1.0) weigh 0.94, and the disagreeing
series position takes 0.10 off. That is a real shape - a file renamed by hand, or
a record whose numbering is the publisher's - so the below-threshold case needs
**no new recording**. It is built from a `Candidate`, which is what a source's
reply is parsed into anyway.

The `Holy Island` row is the other half of "no match": a real candidate came
back, and it agrees on neither the title nor the author, so no book is named.

## 2. A book nobody has, from both sources

The no-match case was asked of both APIs with a title no book carries. Both
answered an empty result, in their own shapes:

```
Hardcover    {"data": {"editions": []}}
Google Books {"kind": "books#volumes", "totalItems": 0}
```

Neither reply carries anything to name a book with, and neither is a failure:
a source with no such edition is a normal answer, which is why `by_isbn` already
treats it that way and `by_title` returns `[]`.

Google Books already had a fixture with this shape
(`googlebooks/by-title-nothing.json`, recorded for *a title nobody has*). The
probe was still asked live, because the query the client sends today carries
CBO-38's widened `fields` mask and that recording predates it. The two replies
are byte-identical apart from the mask, so the recording was sound.

Hardcover had no recording of an empty title reply at all; the closest was
`by-isbn-not-found.json`, which is the ISBN path. Two recordings are therefore
new: `hardcover/by-title-nothing-found.json` and
`googlebooks/by-title-nothing-found.json`, both recorded with the queries the
client ships.

## 3. What the probe changed about the ticket's shape

**The below-threshold case needs no new API reply.** The ticket reads as though
both cases need a recorded response. They do not: the near miss is a real
candidate scored against the file, and the suite already holds one. The
no-match case is the recording above.

**A no-match book is not only one thing.** Two different outcomes reach the
unverified path, and the pipeline can already tell them apart:

* the sources answered, and nothing in their replies agreed on both title and
  author - nothing can be named;
* the sources answered, and the best candidate agreed on both but scored under
  the threshold - `Outcome.passed_over` names it and says what was wrong.

Both are "no confident match", so both are unverified. Whether the log line
keeps the second distinction is a decision, not a finding.

**Hardcover cannot produce a below-threshold candidate on the title path.** Its
title filter is exact, so every candidate it offers scores 1.0 on the title
half. Nothing in this ticket should be built on the assumption that a reply can
be "nearly the right title" from Hardcover; that shape only ever arrives from
Google Books (relevance search, `contained` titles) or from a record whose
subtitle disagrees with the file's.

## 4. What the sources say nothing about

The probe cannot settle any of these, because no API is involved:

1. What the tag is written *as* in an EPUB. `dc:subject` is the element Calibre
   and Calibre-Web NextGen read as tags; the design spec names the tag but not
   the element. (Checked against Calibre's own OPF reader, which takes
   `dc:subject` and the `subject` element as the two spellings of a tag.)
2. What happens to the description when the file has none at all. The spec says
   the message goes at the *end* of the description and the original blurb stays
   at the top, which assumes there is one.
3. Whether the appended sentence is added on every pass or once, given re-dropped
   books are looked up again by design.
4. Whether the dry run appends it too. Dry-run mode is on in the example config,
   so this is the first thing a new user sees.
5. Where a "confidence threshold" lives in `config.toml`, and what range is
   refused.

All five were put to the maintainer before any code was written; the answers are
in the "As built" section at the end of this note.

## As built (2026-09-19)

Settled with the maintainer before any code was written:

1. **Which outcomes are unverified:** only the confidence failure. A book with no
   source configured, no title to ask about, an unreadable package, an unreadable
   key or a source that could not answer keeps its own state and gets no tag -
   "nobody could ask" is not "we asked and could not be sure". Two of those are
   other tickets' (CBO-43's retry and `colophon:source-unavailable`, CBO-44's
   hold-the-books on a rejected key).
2. **The tag is a `dc:subject`,** appended after the book's own subjects and never
   duplicated. That is the element Calibre and Calibre-Web NextGen read as a
   book's tags. `belongs-to-collection` was considered and rejected: no reader
   reads "unverified" as a collection, and it would surface in series UI.
3. **`confidence = 0.85`,** a top-level key so `COLOPHON_CONFIDENCE` works like
   every other setting, replacing the hardcoded `TITLE_CONFIDENCE`.
   Valid range `(0, 1]`: 0 is not a threshold, and 1.0 *is* reachable - the
   question was checked rather than assumed, and a title and an author that both
   agree exactly score exactly 1.0 (`0.6 + 0.4`, series absent on one side or
   agreeing). So 1.0 is a coherent "ISBN matches only" setting.
4. **A book with no description gets one,** containing the sentence alone. The
   ticket's point is finding the book in the library, and a tag is easy to miss.
5. **Marking is idempotent:** the sentence is appended once, in whichever of the
   two forms fits the blurb. Plain text gets a blank line then the sentence;
   text carrying markup gets it as its own `<p>`. Whether it is markup is decided
   by looking for a tag (`<[a-zA-Z][^>]*>`), so a blurb containing `5 < 6` is
   still plain text. An empty `dc:description` counts as having none.
6. **A dry run reports the mark and writes nothing,** like every other change:
   the line says `would mark colophon:unverified` rather than `marked`, because a
   marked book has no `changed`-list to sit behind. A real run backs the original
   up and the book is delivered to output like any other.
7. **The log line keeps the near-miss detail** - which candidate, why, what
   confidence - and both non-match lines add the mark, attributed to `colophon`
   rather than to a source that never saw the book.
8. **The mark is recomputed every pass, not remembered.** A book that is matched
   later comes out clean: the tag goes, and the note comes off the end of the
   description - the note is removed from the text *before* the `[fields]` rules
   run, so `fill` sees the blurb without the note and an `overwrite` blurb
   replaces the marked description whole.

Two things the building turned up that the probe could not:

* **The removal cannot be a rewrite of the marked text backwards.** Taking the
  note off is easy; knowing whether the remaining text was the file's blurb or
  `fill`'s business is not, and a description that was only the note has to be
  *removed* rather than left empty. So `Edits.description` grew a third meaning -
  `None` for "no rule said anything", `""` for "nothing is left of it" - and
  `epub` grew `_set_description` to honour it. The description is now the one
  field a correction can empty.
* **The rule has to be judged against the un-noted blurb.** Judging `fill`
  against the marked description would leave a stale note on any book whose
  description was only the note, because the file "already has a description".
  Stripping first is both what the maintainer asked for ("trim, then apply the
  normal rule") and what makes the two cases one code path.

FB2 was **deferred to CBO-45** by decision, not silently dropped: CBO-45 already
owns reading and writing FB2, this ticket stays EPUB/KEPUB, and CBO-45's
description gained an acceptance criterion for the genre element and
`<annotation>`, pointing back here for the marker's shape. The research that
informs it is worth recording now rather than re-finding:

* **`<genre>` is a closed enum** of FictionBook genre codes
  (`FictionBookGenres.xsd`), so `colophon:unverified` is schema-invalid there
  even though Calibre round-trips it without validating. The schema-sanctioned
  free-text carriers are `<custom-info info-type="…">` and `<keywords>`.
* **`<annotation>` is a markup container** (`pType` children), and Calibre reads
  it as text and writes one `<p>` per line, which is the same shape the HTML
  form of the note already takes here.

