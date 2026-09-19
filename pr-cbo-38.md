# CBO-38: Configurable field rules and covers

Each metadata field now follows its own rule, set in `config.toml`: skip, fill
if empty, or overwrite. A cover is added to a book that has none, from the
source that matched it. Test-first throughout; the suite is 403 tests, `ruff`
is clean.

## What changed, per acceptance criterion

### Defaults: overwrite title, authors, series, series number; fill for description, publisher, date, ISBN, language

`colophon/config.py` gains `FIELD_DEFAULTS` (the nine fields and the rule each
gets), `KNOWN_FIELDS` (the same nine names, in the order the log line uses) and
a `[fields]` table in `config.toml` validated against both. A misspelt field or
an unknown rule is refused rather than ignored: a rule the user believes is
running and that never runs is the one failure of this setting that is
invisible from outside. Rules are read without regard to case, because this is
a setting people write by hand.

`Corrector._edits` decides each field on its own against the file as it was
read: `fill` writes only a field the file is empty of, `overwrite` writes
whatever the source has, `skip` writes nothing. A field the source said nothing
about is written by no rule at all, so `fill` on a field a source is silent
about is not a blank.

The defaults are compared against the ticket's list by
`test_the_default_rules_are_the_ones_the_ticket_names` and by
`test_the_nine_fields_are_the_ones_the_design_spec_names`.

### The description is the book's blurb from the matched source, never AI-written

`Candidate` gains `description`, and both sources fill it from their own
record: Hardcover from `books.description`, Google from
`volumeInfo.description`. No text is generated anywhere. Two tests compare the
written value character for character against the recording it came from
(`test_the_description_is_the_source_s_own_words_character_for_character`, in
both source test modules).

The one Cragside blurb both sources hold is byte-for-byte identical between
them, and it already contains the source's own U+FFFD where `fiancée` was
mangled upstream. That is inherited, not introduced, and is recorded in
`docs/research/cbo-38-field-rules.md`.

### A cover from the source is added only if the book has none

`add_cover = true` by default, a setting of its own rather than a `[fields]`
entry: there are only two sensible outcomes. `_has_cover` reads both ways a
book can declare one (EPUB 2's `<meta name="cover">` and EPUB 3's
`properties="cover-image"`), and a book that has one keeps it.

A cover is fetched from the matched source only, never from a lower-priority
one, for the same reason no other value is. The image is added beside the
package document under a name built from its own bytes, so the same image
added twice is the same entry, and it is declared in both formats as the series
already was. The media type is read off the image's own first bytes.

A cover that cannot be fetched, or that the file will not take, is a warning
and the metadata is still written: an image is the least important thing about
a book, and the relay has no guard around the correction pass.

### All rules can be changed in `config.toml`

`config.example.toml` shows every field and every default, commented.
`test_the_example_config_is_one_that_loads_and_says_what_it_claims` loads the
shipped file, so the one people copy cannot rot.

The seam the criterion actually names is tested end to end:
`test_the_rules_a_config_carries_are_the_rules_the_pass_applies` and
`test_the_cover_setting_a_config_carries_is_applied_too` write a
`config.toml`, run it through `load_config` and `Corrector.from_config`, and
check the corrected book.

### Tests cover each rule type

`FieldRuleTests` in `tests/test_correction.py` has a test per rule and per
awkward case: `fill` writing a missing field and leaving a present one, `fill`
with a source that has nothing, `overwrite` replacing, `skip` never writing, a
blanket skip writing nothing at all, one field kept while another is
overwritten, filling an ISBN and a language, the stale series number, and five
cover cases.

## Other things the ticket settled

- **A skipped series number is dropped when the series around it changes.** A
  number is a position in a named series, so one left behind by a replaced
  series is a claim about the wrong series. `drop_series_number` carries that
  to the EPUB writer, and the move is reported in the log like any other.
- **The log line names `description` and `cover` without their values.** The
  blurb is a thousand characters and a cover's value is bytes; the line's job
  is which fields moved and who supplied them.
- **Both sources' queries were widened** to ask for the fields the rules write:
  Hardcover's `books.description`, `editions.publisher`, `editions.release_date`
  and `editions.image`; Google's `description`, `publishedDate`, `publisher` and
  `imageLinks`.

## Decisions I made myself

- **`fill` is judged against the file, not the source.** So `language = "fill"`
  writes the source's language only when the file has none, and an ISBN rule
  cannot change an ISBN the file already carries.
- **`isbn` is written as `urn:isbn:…`,** on whichever identifier already says
  it is an ISBN, rather than adding a second identifier. A book's UUID or
  Gutenberg URL is left alone.
- **The date is written exactly as the source spells it** (`2017-07-07`,
  `2021-03`). Nothing normalises it; both are valid W3CDTF.
- **An empty string in `Edits` means "take the field off",** distinct from
  `None` meaning "the source said nothing". No rule spells removal, but the two
  had to be distinguishable or a field could never be removed.
- **The cover's zip entry name is `cover-<md5 of the bytes>.<ext>`** so a
  correction is reproducible, which the relay's duplicate detection depends on.
- **`_NAME_ONLY` covers `cover` as well as `description`** — the ticket named
  only the description, but a URL is no more use in a log line than a blurb.
- **A cover is not fetched at all when the book is going to be left alone,** and
  not fetched on a dry run either.

## Review fixes

`/code-review` ran on the first cut, both axes. What it found and what I did:

- **The nine field names were listed twice** (`KNOWN_FIELDS` and a `_WRITTEN`
  tuple) with a test pinning the copies equal. The corrector now walks
  `KNOWN_FIELDS`; the duplicate list and its test are gone.
- **The image signature table was in two modules and had already drifted:**
  `sources.py` accepted a `RIFF` that `epub.py` refuses, so such bytes passed
  the fetch and then raised `EpubError`, which escaped the correction pass.
  `EpubError` is now caught on both of the pass's write attempts, and both
  modules read one table.
- **The file's series was read from Calibre's tags only.** A book declaring its
  series the EPUB 3 way read as empty, so `series = "fill"` overwrote one that
  was already there. Both forms are read now, exactly as the cover already was.
- **A dry run stood in for the cover with empty bytes,** which then read as "not
  an image". It is a `would_add_cover` flag now.
- **A dead module-level `_edits`** left over from making it a method, and a
  stale reference to it in `docs/research/cbo-37-google-books.md`.
- **No test drove a `[fields]` table through `from_config`,** and the cover's
  log rendering was asserted only structurally. Both have tests now.
- **The tests were reaching the network.** Giving `Candidate` a cover URL made
  three hand-built correctors fetch a real 33 KB JPEG, which is what made the
  suite fail about one run in eight: whether the fetch succeeded changed the
  book's bytes and so the relay's duplicate detection. Every corrector a test
  builds now gets a fetch that cannot leave the machine, and both test bases
  patch `urlopen` as a backstop.

## A bug the tests found on the way

- **A correction was not reproducible across a second boundary.** The cover's
  zip entry was stamped with the wall clock, so two corrections of the same book
  either side of a second gave different bytes - and the relay decides a
  re-dropped book is a duplicate by comparing exactly those bytes. Over a
  library that means a re-dropped book is filed beside itself as a "different
  file" instead of being recognised as the duplicate it is. The entry is stamped
  with the book's own date now, and
  `test_two_corrections_a_second_apart_still_give_the_same_bytes` moves the clock
  to keep it that way. Found by the reproducibility test rather than by the
  review; 40 consecutive clean suite runs after the fix.

## Deferred

- **`series = "skip"` with the default `series_number = "overwrite"` writes the
  source's number under the file's own series name.** The mirror of the case
  the ticket settled: the number moves but the series does not, so the two can
  describe different books. `test_a_series_number_with_a_source_that_gave_no_series_name`
  already records that a number is written without a series name at all, so
  this is the existing behaviour of the field rather than a new gap, but it is
  worth deciding on rather than leaving implicit. Not fixed here: it is a
  change to what `series_number` means, not to CBO-38's rules.
- **A cover is only ever looked for on the source that matched.** When that
  source has none for the book - Google's ISBN record for Cragside carries no
  `imageLinks` at all - the book is left without one. Looking at the other
  sources needs its own decision about trusting a lower-priority source for an
  image (noted as a follow-up ticket).
- **Google's thumbnails are small and sometimes a scanned page edge**
  (`edge=curl`). No quality floor is applied, per the decision to show a small
  cover rather than silently refuse one; rewriting the curl is a follow-up.
- **The existing eleven Google recordings were left alone.** They were made
  with the old `fields` mask and hold none of the new fields, so the two new
  recordings carry the new fields and CBO-37's evidence is untouched.

## Research

`docs/research/cbo-38-field-rules.md` records the live probes: where each field
lives in each source's schema, that Google's `fields` mask was discarding three
of the four fields the rules need, that Google's cover URLs are plain HTTP and
that `thumbnail` and `smallThumbnail` are the same bytes, and the two things
that changed the shape while building (the network-reaching tests, and TOML's
rule that a key written after `[fields]` belongs to it).

## Ponytail review

Run on the full branch diff against `main`, unapplied, as the global rule says.

```
colophon/sources.py:L33-36: delete: IMAGE_SIGNATURES, a second image-signature table beside
  epub.COVER_TYPES (already drifted - sources accepts RIFF, the EPUB writer refuses it).
  Nothing replaces it; image() can test the bytes against epub.COVER_TYPES' signatures.
colophon/sources.py:L114-115: delete: _looks_like_an_image, a one-line helper whose whole body
  is that table, called once. Inline the sign test into image()'s one condition.
colophon/sources.py:L86-87: delete: `except SourceError: raise`, a no-op before the
  `except Exception` below it. Nothing replaces it.
tests/coverimage.py:L7-41: delete: a_one_pixel_png, _chunk and the __main__ writer, 41 lines
  generating the 70-byte fixture that is already committed.
  Path("fixtures/covers/one-pixel.png").read_bytes(), 1 line at the two test sites.
tests/fixtures/covers/hardcover-cragside.jpg: delete: recorded 33 KB cover no test opens (only
  google-cragside.jpg is read); the README row goes with it. Nothing replaces it.
tests/test_correction.py:L517-529: delete: test_the_added_cover_is_declared_for_epub_3_as_well,
  a second declaration test; test_a_cover_is_added_to_a_book_that_has_none (L505) and
  test_a_written_cover_is_declared_once_however_the_book_is_read (test_epub L515) already
  assert both declarations. Nothing replaces it.
colophon/correction.py:L526-529: delete: _blamed, a wrapper around _label; one helper called by
  the three sites. _label(source.name) in _failed, _label(...) in _cover.
colophon/correction.py:L338-348: shrink: isbn=None, book=None where the book is the answer to
  the isbn. Drop both params; isbn=book.isbn if book.isbn else None reads the same from a
  required book.
colophon/epub.py:L178-194: shrink: `name, image_bytes, _ = image if image is not None else
  (None, None, False)` plus a rebuild of the third flag. _set_cover returning (name, bytes) and
  bool(would_add_cover) already saying it, 1 branch.
colophon/epub.py:L689-691: yagni: _is_epub3, one line with one caller. Inline
  str(package.get("version", "3.0")).startswith("3") at the call.
tests/test_epub.py:L528-565: delete: _without_its_cover, 38 lines of byte surgery stripping a
  cover out of a Gutenberg book. write_epub(..., SIMPLE, version="3.0") writes a book that
  never had one, and the import re goes with it.
tests/sources.py:L72-79: shrink: the third copy of "refuse a cover fetch" (test_relay.py:L42-60,
  test_correction.py:L127-129). Keep this one, and have all three sites import it.

net: -132 lines possible.
```

Two notes on the list, for whoever picks it up:

- The `IMAGE_SIGNATURES` duplication is the same finding the standards review
  raised, and it is only half fixed. The damage is contained - an image the
  fetch accepts and the writer refuses is now a warning instead of an
  `EpubError` escaping the correction pass - but the two tables still disagree
  about `RIFF`, so `image()` can hand back bytes the EPUB writer will not take.
  One table, read by both, is the fix, and it is the first item to pick up.
- No finding was applied, per the global rule. `_without_its_cover` in
  particular is deliberate despite the line count: it exists so the "the book
  already has a cover, leave it" case is tested against a real Gutenberg book
  rather than a built one, which is what makes that criterion trustworthy.
