# The Gutenberg fixtures

`the-masque-of-the-red-death-epub2.epub` and `the-masque-of-the-red-death-epub3.epub`
are the same Project Gutenberg book, published in Gutenberg's EPUB 2 and EPUB 3
layouts, so the two can be compared:

- EPUB 2: <https://www.gutenberg.org/ebooks/1064.epub.noimages>
- EPUB 3: <https://www.gutenberg.org/ebooks/1064.epub3.images>

They are public domain in the USA (`dc:rights`), and their Project Gutenberg
licence is kept exactly as it came from Gutenberg: Colophon rewrites only the
package document, and tests assert that every other entry survives byte for byte.

Why these: they are real files from a real publisher of EPUBs, they are small
(~80 KB each), and between them they cover the layout differences that matter -
an `opf:scheme="ISBN"` identifier against a `urn:isbn:` one, and a `dc:creator`
that carries `opf:file-as` against one that is refined by separate `meta` tags.
