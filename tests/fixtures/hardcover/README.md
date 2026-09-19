# Recorded Hardcover replies

These are the reply bodies the tests replay, so the suite never needs an API key.

Provenance: Hardcover has no public sample responses and no key was available when
these were written, so the *shape* comes from Hardcover's own published GraphQL
schema and API documentation (see `docs/research/hardcover-api.md` for the cited
sources: `editions.isbn_13`, `book.contributions[].author.name`,
`book.book_series[].position`, `edition.language.code2`) and the *values* are
illustrative rather than captured from a live call.

What each one is for:

| File | What it stands for |
| --- | --- |
| `by-isbn-found.json` | A match with an author, a translator, a series and a language |
| `by-isbn-not-found.json` | An ISBN no edition carries: `data.editions` is empty |
| `by-isbn-no-series.json` | A standalone book: no series, no language |
| `by-isbn-edition-title-only.json` | A record whose work has no title, only the edition does |

If Hardcover is ever called with a real key, these should be replaced with
captured bodies, keeping this file honest about where they came from.
