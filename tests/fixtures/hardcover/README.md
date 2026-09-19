# Recorded Hardcover replies

These are real replies from Hardcover's API, recorded on 2026-09-19 with the
query `colophon/hardcover.py` ships, so the suite never needs a key and never
touches the network. Each one was checked before it was written: a reply
carrying GraphQL errors was never saved as a fixture.

| File | ISBN | What it is | How |
| --- | --- | --- | --- |
| `by-isbn-found.json` | 9781521748831 | *Cragside*, L.J. Ross, DCI Ryan Mysteries #6, the series marked featured | recorded |
| `by-isbn-no-series.json` | 9780571334650 | *Normal People*, Sally Rooney: a standalone book | recorded |
| `by-isbn-not-found.json` | 9781786813891 | no editions at all | recorded |
| `by-isbn-two-series.json` | 9780765311788 | *Mistborn: The Final Empire*, in three series at once | recorded, without the query's ordering |
| `by-isbn-edition-title.json` | 9780007458424 | the edition is called *The Hobbit*; the work is not | recorded |
| `hand-made-work-without-title.json` | 9780000000003 | a work with no title of its own | hand-made |
| `hand-made-wider-than-the-question.json` | 9780000000004 | a reply with a translator and a narrator in it | hand-made |

The recorded bodies are the API's own, re-indented so they can be read in a
diff; nothing inside them is changed.

Two of them are hand-made, and named so, because no real book has shown the
shape: `books.title` is nullable in Hardcover's schema, and a reply *wider* than
the question - a translator where only authors were asked for - is the case
`colophon/hardcover.py` filters again in case the source ever returns one.

`by-isbn-two-series.json` is the only recording made without the shipped
query's `order_by`, because the point of it is the order Hardcover returns
naturally: the featured series **last**. The client has to prefer the featured
row itself rather than trust the server to put it first.

Two things worth knowing, both recorded above rather than described:

- The ISBN the design spec uses for *Cragside*, 9781786813891, is not in
  Hardcover at all. *Cragside* is there as 9781521748831. `by-isbn-not-found.json`
  is that first ISBN, since it is the case the project's own examples hit.
- `book_series.featured` is `Boolean!` and `books.title` is nullable, both
  checked against the API's own schema.
