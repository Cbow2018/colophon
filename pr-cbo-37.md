Metadata sources are now tried in the order `config.toml` sets, and Google Books joins Hardcover as the second source. Ticket: **CBO-37**, a private planning note that cannot be opened from here — this description carries everything a reviewer needs.

**Branch naming.** This branch is `dsh/cbo-37-google-books-priority`. The ticket suggested `callumbowden111/cbo-37-04-google-books-and-the-source-priority-list`; the standing rule in `~/.dsh/AGENTS.md` is `dsh/<short-topic>`, so the shorter one won.

## Acceptance criteria

- [x] **One priority list covers all fields (default: Hardcover, then Google Books); the user can reorder or disable sources** — `sources = ["hardcover", "google_books"]` in `config.toml`, one list for both lookup paths. Reordering is editing the list; disabling is leaving a name out. An unknown name, a duplicate name, or an empty list is a `ConfigError`.
- [x] **If the first source has no match, the next source is tried** — on both the ISBN path and the title path. See the note below on what "no match" excludes.
- [x] **Google Books key (if used) read from a Docker secret file** — `google_books_key_file`, mounted as a Docker secret, wired into `docker-compose.example.yml` alongside `hardcover_token`.
- [x] **The log shows which source supplied each value** — the existing `field="value"<-source` now carries `<-google_books` where Google supplied it, and the match line names the source that made it.
- [x] **Tests use recorded Google Books responses** — 16 recorded bodies under `tests/fixtures/googlebooks/`, replayed through a transport seam so the suite needs no key and never touches the network.

## What changed, per acceptance criterion

**One list (AC 1).** `Config.sources` is a validated tuple, default `("hardcover", "google_books")`. `Corrector.from_config` builds one source object per name, in order, and skips any whose key file is missing or unreadable with a single startup log line. `Corrector.sources` is what both lookup paths iterate. `colophon/googlebooks.py` is the new client; `colophon/sources.py` holds the one `SourceError` both clients raise.

**Falling through (AC 2).** `_by_isbn` and `_by_title` walk `self.sources` and return on the first confident match. The walk advances when a source has no such ISBN, offers nothing, or offers nothing scoring at least 0.85. It **stops** on a source error — see below.

**The key (AC 3).** `GoogleBooks.from_secret_file` mirrors `Hardcover.from_secret_file`: a missing or empty file means `None`, which the corrector skips. The key is sent as the `key` **query parameter**, because Google Books has no bearer header — so the whole URL is a secret, and no URL reaches a log or an error message.

**The log line (AC 4).** Unchanged in shape. One line per book, each written value attributed. The one case that now says more is a book nothing matched, which names every source that was asked (see the decision list).

**The tests (AC 5).** Recorded replies driven through a `Replay` transport, exactly as `test_hardcover.py` already does. `tests/fixtures/googlebooks/README.md` records which query produced each body and what it proves. The suite goes from 239 tests on `main` to 311 here.

## The probe findings that changed the ticket's shape

Written up in full in `docs/research/cbo-37-google-books.md`. Two of them changed the design rather than just confirming it.

### The key is not optional

The ticket says "Google Books key **(if used)**". It is always used: Google answers a keyless caller with `HTTP 429` and `"quota_limit_value": "0"`. A keyless Colophon would 429 on every book, forever, and never once succeed. Per your ruling, Google Books now requires a key whenever it is in the list, and a keyless call is never made at all.

### `isbn:` is a relevance search, not a lookup

```
GET ?q=isbn:9781521748830      (the right ISBN, check digit wrong)
200 OK   "Cragside"   ids=[ISBN_10:1521748837, ISBN_13:9781521748831]

GET ?q=isbn:9780000000000      (no book's ISBN at all)
200 OK   three volumes, none of which carries 9780000000000
```

Google matched the digits, not the identifier. So `by_isbn` reads `industryIdentifiers` off every volume it is offered and keeps only the ones that genuinely carry the ISBN asked about. Without that, CBO-35's "an exact ISBN match is as certain as metadata matching gets" would have been quietly false for this source: Colophon would have written another edition's ISBN into the file and reported confidence 1.00 while doing it. `by-isbn-one-digit-off.json` is the recording that pins it.

**Google Books also has no series data.** `seriesInfo` is a comics-and-collected-editions structure, present in one volume out of roughly a hundred examined, and absent for *Mistborn*, *The Fellowship of the Ring* and all three DCI Ryan books. Where "series" appears it is prose inside `description`. So a book matched from Google Books gets its **title and authors** corrected and **no series written** — which needs no special case, because `_edits(found)` already writes only the fields the source actually has. This makes the two sources unequal in what they can contribute while leaving AC 1 satisfied by the *list*, not by Google's coverage.

Two smaller ones: `langRestrict` is **accepted and ignored** (`langRestrict=fr` returned the same English volumes), and `maxResults` is capped at 40 — above that is a 400.

## Decisions I made myself

Beyond the seven you settled in the grilling round, these were mine to make. Each is reversible and I have flagged the two that are judgement calls.

1. **`SourceError` lives in a new `colophon/sources.py`.** Both clients had their own. Two classes with one name in two modules are not one `except` clause: an unreadable Google key file would have escaped `_build`'s handler and taken down startup. `hardcover.py` re-exports it, so existing imports still work.

2. **"400 or 403 means a rejected key" narrowed to "400 or 403 whose message names the key".** The probe showed all three of Google's 400s are 400: a wrong key (`reason: badRequest`), a missing `q` (`reason: required`), and an over-range `maxResults` (`reason: invalidParameter`). Taking the status alone would treat our own malformed query as a key the user has to go and fix — holding every book and marking the container unhealthy for a bug on our side. Only the message-names-the-key case sets `rejected`.

3. **`SourceError.rejected` is kept, though both reviewers called it unused.** Its only consumer today is the test pinning your 429 ruling (`a_spent_quota_is_not_a_rejected_key`), and the 429-vs-key-rejected distinction is yours, not the reviewers'. Its real consumer is CBO-43's unhealthy-container path. This is a judgement call and I have left it in deliberately.

4. **`Hardcover.by_title` accepts `author` and ignores it.** The priority list calls every source the same way. Hardcover cannot filter on an author server-side (its `_eq` needs the full name spelt Hardcover's way), so the parameter is accepted for interface parity and the comparison stays client-side in `matching.py`.

5. **`sources.py` exports `text()`**, because `_text` was about to exist byte-identically in two clients.

6. **No client-side language filter for Google Books.** `langRestrict` is still sent, as you asked, but the reply is not filtered on `volumeInfo.language` — consistent with CBO-36's settled "a language is a dial on the request, not a veto on the reply".

7. **The nothing-matched log line names every source tried.** Your Q7 ruling: `[no source among hardcover, google_books carries ISBN 9781521748831]`. The matched case still names only the winner, per Q3.

8. **`docker-compose.example.yml` and `config.example.toml` are in this diff.** AC 3 is not demonstrable without the secret being declared, so the compose file gained `google_books_key`. `AGENTS.md` and `docs/agents/` are untouched.

## Review fixes

`/code-review` ran both axes against `main` as parallel sub-agents; the Ponytail review ran separately (below).

**Spec axis — two real gaps, both fixed.**

- **A missing WARNING.** You asked that a source error "pass the book through untouched and log a WARNING naming the source". The stop was right but the level was not: a source error became `Outcome.problem` and was emitted on the relay's per-book `LOG.info`, and no `LOG.warning` existed anywhere in the correction path. Now `_failed` logs at WARNING naming the source, the book, and the reason, and still returns the outcome so the per-book line is unchanged. Three tests pin it, including one asserting a matched book warns about nothing.
- **The nothing-matched line did not name the sources tried** (your Q7). `Outcome` gained `tried`, filled by both walk paths, and the fragment now reads `no source among hardcover, google_books …`.

**Standards axis.** All five actionable findings fixed: the test-only `source=` parameter, `.source` property and setter are gone (tests now pass `sources=`); the unreachable `getattr(source, "SOURCE", ...)` fallback is gone; `_digits` renamed to `_as_isbn`; `_text` and the `_isbn`/`_identifiers` duplication folded into one place; and the new over-88-character lines wrapped.

**The one both axes found independently, and it was a crash.** `Hardcover.by_title` had no `author` parameter while the corrector now passes one to every source in the list — an uncaught `TypeError` on every book without an ISBN, which `except SourceError` would not catch and neither `relay` nor `main` handles. With the default list the first ISBN-less book would have crash-looped the container.

It survived 300-odd tests because **every corrector test used `FakeSource`**, which I had updated to accept `author`. A stand-in can only ever agree with the corrector about an interface someone already wrote down. Fixed, and `ARealSourceThroughTheCorrectorTests` added: the real `Hardcover` and `GoogleBooks` classes driven through the real corrector on recorded replies. I verified those new tests fail without the fix rather than assuming they would.

## Deferred, deliberately

- **The retry window, and `colophon:source-unavailable`** — CBO-43. A failed source currently stops the walk, logs a WARNING, and leaves the book untouched.
- **A rejected key holding all books and marking the container unhealthy** — CBO-43. `SourceError.rejected` carries the flag for it.
- **`colophon:unverified`** — a later ticket. An unmatched book keeps today's behaviour.
- **Per-field source overrides** — the design spec says "possibly later". One list covers all fields, as AC 1 asks.
- **Publisher, date, description and cover writing** — `Edits` is still title, authors, series and series number, so Google's `publisher` and `publishedDate` are recorded in the fixtures but not written. CBO-38's field rules.
- **`ruff format` drift.** 16 files fail `ruff format --check`, including files untouched here. CI runs only `ruff check`, and reformatting untouched files would bury this review, so it is left alone.

## Ponytail review

Run on the full branch diff (`git diff main...HEAD`) with the `ponytail-review` skill, **not applied** as the findings came back — the seven findings, and what I did with each. Five were acted on; two I have deliberately left, with reasons.

```
tests/fixtures/googlebooks/by-title-poe.json:L1-728: delete: 728-line recorded reply nothing reads. Nothing replaces it.
tests/fixtures/googlebooks/by-title-cragside-subtitle.json:L1-75: delete: 75-line recorded reply with no test. Nothing replaces it.
tests/test_googlebooks.py:L47-54: delete: ReplayWithStatus, an 8-line helper never instantiated. Replay(name, status=429) already covers it.
tests/test_googlebooks.py:L141-147: delete: test_the_title_filter_is_what_keeps_the_noise_out. L132 and L98 already assert `intitle` in the query.
tests/fixtures/googlebooks/by-isbn-unrelated.json:L1-208: shrink: 208-line reply of three other-ISBN volumes. One such volume exercises the same branch.
colophon/hardcover.py:L334 + colophon/googlebooks.py:L217-219: yagni: sources.text imported as _text by both source modules, and hardcover still carries its own _text plus a SourceError re-export. Both sources import the shared helpers; the re-export goes.
colophon/correction.py:L31-49: shrink: SECRET_FILES and LABELS are two maps over the same two keys, and _blamed is the third. One entry per source carrying its label; _blamed becomes the lookup.

net: -815 lines possible.
```

**Acted on.**

- **`by-title-poe.json` reads nothing** — true, and my mistake: I recorded it for the Gutenberg end-to-end case and then wrote that test against a hand-made candidate instead. Rather than delete the recording, the test now uses it: `test_a_real_book_is_corrected_from_a_recorded_google_books_reply` drives a real EPUB through the real `GoogleBooks` client against this recording, and asserts the title and authors Google actually returned land in the file. Its replay matches the fixture by the `q` the client really sent, so changing the query fails the test instead of quietly reading the wrong file.
- **`by-title-cragside-subtitle.json` reads nothing** — deleted. A recorded reply with no reader is clutter, and the "both forms go in one request" behaviour is covered by `test_it_asks_about_every_form_of_the_title`.
- **`ReplayWithStatus` never instantiated** — deleted.
- **`test_the_title_filter_is_what_keeps_the_noise_out` duplicated** — deleted; the surviving test carries its comment.
- **The `SourceError` re-export** — removed from both clients, and the three test modules now import it from `colophon.sources`. Ponytail is right that a source module mirroring the failure type invites exactly the two-divergent-classes bug this branch fixed, so leaving a re-export in place would have kept the trap armed. `__all__` on both clients is now `["SOURCE", "<Client>"]`.
- **`SECRET_FILES` and `LABELS` were two maps over one key set** — collapsed into one entry per source carrying its own label, with `_blamed` a single lookup.

**Left alone, deliberately.**

- **`by-isbn-unrelated.json` (three volumes where one would do)** — kept whole. The repo's fixture convention, stated in `fixtures/hardcover/README.md` and repeated in the Google Books one, is that a body is "the API's own, re-indented; nothing inside them is changed", and three-quarters of the fixtures here are largely unread by the client for the same reason. Trimming this one file would break the stated convention for a 200-line saving, and the reply's *shape* — three unrelated books for a nonsense ISBN — is the evidence for the design decision, so a one-volume version would no longer be the recording. The README now says why.
- **`hardcover.by_title(author=...)`** — Ponytail explicitly did not flag this, and it is the sources interface, so it stays.

