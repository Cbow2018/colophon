# Recorded covers

Real images, fetched from the URLs the two sources' own replies point at, so a
test can hand the corrector the bytes it would have downloaded without touching
the network.

| File | Where it came from | What it is |
| --- | --- | --- |
| `hardcover-cragside.jpg` | `editions.image.url` in `fixtures/hardcover/by-isbn-cragside-edition.json` | 33 KB, 333×500 |
| `google-cragside.jpg` | `volumeInfo.imageLinks.thumbnail` in `fixtures/googlebooks/by-title-cragside-other-fields.json` | 9997 bytes |
| `one-pixel.png` | built by `tests/coverimage.py`, which is where it is written from | 70 bytes, a real 1×1 PNG |

`hardcover-cragside.jpg` and `google-cragside.jpg` are the two sources' covers
for the same book, and the size difference is the point: Google's cover URLs are
thumbnails, and Google's `thumbnail` and `smallThumbnail` were the same bytes
for every volume measured. Neither source always has one - the ISBN reply for
Cragside carries no `imageLinks` at all - so a book matched from a source with no
cover for it is left without one.

`one-pixel.png` is built rather than recorded, by
`python tests/coverimage.py`, because a 1×1 PNG is not a book's cover and
pretending it is would be a lie in a diff. It is a real PNG, though, which is
what the media type being read off the bytes needs: a fake signature would be
the signature table tested against itself.

Both JPEGs contain no personal data: they are publisher cover images, the same
ones the public API hands to anyone who asks.
