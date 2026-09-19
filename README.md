# Colophon

Colophon is a relay for ebooks. Books land in an **ingest** folder, Colophon
passes them to an **output** folder, and your library app (Calibre-Web
Automated, Grimmory, anything with a watched folder) imports from there.

Later versions correct the book's metadata on the way through, which is the
point of the project: CWA's Hardcover matcher searches on the raw file title,
so a book like *Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)*
never finds its match. Colophon cleans the question before it is asked.

**What works today:** files pass through, and an EPUB or KEPUB gets its metadata
corrected from Hardcover or Google Books on the way - by its ISBN where the file
carries one, and otherwise by its cleaned title and author. What gets written is
up to you: each field follows its own rule (`overwrite`, `fill` or `skip`), and
a book with no cover of its own is given one from the source that matched it. A
book that already matches, or one nothing confident was found for, is passed
through untouched.

## What it does today

- Watches the ingest folder, including subfolders
- Waits until a file has stopped changing, so a book that is still copying is
  never moved half-written
- Reads the title, author, language, ISBN, description, publisher and date out of
  an EPUB or KEPUB (EPUB 2 and EPUB 3 layouts both), and looks the ISBN up
  exactly on Hardcover
- The book that carries no ISBN is looked up by its title instead, with the
  subtitle and the series bracket taken off first, and searched for in the
  language the file says it is written in
- Applies one rule per field - `overwrite`, `fill` or `skip` - configured in
  `config.toml`, to the title, author(s), series, series number, description,
  publisher, date, ISBN and language. The series is written in Calibre's format
  *and* the EPUB 3 one, so any library app reads it
- Takes the description from the matched source's own record. It is the book's
  blurb, never a generated one
- Adds a cover to a book that has none, from the source that matched it. A book
  that arrived with one keeps the cover it came with
- Backs the original up before it changes a byte, and clears out backups older
  than `backup_retention_days` (30 by default) on the next scan
- Writes into the output folder under a hidden temporary name and renames it
  only once the copy is complete, so your library app cannot import a partial
  file
- Never overwrites: an identical book already in output means the new copy goes
  to the backups folder; a *different* book of the same name is saved as
  `Name (2).epub`
- Leaves part-finished downloads alone (`.part`, `.tmp`, `.!qB`, `.crdownload`,
  and anything beginning with a dot)
- Logs one line per book to `docker logs`, saying what matched, at what
  confidence, what changed and where each value came from
- Runs as a non-root user, with a read-only root filesystem and no open ports

Everything else - the LLM fallback, failure handling and retries, and formats
other than EPUB/KEPUB - is still to come.

## Getting started

1. Copy `docker-compose.example.yml` to `docker-compose.yml` and point the
   three volume paths at your own folders.
2. Set `user:` to the same `PUID:PGID` your library app runs as. Files come out
   owned by that user, which is how your library app can read them.
3. Copy `config.example.toml` to `config/config.toml`.
4. Start it: `docker compose up -d`
5. Watch it: `docker compose logs -f`

It starts in **dry-run** mode, so it will tell you what it would do and move
nothing. When the log looks right, remove `COLOPHON_DRY_RUN=true` from the
compose file (or set `dry_run = false` in `config.toml`) and restart.

## Metadata from Hardcover

Colophon needs a Hardcover API token to look books up. It is a secret, so it
never goes in the config, the environment or the image - it is read from a file,
and the compose file mounts that file as a Docker secret.

1. Get a token from Hardcover: account settings, then **Hardcover API**, then
   **New API Key**. It needs an expiry date; when it expires, lookups stop and
   books pass through unchanged.
2. Put it in a file, one line, nothing else:

   ```
   mkdir -p secrets
   printf '%s' 'your-token-here' > secrets/hardcover_token
   chmod 600 secrets/hardcover_token
   ```

3. Mount it, as `docker-compose.example.yml` does:

   ```yaml
   services:
     colophon:
       secrets:
         - hardcover_token

   secrets:
     hardcover_token:
       file: ./secrets/hardcover_token
   ```

4. Start in dry run and watch the log. Each book gets one line, and a book gets
   a note like one of these:

   ```
   dry run: would move "Cragside.epub" -> /output/Cragside.epub (2.1 MB) [hardcover matched ISBN 9781521748831 by exact ISBN, confidence 1.00; would change title="Cragside"<-hardcover, authors="L.J. Ross"<-hardcover, description<-hardcover, publisher="Independently Published"<-hardcover, date="2017-07-07"<-hardcover, series="DCI Ryan Mysteries"<-hardcover, series_number="6"<-hardcover, cover<-hardcover]
   dry run: would move "Berwick.epub" -> /output/Berwick.epub (1.5 MB) [hardcover matched Berwick by title and author, confidence 1.00; would change title="Berwick"<-hardcover, authors="L.J. Ross"<-hardcover, series="DCI Ryan Mysteries"<-hardcover, series_number="24"<-hardcover]
   ```

   The first is a book matched on its ISBN, the second one with no ISBN in the
   file, matched on its cleaned title and its author. The description and the
   cover are named without their values: a blurb is a thousand characters and a
   cover is an image, and neither belongs in a log line. What each value *is* can
   be read in the book.

If the token file is missing, Colophon says so at startup and passes every book
through with its metadata as it is.

## Sources and their priority

Books are looked up in the sources named by `sources` in `config.toml`, in that
order. The default is Hardcover first, then Google Books:

```toml
sources = ["hardcover", "google_books"]
```

The first source that has the book is the one its values come from, and that is
true of both the ISBN lookup and the title lookup. Reorder the list to change
which source you trust most. Leave a name out to disable it - a list with one
name is fine, and an empty one is an error rather than a silent pass-through.

Two behaviours worth knowing before you set the order:

- **Google Books needs a key.** Google gives a keyless caller no lookups at all,
  so `google_books` in the list without a key in `google_books_key_file` means
  that source is skipped: Colophon logs it once at startup and uses the rest of
  the list.
- **Google Books has no series data.** A book matched from Google Books has its
  title and authors corrected and **no series written**, because Google has no
  series to write. That is the whole of what it contributes.

If a source that is listed cannot be reached, Colophon stops there for that
book: it passes through untouched rather than being corrected from a source you
ranked below the one that is down. A book is never quietly taken from a
lower-priority source because a higher-priority one was busy.

Each written value is attributed in the log line, so you can always see which
source a value came from:

```
[google_books matched ISBN 9781521748831 by exact ISBN, confidence 1.00; changed title="Cragside"<-google_books, authors="L. J. Ross"<-google_books]
```

## What gets written, and what does not

Every field follows one of three rules, set per field in `config.toml`:

| Rule | What it means |
| --- | --- |
| `overwrite` | write the source's value, whatever the file already says |
| `fill` | write it only when the file has nothing for that field |
| `skip` | never write it; the file keeps what it came with |

The defaults are the ones the design settled on:

```toml
[fields]
title = "overwrite"
authors = "overwrite"
series = "overwrite"
series_number = "overwrite"
description = "fill"
publisher = "fill"
date = "fill"
isbn = "fill"
language = "fill"
```

Three things worth knowing:

- **Every value comes from the matched source's own record.** The description is
  the book's blurb as the source has it; Colophon writes no generated text. A
  field the source does not have is never written at all, whatever its rule:
  `fill` on a field a source is silent about is not a blank.
- **`fill` is judged against your file,** so `description = "fill"` keeps the
  blurb your book came with and only supplies one when there is none.
- **A skipped series number is dropped when the series around it changes.** A
  number is a position in a named series, so if the series is overwritten and the
  number is left alone, the old number would be a claim about the wrong series;
  it is taken off instead, and the log says so.

Covers are a setting rather than a rule, because there are only two sensible
outcomes:

```toml
add_cover = true
```

A cover is added **only if the book has none**. A book that arrived with one
keeps it. The cover comes from the source that matched the book - never from a
source you ranked below it, for the same reason no other value does - so a book
matched from a source with no cover for it is left without one.

## Settings

All settings live in `config.toml`; see `config.example.toml` for the full list
with comments. Any of them can be overridden with an environment variable of
the same name in capitals, prefixed with `COLOPHON_`:

| Setting | Environment variable | Default |
| --- | --- | --- |
| `ingest_dir` | `COLOPHON_INGEST_DIR` | `/ingest` |
| `output_dir` | `COLOPHON_OUTPUT_DIR` | `/output` |
| `backup_dir` | `COLOPHON_BACKUP_DIR` | `/backups` |
| `backup_retention_days` | `COLOPHON_BACKUP_RETENTION_DAYS` | `30` |
| `sources` | `COLOPHON_SOURCES` | `hardcover,google_books` |
| `hardcover_token_file` | `COLOPHON_HARDCOVER_TOKEN_FILE` | `/run/secrets/hardcover_token` |
| `google_books_key_file` | `COLOPHON_GOOGLE_BOOKS_KEY_FILE` | `/run/secrets/google_books_key` |
| `add_cover` | `COLOPHON_ADD_COVER` | `true` |
| `dry_run` | `COLOPHON_DRY_RUN` | `true` |
| `poll_seconds` | `COLOPHON_POLL_SECONDS` | `5` |
| `stable_checks` | `COLOPHON_STABLE_CHECKS` | `2` |
| `skip_suffixes` | `COLOPHON_SKIP_SUFFIXES` | `.part,.tmp,.!qb,.crdownload` |
| `log_level` | `COLOPHON_LOG_LEVEL` | `INFO` |

The `[fields]` table has no environment variable: it is nine keys, and nine
environment variables would be a worse way to set them.

The keys themselves never go in any of these: `hardcover_token_file` and
`google_books_key_file` are *paths* to the secrets, not the secrets.

Secrets are never read from the environment: each is read from the file its
setting points at, and never logged. A log line names the source a value came
from, never the key it was fetched with.

## Running the tests

No dependencies to install:

```
python -m unittest discover -s tests -t .
```

They run on every push in GitHub Actions, on Python 3.11 and 3.12.

## How this was built

Colophon is AI-assisted and human-reviewed at every step. The design was worked
out in conversation, each ticket is built test-first, and every change is read
and approved by a person before it is merged.

## Licence

AGPL-3.0. If you run a modified Colophon as a service, you must publish your
changes. See [LICENSE](LICENSE).
