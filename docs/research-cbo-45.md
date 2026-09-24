# CBO-45 — FB2 support: research

Session 1 of 3, research only. Branch `dsh/cbo-45-fb2`, cut from `origin/main`
at **`593f14a`** (merge of PR #17, CBO-73). Nothing but this note is committed.
The probes are two throwaway scripts outside the repo; what they showed is
recorded below.

**Preconditions checked.**

* **CBO-39 is on `main`.** PR #10 merged as `b9d576c`, an ancestor of
  `593f14a` (`git merge-base --is-ancestor b9d576c HEAD`). The marker lives in
  `colophon/epub.py:41-60` (`COLOPHON_PREFIX`, `UNVERIFIED_TAG`,
  `UNVERIFIED_NOTE`), `Edits.unverified` / `drop_description` /
  `notes_taken_off` (`epub.py:128-174`) and `correction.py:1158-1221`
  (`_edits`). Item 5 can build on it.
* **CBO-45's blockers are done.** CBO-35 (Done, PR #5) and CBO-50 (ruff format,
  merged `e5ea994`).

**External sources**, pinned to the commits read:

| Source | Commit | Used for |
| --- | --- | --- |
| calibre, `src/calibre/ebooks/metadata/fb2.py` and friends | `0583cba2680b` (2026-09-23) | what calibre reads and writes |
| Calibre-Web-Automated | `43718d85f6b0` (2026-08-06) | what CWA does with an FB2 |
| KOReader crengine | `517b8f0a6562` (2026-09-22) | one real e-reader's FB2 reader |
| gribuser/fb2 (FictionBook 2.0 XSD) | `4d3740e31903` | the schema |
| r-glazkov/fb2 `examples/books/churchill_trial.fb2` (1.1 MB, a real LitRes-derived book with cover), `tests/resources/*.fb2`; yauhenipakala/FB2Library `files/test.fb2` (the FB2 spec's own example, XML Spy comments); localhots/fb2 `test/fixtures/sample.fb2` | as cloned | the round-trip probe's inputs; **not** for committing (licences unclear) |

"Verified" below means read in that source, or observed in the probe. Anything
not verified is marked **unverified**.

---

## 1. What the EPUB/KEPUB path already gives FB2

**Answer: a seam exists in shape but is not cut. Cutting it is small, lives in
`correction.py`, and does not need `epub.py` touched. It does not need the
ticket split.**

### How it is structured today

All format knowledge is in one module, `colophon/epub.py`, behind two
functions:

* `read(path) -> Book` (`epub.py:177`)
* `correct(path, edits, write=True, cover=None, would_add_cover=False) -> tuple[str]`
  (`epub.py:280`). It returns the names of fields that moved, writes nothing
  when nothing moved, and raises `EpubError` before writing anything.

The walk (`correction.py`) never touches XML. It decides an `Edits` and hands it
over. That is the right interface for FB2, and FB2 can implement it unchanged.

What is **not** format-neutral is the wiring. This is every coupling point
outside `epub.py`:

| Where | What | FB2 needs |
| --- | --- | --- |
| `correction.py:96`, `:510` | `BOOK_SUFFIXES = (".epub", ".kepub")` gate on `path.suffix` | `.fb2` added, and a choice of module |
| `correction.py:530`, `:923`, `:975` | `epub.read(...)`, `epub.correct(...)` called by name | called on the chosen module |
| `correction.py:25` | imports `Edits`, `EpubError`, `UNVERIFIED_TAG`, `unmarked` from `epub` | the error type caught must cover FB2's too |
| `sources.py:26` | `from colophon.epub import is_cover` (the fetcher refuses non-images) | unchanged if FB2 takes the same image types |
| `epub.py:96-174` | `Book` and `Edits` are defined in the EPUB module | FB2 must build the same `Book` and read the same `Edits` |

### The smallest cut

1. `colophon/fb2.py` exposes the same `read` / `correct` pair and raises
   `Fb2Error`. It imports `Book`, `Edits`, `COLOPHON_PREFIX`, `UNVERIFIED_TAG`,
   `UNVERIFIED_NOTE`, `unmarked` and `has_note` **from `colophon.epub`**. The
   name is odd, but nothing in `epub.py` changes.
2. `correction.py` swaps the suffix gate for a lookup: `.epub`/`.kepub` → `epub`,
   `.fb2` → `fb2`, and anything else stays silent pass-through. The three call
   sites call `module.read` / `module.correct`. `except EpubError` becomes
   `except (EpubError, Fb2Error)`, or a shared base class.
3. Keep calling through the module object. `tests/test_correction.py:3588` and
   `:3810` monkeypatch `colophon_epub.correct`, and that only keeps working if
   the dispatch looks the function up on the module at call time.

That is roughly 15–20 changed lines in `correction.py` and none in `epub.py`.
Moving `Book`/`Edits`/the marker constants into a neutral module (say
`colophon/book.py`) is tidier, but it is a refactor of the EPUB path: five test
files import from `colophon.epub`, plus `sources.py`. It isn't needed for FB2.
See decision D1.

### What `Book` means for FB2 (the read side of the seam)

Every `Book` field has an FB2 source (§2). Three are derived rather than read
straight off an element, and they matter for the seam:

* `Book.description` — the text of `title-info/annotation`, with paragraphs
  joined by `"\n\n"`. That is exactly the shape `epub.unmarked()` /
  `has_note()` already recognise (`_UNVERIFIED_PLAIN`, `epub.py:54`). So
  `correction._edits` (`:1189`, `:1201`, `:1212`) works on FB2 unchanged.
* `Book.unverified` — the tag, or the note as the final `<p>` (§5).
* `Book.subjects` — the `title-info/genre` texts that don't start with
  `colophon:`.

### What `Edits` means for FB2 (the write side)

`Edits` already carries enough to write FB2 without guessing. The one
difference is that FB2's writer has to treat the description **structurally**
and not as text (§5):

| `Edits` state | EPUB does (`epub.py:602-621`) | FB2 must do |
| --- | --- | --- |
| `unverified=True` | appends the note to the text | append one `<p>` to the existing annotation; ignore `edits.description` |
| `unverified=False, notes_taken_off=True` | writes the un-noted text | remove the note `<p>`; if `drop_description`, remove the now-empty annotation |
| `description` set by a rule | writes the text | rebuild the annotation from the text |
| `unverified=None` | description as rules left it | same |

Why this matters: writing `edits.description` back as text on every mark would
flatten the user's `<emphasis>`, `<poem>` and `<cite>` markup into plain `<p>`s.
The ticket says "without disturbing the user's own annotation", so marking must
not rebuild it.

---

## 2. The field map

FB2's `<description>` has four children, in schema order (`FictionBook.xsd:91-204`):
`title-info` (required), `src-title-info` (optional; the *original* of a
translation), `document-info` (required; about the *FB2 file* and who made it),
`publish-info` (optional; the *paper edition*). `title-info` child order is
fixed: `genre+ author+ book-title annotation? keywords? date? coverpage? lang
src-lang? translator* sequence*` (`:570-644`).

**Rules that hold for every row:**

* Colophon reads and writes **`title-info` and `publish-info` only**.
  `src-title-info` describes a different book (the original of a translation),
  and `document-info` describes the file. Neither is read or written.
* **Elements that already exist are edited in place**, as text or attributes, so
  their unknown attributes (`xml:lang`, `id`) and children survive. A new
  element goes in at its schema position.
* **Compare in the written form.** A value counts as "moved" only when what
  would be written differs from what's there. That covers digits for ISBN,
  year for date, joined names for authors, and `_position()` for series
  number. It's what keeps a re-dropped book from being rewritten.

| Colophon field | FB2 read | FB2 write | Loss / notes | calibre reads it? |
| --- | --- | --- | --- | --- |
| `title` | `title-info/book-title` | same, text in place | `publish-info/book-name` (the print edition's full name, often long) is neither read nor written | yes, `fb2.py:196-204` |
| `authors` | each `title-info/author`: `first-name middle-name last-name`, space-joined, empty parts skipped; `nickname` only when all three are empty | per author: unchanged display name → element untouched; changed → new `<author>` from a whitespace split (see below) | see below | yes, same join and nickname fallback, `fb2.py:153-193` |
| `isbn` | `publish-info/isbn`; text up to the first comma, then `epub._as_isbn` | same element; **bare digits**, never `urn:isbn:` | none | yes, `fb2.py:268-276`. calibre stores the raw string when `check_isbn` passes, so a `urn:isbn:` form would reach the library verbatim |
| `series` | first top-level `title-info/sequence/@name`; fallback first `publish-info/sequence/@name` | first top-level `title-info/sequence/@name` (created if absent) | nested `<sequence>` children are ignored, and left in place | yes, `fb2.py:251-265` |
| `series_number` | `@number` of that same element | `@number` via `epub._position`; `drop_series_number` removes the attribute | the schema types `number` as `xs:integer` (`:529`), so `1.5` is schema-invalid. calibre writes it anyway (`fb2.py:381`). KOReader reads it with `atoi` and shows `1` (`lvtinydom.cpp:11801`) | yes, as float |
| `language` | `title-info/lang` | same | none. `src-lang` is the original's language, untouched | yes, `fb2.py:302-306` |
| `description` | `title-info/annotation`, paragraph texts joined by `"\n\n"` | see §1 table; a rule-written blurb becomes one `<p>` per paragraph | source HTML (Google) is flattened to paragraphs; inline bold/italic is dropped | yes, as plain text, `fb2.py:279-286` |
| `publisher` | `publish-info/publisher` | same | none. `document-info/publisher` is the e-book seller, untouched | yes, `fb2.py:289-292` |
| `date` | `publish-info/year` | `publish-info/year`, **year only** | month and day are lost. `title-info/date` (when the *work* was written) is not ours. The matcher only scores the year (`matching.py:430`), so reading is lossless for Colophon | yes, year only, `fb2.py:295-299` |
| genres (`Edits.genres`) | `title-info/genre` minus `colophon:*` → `Book.subjects` | append `<genre>` after the last one, add-only | outside the FB2 genre enum (§5) | yes, verbatim, all of them, `fb2.py:240-248` |
| tag (`colophon:*`) | `title-info/genre` | §5 rule | §5 | yes |
| cover | `title-info/coverpage/image/@xlink:href` → `binary[@id]` | `title-info/coverpage/image` + one `binary`; JPEG, PNG or GIF, as for EPUB (D3, Q13) | — | yes, `fb2.py:207-237` |

### `sequence` in both `title-info` and `publish-info`

The schema allows both (`:183`, `:642`). They mean different things:
`title-info/sequence` is the author's series, and `publish-info/sequence` is
the publisher's imprint series (e.g. a "classics" line).

* **Read:** `title-info` wins, and `publish-info` is only a fallback. That
  matches calibre, which takes the first match of `title-info/sequence[1] |
  publish-info/sequence[1]` in document order, and `title-info` always comes
  first (`fb2.py:255-258`). KOReader reads `title-info` only
  (`lvtinydom.cpp:11796`).
* **Write:** `title-info` only. `publish-info/sequence` is left alone.
  calibre's writer deletes every `sequence` in all three sections before
  writing (`fb2.py:67-70`, `:377`). Colophon shouldn't: the publisher series is
  real data that no source replaces, and `title-info` shadows it for every
  reader checked anyway. See D5.
* A book whose series was read from the `publish-info` fallback and then
  overwritten gets a new `title-info/sequence`. That shadows the old one in
  every reader, and the old one is kept.

### Authors: the mapping and where it loses

Colophon holds an author as one display string (`Book.authors`, `Edits.authors`
are tuples of `str`). FB2 holds parts.

* **FB2 → Colophon:** join `first middle last` with single spaces, which is
  calibre's rule (`fb2.py:178-193`). Loss: `nickname` is dropped when there is
  a real name, along with `home-page`, `email` and `id`. Colophon doesn't use
  any of them.
* **Colophon → FB2:** split on whitespace. One token → `<nickname>`. Two →
  first and last. Three or more → first, middle = the second token, last =
  everything else. That is calibre's writer exactly (`fb2.py:331-348`).
* **Round trip is stable.** Joining a split gives back the same string, so a
  corrected FB2 read again reports the same authors, and re-drops are not
  rewritten.
* **Where it's wrong:** compound surnames without a particle ("Gabriel García
  Márquez" → middle `García`, last `Márquez`). Stacked initials ("J. R. R.
  Tolkien" → middle `R.`, last `R. Tolkien`). Surname-first names ("Liu Cixin"
  → first `Liu`). Every reader here re-joins the parts in the same order, so
  the **display** is right. Only sort-by-surname and the file's internal
  structure are wrong. Leaving unchanged authors untouched means the damage is
  limited to authors a source actually changed.
* **Mononyms:** `<nickname>` is schema-valid and calibre reads it, but KOReader
  ignores `nickname` entirely (`lvtinydom.cpp:11764-11774`) and shows no
  author. It's rare enough to accept.

### `FIELD_DEFAULTS` fields with no FB2 home

**None.** All nine have an element that calibre reads. Two are lossy on write:
`date` (year only) and `description` (inline formatting). One has
reader-dependent loss: `series_number` (fractions). Subtitle, which isn't in
`FIELD_DEFAULTS` yet, has no home (§8).

---

## 3. Round-trip safety with `xml.etree`

**Probe.** Each sample was parsed and written back with no edits, the way
`epub.py` does it: register the declared prefixes (`_keep_namespace_prefixes`,
`epub.py:1016`), `ET.fromstring`, then
`ET.tostring(encoding="utf-8", xml_declaration=True)`. It was repeated with
comments and PIs kept. The real book was also re-encoded as windows-1251, with
CRLF, with a BOM, with character references, and with a 15 MB image added. No
sample round-trips byte-identical. **The output is idempotent:** writing it a
second time gives the same bytes. And **every `binary` decodes to identical
bytes.**

Every change beyond the edited fields, from the probe:

| # | Change | Seen in | Would a reader or CWA notice? | Mitigation (for the build) |
| --- | --- | --- | --- | --- |
| 1 | XML declaration becomes `<?xml version='1.0' encoding='utf-8'?>`, with **single quotes** and lower case | every sample | **Possibly.** KOReader/crengine's FB2 sniffer only extracts `encoding="` with double quotes (`lvxml.cpp:2955`). calibre writes its own declaration by hand for exactly this reason: "there exists FB2 reading software that chokes on the use of single quotes in xml declaration" (`fb2.py:437-441`). | Write `b'<?xml version="1.0" encoding="UTF-8"?>\n'` by hand, then `ET.tostring(root, encoding="utf-8")`, which emits no declaration of its own for UTF-8 (probed). |
| 2 | A non-UTF-8 file (windows-1251, KOI8-R, CP866, ISO-8859-5 all parse) is re-encoded as UTF-8. The Cyrillic test grew from 707 KB to 1.1 MB | windows-1251 variant | No. The declaration says UTF-8 and the bytes match it. calibre does the same (`fb2.py:440`) | None. Always write UTF-8 (D4). Writing back in the source encoding is possible (`ET.tostring(encoding="windows-1251")`, with unencodable characters as `&#NNN;`) but isn't worth it |
| 3 | **Multi-byte legacy encodings (GB2312, Shift_JIS) raise `ValueError`, not `ParseError`** | probe | Not a write change. It's a crash if uncaught | Catch `(ET.ParseError, ValueError)` → `Fb2Error`, and the book passes through untouched |
| 4 | UTF-8 BOM dropped | BOM variant | No | None |
| 5 | CRLF → LF everywhere, including inside base64 | CRLF variant (1025 CRs removed) | No. XML normalises line ends, and base64 decoders skip whitespace | None (the whole-file diff is what the backup is for) |
| 6 | Trailing newline after `</FictionBook>` dropped | churchill, sample | No | None |
| 7 | **Comments:** the default parser drops them all. With `TreeBuilder(insert_comments=True, insert_pis=True)`, comments and PIs inside the root survive. Anything **before** the root (a leading comment, `<?xml-stylesheet?>`, `DOCTYPE`) is always lost, because ElementTree has no document node | test.fb2 (2 → 0, or 2 → 1 kept) | No reader checked uses them. A prolog `xml-stylesheet` only affects viewing the raw file in a browser | Parse with the `insert_comments`/`insert_pis` TreeBuilder. Accept losing the prolog |
| 8 | `<x/>` → `<x />`, and `<x></x>` → `<x />` | every sample | No, it's equivalent XML | None |
| 9 | **Namespace declarations** are hoisted to the root, and unused ones are dropped. When two prefixes name one URI (`xmlns:l` and `xmlns:xlink`, both XLink), every use gets the **last registered** prefix, so `l:href` becomes `xlink:href`. Without registration, prefixes become `ns0:`/`ns1:` | sample.fb2, plus a variant with `l:href` | Not by namespace-aware readers: calibre and crengine resolve by URI. A reader that string-matches `l:href` would break. **Unverified** whether one exists | Register declared prefixes per write, as `epub.py` does. When one URI has two prefixes, register the one used on `href` last |
| 10 | Character references and predefined entities are expanded (`&#160;` → U+00A0, `&quot;` → `"`, `&apos;` → `'`). Attribute quotes are normalised to `"` | char-ref variant | No | None |
| 11 | An undeclared entity (`&nbsp;`) is a `ParseError` | probe | Not a write change. The file can't be read | `Fb2Error`, so the book passes through untouched (the EPUB path does the same) |
| 12 | Large `binary`: a 22 MB file round-trips in 0.19 s, ~178 MB peak RSS for the whole probe process. Base64 text is byte-identical apart from #5 | +15 MB variant | No | None. Memory runs at a few times the file size, which is fine for books |
| 13 | Preserved as-is: attribute order, `xml:lang`, nested `sequence`, whitespace text between elements | complex.fb2 | — | — |
| 14 | **Process-global prefix map.** `ET.register_namespace("", FB2)` unmaps OPF's `""`, and a later OPF element serialises as `ns0:package` | probe | Not a reader issue. It's a Colophon hazard if the two writers interleave | Each writer registers immediately before it serialises. `epub.py` already re-registers on every call (`epub.py:337`), and the relay is single-threaded |

Also required, carried over from the EPUB writer: **nothing is written when
nothing moved.** A no-op pass then leaves the file byte-identical, and the
relay's duplicate check (`relay.py:_same_contents`) keeps working. The rewrite
goes to a hidden temp name and is then swapped in with `os.replace`, as
`epub._rewrite` does (`epub.py:1044-1068`). ElementTree output is
deterministic, so correcting the same book twice gives the same bytes.

**Reading must accept** the FB2 2.1 namespace
(`http://www.gribuser.ru/xml/fictionbook/2.1`), as calibre does
(`fb2.py:23-41`). The simplest form is to take the namespace from the root
element's own tag. A file without `description/title-info` is an `Fb2Error`,
mirroring "no metadata section" (`epub.py:340-341`).

---

## 4. `.fb2.zip` — decided: out of scope (D2)

**What happens today (verified by reading the code, not run):**

* **Colophon passes it through untouched.** `path.suffix` of `x.fb2.zip` is
  `.zip`, so the gate returns `Outcome(silent=True)` (`correction.py:510-511`).
  The file is not rejected and not misread. It's delivered as-is. `.fbz` (the
  other zipped-FB2 extension) goes the same way.
* **CWA never imports a `.fb2.zip`.** The watcher only processes files matching
  `SUPPORTED_EXT_REGEX` (`cwa-ingest-service/run:53`, filtered at `:424`). The
  list includes `fb2` and `fbz` but not `zip`, so the file sits in CWA's ingest
  folder indefinitely. (If `ingest_processor.py` is ever run on it directly, as
  happens when a whole folder is moved in, it takes the "unsupported" branch
  and deletes the file unimported in `finally` (`ingest_processor.py:1539`,
  `:799-810`). That's an edge case.)
* **`.fbz` is fine downstream.** CWA converts it (`ingest_processor.py:540`),
  and calibre's FB2 reader opens the zip and reads the first `.fb2` member
  (`fb2.py:83-98`; `file_types = {'fb2', 'fbz'}` in `builtins.py:197`).

**Is it in scope for CBO-45?** The ticket says "FB2 files" and doesn't mention
zips. **Recommendation (D2): out of scope.** Raise a follow-up ticket that
reads and writes the inner `.fb2` of `.fbz` and `.fb2.zip` with `zipfile`
(the `epub._rewrite` pattern, which already exists). It should also decide
whether a `.fb2.zip` should be **delivered unwrapped as `.fb2`**, given that
CWA ignores the zipped form.

---

## 5. The unverified marker as a general tag rule

### Is `colophon:unverified` in `<genre>` dropped or rejected?

| Consumer | What happens | Evidence |
| --- | --- | --- |
| FB2 schema | **Invalid.** `genre` is an enumeration of 186 codes (`FictionBookGenres.xsd`, via `FictionBook.xsd:575`). Strict validators reject it, e.g. FictionBook Editor's validate and library upload checks (**unverified** for specific tools) | verified (schema) |
| calibre's FB2 reader | **Kept verbatim** as a tag. Every `title-info/genre` text becomes a tag, with no vocabulary check and no translation (`fb2.py:240-248`). No genre mapping exists on the input side (grep of `fb2_input.py`) | verified |
| CWA | Goes through calibre: default config converts FB2 → EPUB with `ebook-convert` (`ingest_processor.py:724-757`; defaults `auto_convert=1`, target `epub`, `cwa_schema.sql:41-44`), and FB2Input takes metadata from the same `get_metadata` (`fb2_input.py:140`). With conversion off, `calibredb add` uses the same reader (`builtins.py:195-203`). **The tag reaches the library** | verified |
| KOReader | Kept verbatim. The first 16 `title-info/genre` texts go into "keywords" (`lvtinydom.cpp:11830-11850`) | verified |
| FBReader, PocketBook, Moon+ | **Unverified.** FBReader is known to map genre codes to display names. How it shows an unknown code isn't checked | — |

**Alternatives, and why `<genre>` stays.** CBO-39's note named
`<custom-info info-type="…">` and `<keywords>` as the schema-sanctioned
free-text carriers. **calibre reads neither.** `get_metadata` has no keywords
or custom-info parser (`fb2.py:101-150`). So either would be exactly the
"written but never read" waste item 6 warns about: the tag would never reach
CWA, and the user couldn't find their unverified books. `<genre>` is the only
element that becomes a calibre tag. Keep it, and accept schema invalidity (D7).

### How it interacts with `allowed_genres`

The same way it does on EPUB: they share one element and never interfere.

* Mapped genres are **added** after the book's own and never replace them
  (`epub._set_genres` semantics). The tag goes in the same list and is excluded
  from `Book.subjects` by prefix. So the genre mapping never sees it, and the
  "already carried" casefold check never counts it.
* A user's allowed genres ("Crime") are themselves outside the FB2 enum, just
  like the tag. FB2's own codes (`sf_fantasy`) won't casefold-match "Fantasy",
  so the mapped genre is added beside the code, which is what the add-only rule
  intends.
* Observation, not FB2-specific: `config._to_genres` (`config.py:425-454`)
  doesn't refuse an allowed genre starting with `colophon:`. Listing one would
  make the mapper write a mark. That's a CBO-42 edge worth one line of
  validation some day, and not this ticket's business.

### Where the sentence goes, and how CBO-39's removal finds it again

* **Where:** as a new, final `<p>` child of `title-info/annotation`, with text
  exactly `UNVERIFIED_NOTE`, no attributes and no children. If there's no
  annotation, one is created at its schema position (after `book-title`)
  holding only that `<p>`. The element before it gets a newline tail if it has
  none. calibre reads the annotation with `method='text'` (`fb2.py:29`,
  `:284`), which only separates paragraphs by the whitespace between them, so
  without the newline the note would run onto the blurb's last sentence.
* **Detection** (`Book.unverified`, the note half): the annotation's **last
  element child** is a `<p>` with no attributes, no children and
  `text.strip() == UNVERIFIED_NOTE`. It's end-only, as in CBO-39: a note
  anywhere else wasn't put there by Colophon. The text rendering in §1 gives
  the same answer through `has_note`, so the two can't disagree.
* **Removal:** remove exactly that one `<p>`. If the annotation then has no
  element children and no non-whitespace text, remove the annotation
  (`drop_description`). Nothing else in the annotation is touched: the user's
  paragraphs, their markup and their attributes all stay.
* Mark → unmark is structurally identical to the original, not byte-identical.
  That's the same as EPUB, whose OPF also goes through ElementTree.

### The rule for any `colophon:*` tag in FB2

> **A `colophon:<name>` tag is one `<genre>` element, a direct child of
> `title-info`, whose text is exactly the tag and which has no attributes.**
> **On:** if any `title-info/genre` already has that exact stripped text, do
> nothing. Otherwise insert one after the last existing `<genre>` (or first in
> `title-info` if there's none). **Off:** remove every `title-info/genre` whose
> stripped text equals the tag. Report "tag" as moved only when an element was
> added or removed. **Never touch** a `<genre>` whose text doesn't start with
> `colophon:`, never read or write `src-title-info` genres, and never write a
> `match` attribute.
>
> **The description note is not part of the rule.** It belongs to
> `colophon:unverified` alone, as the section above describes.

For the build: one primitive, `_set_tag(title_info, tag, on) -> bool`, used by
the unverified mark now. Each later tag then costs one call in `fb2.py` and
decides nothing FB2-specific.

---

## 6. Downstream

**Does CWA ingest FB2 as-is or convert it?** Converts it, by default.
`auto_convert` defaults to 1 with target `epub` (`cwa_schema.sql:41-42`), and
`fb2` is in the convertible set (`ingest_processor.py:540`). Conversion is
`ebook-convert in.fb2 out.epub` (`:737`), followed by `calibredb add`. If the
user lists `fb2` in `auto_convert_ignored_formats`, the FB2 is added as-is
(`:1478-1481`). **Both paths read metadata through calibre's
`ebooks/metadata/fb2.py:get_metadata`.** (CWA's own `cps/fb2.py` is only on the
web-upload path, and it opens files as UTF-8, so a windows-1251 upload would
fail there. That's not Colophon's path.)

**What calibre's FB2 reader imports** (all verified, `fb2.py` at `0583cba`):

| Field | Read from | Colophon writes there? |
| --- | --- | --- |
| title | `title-info/book-title` (the `publish-info/book-title` fallback at `:200` names an element FB2 doesn't have; it's `book-name`) | yes |
| authors | `title-info/author`, fallback `src-title-info`, then `document-info` | yes |
| series + number | `title-info/sequence[1]`, else `publish-info/sequence[1]`; number read as float | yes |
| ISBN | `publish-info/isbn`, first comma-separated value, checksum-checked | yes |
| language | `title-info/lang` | yes |
| tags | every `title-info/genre`, verbatim (fallback `src-title-info`) | yes (genres + tags) |
| comments | `title-info/annotation` as plain text | yes |
| publisher | `publish-info/publisher` | yes |
| pubdate | `publish-info/year` (year only) | yes |
| cover | `coverpage/image/@xlink:href` → `binary` | yes (D3) |

**Not read by calibre:** `keywords`, `custom-info`, `title-info/date`,
`translator`, `src-lang`, `publish-info/book-name`, `city`. **Nothing in §2's
map writes to them, so nothing Colophon writes is wasted.**

**Covers — decided: in scope (D3).** Colophon **does** write covers for EPUB:
`add_cover` defaults to true (`config.py:148`), and `correct(...,
cover=...)` adds one to a coverless book (`epub.py:929-975`). If FB2 has no
parity, `correction._write` would still fetch the image (`correction.py:920`)
and hand it to a writer that ignores it. The fetch is wasted and the setting is
silently a no-op for FB2. Parity is small:

* `Book.has_cover` = `title-info/coverpage/image` exists.
* Adding one = a `<coverpage><image l:href="#cover-<md5>.jpg"/></coverpage>`
  at its schema position, plus one `<binary id=… content-type=…>` of base64
  appended at the end of the root. Both go in one rewrite.
* calibre reads it (`fb2.py:207-237`).

Image types (settled by Q13): the same as EPUB, meaning whatever
`sources.is_cover` admits (JPEG, PNG, GIF). The FB2 schema only says "images"
(`FictionBook.xsd:219`). calibre and KOReader both read all three; FBReader and
PocketBook are unverified.

---

## 7. The test fixture

**Recommendation (D6): build it in test code, not as a committed file.** The
EPUB tests already work this way. `tests/samplebooks.py` writes small EPUBs
from string templates so "the difference … is visible in the test rather than
buried in a builder", and the only committed books are real Gutenberg files.
A hand-made FB2 is a few dozen lines of XML, and variants (marked, no
annotation, windows-1251, CRLF) are one `.replace()` each.

**On CBO-74's `hand-made/`:** that convention separates re-recordable **source
replies** from frozen ones. It doesn't exist on `main` yet (CBO-74 is in the
Backlog), and it's scoped to `hardcover/` and `googlebooks/`. An FB2 book is
neither kind: there is nothing to re-record. If you'd still rather have a file
(for example, to test the byte-level items with a non-UTF-8 file on disk), the
consistent place is `tests/fixtures/books/hand-made/fb2-minimal.fb2`, with the
`books/README.md` entry naming CBO-45 and the cases.

**The smallest FB2 that covers items 2–5** (the template; `{…}` are the test's
substitutions):

```xml
<?xml version="1.0" encoding="{encoding}"?>
<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"
             xmlns:l="http://www.w3.org/1999/xlink">
  <!-- kept: an in-body comment -->
  <description>
    <title-info>
      <genre>detective</genre>
      <author><first-name>L.</first-name><middle-name>J.</middle-name><last-name>Ross</last-name></author>
      <author><nickname>Anon</nickname></author>
      <book-title xml:lang="en">Cragside</book-title>
      <annotation><p>A <emphasis>DCI Ryan</emphasis> mystery.</p><p>Second paragraph.</p></annotation>
      <coverpage><image l:href="#cover.png"/></coverpage>
      <lang>en</lang>
      <sequence name="The DCI Ryan Mysteries" number="6"/>
    </title-info>
    <src-title-info>
      <genre>detective</genre>
      <author><first-name>Not</first-name><last-name>This</last-name></author>
      <book-title>Not this title</book-title>
      <lang>fr</lang>
    </src-title-info>
    <document-info>
      <author><nickname>file-maker</nickname></author>
      <date value="2026-09-23">2026</date>
      <id>colophon-test</id>
      <version>1.0</version>
    </document-info>
    <publish-info>
      <publisher>Dark Skies</publisher>
      <year>2017</year>
      <isbn>978-1-5217-4883-1</isbn>
      <sequence name="Publisher's Imprint Series" number="42"/>
    </publish-info>
  </description>
  <body><section><p>Cragside</p><empty-line/></section></body>
  <binary id="cover.png" content-type="image/png">{one_pixel_png_base64}</binary>
</FictionBook>
```

What each part is for:

* **Item 2:** three-part and nickname-only authors. `src-title-info` and
  `document-info` decoys that must never be read. Two sequences, where
  `title-info` must win and `publish-info` must survive a series overwrite. A
  hyphenated ISBN that must not be rewritten when the same digits arrive. A
  year-only date. `xml:lang` on `book-title` that must survive a title write.
* **Item 3:** the `l:` prefix on `href`, an in-body comment, `<empty-line/>`,
  and a `binary`. Built with `{encoding}` = `windows-1251` and encoded
  accordingly, it's the non-UTF-8 case. Assert: the declaration comes out
  double-quoted UTF-8, `l:href` is unchanged, the comment is kept, and a no-op
  pass leaves the bytes identical.
* **Item 5:** annotation with inline markup (must survive mark → unmark), plus
  variants with no annotation, and an annotation that is only the note.
* **Item 6 / D3:** `coverpage` present means `has_cover` is true. Take it out
  for the add-cover case. `tests/fixtures/covers/one-pixel.png` already exists
  and fills `{one_pixel_png_base64}`.

---

## 8. Later tickets that write to FB2

| Ticket | Writes | Follows §5's rule unchanged? |
| --- | --- | --- |
| CBO-80 | `colophon:source-unavailable` | **Yes.** Tag only; the ticket says "no description note". Pass-through with original metadata plus tag is the unverified write minus the note |
| CBO-51 | `colophon:cover-unavailable` | **Yes**, tag only. Its cover fallback is source-side and format-neutral. It only touches FB2 through cover writing, which is D3 |
| CBO-82 | `colophon:incomplete` | **Yes**, tag only. Its written fields are ordinary §2 fields |
| CBO-46 | `colophon:ai-guess` | **Yes** for the tag. The guessed values are ordinary field writes. A guessed release date lands as `publish-info/year`, so year only |
| CBO-75 | subtitle | **Not a tag, so the rule doesn't apply**, and FB2 has **no subtitle element** in `title-info` (`<subtitle>` exists only as a paragraph type in body text and annotations, e.g. `annotationType` at `FictionBook.xsd:381-389`). CBO-75 is currently about *scoring* Google's subtitle, not writing it. If it ever writes one, FB2's only reader-visible home is folding it into `book-title` ("Title: Subtitle"), which is also where calibre, having no subtitle field, would show it. Decide that alongside EPUB's form so the two agree |
| CBO-51, CBO-52 | covers | **Not tags.** CBO-52 (strip `edge=curl` from Google URLs) is format-neutral with no FB2 impact. CBO-51's fallback cover reaches FB2 through the cover writing D3 puts in CBO-45, with the same image types as EPUB (Q13) |

**All four tags follow the rule unchanged, and none needs its own FB2 decision.**
The only structural question they raise belongs to the EPUB side, since
`Edits.unverified` is one bool and four more tags will mean four more flags or a
mapping. Whichever shape EPUB chooses, FB2 calls `_set_tag` once per tag.

**CBO-57 (matcher split)** doesn't move the item 1 seam. The format seam
(`read → Book`, `correct(Edits)`) sits entirely in the file-specific half
CBO-57 says doesn't transfer, and the matcher already has its own input type
(`matching.FileBook`), with no imports from `epub` (`matching.py:23-27`). The
one crossing CBO-57 would have to cut is **`sources.py:26` importing
`is_cover` from `epub`**. That coupling predates FB2, and FB2 doesn't deepen it
provided FB2 accepts the same image types (D3).

---

## Decisions

Recommendations put to Callum and **agreed as recommended on 2026-09-23**, except where a row says otherwise.

| # | Decision | Outcome |
| --- | --- | --- |
| D1 | The seam | **Minimal dispatch inside CBO-45, no split.** `correction.py` picks the module by suffix and calls through the module object; `fb2.py` imports `Book`, `Edits` and the marker helpers from `epub.py`; `epub.py` is unchanged. A neutral module waits for CBO-57, if ever. |
| D2 | `.fb2.zip` / `.fbz` | **Out of scope; raised as CBO-84** (blocked by CBO-45). It reads and writes the inner `.fb2` via `zipfile`, and decides whether `.fb2.zip` is delivered unwrapped, since CWA's watcher never imports `.zip`. Both keep passing through untouched until then. |
| D3 | Cover parity | **In scope.** `has_cover` from `title-info/coverpage/image`; a missing cover is added as one `coverpage` element and one `binary`, in the same rewrite. Image types as for EPUB: JPEG, PNG and GIF (Q13 replaced the original "JPEG and PNG only"). |
| D4 | Output encoding | **Always UTF-8**, with the declaration written by hand as `<?xml version="1.0" encoding="UTF-8"?>`. |
| D5 | `publish-info/sequence` | **Left alone** on a series write. Only `title-info/sequence` is written. |
| D6 | The fixture | **Built in test code** from a string template (the `samplebooks.py` pattern), variants by substitution. No committed file, no `hand-made/` entry. |
| D7 | Schema-invalid genre | **`<genre>` confirmed.** Strict FB2 validators will reject `colophon:*` and mapped genres; calibre, CWA and KOReader keep them. |

### Follow-ups, 2026-09-23

| # | Question | Outcome |
| --- | --- | --- |
| Q8 | Error type `correction.py` catches (from D1) | **The tuple `(EpubError, Fb2Error)`** at the three call sites. No base class, so `epub.py` stays unchanged. |
| Q10 | Source blurb carrying HTML (Google) | **Flatten** to one `<p>` per paragraph and drop inline markup. calibre shows the annotation as plain text anyway (`fb2.py:284`). |
| Q11 | Fractional series number (`1.5`) | **Write it as-is**, as calibre does, even though the schema says `xs:integer`. KOReader shows `1`. |
| Q12 | Deliver `.fb2.zip` unwrapped? | **Left to CBO-84**, where it is the first thing to decide. |
| Q13 | Does FB2 need to refuse GIF covers? | **No: accept GIF, the same as EPUB.** calibre reads a GIF `binary` (`fb2.py:217-235`, where `image/gif` maps to an extension) and KOReader decodes GIF (`LVGifImageSource`, `lvimg.cpp:1002-1049`). No source has served one: every recorded cover is JPEG (14 Hardcover `.jpg`/`.jpeg`, 30 Google `books/content`). FBReader and PocketBook are unverified. With nothing refused there is nothing to fall back from, so CBO-45 adds no cover fallback and CBO-51 needs no change. |
| Q9 | A GIF cover offered for an FB2 | **Superseded by Q13.** Callum: if FB2 refuses GIF, a cover from another source should be used instead. That reopened the premise. |

## Still open

**Nothing.** Every branch was settled on 2026-09-23. CBO-45 is ready to build
on D1–D7 and Q8–Q13, and the zipped forms are CBO-84.
