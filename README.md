# Colophon

Colophon is a relay for ebooks. Books land in an **ingest** folder, Colophon
passes them to an **output** folder, and your library app (Calibre-Web
Automated, Grimmory, anything with a watched folder) imports from there.

Later versions correct the book's metadata on the way through, which is the
point of the project: CWA's Hardcover matcher searches on the raw file title,
so a book like *Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)*
never finds its match. Colophon cleans the question before it is asked.

**This version is the skeleton.** Files pass through untouched. No metadata is
read or changed yet.

## What it does today

- Watches the ingest folder, including subfolders
- Waits until a file has stopped changing, so a book that is still copying is
  never moved half-written
- Writes into the output folder under a hidden temporary name and renames it
  only once the copy is complete, so your library app cannot import a partial
  file
- Never overwrites: an identical book already in output means the new copy goes
  to the backups folder; a *different* book of the same name is saved as
  `Name (2).epub`
- Leaves part-finished downloads alone (`.part`, `.tmp`, `.!qB`, `.crdownload`,
  and anything beginning with a dot)
- Logs one line per book to `docker logs`
- Runs as a non-root user, with a read-only root filesystem and no open ports

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

## Settings

All settings live in `config.toml`; see `config.example.toml` for the full list
with comments. Any of them can be overridden with an environment variable of
the same name in capitals, prefixed with `COLOPHON_`:

| Setting | Environment variable | Default |
| --- | --- | --- |
| `ingest_dir` | `COLOPHON_INGEST_DIR` | `/ingest` |
| `output_dir` | `COLOPHON_OUTPUT_DIR` | `/output` |
| `backup_dir` | `COLOPHON_BACKUP_DIR` | `/backups` |
| `dry_run` | `COLOPHON_DRY_RUN` | `true` |
| `poll_seconds` | `COLOPHON_POLL_SECONDS` | `5` |
| `stable_checks` | `COLOPHON_STABLE_CHECKS` | `2` |
| `skip_suffixes` | `COLOPHON_SKIP_SUFFIXES` | `.part,.tmp,.!qb,.crdownload` |
| `log_level` | `COLOPHON_LOG_LEVEL` | `INFO` |

Secrets are never read from the environment. When Colophon starts calling
metadata sources, their API keys will be read from Docker secrets.

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
