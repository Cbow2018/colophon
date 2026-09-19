# Colophon

Colophon is a relay for ebooks. Books land in an **ingest** folder, Colophon
passes them to an **output** folder, and your library app (Calibre-Web
Automated, Grimmory, anything with a watched folder) imports from there.

Later versions correct the book's metadata on the way through, which is the
point of the project: CWA's Hardcover matcher searches on the raw file title,
so a book like *Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)*
never finds its match. Colophon cleans the question before it is asked.

**What works today:** files pass through, and an EPUB or KEPUB carrying a known
ISBN gets its core metadata corrected from Hardcover on the way. No ISBN, no
match, or a book that already matches: nothing is touched.

## What it does today

- Watches the ingest folder, including subfolders
- Waits until a file has stopped changing, so a book that is still copying is
  never moved half-written
- Reads the title, author, language and ISBN out of an EPUB or KEPUB (EPUB 2 and
  EPUB 3 layouts both), and looks the ISBN up exactly on Hardcover
- Writes back the title, the author(s), the series and the series number the
  source is sure of - the series in Calibre's format *and* the EPUB 3 one, so any
  library app reads it
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

Everything else - cleaning messy titles, Google Books, the LLM fallback, field
rules, covers, failure handling - is still to come. Books without an ISBN and
formats other than EPUB/KEPUB pass through untouched.

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

4. Start in dry run and watch the log. Each book gets one line, and a book with
   an ISBN gets a note like:

   ```
   dry run: would move "Cragside.epub" -> /output/Cragside.epub (2.1 MB) [hardcover matched ISBN 9781786813891 by exact ISBN, confidence 1.00; would change title="Cragside"<-hardcover, authors="LJ Ross"<-hardcover, series="DCI Ryan"<-hardcover, series_number="6"<-hardcover]
   ```

If the token file is missing, Colophon says so at startup and passes every book
through with its metadata as it is.

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
| `hardcover_token_file` | `COLOPHON_HARDCOVER_TOKEN_FILE` | `/run/secrets/hardcover_token` |
| `dry_run` | `COLOPHON_DRY_RUN` | `true` |
| `poll_seconds` | `COLOPHON_POLL_SECONDS` | `5` |
| `stable_checks` | `COLOPHON_STABLE_CHECKS` | `2` |
| `skip_suffixes` | `COLOPHON_SKIP_SUFFIXES` | `.part,.tmp,.!qb,.crdownload` |
| `log_level` | `COLOPHON_LOG_LEVEL` | `INFO` |

The token itself never goes in any of these: `hardcover_token_file` is a *path*
to the secret, not the secret.

Secrets are never read from the environment: the Hardcover token is read from
the file `hardcover_token_file` points at, and it is never logged.

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
