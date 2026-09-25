# Hardcover (hardcover.app) book metadata API — ISBN lookup

Research for a Python 3.11 **standard-library-only** client that looks up a single book by its
exact ISBN.

Primary sources only. Hardcover's API docs live at `docs.hardcover.app` and are generated from
the official repo [`hardcoverapp/hardcover-docs`](https://github.com/hardcoverapp/hardcover-docs)
(the repo is linked from the docs site's own footer). Raw files from that repo are cited below
because the rendered doc pages are behind a Cloudflare challenge that intermittently returns
HTTP 403 to automated fetches.

> **Headline correction to the brief.** There is **no** `books.isbn_13` / `books.isbn_10`.
> The `books` table has no ISBN column at all. ISBNs live on **`editions`**
> (`editions.isbn_13`, `editions.isbn_10`). An ISBN lookup is therefore an **`editions`** query
> that traverses `edition.book` for title, authors and series.

---

## Verified facts

### 1. Endpoint and HTTP method

| Fact | Value | Source |
| --- | --- | --- |
| Endpoint URL | `https://api.hardcover.app/v1/graphql` | [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx) (the documented GraphQL console link is `...graphiql?endpoint=https://api.hardcover.app/v1/graphql`); independently confirmed by probing the URL directly |
| Transport | GraphQL over HTTP (Hasura) | [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx) — "Our API is accessible using GraphQL" |
| Method for queries | `POST` with `Content-Type: application/json` | Method is not spelled out in the prose; `POST` is what the documented Hasura GraphiQL console sends. **See [Unknowns](#unknowns).** |

Observed probe (this research session, no credentials):

```
GET https://api.hardcover.app/v1/graphql
-> HTTP 400
{"error":"invalid_request","error_description":"No Authorization header"}
```

So the route is live and terminates at the auth layer. Note the body is a **bare JSON error
object**, not a GraphQL `{"errors": [...]}` envelope.

### 2. Authorization header and where to get a token

* **Header format:** `Authorization: Bearer <token>`. The docs' own GraphQL console link
  pre-fills the header as `Authorization:Bearer%20` (decodes to `Authorization: Bearer `), and
  the doc text says to add a header called `authorization`. —
  [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)
* **Where to get a token:** account settings → the **Hardcover API** link → **New API Key**
  button. — [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)
* **Expiry:** you must *set* a time period ("Expiration") when creating the token; "After that
  time the token will no longer work, and you'll need to update it." Documentation does not state
  a default or maximum lifetime. — [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)
* **Scopes:** new-style tokens (created after August 2026) carry explicit scopes; legacy tokens
  are equivalent to `all`. Reading the tables needed for an ISBN lookup requires
  **`read:catalog`** (or the narrower `read:catalog:data` / `read:catalog:search`):
  `editions`, `books`, `book_series`, `series`, `languages`, `authors`, `contributions`,
  `publishers` are all listed against `read:catalog, read:catalog:data, read:catalog:search`.
  — [Actions & Scopes](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Actions.mdx)
* **Operational constraints that matter for a metadata client:**
  * "This should only be used from a code backend — never from a browser."
  * "This is only for offline use at this time. You can only access this API from localhost or APIs."
  * Tokens may be reset without notice while the API is in beta.
  — [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)

### 3. Fetching one book by ISBN

**Which table holds the ISBN: `editions`, not `books`.**

* `editions.isbn_13` — type `String`; `editions.isbn_10` — type `String`.
  Also present: `isbn_13_valid` / `isbn_10_valid` (`Boolean`, whether the number is valid) and
  `isbns_match` (`Boolean`, "Whether the ISBN-10 and ISBN-13 point to the same edition").
  — [Editions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx)
* The `books` type has **no** ISBN field. Its complete field list (and `books_select_column`
  enum, and `books_bool_exp` filter type) contains no `isbn` entry.
  — [schema-fields.json](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema-fields.json),
  [schema.graphql](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema.graphql)

**Hyphens:** Hardcover stores ISBNs **without hyphens**. "When you add an ISBN to Hardcover, the
hyphens are automatically removed."
— [ISBN and ASIN](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/librarians/Resources/ISBNAndASIN.mdx)

**Exact match:** use a Hasura `where: {isbn_13: {_eq: "..."}}` boolean-expression filter. The
docs ship this exact form as their "Get Edition Details by ISBN" example
(`editions(where: {isbn_13: {_eq: "9780547928227"}})`), with `isbn_10` used the same way on the
same table. — [Editions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx)

*Do **not** use `search` for this.* The Typesense-backed `search` root field returns
`results: jsonb` rather than typed rows and "does not currently support filtering by parameters
besides `query`". ISBNs are only one weighted field of a fuzzy, typo-tolerant ranked search.
— [Searching](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/Searching.mdx)

**Is the ISBN-10 vs ISBN-13 distinction meaningful? Yes.**

* They are two separate columns, so `_eq` against one will not match a row that only carries the
  other.
* `isbns_match` exists precisely because a single edition may hold both, and the pair may or may
  not describe the same edition.
* `isbn_13_valid` / `isbn_10_valid` let you reject malformed or placeholder values.
* ISBN-10 is case-sensitive in principle (check digit `X`), and nothing documents
  normalisation on write beyond hyphen stripping — see [Unknowns](#unknowns).

### 4. Response field paths (verbatim)

Paths below are relative to the GraphQL response root; prefix with `data.`.

| Need | JSON path | Type | Source |
| --- | --- | --- | --- |
| Edition title | `editions[0].title` | `String` | [Editions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx) |
| Work title | `editions[0].book.title` | `String` | [Books schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Books.mdx) |
| Author names | `editions[0].book.contributions[].author.name` | `String!` | [Contributions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Contributions.mdx), [Authors schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Authors.mdx) |
| Author role filter | `editions[0].book.contributions[].contribution` | `String` | [Contributions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Contributions.mdx) |
| Series name | `editions[0].book.book_series[].series.name` | `String!` | [Book Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx), [Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Series.mdx) |
| Position in series | `editions[0].book.book_series[].position` | `float8` | [Book Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx) |
| Position, as text | `editions[0].book.book_series[].details` | `String` | [Book Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx) |
| Language name | `editions[0].language.language` | `String!` | [Languages schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Languages.mdx) |
| Language ISO 639-1 | `editions[0].language.code2` | `String` | [Languages schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Languages.mdx) |
| Language ISO 639-2 | `editions[0].language.code3` | `String` | [Languages schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Languages.mdx) |

Notes on the traps the brief flagged:

* **Authors really are behind a join table.** `books.contributions` / `editions.contributions` is
  `[contributions!]!`; the name is at `contributions[].author.name`. The role string is
  `contributions[].contribution`, documented with capitalised values `Author`, `Illustrator`,
  `Translator`, `Editor`, `Narrator`, `Foreword`, `Afterword`, `Cover Artist`; the docs' own
  examples filter on `contribution: {_eq: "Illustrator"}` and `{_neq: "Author"}`, which confirms
  the capitalisation. There is also a newer normalised `contributor_role` object relationship
  (`contributions[].contributor_role`) alongside the legacy string.
  — [Contributions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Contributions.mdx)
* Contributions are polymorphic: `contributable_type` is `Book` or `Edition`. "The original author
  is typically credited at the book level, while edition-specific contributors are linked to
  individual editions" — i.e. translators/narrators often hang off the *edition*, so read authors
  from `book.contributions` and treat `editions[].contributions` separately.
  — [Contributions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Contributions.mdx)
* **Series really is behind a join table.** `books.book_series` is `[book_series!]!` and carries
  `position`; the series entity itself is `book_series[].series`, whose display name is
  `series.name` (the Series table's field is `name`, not `title`).
  — [Book Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx),
  [Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Series.mdx)
* A book can belong to several series rows, so `book_series` is an array. `books` also exposes a
  single `featured_book_series` (object) plus `featured_book_series_id`, and each `book_series`
  row has a `featured` boolean — useful if you want the one series Hardcover itself highlights.
  — [Books schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Books.mdx)
* **Language hangs off the edition, not the book.** `editions.language` → `languages`, with
  `language_id: Int`. The column holding the language name is `language` (not `name`), alongside
  `code2` (ISO 639-1) and `code3` (ISO 639-2). The `books` type has no language field at all.
  — [Editions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx),
  [Languages schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Languages.mdx),
  [Books schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Books.mdx)

### 5. Not-found, nulls, and error/rate-limit responses

**Not found:** a `where` filter that matches nothing is a *successful* query — the array
relationship simply comes back empty. So the client must treat `len(data.editions) == 0` as "no
such ISBN", not as an error. (The API's documented code table has no "not found" outcome for
list queries; `404` is listed only generically as "Not Found".)
— [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)

**Record exists but series/language is null:**

* Series: `book_series` is non-nullable `[book_series!]!`, so absent series → `"book_series": []`.
* Language: `editions.language` is a nullable object relationship (`languages`, no `!`), so → `"language": null`. Likewise `language_id: Int` is nullable.
— [Book Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx),
[Editions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx),
[schema-fields.json](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema-fields.json)

**Response codes** (verbatim from the docs):
— [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)

| Code | Meaning | Body example |
| --- | --- | --- |
| 200 | success | — |
| 400 | malformed request body, or unparseable GraphQL query | `{ error: "Malformed request body" }` or `{ error: "invalid_query", error_description: "..." }` |
| **401** | **missing, invalid, or expired token** | `{ error: "invalid_token", error_description: "..." }` |
| 403 | missing scope, disallowed operation, over the top-level query/mutation limit, or no access to the resource | `{ error: "insufficient_scope", error_description: "...", scope: "..." }`; `top_level_limit_exceeded` instead comes back as an `errors` array |
| 404 | Not Found | — |
| 408 | query exceeded max timeout | `{ error: "Request timeout" }` |
| **429** | too many requests | `{ error: "Too Many Requests", message: "..." }` |
| 500 | internal server error | `{ error: "An unknown error occurred" }` |
| 503 | temporarily unavailable, safe to retry | `{ error: "Service temporarily unavailable" }` |

My own unauthenticated probe of the live endpoint returned **400**, not 401, with
`error: "invalid_request"` / `error_description: "No Authorization header"` — so a *wholly
absent* header and a *bad* token are distinguishable by both status and `error` value.

**Rate limits** (verbatim from the docs):
— [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)

| Plan | Daily Limit | Burst Limit | Per Minute Limit |
| --- | --- | --- | --- |
| `Free` | 5,000 | 10 | 60 |
| `Supporter` | 50,000 | 15 | 60 |

* Each **top-level** query counts as one request; nesting fields under one root field is free.
* A single request may contain at most **5 top-level queries** (or 5 mutations, or 1 `search`).
  Exceeding it is rejected outright with **403**, not rate-limited.
* At the daily limit, requests return **429**.

**Rate-limit headers** (both sets are sent):
— [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)

* Modern, IETF-draft style: `RateLimit-Policy` (e.g. `"Free";q=60;w=60;burst=10, "daily";q=5000;w=86400`)
  and `RateLimit` (e.g. `"Free";r=8;t=42, "daily";r=4231;t=51234`) where `q`=quota, `w`=window
  seconds, `burst`=burst size, `r`=remaining, `t`=seconds to reset. The docs recommend building
  new integrations against these.
* Legacy: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`,
  `X-RateLimit-Daily-Limit`, `X-RateLimit-Daily-Remaining`, `X-RateLimit-Daily-Reset` (documented
  as deprecated and subject to removal).
* On a 429, a `Retry-After` header gives seconds to wait.

### 6. Series position can be non-integer

**Yes — positions are floating point.** `book_series.position` is typed **`float8`**, described as
"the numeric position of the book in the series, for collections it will be the first book".
— [Book Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx),
[schema-fields.json](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema-fields.json)

Corroborating first-party evidence for fractional values in real data: the series search index
documents `primary_books_count` as "Number of books in this series with an Integer position
(1, 2, 3; **exlcludes 1.5**, empty)" — i.e. 1.5-style positions exist.
— [Searching](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/Searching.mdx)

Other typing facts:

* The write-side input type is `BookSeriesDtoInput.position: numeric` (also non-integer).
  — [schema.graphql](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema.graphql)
* `book_series.details` is a `String` "Text form of position". For normal books it is just the
  string form of `position`; for a compilation it can be a range like `'1-3'` while `position` is
  still `1`. So `details` is the safer field to show a human, `position` the safer one to sort by.
  — [Book Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx),
  [Getting All Books in a Series](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/GettingBooksInSeries.mdx)
* `book_series.compilation` (`Boolean!`) marks compilation rows; the docs recommend filtering
  `compilation: {_eq: false}` to get the primary series list.
  — [Getting All Books in a Series](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/GettingBooksInSeries.mdx)
* Because it is `float8`, a whole-number position may still arrive as a JSON number that Python
  parses as `int` or `float` depending on serialisation — coerce with `float()` defensively.

### 7. User-Agent and query cost limits

* **User-Agent: recommended, not required.** "When authoring scripts that use the API, it is
  recommended to include a user-agent header with a description of the script." No required format
  is documented, and no request is documented as rejected for lacking one.
  — [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)
* **Query cost / complexity limits documented:**
  * Max **5 top-level queries** per request (1 `search`); over that → 403 `top_level_limit_exceeded`.
  * **30-second** max query timeout (**408**); **2-second** max timeout for search queries.
  * Regular-expression and pattern operators are disabled outright: `_like`, `_nlike`, `_ilike`,
    `_niregex`, `_nregex`, `_iregex`, `_regex`, `_nsimilar`, `_similar`. Plain `_eq`, `_neq`,
    `_in`, `_nin`, `_gt/_gte/_lt/_lte`, `_is_null` are *not* on the disabled list, so
    `{isbn_13: {_eq: ...}}` is fine.
  * No query **depth** limit exists yet; the roadmap lists "Queries will have a maximum depth of 3"
    as a future 2026 change. Keep the ISBN query shallow (it is depth 4 from root:
    `editions → book → book_series → series`) so it stays easy to trim if that lands.
  * No numeric "complexity score" or cost budget is documented — the documented controls are
    top-level count and wall-clock timeout.
  — [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)

---

## Ready-to-use query

One top-level query, one round trip, no `search`. Replace `%%ISBN%%` at call time; the value must
be digits only (ASCII, no hyphens, no spaces).

### ISBN-13 (the primary path)

```graphql
query BookByIsbn13($isbn: String!) {
  editions(where: {isbn_13: {_eq: $isbn}}, limit: 1) {
    id
    title
    subtitle
    isbn_13
    isbn_10
    isbn_13_valid
    isbn_10_valid
    isbns_match
    edition_format
    reading_format_id
    pages
    release_date
    publisher {
      name
    }
    language {
      language
      code2
      code3
    }
    book {
      id
      title
      subtitle
      release_date
      contributions(
        where: {contribution: {_eq: "Author"}}
        order_by: {id: asc}
      ) {
        contribution
        author {
          id
          name
        }
      }
      book_series {
        position
        details
        featured
        compilation
        series {
          id
          name
          slug
        }
      }
    }
  }
}
```

`order_by: {id: asc}` is included **only** to make the author array deterministic across calls.
It is *not* documented to reproduce Hardcover's display order — see [Unknowns](#unknowns).

### ISBN-10

Identical, except the filter column and variable name:

```graphql
query BookByIsbn10($isbn: String!) {
  editions(where: {isbn_10: {_eq: $isbn}}, limit: 1) {
    id
    isbn_10
    isbn_13
    book {
      title
      contributions(where: {contribution: {_eq: "Author"}}, order_by: {id: asc}) {
        author {
          name
        }
      }
      book_series {
        position
        series {
          name
        }
      }
    }
    language {
      language
      code2
    }
  }
}
```

### Accepting either ISBN length in one call

Useful when the caller may hand you either form. Still one top-level query, still an exact match —
`_or` is available on every `*_bool_exp` and is not on the disabled-operator list.

```graphql
query BookByIsbn($isbn: String!) {
  editions(
    where: {_or: [{isbn_13: {_eq: $isbn}}, {isbn_10: {_eq: $isbn}}]}
    limit: 1
  ) {
    id
    isbn_13
    isbn_10
    book {
      title
    }
  }
}
```

### Exact HTTP headers and body

```http
POST /v1/graphql HTTP/1.1
Host: api.hardcover.app
Authorization: Bearer <HARDCOVER_TOKEN>
Content-Type: application/json
Accept: application/json
User-Agent: colophon/0.1 (+https://github.com/Cbow2018/colophon)
```

```json
{
  "query": "<the query string above>",
  "variables": { "isbn": "9780765311788" }
}
```

`Authorization` is the only mandatory header. `User-Agent` is recommended by the docs (see §7).
Python 3.11 stdlib only: build this with `urllib.request.Request(url, data=..., headers=...)` +
`json.dumps`/`json.loads`; the caller must send `POST`, and should surface a non-2xx by parsing the
bare `{"error": ..., "error_description": ...}` body documented in §5 rather than assuming a
GraphQL `errors` array.

---

## Recorded response

> **Status: RECONSTRUCTED, not captured.** No authenticated call could be made from this research
> environment (subprocess network egress is blocked, and the available fetch tool cannot set an
> `Authorization` header), and no token was available. **The field names, nesting and nullability
> below are taken from the cited schema artifacts; the values are illustrative**, except where the
> provenance table marks them as documented. Do not treat this as a real payload.

Shape source: the "Get Edition Details by ISBN" example in
[Editions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx)
(`editions → book → contributions.author.name`, `language.language`), joined to the
`book_series → series.name` / `.position` path from
[Book Series schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx)
and the exact types in
[schema-fields.json](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema-fields.json).
Nesting confirmed as legal by the guides
[Getting Book Details](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/GettingBookDetails.mdx)
and [Getting All Books in a Series](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/GettingBooksInSeries.mdx),
which both traverse `book { contributions { author { name } } }` and `book_series { position book { title } }`.

```json
{
  "data": {
    "editions": [
      {
        "id": 21953653,
        "title": "Mistborn: The Final Empire",
        "subtitle": null,
        "isbn_13": "9780765311788",
        "isbn_10": "076531178X",
        "isbn_13_valid": true,
        "isbn_10_valid": true,
        "isbns_match": true,
        "edition_format": "hardcover",
        "reading_format_id": 1,
        "pages": 541,
        "release_date": "2006-07-17",
        "publisher": {
          "name": "Tor Books"
        },
        "language": {
          "language": "English",
          "code2": "en",
          "code3": "eng"
        },
        "book": {
          "id": 328491,
          "title": "Mistborn: The Final Empire",
          "subtitle": null,
          "release_date": "2006-07-17",
          "contributions": [
            {
              "contribution": "Author",
              "author": {
                "id": 80626,
                "name": "Brandon Sanderson"
              }
            }
          ],
          "book_series": [
            {
              "position": 1,
              "details": "1",
              "featured": true,
              "compilation": false,
              "series": {
                "id": 5507,
                "name": "Mistborn",
                "slug": "mistborn"
              }
            }
          ]
        }
      }
    ]
  }
}
```

### Value provenance

| Value | Status |
| --- | --- |
| All key names, nesting, and `null` vs `[]` placement | **Documented** — [Editions](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx), [Book Series](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx), [Languages](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Languages.mdx) |
| ISBN `9780765311788` ↔ "Mistborn - The Final Empire" ↔ "Brandon Sanderson" | **Documented** (as `isbn_meta` output quoted by Hardcover) — [ISBN and ASIN](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/librarians/Resources/ISBNAndASIN.mdx) |
| `edition_format: "hardcover"` as a legal value | **Documented** — [Editions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx) ("hardcover, paperback, ebook, audiobook") |
| `reading_format_id: 1` as a legal value | **Documented as `Int!`, never null** — [Editions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx) (1 = Physical, 2 = Audio, 3 = Both, 4 = Ebook). **Observed** in **CBO-90**'s build session, which asked for it live for the first time: 41 of the 48 Editions in the re-recorded fixtures carry it, and the distribution is 32 × 1, 9 × 4. The 7 without it are the hand-made fixtures, which are never re-recorded. **It is not a reliable statement of what an Edition is**: Hardcover labels `9781799729945`, the Audible Studios on Brilliance recording of *The Infirmary*, `4` (Ebook) with `edition_format: "Kindle"`, and no Edition on the title path came back `2` (Audio) or `3` (Both). Only a stated `2` may be acted on. |
| `contribution: "Author"` as a legal value | **Documented** — [Contributions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Contributions.mdx) |
| `code2: "en"` / `code3: "eng"` format | **Documented as ISO 639-1 / 639-2** — [Languages schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Languages.mdx) |
| `id`, `slug`, `pages`, `release_date`, `publisher`, `subtitle`, `isbn_10`, `isbns_match`, `reading_format_id`, series name/position, `details`, `featured`, `compilation` | **Illustrative** — plausible values, not a captured record |
| Whole-book `id: 328491` and edition `id: 21953653` | **Illustrative here**; those two IDs appear elsewhere in the docs as an Oathbringer example ([Books](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Books.mdx), [Getting Book Details](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/GettingBookDetails.mdx)), not as Mistborn |

Note the top-level shape: results are under `data.editions` — an **array**, because the root field
is a table collection. There is no `editions_by_pk` path for ISBN because ISBN is not a primary key
(editions are keyed by `id`); `editions_by_pk` exists but takes `id`.
— [Editions schema](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx)

---

## No match

> **Status: RECONSTRUCTED from GraphQL/Hasura conventions, not captured.** An unmatched table
> filter is a successful query returning an empty collection; the docs document no special
> not-found body for list queries, and `404` is listed only as a generic code.
> — [Getting Started](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx)

HTTP status **200**, body:

```json
{
  "data": {
    "editions": []
  }
}
```

Client rule: `200` + `data.editions == []` means **ISBN not present in Hardcover**. Only a non-2xx
status, a top-level `errors` array, or a missing `data` key should be treated as a failure — and
note that per §5 the failure body is typically a bare `{"error": ...}`, not a GraphQL `errors`
envelope.

For contrast, the two "record exists but the optional relationship is empty" cases (also
reconstructed):

```json
{
  "data": {
    "editions": [
      {
        "id": 12345,
        "title": "Some Standalone Novel",
        "language": null,
        "book": {
          "title": "Some Standalone Novel",
          "contributions": [
            { "contribution": "Author", "author": { "id": 999, "name": "A. N. Author" } }
          ],
          "book_series": []
        }
      }
    ]
  }
}
```

`book_series: []` (non-nullable array, so empty rather than null) and `language: null` (nullable
object) are the two shapes to branch on. Nullability is fixed by the schema in
[schema-fields.json](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema-fields.json).

---

## Unknowns

Things **not** verifiable from a first-party source here. Treat as guesses.

1. **The exact HTTP method.** The docs never state `POST`, and no curl example is given. `POST` is
   inferred from the documented tool being a Hasura GraphiQL console. I verified only that a
   plain `GET` to `/v1/graphql` reaches the auth layer and returns
   `400 {"error":"invalid_request","error_description":"No Authorization header"}`.
2. **Every response body in this document.** No authenticated call was possible (no token; the
   available fetch tool cannot set headers). The "Recorded response" and "No match" bodies are
   reconstructions. Field paths and nullability are schema-backed; values and exact JSON
   serialisation are not.
3. **Author ordering.** `contributions` has **no** order/position column — its complete field list
   is `author`, `author_id`, `book`, `contributable_id`, `contributable_type`, `contribution`,
   `contributor_role`, `contributor_role_id`, `contributor_role_specialization`,
   `contributor_specialization`, `contributor_specialization_id`, `created_at`, `id`, `updated_at`
   ([schema-fields.json](https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema-fields.json)).
   Nothing documents what order `contributions` returns without an explicit `order_by`, nor that
   any column reproduces the website's author order. `books.cached_contributors` (`json`) is a
   candidate — it is the cached data the app renders — but its internal structure is undocumented.
   **This is the biggest practical unknown: if author order matters, it is currently unverifiable.**
4. **How `float8` positions serialise in JSON.** Whether a whole-number position arrives as `1` or
   `1.0` is not documented and was not captured; Python's `json` module maps `1` → `int`. Coerce
   with `float()`.
5. **ISBN normalisation rules beyond hyphen stripping.** The docs state hyphens are removed on
   input. Whether whitespace is trimmed, whether an ISBN-10 check digit `X` is upper-cased, and
   whether a leading `ISBN`/`978-` prefix is stripped are all unstated — so `_eq` may miss a value
   stored in a different form. There is also no documented way to search "either column at once"
   other than the `_or` above.
6. **Token lifetime defaults/maximum, and rotation semantics.** Expiration is user-chosen;
   defaults and maximums are not documented. The docs only warn tokens "may be reset without
   notice while in beta".
7. **The precise 401 vs 400 split.** Docs say 401 for "missing, invalid, or expired" tokens; the
   live endpoint returned 400 for a *missing* header. The exact body for an *expired* (as opposed
   to malformed) token is therefore unconfirmed.
8. **Whether `RateLimit` / `RateLimit-Policy` headers are actually emitted** on every response, and
   their exact spelling/casing. Documented, but not observed.
9. **Daily-limit reset timezone.** `X-RateLimit-Daily-Reset` is documented as "midnight UTC"; the
   modern `RateLimit` header's `t` is only "seconds until that bucket resets".
10. **`search` as an ISBN fallback.** The docs say ISBNs are an indexed field of book search with
    `typos: 0` for `isbns`, which hints at exact matching — but the response is untyped
    `results: jsonb`, and its structure is not documented. Not recommended; not verified.
11. **Whether any scope is needed for a legacy `all` token**, and the exact scope set a metadata-only
    client should request. `read:catalog` is the documented requirement, but the
    per-sub-scope distinction (`read:catalog:data` vs `read:catalog:search`) is not explained for
    a plain `editions` query.
12. **`contributor_role` vs `contribution`.** Both exist; the docs describe `contribution` as the
    legacy-ish string role and `contributor_role` as an object relationship, but do not state
    precedence or whether `contribution` will be deprecated. Filtering on the string is what the
    docs' own examples do.

---

## Source index

First-party only.

| Source | URL |
| --- | --- |
| API docs home (links the official GitHub repo in its footer) | https://docs.hardcover.app/ |
| Getting Started (endpoint, auth, token, codes, rate limits, limits) | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx |
| Books schema | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Books.mdx |
| Editions schema (ISBN + language) | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Editions.mdx |
| Series schema | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Series.mdx |
| Book Series schema (`position`) | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/BookSeries.mdx |
| Contributions schema | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Contributions.mdx |
| Authors schema | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Authors.mdx |
| Languages schema | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Schemas/Languages.mdx |
| Actions & Scopes | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/GraphQL/Actions.mdx |
| Searching guide | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/Searching.mdx |
| Getting Book Details guide | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/GettingBookDetails.mdx |
| Getting All Books in a Series guide | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/guides/GettingBooksInSeries.mdx |
| ISBN and ASIN (hyphen stripping) | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/librarians/Resources/ISBNAndASIN.mdx |
| `schema-fields.json` (per-type field lists, generated) | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema-fields.json |
| `schema.graphql` (full schema, 585 KB) | https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/schema.graphql |
| Official docs repo | https://github.com/hardcoverapp/hardcover-docs |
| Live endpoint (probed unauthenticated) | https://api.hardcover.app/v1/graphql |
