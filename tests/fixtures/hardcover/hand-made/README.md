# Hand-made fixtures: the cases a ticket rests on

> A **live** recording is re-recordable at will; nothing asserts its values, only
> its shape. A **hand-made** fixture exists to freeze one case a ticket rests on;
> it is never re-recorded, and it says which ticket and which case in the
> directory README.

This is the rule for both `fixtures/hardcover/hand-made/` and
`fixtures/googlebooks/hand-made/`. A directory rather than a filename suffix,
because the distinction is a different *reason to exist* and a directory is the
only form that cannot be forgotten when someone adds the next one.

## The frozen shapes: replies no book has

These two were named `hand-made-*.json` and sat among the live recordings until
CBO-74, which is exactly the ambiguity the directory removes: the only signal was
a word in the filename, and nothing said what it obliged anyone to do.

| File | Was | Reads it | The case, and why a live recording cannot carry it |
| --- | --- | --- | --- |
| `work-without-title.json` | `hand-made-work-without-title.json` | `LookupTests.test_it_falls_back_to_the_edition_title_when_the_work_has_none` | An edition whose work has **no `title` at all**. `books.title` is nullable in Hardcover's schema, and no real book has turned up to show the shape, so the reply is hand-made: `_candidate` has to fall back to the edition's own title, and a live recording cannot be relied on to contain a work with no title. |
| `wider-than-the-question.json` | `hand-made-wider-than-the-question.json` | `LookupTests.test_it_takes_authors_and_leaves_the_translator_behind` | A reply **wider than the question**: it carries a translator and a narrator where the query asked only for authors. `_author_rows` filters again on `contribution == "Author"` in case the source ever returns one, and this is the only evidence that the second filter is doing anything. |

Both are CBO-35's and CBO-36's, and the two ISBNs they carry
(`9780000000003`, `9780000000004`) are Colophon's own inventions rather than
numbers any book has — as hand-made as the bodies are.

## The absence cases: replies from before a field existed

These are **real recordings**, taken from this repository's own history rather
than invented. The 2026-09-23 re-record gave each of them the field the test
asserts is missing, which is the correct outcome for the corpus and the end of
the case — a test cannot assert an absence against a reply that has the field.
Recovered with `git show <the commit before the re-record>:<path>`.

| File | Source of the body | Recording era | Reads it |
| --- | --- | --- | --- |
| `sparse-isbn-reply.json` | `by-isbn-found.json` | pre-CBO-38 | `LookupTests.test_a_reply_that_does_not_carry_an_id_leaves_it_empty`, `GenreTests.test_a_recording_made_before_this_ticket_carries_none_either`, `test_correction.GenreMappingTests.test_a_recording_made_before_this_ticket_has_no_genres_to_ask_about`, `TheOtherFieldsTests.test_a_book_with_no_publisher_or_cover_carries_neither` |
| `cbo-38-without-tags.json` | `by-title-cragside-other-fields.json` | CBO-38, before CBO-42 | `TheOtherFieldsTests.test_the_title_path_carries_them_too` |
| `no-series.json` | `by-isbn-no-series.json` | pre-CBO-38 | `LookupTests.test_a_standalone_book_comes_back_with_no_series` |
| `two-series-featured-last.json` | `by-isbn-two-series.json` | `89886e2a7`, before the re-record | `LookupTests.test_it_prefers_the_series_hardcover_marks_as_featured` |

The test names in the tables are the ones inside `tests/test_hardcover.py` unless
they name another module.

**One file serves four tests, and that is the point of them.** `sparse-isbn-reply.json`'s
edition carries exactly `title`, `isbn_13`, `isbn_10`, `language`, `book`, and its
book carries exactly `title`, `contributions`, `book_series` — no `description`, no
`image`, no `release_date`, no `cached_tags`, and no `id` on the author or the
series. Four assertions in the client are about that one sparse shape:

- `book.author_ids == (None,)` and `book.series_id is None` — CBO-41's ids are
  absent, and absent is not a bug (`hardcover.py` reads a missing id as `None`);
- `book.genres == ()` — CBO-42's `cached_tags` is absent, and absent answers no
  genres;
- `book.publisher is None` and `book.cover is None` — CBO-38's two edition fields
  are absent, and neither is invented.

It is the body of `by-isbn-found.json`, one of two pre-CBO-38 ISBN replies with
byte-identical key sets at the edition and book level; either would serve all four,
and the Cragside one is kept because three of the four tests are about Cragside.
`no-series.json` is the other one, kept separately because it is about a different
book.

### `no-series.json`

`LookupTests.test_a_standalone_book_comes_back_with_no_series` was the last test
asserting an absence against a live file, and it is the reason this file exists.
Its live body states the absence correctly today — `book_series` is `[]` for
*Normal People*, a standalone book — but "correct today" is what every one of
CBO-74's four expired absence tests also had. A re-recordable file cannot hold an
absence, so this one does not re-record.

This body is the pre-CBO-38 `by-isbn-no-series.json`, and it carries a publisher
(`Faber & Faber`) where `sparse-isbn-reply.json` has none — the two sparse replies
are the same shape but never the same values, which is why both are here rather
than one standing for both.

### `two-series-featured-last.json`

`LookupTests.test_it_prefers_the_series_hardcover_marks_as_featured` needs a reply
whose featured series is **last**, and the live `by-isbn-two-series.json` no longer
is one. The re-record asked Hardcover with the shipped `order_by` and it returned
the featured row **first** — `The Mistborn Saga: The Original Trilogy`, then `The
Mistborn Saga`, then `The Cosmere` — so against the live file a client that took
`memberships[0]` and never read the `featured` flag would pass.

CBO-74 originally read that as "the fixture was never evidence about ordering, so
the case is gone". That was wrong, and this file is the correction: the *case* is
real and the client's behaviour on it is a claim worth keeping, even though the
old fixture's own docstring had the reason backwards. This body is the one from
`89886e2a7`, where the featured row is last. Verified red-capable — with `_series`
changed to return `memberships[0]`, the test fails on this file and passes on the
live one.

`cbo-38-without-tags.json` is the same kind of thing one era later: the title
path's reply once CBO-38 had widened the query but before CBO-42 asked for
`cached_tags`. It carries `description`, `publisher`, `release_date` and `image`,
and no tags. The `TheOtherFieldsTests` family reads it for the *presence* half of
CBO-38; `test_the_title_path_carries_them_too` reads it for the blurb and the
publisher, and would fail against the live file only because the live file has
grown tags since.

**Why these are here rather than left live.** A re-record answers the absence, so
a test asserting an absence against a live file is a test with an expiry date that
nobody wrote down. That is exactly what happened on 2026-09-23: four tests went
red at once, not because the client broke but because Hardcover answered more of
the question. Freezing the sparse reply makes the client's behaviour on a sparse
reply a permanent claim instead of a side effect of what one recording happened to
contain.

## The CBO-90 case: an Edition the source states is Audio

| File | Reads it | The case, and why a live recording cannot carry it |
| --- | --- | --- |
| `audio-edition-earliest.json` | `AudioEditionTests.test_an_audio_edition_is_not_offered`, `StandardEditionTests.test_the_title_path_writes_no_isbn_even_when_an_audio_edition_is_dropped` | The three Work 1198266 Editions of *The Infirmary* out of the live `by-title-the-infirmary.json`, with the Audio Edition `9781799729945` dated **earliest** (`2018-12-01`, where the live reply says `2019-02-10`) so that CBO-68's Standard Edition rule would choose it. **No live reply can carry this case**: Hardcover labels `9781799729945`, the Audible Studios on Brilliance Edition, as `reading_format_id: 4` (Ebook) with `edition_format: "Kindle"`, and none of the 28 Editions on the title path is stated Audio. The live reply's date is the one value this file invents; the dates of the other Editions are the real recording's, which is what leaves the print Edition the Standard Edition once the Audio one is dropped. |
| `audio-edition-only.json` | `AudioEditionTests.test_an_audio_edition_is_an_isbn_hardcover_does_not_have`, `StandardEditionTests.test_a_work_hardcover_lists_only_as_audio_offers_nothing` | The CBO-90 case where the Work's only Edition is an Audio one: the widened `QUERY`'s fields for `9781799729945`, out of `by-isbn-9781799729945-genres.json` as it stood before that recording was superseded, with `reading_format_id: 2`. The same body answers a title reply, because the two shipped queries select the same Edition fields. Two cases rest on it: Q10's, an ISBN Hardcover lists only as an Audio Edition is an ISBN it does not have, and §8 test 4's, a Work with nothing but an Audio Edition offers no candidate at all. |

## What is not here

The re-recordable ISBN and title recordings stay in the parent directory, even the
ones that have drifted, because a ticket does not rest on a drifted reply — it
rests on a reply that was true when it was taken and that nothing may now
overwrite.

`by-isbn-two-series.json` was expected to be the exception: recorded *without* the
query's `order_by` on purpose, because the point of it was the natural order
Hardcover returns, the featured series last. **The 2026-09-23 re-record showed
that claim was false** — asked with the shipped `order_by`, Hardcover returns the
featured row first anyway, so the fixture was never evidence about ordering and is
now an ordinary live recording. See the parent `README.md`.
