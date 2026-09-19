# CBO-38: the fields and covers the two sources really offer

Probed live on 2026-09-19 with the real keys, from `.tmp/probe_cbo38.py`,
`.tmp/probe_cbo38_covers.py` and `.tmp/probe_cbo38_mask.py`. Raw replies are in
`.tmp/cbo38/`. Everything below is what the API actually answered, not what the
documentation says it would.

This is the probe for CBO-38 (*Configurable field rules and covers*), whose
acceptance criteria are that each metadata field follows its own rule (skip,
fill if empty, overwrite), that the description comes from the matched source
and is never AI-written, that a cover is added only when the book has none, that
all of it is configurable in `config.toml`, and that each rule type is tested.

## 1. What each source even has

CBO-35's client reads four fields. Three more are needed, and the two sources do
not offer the same ones.

### Hardcover

Introspection (`__type(name: "books")`, `__type(name: "editions")`) says:

| Field | Where | Type |
| --- | --- | --- |
| `description` | `books` | `String` (nullable) |
| `release_date` | `books`, `editions` | `date` (nullable) |
| `image` | `books`, `editions` | `images` (nullable) |
| `publisher` | `editions` only | `publishers` (nullable) |
| `language` | `editions` only | `languages` (nullable) |

`books` has no publisher column at all, and `editions` has no description
column at all. A candidate built from a Hardcover edition therefore gets its
description from `book.description` and its publisher from `edition.publisher`,
the same way the title already comes from `book.title` while the language comes
from `edition.language`.

Asked for the real Cragside edition (`isbn_13 = 9781521748831`), Hardcover
answered with all of it:

```
"publisher": {"name": "Independently Published"}
"release_date": "2017-07-07"
"image": {"url": "https://assets.hardcover.app/external_data/40810017/88c4da5caf5a76472600888c8c4ada978965ebdd.jpeg",
          "width": 333, "height": 500}
"language": {"language": "English", "code2": "en", "code3": "eng"}
"book": {"description": "FROM THE #1 INTERNATIONAL BESTSELLING AUTHOR OF HOLY ISLAND ...",
         "release_date": "2017-07-07"}
```

`editions.release_date` and `books.release_date` were **the same date**
(`2017-07-07`) for this book. Which one a candidate should carry is therefore not
observable from this one book; the edition's is the one that belongs to the
edition being matched.

### Google Books

Google's `/books/v1/volumes` reply for the same ISBN carries `description` and
`publishedDate`, and carries **no** `publisher` and **no** `imageLinks`:

```
publisher      = null
publishedDate  = "2017-07-07"
description    = "FROM THE #1 INTERNATIONAL BESTSELLING AUTHOR OF HOLY ISLAND ..."   (1084 chars)
imageLinks     = null
```

Across three title searches (Cragside, Poe, Sapiens), `imageLinks` was present
on some volumes and absent on others (1 of 2, 7 of 10, 10 of 10), and
`publisher` was `null` on a good share of them. Google simply does not have a
publisher for this Cragside record.

**This is the finding that changes the ticket's shape.** "Fill if empty" reads
like "if one source has nothing, the next one tops it up", but the pipeline
takes every value from the single source that matched the book. So a book
matched from Google Books gets no cover when Google's record has no
`imageLinks`, and no publisher when Google's record has none - and a book
matched from Hardcover gets no description when `books.description` is null.

## 2. The `fields` mask is throwing away two of the three new fields

The client sends `fields=` on every request, and today's mask is:

```
totalItems,items/id,items/volumeInfo/title,items/volumeInfo/authors,
items/volumeInfo/language,items/volumeInfo/industryIdentifiers
```

Asked with that mask, the very same ISBN request comes back with only
`authors`, `industryIdentifiers`, `language`, `title`:

| Field | with the mask | without it |
| --- | --- | --- |
| `description` | absent | present |
| `publishedDate` | absent | present |
| `imageLinks` | absent | absent for this volume, present for others |
| `publisher` | absent | `null` for this volume, present for others |

So the mask has to be widened before any of this can be written, and any
recording made with the old mask cannot be used to test the new fields.

## 3. Covers: what is actually downloadable

Hardcover's `image.url` is a plain HTTPS JPEG:

```
HTTP 200  type=image/jpeg  len=33380  magic=b'\xff\xd8\xff\xe0'
https://assets.hardcover.app/external_data/40810017/88c4da5caf5a76472600888c8c4ada978965ebdd.jpeg
```

Google's `imageLinks` URLs are handed out over **plain HTTP**:

```
http://books.google.com/books/content?id=7kMMzgEACAAJ&printsec=frontcover&img=1&zoom=1&source=gbs_api
```

Both the `http://` and the `https://` form of that URL answered 200
`image/jpeg`, and the bytes were identical either way. The `https://` rewrite is
worth doing - it is the same image - but it is not required for the fetch to
work.

Three more things about Google's cover URLs:

* **`thumbnail` and `smallThumbnail` are the same image.** For every volume
  measured, both zoom levels returned the same byte count (9997 for one, 11234
  for another). Asking for the "bigger" one buys nothing.
* **A thumbnail is small.** 9997 bytes, roughly a 128px-wide cover.
* **Some thumbnails have a scanned page edge in them.** URLs carrying `edge=curl`
  are the page as photographed, not a flat cover.

Google's covers are therefore usable but poor, and Hardcover's are not always
present. Neither is a reliable source of covers on its own.

## 4. The blurb is one string, and the same one from both sources

The Cragside blurb that Hardcover returned is **byte-for-byte identical** to the
one Google returned (1084 characters, `hc_text == gb_text`). Neither source
mangles it; what mangling there is is already in the data both sources hold:

```
raw bytes:  b'fianc\xef\xbf\xbde'      -> "fianc\ufffde"
```

`\xef\xbf\xbd` is UTF-8 for U+FFFD, the replacement character. It is the
*record's* `fiancée`, not a decoding mistake on our side: the reply is valid
UTF-8 and the character count agrees with what the fixture already holds.

The blurb contains no control characters and nothing XML 1.0 forbids
(`[hex(c) for c in text if ord(c) < 0x20]` is empty), so it can be written into
`dc:description` as it stands. A mojibake character in a description is a
cosmetic fault inherited from the source, not a reason to reject the record.

The blurb is 1 KB. The one-log-line-per-book rule means a log line that wrote
the description's value out in full would be 1 KB of prose per book.

## 5. What the test corpus already covers, and what it does not

Both Gutenberg fixtures **already have a cover**, declared both ways:

```
EPUB 2:  <meta name="cover" content="item1"/>
         <item href="...cover.png" id="item1" media-type="image/png"/>
EPUB 3:  <item href="...cover.png" id="item1" media-type="image/png" properties="cover-image"/>
```

and both carry `dc:date`.

So the "the book already has a cover, leave it" case is covered by a real book,
and the "add a cover to a book that has none" case needs a built fixture.
`tests/samplebooks.py` already has the builder for that.

## 6. Two things that changed the shape while building

### A cover URL in a test stand-in reached the network

Giving `Candidate` a `cover` field turned the existing relay tests into network
tests without touching them. `tests/sources.py`'s stand-in is built from the
real Hardcover recording, so once the new recording carried
`editions.image.url`, every test that corrected a book without a cover fetched a
33 KB JPEG from `assets.hardcover.app` - and the suite began failing about one
run in eight, because whether that fetch succeeded changed the book's bytes and
so the relay's judgement of whether a re-dropped book was a duplicate.

Two things came out of it:

* **A correction has to be reproducible**, because the relay decides a re-drop
  is a duplicate by comparing bytes. A cover's entry name is therefore built
  from the image's own bytes, never from a timestamp.
* **No test may reach the network at all.** The relay tests now patch
  `urllib.request.urlopen` so an outbound request fails loudly, and the stand-in
  offers no cover unless a test asks for one. This is test infrastructure, not a
  behaviour change: production still fetches the real cover.

### `add_cover` cannot be written after the `[fields]` table

In TOML everything after a table header belongs to that table, so an `add_cover`
placed below `[fields]` arrives as a *field* named `add_cover` and is refused as
one Colophon does not have. The example config puts it above the table and says
why, and a test loads `config.example.toml` so the file people copy cannot rot.

## 7. Open decisions this probe does not settle

1. How a per-field rule is spelled in `config.toml`, and whether the cover is
   one of the fields or a setting of its own.
2. Which of the nine fields the rules cover, given `isbn` and `language` are
   never written today.
3. Where a cover may come from when the matched source has none.
4. What happens to a file's series number when the series is overwritten but the
   number is not.
5. How much of Google's reply the widened mask should ask for, and whether the
   existing recordings are re-recorded or only added to.

All five were settled with the maintainer before any code was written: a
`[fields]` table, `add_cover` as a setting of its own, all nine fields
configurable, the matched source only, the number dropped when the series
changes, and only the new recordings added rather than all of them re-recorded.
