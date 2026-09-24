# CBO-44 — the notice EPUB: research

Session 1 of 3, research only. Branched as `dsh/cbo-44-notice-epub` from
`origin/main` at **`593f14a`** (`593f14a0e620b9bba782c283be15caa09685f0e2`,
"Merge pull request #17 … cbo-73-title-query-isbn"), fetched 2026-09-23.
Nothing tracked was changed except this file. Scratch probes were run outside
the repo and are not committed. No Hardcover, Google Books or LLM API was
called.

**Decisions were grilled on 2026-09-23, after this note was drafted.** §7
records them. Where §1 to §6 recommend something different, §7 wins; the
places that changed carry a pointer to it.

**CBO-43 is not built.** None of CBO-78 to CBO-83 is on `main`. Every claim
below about failure handling is a claim about the **agreed design**, and it
cites the ticket and the date it was decided:

| Where | What it settled | Decided |
| --- | --- | --- |
| CBO-33 (design spec), "Notice EPUB" and "Alerts (webhook)" | The notice is off by default, fires only on a rejected or expired key, and is written once per incident | spec, 2026-09-18/19 |
| CBO-43, "Decisions (grilled 2026-09-20)" | Retry and incident state are **per source**, and that state is also what the webhook's "once per incident" uses: "one mechanism rather than two" | 2026-09-20 |
| CBO-43, "Second grilling (2026-09-23)" | The ticket is split into CBO-78 to CBO-83. `webhook_url` becomes `webhook_url_file`, the LLM gets `llm_retry`, an LLM 402 is temporary, and anything that is neither temporary nor a key is "held like a rejected key" | 2026-09-23 |
| `cbo-43-failure-handling.md — research` (Linear document on CBO-43) | The evidence base for the above: status codes per provider, measured webhook shapes, measured healthcheck | written 2026-09-23 against `593f14a` |
| CBO-78 to CBO-83 | The six build tickets (10.1 to 10.6) | all 2026-09-23 |

"Research note" below means that Linear document. `§n` refers to its sections.

---

## 0. What I probed, and what it showed

| Probe | Question | Result |
| --- | --- | --- |
| Built two notice EPUBs with `zipfile` and string templates, and ran **EPUBCheck 5.3.0** on them | Can the standard library make a valid EPUB 3, and how small can it be? | **Both valid: 0 fatals, 0 errors, 0 warnings.** The four-entry version (nav document doubling as the only page) is 1,354 bytes. The five-entry version (nav plus a separate page) is 1,664 bytes. |
| Built the same book twice | Are the bytes deterministic? | **Yes**, when the zip entries are stamped with a fixed date (as `epub.py`'s `_EPOCH` already does) and `dcterms:modified` is fixed. |
| Moved `mimetype` to the end | Does EPUBCheck catch it? | Yes: `ERROR(PKG-006) Mimetype file entry is missing or is not the first file in the archive.` |
| Deflated `mimetype` (still first) | Does EPUBCheck catch it? | **No. 0 errors.** So a test has to assert `ZIP_STORED` directly, as `tests/test_epub.py:278` already does for rewritten books. |
| Read the probe with Colophon's own `epub.read` | Does Colophon's reader cope with it? | Title `⚠ Colophon: Hardcover key rejected`, authors `('Colophon',)`, language `en`, `subjects == ()` (Colophon's `colophon:` marks are excluded by design, `epub.py:199–212`), `unverified == False`. |
| Read CWA's source (`crocodilestick/Calibre-Web-Automated` `main` at `43718d8`, 2026-08-06; latest tag `v4.0.6`), the NextGen fork (`new-usemame/Calibre-Web-NextGen` `main` at `7f0a567`, 2026-09-23; latest tag `v4.1.43`), and calibre's own source (`kovidgoyal/calibre` `master` at `0583cba`, 2026-09-23) | What happens to the notice after Colophon drops it? | See §4. The ingest defaults, the metadata fetch and the duplicate handling are the same in both CWA and NextGen. |

---

## 1. What CBO-43 already gives the notice

**Answer: the notice is a second listener on an existing event. It is not a new
mechanism.** It can only be built after **CBO-81**, and it is simpler if it
comes after **CBO-83**.

How the agreed design divides the state:

* **CBO-78 (10.1)** classifies every source and LLM failure as **temporary** or
  **held**, "as data rather than message text", and gives it a key-free short
  reason (2026-09-23). CBO-78 owns the *classification*, not any state.
* **CBO-80 (10.3)** owns the **outage** state: "State is per source and kept in
  memory". An outage ends the first time the source answers (2026-09-23). A
  notice never fires on an outage, so this is the wrong state to attach to.
* **CBO-81 (10.4)** owns the **held** state: "A source or LLM in the held state
  **is not retried**. The documented fix is 'fix the key or setting and
  restart'" (2026-09-23). Books wait, the heartbeat says `unhealthy: <reason>`,
  and nothing is tagged. **This is the incident state the notice needs.**
* **CBO-83 (10.6)** sends the **held** webhook "when it's first noticed", once
  per held failure (2026-09-23). This is the event.

CBO-43's first grilling said that per-source state is "what 'sent once per
incident, not per book' needs for the webhook, so it is one mechanism rather
than two" (2026-09-20). The notice's rule, "once per incident, not per retry or
per book", is the same rule. **So the notice is a second listener on CBO-81's
"source X has entered the held state" transition, the same one CBO-83's held
message listens to.**

Why it is once per incident without any extra work, **within one process**:

* **Not per retry.** A held source is never retried (CBO-81), so the
  transition happens once.
* **Not per book.** Books after the first one find the source already held.
  They join the waiting books, and no new transition happens.
* **Not at startup.** The design makes no health-check requests (CBO-80: "No
  per-source health-check requests"). So a rejected key is only noticed when a
  book is actually looked up. With an empty ingest folder there is no incident
  and no notice. The docs should say so.

Build order:

* **Hard dependency: CBO-81.** Without the held state there is no transition
  to listen to. CBO-81 needs CBO-78.
* **Soft dependency: CBO-83.** If CBO-83 lands first, the "held, first noticed"
  call site already exists, and CBO-44 adds one listener beside the webhook. If
  CBO-44 lands first, it has to create that hook, and CBO-83 attaches to it
  afterwards. Either way works. The first way is less churn.

Three gaps in the agreed design that the notice depends on. §7 records what
was decided about each (D3, D7, D8).

1. **Key vs configuration is only text.** CBO-78 carries the *kind* (temporary
   or held) as data, but whether a held failure was a key or a configuration
   problem is carried only in the reason string ("rejected the key" /
   "configuration problem, HTTP 400"). The notice needs that difference (see
   §2), and reading it from text is the smell the research note's §1.2 already
   objected to. Today's `SourceError` has a `rejected` flag
   (`colophon/sources.py:43–56`), and `LlmError` has none. CBO-78 does not say
   whether `rejected` survives.
2. **An LLM key rejected during genre mapping.** `_map_genres` catches
   `LlmError` and drops the genre (`correction.py:1025`). CBO-81 says "a genre
   whose mapping can't be asked is dropped, as today", but it doesn't say
   whether an LLM 401 seen *there* puts the LLM into the held state. If it
   doesn't, neither the webhook nor the notice fires until a book reaches the
   chooser.
3. **Cover fetches raise `SourceError` too** (`sources.py:84–122`). CBO-78 says
   "every source and LLM failure" gets a kind, and everything that is not
   temporary is held. A cover CDN answering 403 would then be *held*, and so a
   notice candidate, even though no key is involved.

---

## 2. The trigger, class by class

CBO-44 says: "Triggered only by a rejected or expired API key, not by source
outages." CBO-43's second grilling (2026-09-23) put configuration 4xx
responses, TLS failures and unreadable replies into the same **held**
behaviour as a rejected key: books wait and the container goes unhealthy. It
did not make them *keys*.

The keys in scope are the three secrets Colophon reads at startup:

* the **Hardcover** token (`hardcover_token_file`)
* the **Google Books** key (`google_books_key_file`)
* the **LLM** key (`llm_key_file`). Ollama sends none, and a custom endpoint may.

The webhook URL (`webhook_url_file`) is a credential but not an API key. Its
failures are logged and not retried (CBO-83), so they are never a trigger.

| CBO-78 class | Example | Hardcover | Google Books | LLM | Notice? |
| --- | --- | --- | --- | --- | --- |
| **Temporary**: timeout, connection refused or reset, DNS failure | network down | ✓ | ✓ | ✓ (a rebooting local model too) | **No.** An outage |
| **Temporary**: HTTP 408, 429, any 5xx | Hardcover 503; Google's daily quota (429) | ✓ | ✓ | ✓ | **No** |
| **Temporary**: LLM **402** (out of balance) | DeepSeek "Insufficient Balance" | n/a | n/a | ✓ | **No.** Decided temporary on 2026-09-23 so that topping up recovers without a restart. Covered by the source-failure webhook after `llm_retry` |
| **Held, key**: 401 | "Missing, invalid, or expired token" (Hardcover docs); DeepSeek 401 | ✓ | Google sends 400 for a bad key, not 401 | ✓ | **Yes.** This is the ticket's case, and the most likely real trigger: Hardcover "may reset tokens without notice while in beta" (research note §2) |
| **Held, key**: Google 400/403 whose message contains `_KEY_WORDS` | "API key not valid", "API key expired" | n/a | ✓ | n/a | **Yes** |
| **Held**: Hardcover **403** | `insufficient_scope`, `unsupported_operation`, `top_level_limit_exceeded` | ✓ | n/a | n/a | **⚑ A1.** Today's code calls every 401/403 "rejected the token" (`hardcover.py:244`), but only `insufficient_scope` is about the token |
| **Held**: LLM **403** | a provider refusing the account or region | n/a | n/a | ✓ | **⚑ A1.** Today's code says "the LLM rejected the key (HTTP 403)" (`llm.py:382–383`) |
| **Held**: Google **403 `accessNotConfigured`** | "Books API has not been used in project … or it is disabled" | n/a | ✓ | n/a | **⚑ A2.** Held since CBO-78 ("both are held now"). The key is valid, but the project behind it cannot use the API. The fix is in the same Google console as a key fix |
| **Held, configuration**: other 4xx | Hardcover 400 (Colophon's own query), 404; Google 400 without key words; LLM 400 unknown model, 404 wrong base URL | ✓ | ✓ | ✓ | **⚑ A3.** The ticket says no, because it is not a key. But since 2026-09-23 the user sees exactly what a key rejection looks like (held, unhealthy) and fixes it the same way (fix a setting and restart). The LLM model and base URL are *user* settings. A Hardcover 400 is Colophon's own bug |
| **Held, configuration**: GraphQL `errors` array on a 200 | a Hardcover schema change | ✓ | n/a | n/a | **⚑ A3.** Not a key, and not the user's to fix |
| **Held**: TLS certificate failure | an intercepting proxy, a wrong clock | ✓ | ✓ | ✓ | **⚑ A4.** Not a key. It is the user's network, and fixable |
| **Held**: unreadable reply | a non-JSON 200, a reply missing `editions` | ✓ | ✓ | ✓ | **⚑ A4.** Not a key |
| *Neither*: `LlmLimited` (the daily limit is spent) | 200 calls today | n/a | n/a | ✓ | **No.** It waits until the next UTC day (CBO-80) |
| *Not a source error*: a non-network exception | a `TypeError` (a bug) | ✓ | ✓ | ✓ | **No.** CBO-78 stops catching these |
| *Not a failure*: the key file is missing | no secret mounted | ✓ | ✓ | ✓ | **No.** The source is simply not built, and this is logged once at startup (`correction.py:1338–1360`) |
| *Not a failure*: the key file is unreadable | wrong permissions | ✓ | ✓ | ✓ | **No** under the agreed design. It is logged at ERROR and the relay carries on without that source (`correction.py:1349`, `correction.py:478`). It never reaches CBO-81's held state |
| "No match" | the unverified path | ✓ | ✓ | ✓ | **No** |

**Decided (§7, D1): every held failure raises a notice**, so rows A1 to A4
all trigger one, and "Yes" now covers every **held** row above. Temporary
failures, the LLM 402 and the daily limit still never do. The cover gap from
§1 (3) is settled by D8: a cover fetch is never held, so it never reaches a
notice.

---

## 3. "Once per incident" across a restart

**Is CBO-43's state persisted? No.**

* **Outages:** "State is per source and kept in memory. A restart starts the
  window again, which costs waiting time but never tags a book wrongly"
  (CBO-80, Q7, 2026-09-23).
* **Held:** CBO-81 says nothing about persistence. Its recovery is "fix the key
  or setting and restart, because keys are only read at startup" (2026-09-23).
  That implies in memory, like CBO-80. It is **not stated explicitly** for the
  held state.

So after a restart, the first book looked up with the still-bad key produces a
new "held, first noticed" transition, and a second notice. Docker's own
restart policy does **not** cause this: an unhealthy container is not
restarted under `restart: unless-stopped` (**measured**, research note §4). A
restart *without* a fix does happen, though: a host reboot, an image update
(Watchtower and similar), a `docker compose up` after editing some other
setting, or a crash loop. Any of these, during a key incident that lasts days,
means a second notice. With CWA's default `new_record` automerge (§4.3), that
second notice becomes a second book.

The three options you named, against what CWA actually does:

| Option | Does it stop the duplicate? | Why |
| --- | --- | --- |
| **Check the output folder** | **No, not with CWA** | CWA deletes each file from its ingest folder (which is Colophon's output) once it has processed it (`scripts/ingest_processor.py:799–822`, `os.remove(self.filepath)` at 807). The notice is gone seconds after it lands, long before any restart. It would only work for a library that leaves files in place, which Colophon can't assume ("doesn't depend on any specific library app", CBO-33). |
| **Deterministic filename (and bytes)** | **No** | Colophon never overwrites in output: a taken name becomes `Name (2).ext` (CBO-33, "Name collision"; `relay.py` `_destination_for`). And the earlier file is already gone (above). The only remaining dedupe is downstream, in calibre's automerge, whose CWA default is `new_record`, which **adds** a second book (§4.3). Deterministic bytes are still worth having for Colophon's own duplicate check while the file sits in output, but they don't solve this. |
| **Persisted state** | **Yes** | One small file records, per source and class, that a notice has been written for the current held incident. **Decided (§7, D5).** |

**Cheapest shape that works (the shape only, nothing built):**

* **File:** a dotted JSON file in the backups folder, e.g.
  `/backups/.colophon-notice.json`, containing
  `{"hardcover": {"class": "key", "since": "2026-09-23T10:00:00Z"}}`. The precedent is CBO-40's durable
  counter `/backups/.colophon-llm.json` (`llm.py:39`, CBO-40 Q10) and the
  record `/backups/.colophon.db`. That folder is already writable, already
  created at startup, and its 30-day cleanup leaves dotted names alone
  (`config.py`, `DEFAULT_RECORD_PATH` comment). No new setting is needed.
* **Written** when a notice is written. **Read** once at startup.
* **Cleared** for a source the first time that source answers successfully.
  That is CBO-80's "an outage ends the first time the source answers", applied
  to the held state. For a held source this can only happen after a restart
  with a fixed key, which is exactly the recovery CBO-81 documents.
* **Also cleared at startup** for any source that is no longer built (removed
  from `sources`, or its key file removed). Otherwise a stale entry would
  silence the next real incident for that source.
* **Keyed per source and class** (`key` or `held`, D5). Within one process a
  held source can't change class, because it is never retried. Across a
  restart it can: fix the key, restart, and the same source now fails with a
  configuration 400. A different class for the same source is a new incident
  and writes a new notice, which has a different title (D10), so the library
  keeps both and neither is a duplicate.
* **If it's unreadable**, treat it as empty and log once. The worst case is one
  duplicate notice, which errs towards telling the user.
* **Dry run** writes no notice (see D6), so it writes no state either.

This is about 20 lines of standard library (`json`, `pathlib`). A table in the
SQLite record would also work, but it means a schema change for one bit per
source.

---

## 4. What happens to the notice downstream

Everything in this section cites source code read at the commits in §0. **CWA**
means `crocodilestick/Calibre-Web-Automated` `main` at `43718d8`. The NextGen
fork was checked for the same behaviour where noted.

### 4.1 Can Colophon's own walk pick up its own notice?

**Not with a normal setup.** The relay walks `config.ingest_dir` and nothing
else (`relay.py:110–122`, `os.walk(self.config.ingest_dir)`). The notice is
written into `output_dir`.

Two ways it still could:

1. **The output folder is mounted inside the ingest folder.** `load_config`
   doesn't check for that (`config.py`), and `os.walk` descends into every
   subfolder whose name doesn't start with a dot. This is an existing risk for
   every delivered book, not something the notice introduces.
2. **The user re-drops the notice** into ingest. "To retry: re-drop the file"
   is the documented habit (CBO-33). Colophon would then try to match
   "⚠ Colophon: Hardcover rejected the key" against the sources. See D9.

### 4.2 Would CWA rewrite the ⚠ title or strip the `colophon:notice` tag?

With CWA's defaults, **no**. With auto metadata fetch turned on, **the title
can be replaced, but the tag survives.**

| Stage | Default | What it does to the notice | Source |
| --- | --- | --- | --- |
| **Conversion** | `auto_convert = 1`, target `epub` | An EPUB *is* the target format, so it is imported without conversion | `cwa_schema.sql:41–42`; `ingest_processor.py:570, 1470` |
| Conversion when the user's target is `kepub` | not the default | `kepubify --inplace --calibre` | `ingest_processor.py:777`. **Unverified** whether `dc:subject` survives kepubify |
| Conversion when the target is anything else (e.g. `azw3`) | not the default | `ebook-convert` | `ingest_processor.py:737`. **Unverified** here, though calibre conversion generally carries OPF metadata through |
| **Kindle EPUB fixer** | **on** (`kindle_epub_fixer = 1`) | Runs before import when the target is `epub`. It rewrites the zip, but it only fixes body-id links, `container.xml`, encoding, `dc:language` and stray images. **The title and `dc:subject` are not touched.** | `cwa_schema.sql:51`; `ingest_processor.py:857–862`; `kindle_epub_fixer.py:1098–1113, 1023–1044` |
| The fixer's language check | on | Skips the language fix if the OPF text lacks `xmlns:dc` (non-aggressive mode). Otherwise it looks for elements literally named `dc:language` with `minidom`, and inserts or replaces one if it is invalid. **So the notice must declare `xmlns:dc` with the `dc:` prefix and carry a valid `dc:language` (`en`).** If the OPF were written by ElementTree with default `ns0:` prefixes, the fixer would add a second language element | `kindle_epub_fixer.py:552–715` (`xmlns:dc` check at 609, `getElementsByTagName('dc:language')` at 614) |
| **Import** (`calibredb add`) | always | calibre reads each `dc:subject` as tags, **splitting on commas**. `colophon:notice` has no comma, so it arrives as one tag. The title is stored as written, ⚠ included | calibre `src/calibre/ebooks/metadata/opf3.py:734–739` (EPUB 3), `opf2.py:945–951` (EPUB 2); `ingest_processor.py:904–907` |
| **Auto metadata fetch** | **off** (`auto_metadata_fetch_enabled = 0`) | If on: it searches "title + authors", takes **the first result** of the first provider that returns any (`metadata_helper.py:90–95`), then **overwrites the title** (`:140`/`:143`; in smart mode only if the new title is longer), **replaces the authors** (`:150`) and the description, and **appends** tags (`:211`). **So the tag survives, but the ⚠ title can become some unrelated book's title**, and the notice then looks like a random book. NextGen has the same code (`nextgen/cps/metadata_helper.py:175–178, 249`) | `cwa_schema.sql:60–71`; `cps/metadata_helper.py` |
| **Auto-send** | per user | Every newly imported book is emailed to each user with auto-send on and a Kindle address. **The notice goes too** | `ingest_processor.py:982, 1140–1175` |
| **Kobo sync** | per user | When `kobo_only_shelves_sync` is off, the whole library syncs, the notice included. **Behaviour inferred from the setting name** (`cps/admin.py:791, 2550`), not traced through the sync code | |

Auto metadata fetch would clobber every Colophon correction, not just the
notice. Colophon exists because that fetch sends the raw title (CBO-33,
"Problem"). So the docs should say once, in general: *turn CWA's automatic
metadata fetch off when Colophon is in front of it.*

### 4.3 Two notices with the same title

`calibredb add` is run with `--automerge <CWA setting>`, **default
`new_record`** (`cwa_schema.sql:46`, `ingest_processor.py:906`). calibre
decides two books are "identical" when every author matches (case-insensitive),
the `fuzzy_title` values are equal (lower-cased, `[](){}<>'";,:#` and leading
articles removed, `-._` turned into spaces) and the languages are compatible
(calibre `src/calibre/db/utils.py:65–103`). What it then does
(`src/calibre/db/cli/cmd_add.py:46–105`, help text `:367–377`):

| CWA `auto_ingest_automerge` | A second identical notice (both EPUB) |
| --- | --- |
| **`new_record` (default)** | **Added as a second book.** The library holds two notices |
| `overwrite` | The EPUB in the existing book is replaced (`add_format(..., replace=True)`). **Unverified** whether the record's title and tags are refreshed from the new file. Either way there is still one book |
| `ignore` | The second one is discarded as a duplicate |

Then **CWA's duplicate detection** (on by default, scanning after import,
matching on title, author and language: `cwa_schema.sql:76–104`) flags the
pair and notifies. **Auto-resolve is off by default** (`:92`). If a user turns
it on with the default `newest` strategy, the older notice is backed up and
deleted (`cps/duplicates.py:148–150, 1725–1745`).

What follows for Colophon:

* **Give each source and class its own title** (decided, D10):
  "⚠ Colophon: Hardcover rejected the key" or "⚠ Colophon: Hardcover is
  holding books", and the same for Google Books and the LLM. Notices about
  different sources or classes are then never duplicates of each other. Only
  a genuine repeat of the same source and class is, and §3 stops that.
* **Use one fixed author, "Colophon".** `find_identical_books` needs a matching
  author, and a fixed one also groups the notices under one author in the
  library.

### 4.4 When the incident is over

**Colophon cannot remove the notice.** By then the file has left Colophon's
output folder (CWA deletes it on ingest, §3), and Colophon has no library API
by design (CBO-33). Writing a second "resolved" notice would only add clutter.

What the docs must tell the user:

1. After fixing the key and restarting, **delete the notice from the library
   yourself**. Search for the tag `colophon:notice` to find every one.
2. If the library **syncs every book** (Kobo sync without "only shelves", or
   CWA's auto-send to Kindle), the notice may already be on the e-reader.
   Delete it there too. (The ticket's own criterion.)
3. Keep CWA's **automatic metadata fetch off**, or the notice's title may be
   replaced by an unrelated book's (§4.2).
4. With CWA's default automerge, a repeated notice for the same source becomes
   a second book. The duplicates page will show it.

### 4.5 Not verified

* Whether `kepubify --calibre` and `ebook-convert` keep `dc:subject` (only
  relevant when the user's target format isn't `epub`).
* Whether `--automerge overwrite` refreshes the record's metadata or only the
  file.
* Whether CWA's Kobo sync pushes a library deletion to the device.
* Grimmory, or any library app other than CWA and NextGen.

---

## 5. Building the EPUB

**Nothing in the repo writes an EPUB from scratch.** `epub.correct` *rewrites*
an existing book: it copies every entry in order, keeps each one's compression,
and stamps a fixed date so that a re-drop gives the same bytes
(`epub.py:1027–1084`, `_EPOCH`). The tests build small EPUBs by hand
(`tests/samplebooks.py:185`, with `mimetype` written first through a bare
`ZipInfo`, which defaults to stored). `tests/test_epub.py:278–279` asserts that
a rewritten book's first entry is a stored `mimetype`.

**The minimum valid EPUB, standard library only (measured, §0).** It has four
zip entries:

1. `mimetype` → `application/epub+zip`. It must be the **first** entry,
   **stored** (not compressed), with no extra field (EPUB 3.3 §4.3,
   <https://www.w3.org/TR/epub-33/#sec-zip-container-mime>). With `zipfile`,
   that means a `ZipInfo("mimetype", _EPOCH)` with
   `compress_type = ZIP_STORED`, written before anything else.
2. `META-INF/container.xml` → points at the package document.
3. `OEBPS/content.opf`, an EPUB 3 package document with:
   * the required `dc:identifier`, `dc:title` and `dc:language`, and
     `meta property="dcterms:modified"` (EPUB 3.3 §5.5.3.1, §5.5.5)
   * `dc:creator` Colophon
   * `dc:subject` `colophon:notice`
   * a short `dc:description`, so the library shows the problem without the
     book being opened
   * a manifest holding one item, the nav document, with `properties="nav"`
   * a spine holding one `itemref` to it
4. `OEBPS/nav.xhtml` → the navigation document every EPUB 3 must have
   (EPUB 3.3 §2, §7). It **doubles as the notice page**. A nav document may
   appear in the spine (§7.5).

A fifth entry, a separate `notice.xhtml` page, is also valid (measured). It
costs 310 bytes and keeps the table of contents apart from the text.

* **Which EPUB version CWA accepts.** CWA has **no version gate**. EPUBs go
  through the fixer and `calibredb add`, and calibre reads both OPF 2
  (`opf2.py`) and OPF 3 (`opf3.py`). **EPUB 3 is the smaller valid shape.** A
  valid EPUB 2 needs an NCX file as well (OPF 2.0's spine `toc`). Colophon's
  reader already handles both (the Gutenberg fixtures).
* **Where the tag goes.** `<dc:subject>colophon:notice</dc:subject>` inside
  `<metadata>`. That is the same element `UNVERIFIED_TAG` uses, and for the same
  reason: it is what Calibre and CWA read as a tag (`epub.py:42–50`). A
  `NOTICE_TAG = f"{COLOPHON_PREFIX}notice"` beside `UNVERIFIED_TAG` would keep
  it out of `Book.subjects` automatically (`epub.py:211`).
* **Write the OPF as a literal template, not with ElementTree**, so the prefix
  is literally `dc:` (CWA's fixer matches on it, §4.2). The only dynamic
  values are the source label, picked from a fixed set, and a date. Anything
  interpolated still goes through `xml.sax.saxutils.escape`.
* **Deterministic bytes:** fixed zip dates (`_EPOCH`) and a fixed
  `dcterms:modified` (for example the date the incident was first noticed, to
  the day). Then the same incident always gives the same file.
* **Putting it in place:** under a hidden temporary name, then renamed, like
  every other file Colophon writes to output (`files.py`, `temp_name` /
  `os.replace`; CBO-33 "Partial files"). Use `free_name` if the name is taken.
  Never overwrite.
* **Filename:** ASCII, e.g. `colophon-notice-hardcover-key.epub` or
  `colophon-notice-hardcover-held.epub` (D10). CWA imports by
  metadata, not by filename. A `⚠` or `:` in a filename is a needless risk on
  SMB or Windows shares. The ⚠ belongs in `dc:title`.

**Ponytail:** `zipfile` and string templates are enough, as the probe shows.
**No new dependency.**

---

## 6. Secrets

**Does CBO-83 give the notice a scrubber to reuse? No.** CBO-83 (2026-09-23)
avoids the problem rather than solving it. Its messages are "fixed wording: no
error details, no keys". Its only scrub removes the URL from its *own* failure
log line, "including from `URLError` text". Neither is a general function for
arbitrary error text.

The scrubbers that exist today are private, per-source methods applied to
exception messages:

* `GoogleBooks._without_key` replaces the whole key (`googlebooks.py:225–228`)
* `Hardcover._without_token` replaces the whole token (`hardcover.py:270–273`)
* `Llm._without_key` replaces the whole key **and its last four characters**,
  because DeepSeek echoes `****<last 4>` (`llm.py:470–481`)

The one reusable, key-free piece in the agreed design is CBO-78's **short
reason**: "rejected the key" / "configuration problem, HTTP 400", specified as
"never key material" (2026-09-23).

**Every string that could reach the notice body, and the scrub it needs:**

| String | Where it comes from | Can it carry a secret? | Scrub |
| --- | --- | --- | --- |
| Source label ("Hardcover", "Google Books", "the LLM") | a fixed table | No | none; fixed text |
| Short reason | CBO-78, built from the status code | No, by specification | none. Test it anyway |
| Date first noticed | the clock | No | none |
| Setting name and configured key-file path (`hardcover_token_file` = `/run/secrets/hardcover_token`) as "how to fix" | `Config` | No. A path, not the file's contents | none. **Never read the file's contents into the notice** |
| **The exception text, `str(error)`** | `SourceError` / `LlmError` messages | **Yes.** See the rows below | **Don't include it at all** |
| ↳ Google transport error | "could not reach Google Books: …" (`googlebooks.py:176–179`) | **Yes.** The key is a query parameter, so any exception text that quotes the request URL carries it | `_without_key` replaces the exact key. Google keys use only `[A-Za-z0-9_-]`, which `urlencode` leaves unchanged, so the exact match works for a *valid* key. A key file holding anything else would be percent-encoded and slip past the exact match. That is another reason to leave the text out |
| ↳ Google refusal reason | the server's `error.message` (`googlebooks.py:350–363`) | Not the key as measured ("API key not valid"). But `accessNotConfigured` names the **project number**, which is identifying, not secret | leave it out |
| ↳ LLM refusal body | `_summarise` (`llm.py:624–638`), up to 200 characters of the provider's reply | **Yes.** DeepSeek echoes the key's last four characters | `_without_key` (whole key and tail). Leave it out |
| ↳ Hardcover refusal | `_summarise` GraphQL messages (`hardcover.py:469–475`) | Unlikely, since the token travels in a header | `_without_token`. Leave it out |
| ↳ TLS error text | `ssl.SSLCertVerificationError` | The hostname only | leave it out |
| `llm_base_url` | `Config` (a plain setting) | **Yes, possibly.** A custom endpoint URL can carry `user:pass@` or `?key=` | **Don't include it** |
| Webhook URL | `webhook_url_file` (CBO-83) | **Yes.** ntfy's `?auth=` and topic, Gotify's `?token=` | never read by the notice at all |
| LLM key | `llm_key_file` | **Yes** | never read by the notice |
| Held books' file names or a count | the relay | Not secret, but private and it goes stale. CBO-83 dropped the count for the held message too | leave it out |

**Decided (D12):** the body is **fixed wording**, plus the source label, plus
CBO-78's short reason, plus the date, plus a fix. For the `key` class the fix
names the setting and its path; for `held` it is generic.
No `str(error)`, no server text, no URLs. Then there is nothing to scrub, and
the test proves it.

**The basis for the "no secrets in the output" test:**

* **Plant sentinels:**
  * a Hardcover token
  * a Google key
  * an LLM key of at least 8 characters, and separately its last 4 characters
  * a webhook URL carrying `?token=`
  * an `llm_base_url` carrying `user:pass@`
* **Trigger the notice with hostile inputs:**
  * a 401 whose body echoes the key and the tail
  * a Google transport exception whose message contains the full request URL
    with `key=`
* **Assert** that no sentinel appears in:
  * any decompressed zip entry
  * the zip's file names or comment
  * the notice's filename
  * the log line announcing it

---

## 7. Decisions (grilled 2026-09-23)

Grilled with Callum on 2026-09-23, after §1 to §6 were drafted. Where a
decision differs from a recommendation earlier in the note, the decision wins.

| # | Question | Decided |
| --- | --- | --- |
| **D1** | What triggers a notice? | **Every held failure** (CBO-78): a rejected key, a configuration 4xx, a GraphQL `errors` reply, a TLS failure or an unreadable reply, for Hardcover, Google Books and the LLM. **Never** an outage, an LLM 402 or the daily limit. This supersedes "triggered only by a rejected or expired API key" in CBO-44 and CBO-33 (amended wording below). |
| **D2** | Borderline 403s (Hardcover 403, LLM 403, Google `accessNotConfigured`) | **Moot under D1.** They are held, so they raise a notice. Which class they fall in follows CBO-78's `rejected` flag (D3). |
| **D3** | How the notice tells a key from anything else | **As data: two classes, `key` and `held`.** Keep `SourceError.rejected` and add the same flag to `LlmError`, beside CBO-78's temporary/held kind. `rejected=True` is the `key` class; every other held failure is `held`. **A line for CBO-78.** |
| **D4** | Build order | **After CBO-83.** The notice is a second listener on CBO-81's "held, first noticed" event, beside the held webhook. CBO-44 is blocked by CBO-83 (and so by CBO-81 and CBO-78). |
| **D5** | Once per incident across a restart | **Persisted.** `/backups/.colophon-notice.json`, keyed by source and class: `{"hardcover": {"class": "key", "since": "…"}}`. Written when a notice is written; read once at startup. An entry is cleared the first time its source answers successfully, and at startup for any source that is no longer built. A different class for the same source is a new incident. An unreadable file is treated as empty and logged once. |
| **D6** | Dry run | **No notice and no state.** It logs `dry run: would write notice …`. (CBO-81 still writes the health file and CBO-83 still sends webhooks in a dry run.) |
| **D7** | An LLM key rejected during genre mapping | **Any LLM 401 puts the LLM in the held state**, genre mapping included. **A note for CBO-81.** |
| **D8** | Cover fetch failures | **A failed cover fetch is never held.** It stays the cover's business (CBO-51's `colophon:cover-unavailable`). **A note for CBO-78.** |
| **D9** | A notice re-dropped into ingest | **Nothing special (YAGNI).** The docs say not to re-drop notices. |
| **D10** | Title, author and filename | `key`: **"⚠ Colophon: \<Source> rejected the key"**, file `colophon-notice-<source>-key.epub`. `held`: **"⚠ Colophon: \<Source> is holding books"**, file `colophon-notice-<source>-held.epub`. Source slugs: `hardcover`, `google-books`, `llm`. Author **Colophon**. The status code and the reason stay in the body, so the title is stable within a class. |
| **D11** | EPUB shape | **EPUB 3, five entries**, standard library only: stored `mimetype` first, `META-INF/container.xml`, `OEBPS/content.opf`, `OEBPS/nav.xhtml`, `OEBPS/notice.xhtml`. The OPF is a literal template with the `dc:` prefix, `<dc:subject>colophon:notice</dc:subject>`, `dc:language` `en`, a short `dc:description`, and fixed dates (`_EPOCH` for zip entries, the incident's day for `dcterms:modified`). Written under a hidden temporary name and renamed; never overwrites (`free_name`). |
| **D12** | What the notice says | **Fixed wording**, plus the source label, CBO-78's short reason, the date first noticed, and a fix. `key`: name the setting and its configured path (e.g. `hardcover_token_file` = `/run/secrets/hardcover_token`), then "restart Colophon". `held`: "fix the setting named above, restart Colophon, and see `docker logs` for details; if this keeps happening with correct settings, report it". Always "delete this book once fixed". **Never** error text, server text, URLs, `llm_base_url`, counts or file names (§6). |
| **D13** | The setting | **`notice_epub = false`**, overridable as `COLOPHON_NOTICE_EPUB`. |
| **D14** | What the docs say | In `config.example.toml` beside `notice_epub`, and in the README: (1) off by default; one EPUB when Colophon starts holding books (rejected key, configuration problem, TLS failure or unreadable reply), never for an outage; (2) it only appears once a book has been looked up; (3) a dry run writes none, only logs it; (4) after fixing and restarting, delete it from the library yourself: search the tag `colophon:notice`; (5) if the library syncs every book (Kobo sync, CWA's auto-send to Kindle) it may reach the e-reader, so delete it there too; (6) keep CWA's automatic metadata fetch off, or it can replace the notice's title and your corrected titles; (7) don't re-drop a notice into ingest; (8) notices already written are remembered in `/backups/.colophon-notice.json`, so a restart doesn't repeat one. |
| **D15** | Tests | (1) `notice_epub` off: no file. (2) Several books, one held source: exactly one notice. (3) Restart, same source and class: no second notice. (4) Restart, different class for the same source: a new notice. (5) After the source answers, its entry is cleared, and a later failure writes a notice again. (6) Dry run: no notice and no state. (7) No secrets: sentinel Hardcover token, Google key, LLM key and its last four characters, webhook URL token, and `llm_base_url` with `user:pass@`; a 401 that echoes the key and a transport error carrying the URL; none appears in any zip entry, the filename, the zip comment or the log line. (8) The EPUB: `mimetype` first and `ZIP_STORED`, the `colophon:notice` tag, and the title for the class. EPUBCheck stays a manual one-off, not a test dependency. |

### Amended acceptance criteria for CBO-44

Replaces the ticket's list. Paste into CBO-44; the "Notice EPUB" section of
CBO-33 needs the trigger line changed to match.

- [ ] `notice_epub`, **off by default**, clearly documented in the example `config.toml` and in the code; overridable as `COLOPHON_NOTICE_EPUB`
- [ ] Triggered by **any held failure** (CBO-78): a rejected or expired key, a configuration problem, a TLS failure or an unreadable reply, for Hardcover, Google Books or the LLM. **Never** by an outage, an LLM 402 or the daily limit
- [ ] Drops one EPUB 3 into output: "⚠ Colophon: \<Source> rejected the key" or "⚠ Colophon: \<Source> is holding books", explaining the problem and how to fix it
- [ ] Tagged `colophon:notice`; written **once per incident** (per source and class), not per retry, per book or per restart
- [ ] Error details are never included; never contains keys, URLs or server text
- [ ] Not written in a dry run (logged instead)
- [ ] Docs cover the points in D14, including that it may sync to an e-reader and must be deleted by hand once fixed
- [ ] Tests: the eight in D15

### Notes for other tickets (not changed by this note)

* **CBO-78:** keep `SourceError.rejected` and add `rejected` to `LlmError` (D3); a failed cover fetch is never held (D8).
* **CBO-81:** any LLM 401, genre mapping included, enters the held state (D7).
* **CBO-33:** the "Notice EPUB" trigger line changes to "any held failure" (D1).

---

## Sources

Linear (read 2026-09-23): CBO-44; CBO-43 (description, both grillings, and the
CBO-40 scope comment); the document `cbo-43-failure-handling.md — research`;
CBO-78, CBO-79, CBO-80, CBO-81, CBO-82, CBO-83; CBO-33 (design spec).

Repository, `593f14a`: `colophon/relay.py`, `files.py`, `sources.py`,
`config.py`, `epub.py`, `googlebooks.py`, `hardcover.py`, `llm.py`,
`correction.py`, `__main__.py`; `tests/samplebooks.py`, `tests/test_epub.py`.

CWA, `crocodilestick/Calibre-Web-Automated` `main` at
`43718d85f6b0adbc2faff36c393fc7a823c60fd7` (2026-08-06):

* `scripts/ingest_processor.py`, `scripts/kindle_epub_fixer.py`,
  `scripts/cwa_schema.sql`, `cps/metadata_helper.py`, `cps/duplicates.py`,
  `cps/admin.py`, `dirs.json`
* <https://github.com/crocodilestick/Calibre-Web-Automated>

Calibre-Web NextGen, `new-usemame/Calibre-Web-NextGen` `main` at
`7f0a567d0c9ed5c652ddce940b691765c7b8f4fb` (2026-09-23):

* `scripts/cwa_schema.sql`, `scripts/ingest_processor.py`,
  `cps/metadata_helper.py`
* <https://github.com/new-usemame/Calibre-Web-NextGen>

calibre, `kovidgoyal/calibre` `master` at
`0583cba2680b4184c191d89d3a26282804fb49c3` (2026-09-23):

* `src/calibre/ebooks/metadata/opf3.py` (`read_tags`),
  `src/calibre/ebooks/metadata/opf2.py` (`tags`), `src/calibre/db/utils.py`
  (`fuzzy_title`, `find_identical_books`), `src/calibre/db/cli/cmd_add.py`
  (`do_adding`, `--automerge`)
* <https://github.com/kovidgoyal/calibre>

EPUB 3.3, W3C Recommendation: <https://www.w3.org/TR/epub-33/>. See §2 (a
navigation document is required), §4.3 (ZIP and `mimetype` requirements),
§5.5.3.1 (required metadata), §5.5.5 (last-modified date) and §7.5 (the nav
document in the spine).

Measured on 2026-09-23 with EPUBCheck 5.3.0 (the `epubcheck` wrapper from
PyPI, running on OpenJDK 21) and Python 3.11.15. The probe scripts were
scratch files and are not committed.
