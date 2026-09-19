# Recorded Hardcover replies

These are real replies from Hardcover's API, recorded on 2026-09-19 with the
queries `colophon/hardcover.py` ships, so the suite never needs a key and never
touches the network. Each one was checked before it was written: a reply
carrying GraphQL errors was never saved as a fixture.

## By ISBN — the query that walks from an edition to its work

| File | ISBN | What it is | How |
| --- | --- | --- | --- |
| `by-isbn-found.json` | 9781521748831 | *Cragside*, L.J. Ross, DCI Ryan Mysteries #6, the series marked featured | recorded |
| `by-isbn-no-series.json` | 9780571334650 | *Normal People*, Sally Rooney: a standalone book | recorded |
| `by-isbn-not-found.json` | 9781786813891 | no editions at all | recorded |
| `by-isbn-two-series.json` | 9780765311788 | *Mistborn: The Final Empire*, in three series at once | recorded, without the query's ordering |
| `by-isbn-edition-title.json` | 9780007458424 | the edition is called *The Hobbit*; the work is not | recorded |
| `hand-made-work-without-title.json` | 9780000000003 | a work with no title of its own | hand-made |
| `hand-made-wider-than-the-question.json` | 9780000000004 | a reply with a translator and a narrator in it | hand-made |

## By title — the query for a book whose file carries no ISBN

The reply is a list of editions, because that is what the `editions` root field
returns; the client keeps the first edition of each work. Every one of these was
recorded with `{book: {title: {_in: ["…"]}}, language: {code2: {_eq: "en"}}}`,
the cleaned title the file really carries, and `The Infirmary` was recorded too
because it is the one that must be *rejected*.

| File | Title asked about | What came back | How |
| --- | --- | --- | --- |
| `by-title-cragside.json` | `Cragside` | work 1198994, *Cragside*, L.J. Ross, #6 | recorded |
| `by-title-berwick.json` | `Berwick` | work 2379453, *Berwick*, L.J. Ross, #24 | recorded |
| `by-title-belsay.json` | `Belsay` | work 1647114, *Belsay*, L.J. Ross, #23 | recorded |
| `by-title-the-infirmary.json` | `The Infirmary` | work 1198266 (*The Infirmary*, L.J. Ross, #11) **and** work 2284109 (*The Infirmary*, Carly Reagon) | recorded |

`by-title-the-infirmary.json` is the important one: two different books share the
title, and only the author tells them apart. It is the reply that proves a title
match on its own is not a match.

These four keep `books.id`, which the ISBN recordings do not. The reason is in
the reply's shape: several editions of one work come back for a single title, and
`id` is the only thing that says they are the same work. Without it the client
would offer the same book twice, and the second copy would be scored as if it
were a different candidate. The ISBN recordings omit `id` deliberately (the point
of `hand-made-work-without-title.json` is the nullability of `books.title`), so
the two sets are not consistent with each other; this is the stated difference.

The recorded bodies are the API's own, re-indented so they can be read in a
diff; nothing inside them is changed.

Two of the ISBN recordings are hand-made, and named so, because no real book has
shown the shape: `books.title` is nullable in Hardcover's schema, and a reply
*wider* than the question - a translator where only authors were asked for - is
the case `colophon/hardcover.py` filters again in case the source ever returns
one.

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
