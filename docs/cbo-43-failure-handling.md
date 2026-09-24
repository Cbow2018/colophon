# CBO-43: failure handling and the webhook

**For the sessions that build CBO-43's sub-issues (CBO-78 to CBO-83).** Written
and grilled 2026-09-23 against
`main` at `593f14a`. Everything marked **measured** was run on 2026-09-23:
the webhook shapes against a local Gotify 3.1.1 and a local ntfy 2.25.0 (both
official release binaries), and the healthcheck against a local Docker Engine
29.4.3. Everything else is the code as it stands or a primary source, cited
at the end.

Read with the ticket
[CBO-43](https://linear.app/cbow/issue/CBO-43/10-failure-handling-and-webhook),
its scope comment from CBO-40 (the LLM is covered too), and
`docs/research/cbo-40-llm-fallback-chooser.md` Q9, Q12 and "A 4xx that is not
401 or 429 repeats every day".

## Where the work sits

- Blockers: CBO-35 and CBO-39 (check they are Done in Linear), and CBO-50
  (merged as PR #15).
- **CBO-67 may already be done.** Since CBO-59 (`04e5585`), `_by_isbn` sends a
  `SourceError` to `_failed`, which holds the book (`correction.py:571`). Its
  description ("an ISBN-path source outage delivers the book anyway") no longer
  matches `main`. Confirm before building on either ticket.
- Linear's suggested branch is `callumbowden111/cbo-43-…`. Earlier tickets used
  `dsh/<short-topic>`.

## 1. What the code does today

Every failure ends in one of three places. None of them is what CBO-43 asks for.

| Where | What fails | What happens now |
| --- | --- | --- |
| `_by_isbn` / `_gather` → `_failed` → `_hold` | A source raises `SourceError` | Waits until the next UTC day, then asked again from scratch. No limit on how many days. |
| `_ask_llm` → `_wait` → `_hold` | `LlmError` or `LlmLimited` | Waits until the next UTC day, same as above. |
| `_cover` | The cover fetch raises `SourceError` | Logged. The book is corrected without a cover and gets no tag. |
| `_map_genres` | `LlmError` / `LlmLimited` | Logged. The genre is dropped. The book does not wait. |

**What is missing, and where:**

1. **Hardcover never sets `rejected=True`.** `hardcover.py:244` raises
   `SourceError("Hardcover rejected the token (HTTP 401/403)")` without the flag.
   Only Google Books sets it (`googlebooks.py:210`). The healthcheck has nothing
   to read for Hardcover until this is fixed.
2. **`LlmError` has no `rejected` field and no category at all.** "Key
   refused", "5xx", "429" and "config 4xx" are only different message strings
   (`llm.py:377–398`). CBO-40 Q12 asked for the log to name them "so CBO-43
   has something to inherit". What it inherits is text, not data.
3. **`SourceError` only knows two things: rejected or not.** CBO-43 needs three:
   *temporary* (retry), *rejected* (hold and mark unhealthy), and *everything
   else*. "Everything else" covers a reply that is not JSON, a GraphQL
   `errors` array, a 400, a 404, or a cover that is not an image. Today all of
   these are "not rejected", so under CBO-43 they would be retried as if they
   were outages.
4. **Every transport exception looks like an outage.** Each source wraps
   *any* `Exception` from the transport as "could not reach …"
   (`hardcover.py:239`, `googlebooks.py:176`, `llm.py:374`). A timeout, a DNS
   failure, a TLS certificate error and a genuine bug (`TypeError`) are all
   the same `SourceError(rejected=False)`.
5. **The hold list is keyed by the UTC day, per book** (`_waiting[path] =
   (day, note)`, and `forget_yesterdays_waits`). CBO-43 replaces this with state
   per source. The UTC-day rule must still be kept for `LlmLimited`: a spent
   daily limit is not an outage.
6. **The Dockerfile has no `HEALTHCHECK`**, and the compose example has no
   `healthcheck:`. `__main__.py` rejects any argument except `--reset-record` and
   `--yes`. So a `--health` flag, or anything similar, is a change to that list.
7. **Tags.** `epub.py` knows one Colophon tag, `UNVERIFIED_TAG`. The mark is
   carried as `Edits.unverified: bool | None`, where `None` means "leave it" and
   `False` means "take it off". `colophon:source-unavailable` and
   `colophon:cover-unavailable` need the same add-and-remove handling. The spec
   says "to retry: re-drop the file", so a later successful match must take
   the mark off, just as it does for `unverified`.

## 2. Sorting failures into kinds

What each provider documents or was measured to send, and the kind each one
suggests.

### Hardcover (from the docs, re-read 2026-09-23)

| Status | Documented meaning | Suggested kind |
| --- | --- | --- |
| 400 | Malformed body or unparseable GraphQL query | **other**: Colophon's own query is wrong |
| 400 | *Missing* auth header (**measured** earlier in `hardcover-api.md`, not documented) | a missing key cannot happen: no token file means the source is not built |
| **401** | "Missing, invalid, or expired token" | **rejected** |
| 403 | `insufficient_scope`, `unsupported_operation`, `top_level_limit_exceeded`, or other access refusals | **rejected** for `insufficient_scope` (a scoped token that cannot read). Colophon sends one top-level query, so it never hits the top-level limit |
| 408 | Query went over the 30 s maximum | **temporary** |
| 429 | Burst limit or daily limit (Free: 5,000 a day, resets at midnight UTC). Sends `Retry-After` in seconds | **temporary** |
| 500 | "An unknown error occurred" | **temporary** |
| 503 | "Temporarily unavailable, safe to retry" (**new** since `hardcover-api.md`) | **temporary** |
| 200 + `errors` | GraphQL refused the query | **other** |

The docs also say "We may reset tokens without notice while in beta". An
expired or reset token is a 401. That makes 401 the main expiry signal, and
the most likely real-world trigger for the key-rejected path.

### Google Books (from `cbo-37-google-books.md` and the code)

- A wrong, junk or truncated key: **HTTP 400** "API key not valid" (**measured**
  in CBO-37). The code decides it is a key problem from the *message*
  (`_KEY_WORDS`), not from the status.
- **429 is the daily quota.** Google's per-day quotas "reset at midnight Pacific
  Time". Google's own retry guidance says RESOURCE_EXHAUSTED retries "may not
  be expected to work for several hours". A 24 h window still covers that.
- **Gap:** CBO-37's table says "HTTP 403 → the key-rejected path, including
  the API not being enabled". The code only treats 400/403 as a key problem
  when the message contains a key word. A 403 `accessNotConfigured`
  ("Books API has not been used in project … or it is disabled") probably
  matches none of `_KEY_WORDS`, so it would be retried as an outage and end
  with `source-unavailable` rather than unhealthy. **Not measured.** Decide
  which one is intended.

### The LLM (DeepSeek, measured in CBO-40)

- 401 with a JSON body that echoes `****<last 4>`; 401 with a *bare string* body
  when there is no header; 400 for an unknown model; 404 with an *empty* body
  for a wrong path.
- The CBO-40 comment asks CBO-43 to decide whether "a 4xx that isn't 401 or 429"
  goes into the retry window. The facts: it does not change tomorrow (CBO-40
  §"A 4xx that is not 401 or 429"). Google's retry guidance says the same about
  INVALID_ARGUMENT: "Retrying a request with an invalid argument will never
  succeed". The realistic choices are covered in §7 Q3.

### Transport failures (Python standard library)

`urllib.request.urlopen(timeout=…)` raises `TimeoutError` (which
`socket.timeout` has been an alias of since 3.10) or a `URLError` wrapping the
cause: DNS, connection refused, or TLS. Timeouts, connection refused and DNS
failures are reasonably **temporary**. A TLS certificate failure
(`ssl.SSLCertVerificationError` inside `URLError`) is arguably **other**. A
non-network exception (a bug) should not be caught as an outage at all. Today
the catch-all hides all of these differences.

## 3. The webhook: **measured**

The spec says "`webhook_url` (ntfy/Gotify plain text)". **One plain-text body
does not work for both.** Each shape below was sent to a local server, and
the server's stored messages were then read back.

| Shape | ntfy 2.25.0 stored | Gotify 3.1.1 answered |
| --- | --- | --- |
| A. `POST`, `text/plain` body | the body ✔ | **400** "Field 'message' is required" |
| A2. `POST`, raw body, no Content-Type | (same as A) | **400** "Field 'message' is required" |
| **B. `POST`, empty body, `title` + `message` as query parameters** | **title ✔ message ✔** | **200, title ✔ message ✔** |
| C. `POST`, form-urlencoded body | the literal string `title=Colophon&message=probe+C+form` ✘ | 200 ✔ |
| D. `POST`, JSON body to the topic URL | the literal JSON text ✘ | 200 ✔ |
| F. text body and `?message=` | the **body** wins | the **query** wins |

Why, from the source: ntfy's `readParam` reads `message`/`title` from the
headers or the query, and an empty body "should not override message"
(`handleBodyAsTextMessage`). Gotify binds `CreateMessage` with gin's
`ctx.Bind`. For any content type other than JSON, XML or multipart that is
the form binder, which maps from `req.Form`. `req.Form` includes the URL
query, so `?message=` satisfies `binding:"required"`. A plain-text body is
never read.

**Shape B works on both.** It also worked when the URL already carried a
query string, both Gotify's `?token=` and ntfy's `?auth=`, when the parameters
were merged with the standard library:

```python
parts = urllib.parse.urlsplit(webhook_url)
query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
query += [("title", title), ("message", message)]
url = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))
urllib.request.Request(url, data=b"", method="POST")
```

Non-ASCII text (`—`, `Ü`, `⚠`) arrived intact on both servers. `ntfy.sh`
itself could not be reached from the probe environment, so only the
self-hosted servers were measured.

**What the servers answered on failure (measured):**

| Case | ntfy | Gotify |
| --- | --- | --- |
| Wrong token | 401 `{"code":40101,…}` | 401 "you need to provide a valid access token…" |
| No token on a protected topic/app | **403** `{"code":40301,…}` | 401 |
| Nothing listening | `URLError` "Connection refused" | same |

**The webhook URL is itself a secret.** ntfy's docs: "the topic is essentially
a password". A protected ntfy topic carries `?auth=<base64 credentials>`, and
Gotify's only URL-borne credential is `?token=`. But the spec says
"`webhook_url` setting" and "secrets never go in environment variables", and
`config.py` promises "every setting here is a plain, non-secret one". That
conflicts. See §7 Q1. Whatever is chosen, the URL must never reach a log line
or an exception message, including `URLError` text. The message text is
Colophon's own fixed wording, so it cannot carry a key if error details are
never interpolated into it.

**Limits worth knowing:** ntfy messages are at most 4,096 bytes (anything longer
becomes an attachment). ntfy's default visitor limit is a bucket of 60 requests
that refills at one every 5 s. Two messages per incident are nowhere near
either limit.

**The webhook call blocks the scan loop** (`run` is single-threaded). It needs
its own short timeout, so a dead notification server does not stall
delivery.

## 4. The healthcheck: **measured**

Colophon has no port by design, so the check can only read something the
process leaves behind: in practice a file. It was tested on a minimal image
under the same hardening as `docker-compose.example.yml` (`read_only`, `tmpfs:
/tmp`, `user: 1000:1000`, `cap_drop: ALL`, `no-new-privileges`, `restart:
unless-stopped`). The main process wrote `/tmp/colophon.health` after 5 s, and
the check was `exit 1` whenever that file existed:

| Observation | Result |
| --- | --- |
| Status after the file appeared, `--health-retries 2` | `healthy` → `unhealthy` after 2 failures in a row |
| **`RestartCount` while unhealthy, `restart: unless-stopped`** | **0: an unhealthy container is not restarted** |
| The check's output | stored in `.State.Health.Log`, e.g. `1 unhealthy: hardcover rejected the token`. `docker ps` shows `(unhealthy)` |
| The check runs as | the container's user (it read a file that uid 1000 wrote) |
| **`read_only` with no tmpfs on `/tmp`** | the write fails with "Read-only file system", and **the check stays `healthy`** |
| A tmpfs over a `/tmp` that is mode 755 in the image | uid 1000 cannot write to it. The tmpfs took the mode of the image's directory |

What follows from that:

- **Unhealthy is a signal and nothing more.** Docker's restart policies act when
  the container exits. Nothing in the policy table mentions health. So the
  webhook, not a restart, is what actually tells the user.
- **"Write a file when unhealthy" fails open.** When `/tmp` is not writable
  (a user who dropped the `tmpfs` line), a rejected key would show as healthy.
  The alternative fails closed: the process writes a status file on every scan,
  and the check requires it to exist, be recent and say healthy. That also
  catches a hung loop, but it adds a freshness rule. See §7 Q6.
- `python:3.11-slim`'s `/tmp` is expected to be the Debian default `1777`,
  so the compose `tmpfs` should be writable by uid 1000. **Not measured**:
  the registry could not be reached from the probe environment.
- Docker's defaults are `--interval 30s`, `--timeout 30s`, `--retries 3`. Only
  the last `HEALTHCHECK` in a Dockerfile counts, and a compose `healthcheck:`
  overrides it. Exit `0` means healthy, `1` means unhealthy, and `2` is
  reserved.
- A `HEALTHCHECK` in the Dockerfile reaches every user without a compose
  change. The check should not load `config.toml`: if a bad setting made the
  check itself fail, it would show as unhealthy for the wrong reason.

## 5. Durations and clocks

- **Parsing** is one regular expression from the standard library:
  `^(\d+)([mhd])$`, plus the literal `0`. Edge cases the ticket does not
  settle: `"0h"`, `"1h30m"`, `"24H"`, `" 24h "` and `"-1h"` (see §7 Q9).
- **TOML against the environment.** `_setting` type-checks values from the file
  and passes values from the environment through as strings. A duration key
  will get `"24h"` (str) from both, but `source_retry = 0` in TOML is an
  **int**, which `_setting(…, str)` would refuse as "the wrong kind of value".
  The ticket says `0` is valid, so the int `0` probably needs accepting
  explicitly.
- **Which clock.** `time.monotonic()` "is not affected by system clock updates",
  which is right for "5 minutes from now". On Linux it does not count time
  the machine was suspended (`CLOCK_BOOTTIME` does). That matters little
  for a homelab server.
- **The schedule inside the default window.** With 5 min, 15 min, 1 h and then
  every 3 h, the probes fall at 0h05, 0h20, 1h20, 4h20, 7h20, 10h20, 13h20,
  16h20, 19h20 and 22h20. That is **10 probes**, and the window closes at 24h00
  **with no probe in the last 1h40**. Whether to probe once more at the edge
  is a decision (decided: §7 Q15, yes).
- **State is in memory.** The `_waiting` list and a per-source health state
  both vanish on restart. The window then starts again, and a crash loop under
  `restart: unless-stopped` could hold a book indefinitely. CBO-40 made its
  counter durable (`/backups/.colophon-llm.json`) for exactly this reason (Q10).
  See §7 Q7.

## 6. What a probe could be

The ticket says "one probe per source per scheduled attempt". A probe can take
two shapes (decided: §7 Q5, the first):

- **Re-run one held book's own lookup.** It needs no special request and makes
  progress with the answer. But the pooled title walk asks *every* source,
  so a probe for Hardcover also queries Google Books.
- **A dedicated cheap call per source.** Hardcover documents `query { me { id } }`
  as its example request. It costs 1 of the 5,000 daily requests and proves the
  token without touching a book. Google Books has no free call: any `volumes`
  query spends quota. For the LLM, `GET /models` spends no tokens.
  **But** CBO-40 Q1 rejected a `/models` check because the counter "spends a
  request". Whether `/models` counts against `llm_daily_limit` is undecided.
  A chat call spends real money.

## 7. The grilling: decisions

Every question in the first draft of this section was put to the maintainer on
2026-09-23, and each one below is answered. They are decisions, not
deductions. Where one changes CBO-43's original acceptance criteria, it says
so.

### Round 1

- **Q1 The webhook URL is a secret.** It is `webhook_url_file`, a Docker secret
  at `/run/secrets/webhook_url`. If the file is missing, no webhook is sent.
  *This changes the AC*, which named `webhook_url`.
- **Q2 One request shape, with no format setting.** It is shape B from §3: a
  `POST` with an empty body and `title=Colophon&message=…` in the query. The
  title is always "Colophon", and no ntfy priority or tags are sent.
- **Q3 There are two kinds of failure.** *Temporary* ones are retried on the
  schedule. *Everything else* (a key or a configuration problem) is **held**:
  books wait, the container goes unhealthy, nothing is tagged, and you fix it
  and restart.
- **Q4 The window is per source.** It starts at the source's first failure.
  Once the outage is older than the window, held books and newly arriving
  books pass through tagged until the source answers.
- **Q5 An attempt re-runs the oldest book waiting on that source.** If the
  source answers, every book waiting on it is retried on the next scan. There
  are no special health-check requests.
- **Q6 The heartbeat fails closed.** The process rewrites
  `/tmp/colophon.health` (`ok` or `unhealthy: <reason>`) after every book and
  every scan. `python -m colophon --health` exits 1 if the file is missing,
  older than about 10 minutes, or doesn't say `ok`. It does not load the
  config.
- **Q7 Outage state is kept in memory.** A restart starts the window again.
- **Q8 A rejected LLM key holds only the books that need the LLM.** The
  container is still unhealthy. Books the rules match confidently still go
  through.
- **Q9 The duration format** is a number followed by lower-case `m`, `h` or
  `d`, with surrounding whitespace stripped. `0`, `"0"` and `0h` all mean
  "don't hold". Anything else is a `ConfigError`, including `1h30m`, `24H`
  and `-1h`.
- **Q10 The LLM daily limit is not an outage.** It stays a wait until the next
  UTC day and does not count toward the window.
- **Q11 `colophon:cover-unavailable` is defined here**, including adding and
  removing it. CBO-51 is what applies it.
- **Q12 The fix for a held failure is to correct it and restart.** A held
  source is not retried.
- **Q13 A dry run** still sends webhooks and writes the health file.
- **Q14 `Retry-After` is ignored.** The schedule stays fixed.

### Round 2

- **Q15 One final attempt when the window closes.** Otherwise the last try
  would be at 22h20.
- **Q16 After the window**, new books are still asked. If the source still
  fails, they pass straight through tagged. There is no background retrying.
- **Q17 Temporary** means a timeout, connection refused or reset, a DNS
  failure, or HTTP 408, 429 or any 5xx. Everything else is held, including a
  TLS certificate failure, an unreadable reply and a GraphQL `errors` array.
  Errors that aren't network errors (real bugs) are no longer caught as
  outages.
- **Q18 The messages.** *Held*: "Colophon: Hardcover rejected the key. Books
  are being held; fix the key and restart." It carries no count. *Source
  failure* names the source and how many books left. There is no
  "recovered" message.
- **Q19 Webhook failures** have a 10s timeout, are logged once at WARNING with
  the URL removed, and are not retried.
- **Q20 An outage ends** the first time the source answers, and a later failure
  starts a new outage. The held state is cleared only by a restart.
- **Q21 A `source-unavailable` book** keeps its original metadata, with the
  tag only and no description note. The same tag is used for the LLM. A
  later full match removes it.
- **Q22 The Dockerfile healthcheck** is
  `HEALTHCHECK --interval=1m --timeout=10s --start-period=1m --retries=3 CMD ["python", "-m", "colophon", "--health"]`.
- **Q23 New settings** are `source_retry` and `webhook_url_file`. CBO-51 adds
  `cover_retry` using the same parser.
- **Q24 The vocabulary.** An **outage** is the temporary kind. **Held** is the
  key or configuration kind.

### Round 3: "Hardcover is down but Google Books is up"

Today such a book waits, even when Google has a strong match, because the walk
is half-asked (CBO-59). Under Q21 it would then leave after 24h with its
*original* metadata, and Google's match would be thrown away. The maintainer
asked for a fallback:

- **Q25 `fallback_score`** defaults to **0.89**, the same bar as `strong_score`,
  and can be lowered (for example to 0.80). The match must still pass the
  existing author check.
- **Q26 `fallback_after`** defaults to `"1h"`. `"0"` means write straight
  away. Setting it to at least `source_retry` turns the fallback off.
- **Q27 A fallback book is tagged `colophon:incomplete`**, and a later full
  match removes the tag. `source-unavailable` stays for books that went
  through untouched.
- **Q28 The source-failure webhook** is sent the first time a book leaves
  without that source, through the fallback or at window close, once per
  outage. *This replaces "sent at window close" from Q18.*
- **Q29 Below `fallback_score`**, the book keeps waiting on the normal window.
- **Q30 The fallback applies to any source that is down**, whichever way round,
  including on the ISBN path, which must now carry on past a failed source.
- **Q31 It applies to source outages only**: not to LLM waits, and not to held
  failures.

### Round 4: the LLM gets its own window

The maintainer asked for LLM trouble to have its own configurable wait, since
it "might just be topping up the LLM agent or rebooting the local LLM".

- **`llm_retry`** is a separate duration from `source_retry`, defaulting to
  `"24h"`. LLM outages follow the same schedule and tag on this window.
- **An LLM 402 is temporary.** DeepSeek documents 402 as "Insufficient
  Balance… go to the Top up page", so topping up recovers without a restart.
  A local LLM that is rebooting (connection refused) is already temporary.
- Every other LLM 4xx except 429 is held, which answers the question the
  CBO-40 comment left open.

### The build tickets

CBO-43 is built as six sub-issues, in this order:

| Ticket | What | Blocked by |
| --- | --- | --- |
| CBO-78 **10.1** | Sort every failure into temporary or held | none |
| CBO-79 **10.2** | Duration settings: `source_retry`, `llm_retry` | none |
| CBO-80 **10.3** | Outages: per-source schedule, pass-through tagging | 78, 79 |
| CBO-81 **10.4** | Held books and the container healthcheck | 78 |
| CBO-82 **10.5** | Fallback from the sources that answered | 79, 80 |
| CBO-83 **10.6** | Webhook for ntfy and Gotify | 80, 81, 82 |

## 8. Fixtures and tests

- Hardcover has no recorded 401/403/429/503 reply in `tests/fixtures/hardcover/`.
  Build them by hand from the documented bodies (§2), named `hand-made-*`
  as the folder already does.
- Google Books already has `error-key-rejected.json` (a real 400). There is no
  recorded 429 quota reply.
- The LLM's rejected-key reply was deliberately **not** committed in CBO-40
  (it echoes key material). Build it by hand.
- Webhook tests need no network: the sources' `transport=` seam pattern
  (a callable returning `(status, body)`) fits a notifier directly.
- The ticket's own test list still stands: the retry schedule, pass-through
  after the window, key rejection → unhealthy, one webhook per incident,
  duration parsing (including `0` and a malformed value), and one probe
  releasing several held books.

## Sources

Primary sources, read 2026-09-23:

- Hardcover API, Getting Started (status codes, 403 variants, rate limits,
  `Retry-After`, token expiry and resets):
  https://raw.githubusercontent.com/hardcoverapp/hardcover-docs/main/src/content/docs/api/Getting-Started.mdx
- ntfy publishing docs (plain `POST`, parameters as headers or query, auth
  forms, "the topic is essentially a password", limits):
  https://raw.githubusercontent.com/binwiederhier/ntfy/main/docs/publish.md
- ntfy server, `handleBodyAsTextMessage` and `readParam`:
  https://raw.githubusercontent.com/binwiederhier/ntfy/main/server/server.go
- Gotify `CreateMessage` model (`binding:"required"` on `message`):
  https://raw.githubusercontent.com/gotify/server/master/model/message.go
- Gotify create-message handler (`ctx.Bind`):
  https://raw.githubusercontent.com/gotify/server/master/api/message.go
- Gotify token lookup (query `token`, `X-Gotify-Key`, Bearer) and 401/403:
  https://raw.githubusercontent.com/gotify/server/master/auth/authentication.go
- Gotify push docs: https://raw.githubusercontent.com/gotify/website/master/docs/pushmsg.md
- gin `binding.Default` and `formBinding.Bind` (maps from `req.Form`):
  https://raw.githubusercontent.com/gin-gonic/gin/master/binding/binding.go,
  https://raw.githubusercontent.com/gin-gonic/gin/master/binding/form.go
- Dockerfile `HEALTHCHECK` reference: https://docs.docker.com/reference/dockerfile/#healthcheck
- Compose spec, `healthcheck`:
  https://raw.githubusercontent.com/compose-spec/compose-spec/main/05-services.md
- Docker restart policies:
  https://raw.githubusercontent.com/docker/docs/main/content/manuals/engine/containers/start-containers-automatically.md
- Google AIP-194, which errors to retry: https://google.aip.dev/194
- Google Cloud quotas, per-day reset at midnight Pacific:
  https://docs.cloud.google.com/docs/quotas/overview
- Python `time.monotonic` / `CLOCK_BOOTTIME`: https://docs.python.org/3/library/time.html

Measured locally on 2026-09-23: Gotify 3.1.1 (`gotify-linux-amd64.zip`, the
latest release), ntfy 2.25.0 (`ntfy_2.25.0_linux_amd64.tar.gz`), and Docker
Engine 29.4.3 with a minimal imported image. The probe scripts were scratch
files and are not committed.
