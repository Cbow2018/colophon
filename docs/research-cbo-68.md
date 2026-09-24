# [CBO-68](https://linear.app/cbow/issue/CBO-68/title-search-returns-editions-not-works-the-medium-band-is-the-normal): the standard edition rule — is it derivable, and is it worth it

## Session 1b re-measure (2026-09-23)

Research only: nothing in the repository was changed, committed, recorded or
pushed; this note and its probe are delivered as files. Everything was measured
against `main` at `22f456b` ([CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re) merged). A rebase of
`dsh/cbo-68-standard-edition-rule` onto that commit was tried in a scratch copy and
has **no conflicts**. The body below this section is session 1's record
of 2026-09-22 and is left as written; figures in it that the re-record killed are
struck through where they stand, with a pointer here.

**Measured at** `22f456b`**.** These figures are a snapshot of `main` before the build.
Once D12 lands, the probe's "baseline" column shows option 1's behaviour, so it is
re-run once by the build session for the "after" figures and is not kept current
after that (D20).

**Settled in the session 1b review (2026-09-24):** D15–D23, recorded in
`cbo-68-build-brief.md` on the ticket. In short: §0.8's amendments 1–3 are accepted
(D15–D17); the dated-file singleton consequence is accepted and documented (D18);
the Hardcover Poe row is the build's first commit (D19); the probe stays as a
snapshot (D20); the file-year preference goes to [CBO-71](https://linear.app/cbow/issue/CBO-71/filename-edition-markers-let-the-user-disambiguate-which-edition-they) (D21); series position stays
out of the key and [CBO-65](https://linear.app/cbow/issue/CBO-65/dedupe-collapses-editions-differing-only-in-series-position-silently) is scoped against it (D22); `Candidate` does not carry
`book.id` (D23). Every format — audiobook and hardback included — is an Edition of
the Work, and the risk of a non-ebook Edition's ISBN being written into an EPUB is
[CBO-90](https://linear.app/cbow/issue/CBO-90/title-path-can-write-a-non-ebook-editions-isbn-publisher-and-date-into) (D24); audiobook support as a feature is [CBO-91](https://linear.app/cbow/issue/CBO-91/explore-audiobooks-as-an-option-for-colophon-reusing-the-same-codebase), after v1.0.0. The terms
Work, Edition and Standard Edition are defined in `context-additions-cbo-68.md`, and
the rule's rationale is in the ADR draft `adr-draft-standard-edition.md`. The extra
strike-throughs in the body were reviewed and kept.

**Every number in this section comes from one command**, run from the repository
root, which prints every row quoted below:

```
python docs/research-cbo-68-probe.py --shuffle 100
```

`docs/research-cbo-68-probe.py` is delivered with this note and belongs at that
path (D20), so the figures can be re-run. It is a probe, not shipped code, and it does three things worth knowing
before trusting it:

* **The walk is the real one.** Each book is an EPUB on disk, read by `epub.read`
  and passed to `Corrector.correct` with `dry_run=True` and `llm=None` — a
  default install with no LLM configured — over the real `Hardcover` and
  `GoogleBooks` clients. Only the transport is replaced.
* **A reply is replayed only for the exact request it was recorded with.** The
  transport compares what the client sends with `tests/recordings.sent_request(row)`
  for every declared title row, and refuses when nothing matches. So nothing is
  approximated: a book whose request no fixture answers is reported as unmeasured,
  not guessed.
* **The options are simulated, not implemented.** The probe's `_gather` is the
  shipped one (`correction.py:676`) with one line changed — the pool passes through
  the option before `dedupe` (`:706`) — and, for options 1 and 2, `hardcover._candidates`
  is swapped for one that hands up every edition (D12) for the length of the run.
  "Distinct outcomes" below is the number of different (band, written payload)
  pairs seen over 100 runs in which every source's reply list was shuffled
  (`random.Random(68)`).

### 0.1 Where this contradicts the brief or earlier notes

Stated first, by name, rather than worked round.

1. **The Infirmary (Carly Reagon) is** `strong`**, not** `low (1)`**.** Commit `728c7ea`'s
   table (the *Session 2* section at the foot of this note) says `low (1)`. Through
   the real walk it is `strong` in every configuration. Hardcover's title request
   carries no author (`hardcover.py` `by_title` accepts it and does not send it), so
   the request for Reagon's file is byte-identical to the Ross one and
   `hardcover/by-title-the-infirmary.json` **is** Reagon's Hardcover reply — the
   probe checks that equality rather than assuming it. Session 1's "none (no
   recording)" for Reagon on Hardcover was wrong for the same reason.
2. **The live reply's** `earliest` **survivor is not** `du6sYyygMgIC`**.** The brief says it
   was session 1's survivor and asks whether it still is. On
   `googlebooks/by-title-poe.json` as re-recorded it is not: `0uZ6IaW21DQC`
   (`Penguin UK`, `2008-10-02`) is earlier than `du6sYyygMgIC` (`2013-01-29`). The
   `hand-made/README.md` sentence "`2013-01-29` is the **earliest** `publishedDate`
   in the reply" is true of the ten-volume reply and of the frozen five, and false
   of the live twenty.
3. **A gap of 0.0602 comes back, on different volumes.** The brief lists session
   1's 0.0602 as dead, and it is: it was `du6sYyygMgIC` against `Q8jPsgEACAAJ` on a
   reply that no longer exists. Re-measured on the live reply under option 1 with
   D11's strict key, the gap is **0.0602 again** — leader `0uZ6IaW21DQC` 0.9231,
   runner-up `Q8jPsgEACAAJ` (`Edgar Allen Poe`) 0.8629. Same arithmetic (both lose
   only the year to the file's `2010`; `Allen` also loses author similarity),
   different leader. It is quoted in §0.4 as a new measurement, not a survival.
4. **"Five tied at 1.0000" was never in this note's §4.** §2.2 and §4 both say
   0.9231. The 1.0000 was [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re)'s ticket, its research note §3.2 and a Linear
   comment. Harmless, but the dead-figure list in the brief attributes it here.
5. [CBO-75](https://linear.app/cbow/issue/CBO-75/google-subtitle-is-never-read-and-cbo-58md-claims-it-is) **is now "never fetched", not only "never read".** Session 1 §6.2 found a
   Google `subtitle` on 8 of 18 recorded volumes. The shipped mask
   (`googlebooks.py:52`, `FIELDS`) does not ask for `items/volumeInfo/subtitle`, so
   the re-record carries it on **0 of the 26** distinct live title-path volumes.
   Only `hand-made/poe-core-cases.json`, frozen from the unmasked recording, still
   has it (4 of 5).
6. **The shipped configuration cannot be measured for Poe.** There is no Hardcover
   reply for `{"titles": ["The Masque of the Red Death"], "language": "en"}`, and
   `tools/record-fixtures.py` cannot record one: it records declared rows only, and
   no Hardcover Poe row is declared. §0.9 has the steps.

### 0.2 The population

The books the title fixtures were recorded **about**, as `tests/recordings.py`
declares them — not the sample files. A sample file such as
`samplebooks.CRAGSIDE` (`Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)`)
makes the client send a second title form no fixture was recorded with, so it
cannot be walked without approximating. The price is that the file's series number
is never compared; see §0.7.

| Book (file) | Hardcover reply | Google reply |
| -- | -- | -- |
| Cragside / L. J. Ross | `hardcover/by-title-cragside.json` | `googlebooks/by-title-cragside.json` |
| Berwick / L. J. Ross | `hardcover/by-title-berwick.json` | `googlebooks/by-title-berwick.json` |
| Belsay / L. J. Ross | `hardcover/by-title-belsay.json` | `googlebooks/by-title-belsay.json` |
| The Infirmary / L. J. Ross | `hardcover/by-title-the-infirmary.json` | `googlebooks/by-title-the-infirmary.json` |
| The Infirmary / Carly Reagon | `hardcover/by-title-the-infirmary.json` (same request) | `googlebooks/by-title-the-infirmary-reagon.json` |
| The Masque of the Red Death / Edgar Allan Poe — the real Gutenberg EPUB, `dc:date` `2010-06-06` | **none** | `googlebooks/by-title-poe.json` (live, 20 volumes) |
| The Cragside Compendium of Nothing / no author | **none** | `googlebooks/by-title-nothing.json` |

The three `-other-fields` title fixtures are byte-identical to their partners (the
probe checks), so each book is counted once. Session 1's *Holy Island* and
*Cragside (no author)* rows are dropped: no declared fixture answers either book's
request, and session 1 answered them with replies recorded for other questions.

Four source configurations, since D10 asks for both orders: the shipped order
(`hardcover`, `google_books` — `config.KNOWN_SOURCES`, which is also the default
list), the reverse, and each source alone. Which of these a default install
actually runs depends on which keys the user supplied; none of them has an LLM.

### 0.3 The baseline, by book (step 2a)

Baseline is the code on `main`. **It is also option 3**: keeping `unverified` as the
answer changes nothing in the walk, so its distribution is this one.

| Book | shipped order | reversed | Hardcover only | Google only |
| -- | -- | -- | -- | -- |
| Cragside | strong (1) | **medium (2)** | strong (1) | **medium (2)** |
| Berwick | strong (1) | strong (1) | strong (1) | strong (1) |
| Belsay | strong (1) | strong (1) | strong (1) | strong (1) |
| The Infirmary (Ross) | strong (2) | strong (1) | strong (2) | strong (1) |
| The Infirmary (Reagon) | strong (2) | strong (1) | strong (2) | strong (1) |
| The Masque of the Red Death | *unmeasured* | *unmeasured* | *no reply* | **medium (20)** |
| The Cragside Compendium of Nothing | *unmeasured* | *unmeasured* | *no reply* | none (0) |

Pool size in brackets. Every `medium` above ends `colophon:unverified`, because
there is no LLM to ask. **Which tie, and why:**

* **Cragside, Google first or Google only.** `7kMMzgEACAAJ` (`Ulverscroft Special Collection`, `2021-03`) and `RASDtAEACAAJ` (`2017-07-07`) both score **1.0000**,
  gap **0.0000**. The file states a title and an author, both volumes agree on
  both, and nothing else is compared. In the shipped order Hardcover answers first
  with one work (`book.id` 1198994), scores 1.0000 as a singleton and the walk exits
  before Google's reply is read.
* **The Masque of the Red Death, Google only.** **Ten** of the twenty volumes tie at
  **0.9231**, gap **0.0000**: `q6T5zQEACAAJ`, `XcE-EAAAQBAJ`, `_hSNzQEACAAJ`,
  `du6sYyygMgIC`, `nPByzgEACAAJ`, `wwLYDwAAQBAJ`, `hch-zQEACAAJ`, `AuV20QEACAAJ`,
  `qIfzzQEACAAJ`, `0uZ6IaW21DQC`. All ten agree on title and author and disagree
  with the file's `2010` year, which is the whole of the 0.0769 they lose. This
  confirms the brief's live figures (20 volumes, tie at 0.9231, gap 0.0000).
* **Nothing is medium on the shipped order**, among the five books it can be
  measured on. That is session 1's structural finding, re-confirmed: Hardcover's
  exact-title reply is works, not printings, and a one-work pool exits early.

**Determinism, the D10 bar, fails on the baseline** — and not only where the band
is medium:

| Book, configuration | Distinct outcomes in 100 shuffles | What varies |
| -- | -- | -- |
| Berwick, shipped / Hardcover only | 2 | which of the two `2026-02-26` editions is written: `9781529978940` (`Century`) or the ISBN-less `Amazon Digital Services` one |
| The Infirmary (Ross), shipped / Hardcover only | 3 | which of work 1198266's three editions is written: `9781799729945`, `9781912310111` or `9781792780844` |
| Cragside, reversed / Google only | 2 | which tied volume leads |
| The Masque of the Red Death, Google only | 10 | which tied volume leads |

The first two rows are **strong** books that are **written**: Hardcover's
`_candidates` keeps the first edition of each work in reply order
(`hardcover.py:351`), and the title query has no `order_by`. So option 3 is not
"do nothing safely" — it leaves a live defect on the shipped configuration that the
ticket's own acceptance criterion names.

#### Year sensitivity

Only one real file in the corpus carries a `dc:date` (Poe). To see what a date does,
the probe also walks Cragside with `dc:date` set to 2017 (the original), 2021 (the
Ulverscroft large print) and 2019 (neither). `dc:date` is not in either request,
so the recorded replies still answer exactly; only the file differs, and these are
labelled synthetic.

| Cragside file | shipped | reversed | Hardcover only | Google only |
| -- | -- | -- | -- | -- |
| no date | strong (1) | medium (2) | strong (1) | medium (2) |
| `dc:date` 2017 | strong (1) | medium (2), gap 0.0769 | strong (1) | medium (2), gap 0.0769 |
| `dc:date` 2021 | medium (2), gap 0.0769 | medium (2), gap 0.0769 | medium (1), 0.9231 | medium (2), gap 0.0769 |
| `dc:date` 2019 | medium (2), gap 0.0000 | medium (2), gap 0.0000 | medium (1), 0.9231 | medium (2), gap 0.0000 |

**A year can never separate two editions on its own.** \`YEAR_WEIGHT / (TITLE_WEIGHT

* AUTHOR_WEIGHT + YEAR_WEIGHT)`is 0.15 / 1.95 = **0.0769**, under`BAND_GAP`'s **0.08** (`[matching.py:39](<http://matching.py:39>)`, `:76\`). A file that names the right edition's year still
  grades medium against a reply holding a second edition.

### 0.4 The three options, simulated (step 2b)

Option 1 is D3 as decided and amended (D11–D13): group by work, keep the earliest,
then the most complete, then a total order. The simulated key is the title head as
the scorer normalises it plus every author compared letter for letter after
`matching._name`. Option 2 replaces each group by one work-level candidate: no
ISBN, publisher, edition date or edition cover; Hardcover's work date, blurb and
work image where a Hardcover member supplies them; nothing for a group of Google
volumes, because Google has no work layer. Option 3 is the baseline above.

| Book | Config | baseline / option 3 | option 1 | option 2 |
| -- | -- | -- | -- | -- |
| Cragside | reversed | medium (2) | **strong**, `RASDtAEACAAJ` 2017-07-07 | **strong**, undated work |
| Cragside | Google only | medium (2) | **strong**, `RASDtAEACAAJ` | **strong**, undated work |
| The Masque of the Red Death | Google only | medium (20), gap 0.0000 | medium (11), leader `0uZ6IaW21DQC` 0.9231, gap **0.0602** to `Q8jPsgEACAAJ` | medium (11), leader 1.0000, gap **0.0652** to `Allen` |
| The Infirmary (Ross) | shipped, Hardcover only | strong, writes whichever edition came first | strong, writes `9781792780844` (`Independently Published`, 2019-01-01) | strong, writes no ISBN |
| Berwick | shipped, Hardcover only | strong, writes either edition | strong, writes `9781529978940` (`Century`) | strong, writes no ISBN |
| every other measured row | — | strong | strong, same record | strong |

Totals, measured books only, in the configuration where the ticket's complaint
lives (**Google only**): baseline medium = Cragside, The Masque of the Red Death;
option 1 medium = The Masque of the Red Death; option 2 medium = The Masque of the
Red Death. On the **shipped order**: no measured undated book is medium under any
option (the dated rows are in the year-sensitivity table and item 2 below).

**What the table says, option by option:**

1. **Option 1 resolves every undated tie except Poe, and Poe is the one D11 already**
   **gave away.** Cragside goes medium → strong in both configurations where it tied.
   Poe stays medium for the reason D11 accepted: `Edgar Allen Poe`
   (`Q8jPsgEACAAJ`) is a different author to a letter-strict key, so it survives as a
   second work 0.0602 behind. **Deterministic on every row**: one outcome in 100
   shuffles, on both source orders, including the two Hardcover rows the baseline
   gets wrong. **No row moves from strong to anything weaker**, in any
   configuration, dated or not.
2. **For a dated file, option 1 swaps a tie for a singleton.** Collapsing a work to
   one candidate makes the pool a pool of one, graded against `singleton_score`
   0.95 rather than `strong_score` 0.89 plus the gap. The survivor scores 1.0000 only
   when the file's year is the earliest edition's: the 2017 Cragside file goes
   strong everywhere, the 2021 and 2019 files stay medium (0.9231) everywhere. The
   frozen Poe case shows the same thing with no other work present:
   `hand-made/poe-core-cases.json` collapses to `du6sYyygMgIC` alone and grades
   **medium** on the singleton bar. No regression, but no fix either, for any
   file whose edition is not the earliest — and how many real files carry a
   `dc:date` that names their edition is not something this corpus can say.
3. **Option 2 is not deterministic, and it wins strong by discarding evidence.** On
   Poe it gives two outcomes in 100 shuffles on the live reply and two on the
   frozen one, because the work's title must be spelt somehow and the group offers
   `The Masque Of The Red Death` (`du6sYyygMgIC`) and `The Masque of the Red Death`.
   Picking a spelling is [CBO-69](https://linear.app/cbow/issue/CBO-69/a-written-title-does-not-carry-the-records-spelling-normalised-match)'s decision, made early. A Google "work" has no date,
   so the year check vanishes: the dated Cragside files all grade **strong** on
   Google only and on the reversed order, and **medium** on the shipped order,
   where Hardcover's work date (`2017-07-07`) is present — **the same file grades**
   **differently by source order**. On the frozen Poe case it grades **strong** and
   writes, which would put [CBO-69](https://linear.app/cbow/issue/CBO-69/a-written-title-does-not-carry-the-records-spelling-normalised-match)'s casing bug onto a default install. It also
   writes no ISBN, publisher, date or cover on every Google match.
4. **Option 3 fails the acceptance criterion as it stands**, on the four rows in the
   determinism table in §0.3, two of which are strong books that get written.

**One sensitivity, not an option.** Preferring the edition whose year is the file's
own `dc:date` year before falling back to the earliest ("option 1b" in the probe)
turns the 2021 Cragside file strong, written from `7kMMzgEACAAJ` (the Ulverscroft
large print) on every configuration that asks Google, the shipped order included —
so it overrides Hardcover, first in the trust order (Hardcover only stays medium:
it has no 2021 edition). The 2019 file and Poe are unchanged. Not
recommended for this ticket: it amends D3, and it leans on `dc:date` meaning the
edition's date, which the one real dated file contradicts (Gutenberg's `2010` is a
production date). It belongs with [CBO-71](https://linear.app/cbow/issue/CBO-71/filename-edition-markers-let-the-user-disambiguate-which-edition-they), where the file tells Colophon which
edition it is.

### 0.5 Can a work-level candidate come from Google alone? (step 3)

**No.** The mask (`googlebooks.py:52`) fetches `items/id`, which is a volume, and no
field in a Google reply relates one volume to another. A Google "work" is a key
Colophon makes up, and the live Poe reply shows what that key has to swallow:
author spellings that are not the same letters (`Edgar Allen Poe`,
`Q8jPsgEACAAJ`; `Edgar Allan Edgar Allan Poe`, `ZIxdnQAACAAJ`), and edition words
inside the title field, where no head/subtitle split can reach them
(`mt6NzgEACAAJ` "…Illustrated Edition", `vnS2vAEACAAJ` "…(Short Story Books)
(Hardcover)", `etykzgEACAAJ` "…by Edgar Allan Poe Annotated", `QxhczgEACAAJ`
"…By "Edgar Poe" Annotated Edition", `FRBJDwAAQBAJ` "…\[diglot\]"). It also has no
work date, which is what makes option 2 lose the year (§0.4 item 3).

**Hardcover already gives the grouping.** `book { id }` is in `TITLE_QUERY`
(`hardcover.py:107`), and `_candidates` groups on it (`:351`, `:365`). On every
Hardcover title fixture the `book.id` groups and the letter-strict key's groups are
**identical** — `by-title-berwick.json` {2379453: editions 0, 1};
`by-title-the-infirmary.json` {1198266: 0, 1, 2; 2284109: 3}; the single-edition
Cragside (1198994) and Belsay (1647114) — printed by the probe's first block. Two
limits on that: `Candidate` does not carry `book.id`, so the grouping is lost the
moment D12 hands every edition to the pool; and it cannot group across sources,
since Google has no id to match. **So D5 stays positive and** [CBO-70](https://linear.app/cbow/issue/CBO-70/review-additional-metadata-providers-open-library-isbndb-worldcat) **is not pulled**
**forward**, but the pooled rule needs the synthesized key whichever option is
chosen. That is the argument for option 1 over option 2: option 1 only has to
*choose* an edition from a group; option 2 has to *invent* a work, and on Google
there is nothing to invent it from.

The risk the corpus cannot measure: two Hardcover works with the same head and the
same author letters (a novel and a same-titled novella, say) are two `book.id`s but
one key. No fixture has one.

### 0.6 Interactions (step 4)

[CBO-69](https://linear.app/cbow/issue/CBO-69/a-written-title-does-not-carry-the-records-spelling-normalised-match) **— does** `du6sYyygMgIC` **survive?**

| Reply | baseline | option 1 | option 2 |
| -- | -- | -- | -- |
| live `by-title-poe.json` | one of ten tied at 0.9231; leader by reply order (`q6T5zQEACAAJ` as recorded) | **does not survive** — `0uZ6IaW21DQC` is earlier | its spelling is the work title whenever it arrives first in the group |
| frozen `hand-made/poe-core-cases.json` | one of five tied | **survives**, alone, medium (singleton, 0.9231) | its spelling is the work title when it arrives first; **strong, written** |

On a default install `du6sYyygMgIC` is **never written** under the baseline or
option 1, because every Poe row is medium and there is no LLM. So [CBO-69](https://linear.app/cbow/issue/CBO-69/a-written-title-does-not-carry-the-records-spelling-normalised-match)'s
reproduction must stay on the frozen file, and its test cannot rely on the title
path writing it: it needs the LLM path or a direct `_write`. That is consistent with
D11 moving Poe to [CBO-69](https://linear.app/cbow/issue/CBO-69/a-written-title-does-not-carry-the-records-spelling-normalised-match). Option 2 is the only option under which [CBO-69](https://linear.app/cbow/issue/CBO-69/a-written-title-does-not-carry-the-records-spelling-normalised-match)'s bug
reaches a no-LLM install.

[CBO-65](https://linear.app/cbow/issue/CBO-65/dedupe-collapses-editions-differing-only-in-series-position-silently) **— dedupe.** The collapse runs before `dedupe`, so after option 1 each work
is one candidate and `dedupe` only ever sees candidates the collapse called
different works. The collapse key has no series position and no year, so [CBO-65](https://linear.app/cbow/issue/CBO-65/dedupe-collapses-editions-differing-only-in-series-position-silently)'s
defect — editions differing only in series position merged — would move out of
`dedupe` and **into the collapse**. The corpus has no case: every Hardcover work's
editions share one series position (it is a work field), and Google carries none.
[CBO-65](https://linear.app/cbow/issue/CBO-65/dedupe-collapses-editions-differing-only-in-series-position-silently) must therefore be scoped against the collapse key, deciding whether series
position is part of a work's identity. D9's order ([CBO-68](https://linear.app/cbow/issue/CBO-68/title-search-returns-editions-not-works-the-medium-band-is-the-normal) merges first) stands.

[CBO-75](https://linear.app/cbow/issue/CBO-75/google-subtitle-is-never-read-and-cbo-58md-claims-it-is) **— the subtitle.** Simulated on the frozen Poe volumes by joining
`subtitle` onto the title: **no change** to grouping or band under any option,
because the file has no subtitle and §3.3 compares heads, and the key uses heads.
Two constraints for whoever fixes [CBO-75](https://linear.app/cbow/issue/CBO-75/google-subtitle-is-never-read-and-cbo-58md-claims-it-is): the collapse key must stay on the head,
or `Annotated`, `Short Story` and `Original Classics and Annotated` split one work
into four; and the fix needs `items/volumeInfo/subtitle` added to the mask and a
re-record, not only a change to `_candidate` (§0.1 item 5).

### 0.7 What this sample can and cannot support

* **Seven books, and two of them are the only popular titles.** Five are one
  author's books in one series; one is a public-domain story; one is a deliberate
  miss. The multi-edition replies are Cragside and Poe on Google, Berwick and
  The Infirmary (Ross) on Hardcover. That is enough to show a mechanism works or
  fails; it is **not** a rate, and no percentage in this section should be read as
  one. [CBO-76](https://linear.app/cbow/issue/CBO-76/build-44s-tuning-set-no-threshold-in-this-design-has-ever-been-tuned)'s tuning set is what a rate needs.
* **One real dated file.** The year-sensitivity rows are synthetic files over real
  replies. They show what the arithmetic does; they cannot say how often a library's
  `dc:date` names the edition, which decides how much option 1 helps in practice.
* **The series signal is never exercised**, because the files are the declared bare
  titles (§0.2).
* **The shipped order cannot be measured for Poe or the miss** without a Hardcover
  reply (§0.9).
* **The options are simulated.** The key, the survivor order and option 2's
  work-date rule are this probe's choices, stated in its docstrings; the build will
  make its own and must re-run the measurement.
* **100 shuffles is evidence, not proof.** The proof of option 1's determinism is
  structural: the survivor is a minimum over a key made of values, never of
  positions.

### 0.8 Recommendation

**Option 1**, as D1–D3 and D11–D13 already decided — the same option session 1
recommended — **with two amendments to the rule and one to the key**, all three
accepted in the session 1b review as D15–D17, each forced
by a measurement above. The rule as it should appear in the design spec ([CBO-33](https://linear.app/cbow/issue/CBO-33/colophon-ebook-metadata-relay-design-spec-v1)):

> **The standard edition (title path).** A title search returns editions, not
> works. Before a pool is ranked, its candidates are grouped by work: two candidates
> are the same work when their titles have the same head, as the scorer normalises
> it, and their authors are the same letters once each name has been through the
> scorer's name normalisation — so `L. J. Ross`, `LJ Ross` and `Ross, L. J.` are one
> author, and `L. K. Ross` or `Edgar Allen Poe` is another. Each work keeps one
> candidate, its standard edition: the one with the **earliest date** (dates compared
> as ISO prefixes; an undated candidate comes last); among equal dates, the one from
> the source **highest in the user's source list**; then the one carrying **more of**
> **the ten payload fields**; and last, the candidates' payloads compared field by
> field, so two survivors can only tie when they would write the same thing. This
> runs on the pooled candidates each time a source's reply joins the pool, before
> `dedupe` and `rank`, so every source hands up every edition and the choice is made
> in one place. A title-path match therefore comes out the same whatever order a
> source lists its reply in. The standard edition is the earliest *listed*
> printing, not the first published one, and nothing Colophon writes or logs may
> call it the first edition.

**Where it differs from session 1, and why:**

1. **The source list decides before completeness.** Session 1 (and D3) had
   completeness straight after the date. The reversed-order 2019 Cragside row shows
   what that does across sources: Hardcover's `2017-07-07` edition and Google's
   `RASDtAEACAAJ` share a date, and completeness picks Hardcover's even though the
   user put Google first. `dedupe` already treats the source list as the trust order
   (first wins), and session 1 §5.3 already warned that completeness lets whichever
   source fills more fields decide. Within one source — Berwick's two Hardcover
   editions — completeness still decides. **This amends D3.** *Accepted as D15.*
2. **The last resort is the payload, not the ISBN.** Session 1 proposed ISBN, then
   title. The Belsay Hardcover edition has no ISBN and `wwLYDwAAQBAJ` only an EAN,
   so an ISBN cannot be the total order. Neither `Candidate` carries an id to use
   (Google's volume id and Hardcover's edition id are not kept). Comparing the
   payload itself is total up to candidates that would write identical files, where
   the choice cannot be observed. This meets D10's third criterion ("a value unique
   per candidate that is actually fetched") in the only way the fetched fields allow.
3. **The key reads names through** `_name` **first.** D11 said letters, not symbols;
   letters alone would make `Ross, L. J.` a different person from `L. J. Ross`.
4. **Session 1 said the collapse changes nothing on the shipped configuration.**
   True for bands; untrue for what gets written (The Infirmary's ISBN changes from
   `9781799729945` to `9781792780844`) and for determinism (Berwick and The
   Infirmary stop varying run to run). The behaviour change is the point, and the PR
   should say so.

`most_complete` stays dropped and `earliest` hard-coded (D13). Scoring weights,
`BAND_GAP` and the thresholds stay as they are; §0.3's 0.0769 and §0.4 item 2's
singleton effect are recorded for [CBO-76](https://linear.app/cbow/issue/CBO-76/build-44s-tuning-set-no-threshold-in-this-design-has-ever-been-tuned), not fixed here.

### 0.9 What the build session must do and test

| Acceptance criterion | What the build does | The test |
| -- | -- | -- |
| The chosen rule is stated in the design spec | Put §0.8's rule text into [CBO-33](https://linear.app/cbow/issue/CBO-33/colophon-ebook-metadata-relay-design-spec-v1), including the "earliest listed, not first published" sentence and the singleton consequence for dated files (§0.4 item 2) | — (review) |
| ~~Medium-band rate measured before and after~~ → [CBO-76](https://linear.app/cbow/issue/CBO-76/build-44s-tuning-set-no-threshold-in-this-design-has-ever-been-tuned) (D10); report per configuration as information | Re-run this probe against the built code; the option-1 column is the expected "after" | — (report in the PR) |
| A default install with no LLM is the case tested | Every new test builds the corrector with `llm=None` | as below |
| A multi-edition reply resolves the same way every run — D10: stable under a shuffled reply, on both source orders | `collapse()` in `matching.py`, called from `_gather` before `dedupe`; `hardcover._candidates` hands up every edition (D12) | Shuffle `googlebooks/by-title-cragside.json`, `hardcover/by-title-berwick.json`, `hardcover/by-title-the-infirmary.json` and `hand-made/poe-core-cases.json`; assert the same band **and the same written ISBN/publisher/date**, with the sources in both orders |
| D10: the total-order fallback is a value actually fetched, not ISBN | Payload comparison as the last key | Synthetic: two candidates equal on date, source and completeness, differing only in cover URL, in both input orders — same survivor |
| D13: the tiebreak is exercised | — | Now recorded, not only synthetic: `by-title-berwick.json` (two editions, both `2026-02-26`) → `9781529978940` wins on completeness |
| D11: the key is strict on letters | `_name` then letters | `L. J. Ross` = `LJ Ross` = `Ross, L. J.`; `L. K. Ross` ≠ `L. J. Ross`; The Infirmary's Ross and Reagon works stay two; live Poe stays **medium** with `Q8jPsgEACAAJ` as the runner-up |
| No strong book regresses (D8, kept as a check) | — | Cragside, Berwick, Belsay and both Infirmary files stay strong on every configuration they are strong on today |
| D15 | Source order before completeness; the source's rank is where its first candidate appears in the pool, never the candidate's own position | Cragside dated 2019, Google first: the pool's leader is `RASDtAEACAAJ`, not Hardcover's edition (the band is medium, so assert on the pool) |

Also for the build: update the `test_hardcover` cases that assert one candidate per
work, which D12 makes false; call out the written-ISBN change for The Infirmary in
the PR; document for users that a file whose `dc:date` is not its work's earliest
edition still grades medium without an LLM (D18). Declare the Hardcover Poe row as
the first commit and stop for Callum to record it (D19). Leave series position out
of the key (D22) and `book.id` off `Candidate` (D23), and put both limits in the
design spec.

The probe's option 1 used D3 as it stood (completeness before source), so on the
reversed order its survivor for the dated Cragside rows is Hardcover's edition;
under D15 it is Google's. The bands are the same either way.

**One live reply is missing, and it only matters for measuring, not for the**
**recommendation:** Hardcover's answer for *The Masque of the Red Death*, without which
Poe's shipped-order row stays unmeasured. `tools/record-fixtures.py` only records
declared rows, so today
`python tools\record-fixtures.py hardcover/by-title-poe.json` stops with
`no declared recording for hardcover/by-title-poe.json`. A row has to be declared
in `tests/recordings.py` first — a test-infrastructure change this session was not
to make. Once it is (the build session's first commit is the natural place), this
is the procedure, one PowerShell command per step, from `A:\Documents\GitHub\colophon`:

1. `git pull`
2. `$env:COLOPHON_HARDCOVER_TOKEN = "paste-the-hardcover-token-here"`
3. `$env:COLOPHON_GOOGLE_BOOKS_KEY = "paste-the-google-key-here"` (the recorder
   refuses to start without both, even for a Hardcover-only row)
4. `python tools\record-fixtures.py --list` — check that a line reads
   `hardcover/by-title-poe.json  Hardcover {"titles": ["The Masque of the Red Death"], "language": "en"}`
5. `python tools\record-fixtures.py hardcover/by-title-poe.json`
6. `python -m unittest -q`
7. `python docs\research-cbo-68-probe.py`

The row to declare, beside the Google Poe row:

```text
    {
        "source": "hardcover",
        "fixture": "by-title-poe.json",
        "lookup": "title",
        "book": POE,
    },
```

---

Session 1 of 3, research only. Branch `dsh/cbo-68-standard-edition-rule` off `main`
at `e5ea994` ([CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk) is still unmerged; §2.1 covers what that means). Nothing
tracked was changed; the probes are
`scratch/cbo68-survey.py`, `cbo68-measure.py`, `cbo68-measure2.py`,
`cbo68-measure3.py` and `cbo68-measure4.py`, all gitignored, and every number
below is computed rather than estimated.

Read with the ticket [CBO-68](<https://linear.app/cbow/issue/CBO-68/title-search-returns-editions-not-works-the-medium-band-is-the-normal>),
its comment *Decisions from grilling, 2026-09-22* (D1–D9, settled and not
reopened here), `docs/research/cbo-58.md` (the design spec behind every §-reference),
and `docs/pr-cbo-59.md`.

**Two corrections to the reading list, before anything else.**

* **There is no** `docs/research-cbo-59.md` **on** `main`**.** The [CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk) research note
  and a session-2 handover are committed on the unmerged branch
  `dsh/cbo-59-pooled-walk` (`git show dsh/cbo-59-pooled-walk:docs/research-cbo-59.md`).
  Its F1–F5 follow-up is the source of this ticket, and F2 is the measurement
  this note's step 2 is asked to be comparable with.
* [CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk) **is unmerged.** `main` has [CBO-58](https://linear.app/cbow/issue/CBO-58/model-the-matcher-on-beets-distance-scoring-and-confidence-grading)'s `rank()` / `dedupe()` / `band_of()`
  but no production caller of any of them: `correction.py:_by_title` still races
  the sources and writes anything at or above `strong_score`. So "the current
  medium-band rate" is not something `main` can be run to produce. Every band
  below is `dedupe` → `rank` → `band_of` over the recorded replies, which is
  [CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk)'s `_gather` transcribed, and that is stated wherever it matters.

## Answers, in the order asked

| \# | Question | Answer |
| -- | -- | -- |
| 1 | Does Hardcover expose a work-level identity? | **Yes —** `books.id` **— and the client already collapses on it.** [CBO-70](https://linear.app/cbow/issue/CBO-70/review-additional-metadata-providers-open-library-isbndb-worldcat) is **not** a blocker. |
| 2 | Baseline medium rate on title-path books | ~~**11% on the shipped source order, 33% if only Google answers.**~~ *Dead: measured before* [CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk) *merged and before* [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re)*'s re-record; re-measured by book in §0.3.* §4.4's tuning set does not exist; the fixture population is 9 rows. |
| 3 | Is D3's rule derivable? | **Yes on Google** (dates on every multi-edition reply, earliest never tied). ~~**Unproven on Hardcover** (0/8 recorded editions carry a date)~~ *Dead: 13 of 13 Hardcover title editions are dated since* [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re) *(foot of this note)* and not yet deterministic there (no `order_by`). |
| 4 | Projected effect of D2 | **Nil on the shipped configuration.** It fixes the two Cragside rows on the Google-only path and **leaves the Poe fixture medium** — the one book the ticket exists for — unless the collapse key tolerates Google's own author spellings. *(Still true on the live reply, for the reason D11 accepted: §0.4.)* No strong→weaker regression in any variant. |
| 5 | Is `most_complete` worth a config key? | **No. Hard-code** `earliest`**.** As a primary it ties where a date does not. |
| 6 | D6: where does edition wording live? | Hardcover: separate edition fields, already ignored. Google: a `subtitle` field Colophon **drops**, and the title on 3 of 10 Poe volumes. **The filename is read by nothing that scores** — D6's premise as written is false. |

---

## 1. Does Hardcover expose a work-level identity? Yes

`docs/research/hardcover-api.md` already records the schema split — `books` is the
work, `editions` is the printing, ISBNs live on `editions` and the work is reached
at `editions[].book` — and the fixtures carry it: **every edition in every one of**
**the four non-empty** `hardcover/by-title-*.json` **recordings has** `book.id`**.**

| Fixture | Editions | Distinct `book.id` | Candidates `_candidates()` returns |
| -- | -- | -- | -- |
| `by-title-cragside.json` | 1 | 1198994 | 1 |
| `by-title-berwick.json` | 2 | 2379453 | **1** |
| `by-title-belsay.json` | 1 | 1647114 | 1 |
| `by-title-the-infirmary.json` | 4 | 1198266, 2284109 | **2** |
| `by-title-cragside-other-fields.json` | 1 | 1198994 | 1 |

**The collapse is not merely available on the Hardcover side; it is shipped.**
`hardcover.py:_candidates` groups the reply by `book.id` and keeps one edition per
work, with a docstring saying exactly why ("a second edition would only offer the
same book twice"). Berwick's two printings become one candidate, and The
Infirmary's four editions become two — the two *works* that share the title, which
is the distinction [CBO-36](https://linear.app/cbow/issue/CBO-36/03-title-cleaning-and-titleauthor-matching) exists to draw.

So D5 comes back **positive**, and [CBO-70](https://linear.app/cbow/issue/CBO-70/review-additional-metadata-providers-open-library-isbndb-worldcat) is not pulled forward. The rest of this
note is about the Google side for the plain reason that **Hardcover is not the**
**source that produces the medium band: its reply is already one candidate per**
**work.**

**What is not free, and is this ticket's actual work on the Hardcover side.**

1. **The rule is arrival order, not D3.** `_candidates` keeps the *first* edition
   of each work. The surviving edition supplies the ISBN, the publisher, the cover
   and the date, so which of Berwick's two printings wins decides what gets
   written. The Infirmary's three L.J. Ross editions carry ISBNs
   `9781799729945`, `9781912310111` and `9781792780844`, and the reply picks the
   first with no reason recorded.
2. **There is no** `order_by` **on** `editions` **in the title query**, so "first" is not
   even a stated order: Hasura's row order with no sort is not a guarantee across
   requests. **This is a live determinism defect on the path the ticket's**
   **acceptance criterion names** ("a multi-edition reply for a popular title
   resolves the same way every run"), independent of anything Google does.
3. ~~**The committed title recordings carry no**~~ `~~release_date~~` ~~**at all** — 0 of 8~~
   ~~editions.~~ *Dead: 13 of 13 since* [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re)*'s re-record (foot of this note).* They predate [CBO-38](https://linear.app/cbow/issue/CBO-38/05-configurable-field-rules-and-covers)'s widening of the query, and only the widened
   `by-title-cragside-other-fields.json` has one (1/1, `2017-07-07`). The field is
   in the shipped query and in the schema (`editions.release_date`, a nullable
   `date`, plus `release_year` as a nullable `Int`), so this is a recording-era
   gap rather than a source gap — but **no committed fixture proves Hardcover**
   **populates it**, and D3's primary key for Hardcover therefore rests on an
   unverified assumption (§3).

## 2. Baseline: what fraction of title-path books grade medium

### 2.1 The population, and what "§4.4's tuning set" is

**§4.4's tuning set does not exist.** `docs/research/cbo-59.md` says so outright
("re-run §4.4's tuning set, which does not exist yet"), and nothing in the repo
contradicts it: there is no committed or gitignored labelled set of real books with
the identifiers of the record that *is* the same book from each source. §4.4 step 1
asks for 20–50 such books, step 1a for the pool size per book, and neither has been
built. **Steps 2, 3 and 6 cannot be run, so no threshold in this design has ever**
**been tuned.**

What exists instead is the fixture population: every recorded `by-title-*` reply
paired with the file book it was recorded for — **9 rows over 8 distinct file**
**fixtures**. Cragside is one file recorded twice (before and after [CBO-38](https://linear.app/cbow/issue/CBO-38/05-configurable-field-rules-and-covers) widened
the query) plus a no-author variant, and two rows are single-source because only
one source has a recording for that book. Both facts are limitations of the
population, not choices.

Method, so the numbers can be re-run: `FileBook` from a real sample book read by
`epub.read`, candidates from the real `Hardcover`/`GoogleBooks` parsing functions
over the real recordings, pooled in the shipped `sources` order
(`("hardcover", "google_books")`, `config.py:27`), `dedupe`d, `rank`ed,
`band_of`ed, with [CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk)'s early exit on a strong pool. No LLM: a default install
with no key is the case D7 names, and on that install every non-strong band is
`colophon:unverified`.

### 2.2 The band distribution, in F2's shape

F2's shape is an exclusive-category table with counts and a total. The same shape,
for the fixture population, under three source configurations:

| Configuration | strong | medium | low | none | total | **medium** |
| -- | -- | -- | -- | -- | -- | -- |
| ~~both sources, shipped order~~ | ~~6~~ | ~~**1**~~ | ~~1~~ | ~~1~~ | ~~9~~ | ~~**11%**~~ |
| `~~hardcover~~`~~ only~~ | ~~5~~ | ~~**0**~~ | ~~1~~ | ~~3~~ | ~~9~~ | ~~**0%**~~ |
| `~~google_books~~`~~ only~~ | ~~3~~ | ~~**3**~~ | ~~2~~ | ~~1~~ | ~~9~~ | ~~**33%**~~ |

*Dead, with the per-book table below: measured against pre-*[CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re) *fixtures and a*
*hand-transcribed walk (§2.1's "no production caller of* `rank()`*" stopped being true*
*when* [CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk) *merged). Berwick is now strong on every configuration, The Infirmary*
*(Carly Reagon) has a Hardcover reply after all, and Holy Island and Cragside (no*
*author) had no recording for their own request. Re-measured by book in §0.3.*

The per-book rows, which are the ones that carry information:

| Book | both | `hardcover` only | `google_books` only |
| -- | -- | -- | -- |
| Cragside (no ISBN) | strong (pool 1) | strong (1) | **medium** (2) |
| Cragside (widened recording) | strong (1) | strong (1) | **medium** (2) |
| Belsay | strong (1) | strong (1) | strong (1) |
| Berwick | strong (1) | strong (1) | low (1) |
| The Infirmary (L.J. Ross) | strong (2) | strong (2) | strong (1) |
| The Infirmary (Carly Reagon) | strong (1) | none (no recording) | strong (1) |
| Holy Island | none (0) | none (0) | none (0) |
| The Masque of the Red Death | **medium (10)** | none (no recording) | **medium (10)** |
| Cragside (no author) | low (2) | low (1) | low (1) |

~~**The headline is that the shipped configuration is already at 11%, under the 20%**~~
~~**bar, and the collapse would not move it.**~~ *(Dead figure; the structural point*
*below survives and is re-confirmed in §0.3.)* The reason is structural and worth
stating plainly: Hardcover is asked first, its exact-title query returns works
rather than printings, and one work from one title is a singleton pool that clears
`singleton_score` on an exact title and author — so the walk **exits early and**
**Google's multi-edition reply is never read**. Of the nine rows, only the Poe
fixture reaches the state the ticket describes, and only because Hardcover has no
Poe recording.

That makes the rate a function of which sources are configured, not a single
number, and the ~~33%~~ Google-only rate is the one that matches the ticket's
complaint. Two of its three medium rows are Cragside (two printings of one work,
both scoring 1.0000, gap 0.0000), and the third is Poe ~~(ten volumes, five tied at~~
~~0.9231, gap 0.0000)~~ *(live reply: twenty volumes, ten tied at 0.9231 — §0.3)*.

### 2.3 The second basis: F2's own 1071-row sweep, in F2's shape

Comparability with F2 needs F2's basis: 17 title similarities × 7 author
similarities × 3 series states × 3 year states = **1071 rows, 500 distinct**
**scores** — reproduced here exactly, including F2's corrected count of **70**
distinct scores in `[0.89, 0.95)`.

| Band | Rows | Share | Distinct scores |
| -- | -- | -- | -- |
| strong | 58 | 5.4% | 29 |
| medium | 292 | 27.3% | 208 |
| low | 709 | 66.2% | 262 |
| none | 12 | 1.1% | 1 |
| **total** | **1071** |  | **500** |

**This is a field-state distribution, not a book rate**, and the two must not be
averaged together or read as one. The fixture table says what a library does; this
one says what the scorer can reach. The 27.3% here is not "27% of a library grades
medium" — it is 27% of a synthetic enumeration of field states, weighted by a
ladder chosen for coverage rather than for frequency. What it does establish is
that the medium band is **densely populated on purpose** (208 distinct scores), so
a medium outcome cannot be dismissed as a rare edge.

## 3. Is the D3 rule derivable?

D3: the standard edition is the **earliest publication date of the work**,
tiebroken on **payload completeness**. Two questions: is a usable date present on
every candidate in a multi-edition reply, and is "payload completeness" defined
tightly enough to score.

### 3.1 The date, per source

| Source | Recordings | Candidates with a four-digit year |
| -- | -- | -- |
| `~~google_books~~` | ~~18 volumes across the 7 non-empty ~~`~~by-title-*~~`~~ recordings~~ | ~~**17 (94%)**~~ |
| `~~hardcover~~` | ~~8 editions across 4 pre-~~[CBO-38](https://linear.app/cbow/issue/CBO-38/05-configurable-field-rules-and-covers) ~~title recordings~~ | ~~**0**~~ *dead: 13 of 13 since* [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re) |
| `hardcover` | 1 edition, the widened recording | **1** |

**Google: derivable, and stronger than the average suggests.** The one undated
volume is the single Berwick volume — a reply with nothing to choose between, so
the rule has no decision to make there. **Every multi-edition Google reply in the**
**fixtures is 100% dated** (Cragside 2/2, Cragside widened 2/2, ~~Poe 10/10~~), and on
those the rule is decided by its primary key alone: Cragside `2021-03` against
`2017-07-07`; ~~Poe ten distinct dates from ~~`~~2013-01-29~~`~~ to ~~`~~2021-09-02~~`. ~~**The**~~
~~**tiebreak never fires on any recorded reply.**~~ *Dead:* `hardcover/by-title-berwick.json`
*now has two editions dated* `2026-02-26`*, and the tiebreak decides it (§0.9).* Partial dates are the norm rather
than the exception (`2021-03`, `2019-02`, `2026-01-22`), and they order correctly
by plain string comparison while the forms are ISO-8601 prefixes — no parsing, no
dependency.

~~**Hardcover: unproven.**~~ *(Dead: populated on 13 of 13 editions since* [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re)*.)* The schema has the field (`editions.release_date` is a
nullable `date`; `editions.release_year` a nullable `Int`; `books.release_date`
exists too, and `_candidate` already falls back to the work's), and the shipped
query asks for it. But **no committed recording shows it populated**, and this
session had no token, so it could not be recorded. Two consequences, and neither is
hypothetical:

* If Hardcover's editions carry no date in practice, D3's primary key **degenerates**
  **to its tiebreak for Hardcover**, and the tiebreak ties: The Infirmary's three
  L.J. Ross editions are identical on every payload field except the ISBN, so
  completeness is equal and the choice falls back to arrival order — which is the
  current behaviour, and not deterministic (§1.2).
* Even with dates, they are the *edition's* date, which is what the field means in
  the schema and what `_candidate` already prefers.

**One limitation of "earliest" that must be recorded rather than discovered later:**
**earliest *listed* is not first *published*.** Poe's earliest candidate is a 2013
Harper Collins reprint; the story is from 1842 and the Gutenberg file says 2010.
For any public-domain or long-reprinted work every candidate is a modern printing,
so the rule picks the oldest surviving listing. That is still deterministic and
still a defensible "standard edition", but it is not the first edition and the
diagnostic wording must not claim it is.

### 3.2 "Payload completeness" scores over these fields

The concrete set, taken from what Colophon can write rather than from the
`Candidate` dataclass, because `Candidate` also carries fields that are **not**
payload:

`FIELD_DEFAULTS`**' nine (**`config.py:67`**) plus the cover:**

`title`, `authors`, `series`, `series_number`, `description`, `publisher`,
`date`, `isbn`, `language`, and `cover`.

Deliberately excluded, and the reason is that they are identity or provenance
rather than something written: `source` (which source offered it), `author_ids`
and `series_id` ([CBO-41](https://linear.app/cbow/issue/CBO-41/08-colophons-own-record-and-name-standard)'s names for the same people, never written), and `genres`
(written only through [CBO-42](https://linear.app/cbow/issue/CBO-42/09-genre-mapping)'s mapping and its own setting, so counting them would
let an unmapped tag list decide which edition is standard). Nine of the ten are
greppable to `FIELD_DEFAULTS`; the cover is its own setting
(`config.py`'s `cover` rule) and is included because it is the one payload field
the file visibly gains.

### 3.3 Determinism: where it holds and where it does not

| Question | Answer |
| -- | -- |
| Is the earliest date ever tied, on a recorded reply? | ~~**Never.**~~ Cragside's pair and Poe's five-member group all have distinct dates. *Now yes: Berwick's two Hardcover editions share* `2026-02-26`*.* |
| Would `earliest` resolve a shuffled reply the same way? | **Yes on Google**, because the sort key is a value rather than a position — provided the final fallback is a total order on the candidate, which needs stating (see below). |
| Would it on Hardcover today? | **No.** The reply is unordered ~~and the date is absent from every recording~~, so the answer is the reply's order. *Measured in §0.3: Berwick 2 and The Infirmary (Ross) 3 distinct outcomes in 100 shuffles.* |

Two gaps the rule needs closed when it is built, both small:

1. **A total-order fallback.** `sorted` is stable, so two candidates tied on date
   *and* completeness keep input order — deterministic for one reply, but not
   across two replies that list the same editions differently. The honest fallback
   is a value that is already unique per candidate (the ISBN, then the normalised
   title, then the source's own edition key if [CBO-70](https://linear.app/cbow/issue/CBO-70/review-additional-metadata-providers-open-library-isbndb-worldcat) gives one).
2. **Hardcover's** `order_by`**.** Adding `order_by: {release_date: asc}` to the title
   query's `editions`, or routing Hardcover's per-work collapse through the same
   rule, is what makes the Hardcover side obey D3 instead of arrival order. **It**
   **changes which edition's ISBN, publisher and cover get written**, so it is a
   behaviour change and not a tidy-up.

## 4. Projected effect of D2, estimated against the fixtures

Four collapse variants, same population, same source order. "Head" is the
candidate's title before its colon; "exact author" is `_name`'s normalised key;
"file-author gate" admits a candidate to a work group only when its author reaches
`AUTHOR_AGREES` against the **file's** author, the same floor `score_candidate`
gates on.

| Collapse | both sources | `google_books` only |
| -- | -- | -- |
| ~~none (~~[CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk) ~~as shipped)~~ | ~~strong 6, medium 1, low 1, none 1 — **11%**~~ | ~~strong 3, medium 3, low 2, none 1 — **33%**~~ |
| ~~head + exact author~~ | ~~strong 6, medium 1, low 1, none 1 — **11%**~~ | ~~strong 5, medium 1, low 2, none 1 — **11%**~~ |
| ~~whole title + exact author~~ | ~~same as head + exact author~~ | ~~same as head + exact author~~ |
| ~~head + file-author gate~~ | ~~strong 7, medium 0, low 1, none 1 — **0%**~~ | ~~strong 6, medium 0, low 2, none 1 — **0%**~~ |

*Dead: the same population and walk as §2.2. Re-measured by book, per option, in*
*§0.4; the file-author gate was overruled by D11 and is not re-measured.*

**No variant moves any book from strong to a weaker band**, on either
configuration. D8's second half is met.

**And on the shipped configuration the collapse changes nothing at all.** That is
not a modelling artefact: the three rows it can reach are either already strong,
because Hardcover answered first and exited before Google's reply was read, or
missing a Hardcover recording entirely and left exactly where they were. The two it
does fix are the two Cragside recordings on the Google-only path. ~~**The projected**~~
~~**effect is 3 books out of 9 in the most favourable configuration, and 0 out of 9 in**~~
~~**the shipped one.**~~

**The Poe fixture is the finding, and it survives the obvious fix.** ~~Collapsing its~~
~~ten volumes by head and exact author gives six~~, and the band stays **medium**
*(live reply: twenty volumes collapse to eleven, still medium — §0.4)*:

| After collapse | Score | Why |
| -- | -- | -- |
| ~~leader: ~~`~~The Masque Of The Red Death~~`~~, 2013-01-29~~ | ~~0.9231~~ | ~~earliest of the five-member group; year disagrees with the file's 2010~~ |
| ~~runner-up: ~~`~~The Masque of the Red Death~~`~~, 2015-05-30~~ | ~~0.8629~~ | ~~Google spells its author ~~`~~Edgar Allen Poe~~`~~, so this is a *separate work* to the key, and its author similarity is 0.8533~~ |
| ~~gap~~ | ~~**0.0602**~~ | ~~strong needs 0.08; every other work must score ≤ 0.8431~~ |

*Dead: computed on the ten-volume reply. On the live reply the leader is*
`0uZ6IaW21DQC` *(2008-10-02), not* `du6sYyygMgIC`*; the gap happens to be 0.0602 again,*
*for the same arithmetic on different volumes (§0.1 item 3).*

The collapse cannot reach the tie it was aimed at, because **the work key's author**
**component splits one work in two over a spelling Google itself disagrees with**: the
~~ten volumes carry ~~`~~Edgar Allan Poe~~`~~ (seven), ~~`~~Edgar Allan Edgar Allan Poe~~`~~ (one)~~
~~and ~~`~~Edgar Allen Poe~~`~~ (one). Merge those three spellings and the pool is four~~
~~candidates, the gap is **0.3254**, and the band is **strong**.~~ *(Dead: ten-volume*
*reply. D11 has since refused the merge.)*

So the choice of author key is not a detail; it is the difference between D2
working and D2 not working on the only fixture that motivated the ticket:

| Author in the key | Poe | Risk |
| -- | -- | -- |
| exact (`_name` equality) | **medium** — gap ~~0.0602~~ | none beyond this failure |
| fuzzy (`AUTHOR_AGREES`, 0.5) | **strong** | inherits §6 item 3's sharp edge: `L. J. Ross` / `L. K. Ross` score 0.6814 and would merge two different people's books into one work |
| the file's author as the gate | **strong** | couples the collapse to the file; can never merge two works whose authors disagree with the file |

**A head with no author at all is the one variant that must be refused**, and the
fixtures show why. The Infirmary's four Hardcover editions are two books — L.J.
Ross's and Carly Reagon's — and a head-only key merges them. Measured on the
Reagon file: head + author gives `strong` (1.0000 against Reagon, 0.7000 against
Ross, gap 0.3); head only gives `low`, because the single surviving work is
chosen by completeness, which Ross's edition wins, so the file is offered a
different author's book with no runner-up left to catch it.

**What this means for the estimate, stated as a limit.** Nine rows over eight file
fixtures is not a library. Two of the three medium rows in the Google-only
configuration are the same book recorded twice, so the true denominator of "popular
titles that tie" here is **one**. The projection is directional: the collapse is
free (no regressions), it is nearly a no-op where Hardcover answers, and whether it
achieves D2's stated goal ("popular titles grade strong") depends entirely on a key
decision this session cannot make from 9 rows.

## 5. Is `most_complete` worth a config key?

**No. Hard-code** `earliest` **and do not ship the key.** D4's own instruction covers
this ("if session 1 finds nobody would set `most_complete`, drop the key and
hard-code the rule"), and there are three reasons, in order of weight:

1. **As a primary it reintroduces the tie it exists to break.** A publication date
   is nearly unique per work; payload completeness is a small integer with a heavy
   floor, so editions of one work cluster on it. Measured on the Poe group:
   completeness `[7, 9, 8, 9, 6]` — **two candidates share the maximum 9**, where the
   dates `[2020-10-06, 2021-09-02, 2020-03-19, 2013-01-29, 2021-03-09]` share
   nothing. `most_complete` therefore needs the date as its own tiebreak, which is
   `earliest` with the arguments swapped and a worse first key.
2. **As a tiebreak it never fires.** Every multi-edition reply in the fixtures has
   distinct dates, so the second half of D3's rule is dead code on the only evidence
   available. A key whose second value exercises a branch that cannot be reached
   cannot be evaluated by a user either.
3. **It is the same class of choice D3 already rejected.** "Most popular by
   ratings/count" was rejected because the signal is unstable and breaks
   determinism. "Most payload" is more stable but it is not stable *between*
   *sources*: ~~across the 18 recorded Google volumes, ~~`~~publisher~~`~~ is absent on **10**~~
   ~~and ~~`~~imageLinks~~`~~ on **6**~~ *(pre-*[CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re) *corpus; not re-counted)*, while a Hardcover edition carries both — so a
   `most_complete` pool prefers whichever source happens to fill more fields, which
   makes a source's completeness decide a match, the thing §4.4 and the "source
   priority carries no weight in the score" principle both refuse.

[CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk)'s review found `singleton_score`, `medium_score` and `llm_full_scan` parsed
and read by nothing. A `standard_edition` key with a second value nobody sets, on a
branch the fixtures never reach, is the same defect written deliberately.

## 6. D6: where edition wording actually lives

### 6.1 Hardcover puts it in separate fields, and Colophon already ignores it

`editions` has its own `title`, `subtitle`, `edition_information` and
`edition_format` (documented, the last two not queried), and the work has
`books.title`. `hardcover.py:_candidate` prefers the work's title and only falls
back to the edition's, so edition wording never reaches `Candidate.title`. The
fixture shows both spellings side by side under one work:

```
work 1198266  books.title = 'The Infirmary'
              editions.title = 'The Infirmary'                     (isbn 9781799729945)
              editions.title = 'The Infirmary: A DCI Ryan Mystery'  (isbn 9781912310111)
              editions.title = 'The Infirmary: A DCI Ryan Mystery'  (isbn 9781792780844)
```

That is precisely what makes the Hardcover collapse work: the edition wording is
where the collapse can see it and the scorer cannot.

### 6.2 Google puts it in a `subtitle` field Colophon drops, and in the title often enough to matter

`volumeInfo.subtitle` is a separate field on ~~**8 of the 18** recorded volumes~~
*(dead: 0 of 26 since* [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re)*, because the mask does not ask for it — §0.1 item 5)*, and
`googlebooks._candidate` **never reads it** — `title=_text(info.get("title"))`.
That is worth flagging beyond this ticket: `cbo-58.md:1100` records
"`googlebooks._candidate()` **joins title and subtitle**" as one of the changes
[CBO-58](https://linear.app/cbow/issue/CBO-58/model-the-matcher-on-beets-distance-scoring-and-confidence-grading) makes outside the matcher. It does not join them, and the docstring at
`googlebooks.py:255` says the opposite ("The subtitle is left off the title"). So a
Google candidate is scored on a head the source may never have used as the whole
title, and the difference is exactly the case §3.3's "one form per side" rule was
written for.

Google also puts edition wording **in the title** for ~~3 of the 10~~ Poe volumes
*(live reply: five of twenty, §0.5)* —
`The Masque of the Red Death by Edgar Allan Poe Annotated`,
`The Masque of The Red Death Illustrated Edition`,
`The Masque of the Red Death (Short Story Books) (Hardcover)` — and varies the
casing on a fourth. So it is not "neither": for Google it is **both, and mostly the**
**field Colophon ignores**.

### 6.3 The filename is read by nothing that scores

**D6's premise — "edition words in a filename already ride in the title distance" —**
**is false as the code stands.** `epub.read` takes the title from the OPF
(`epub.py:184`, `_first_text(metadata, "title")`) with no filename fallback, and
`score_candidate` reads only `FileBook.title`. `path.name` has exactly two kinds of
consumer and neither scores: the LLM prompt (`correction.py:645` → `llm.py:341`,
`Filename:`), and log lines (`correction.py` ×3, `relay.py`). Measured: holding the
title at `Cragside` and changing the filename from `Cragside.epub` to
`Cragside (Large Print).epub` to `Cragside - Ulverscroft Large Print Edition.epub`
gives an identical leader (`1.0000`) and an identical band.

**What does ride in the title distance is edition wording in the file's**
`dc:title`, and the measurement is less flattering than "a small distance
penalty", because the query is affected first:

| File `dc:title` | Asked about | Leader | Band | What happened |
| -- | -- | -- | -- | -- |
| `Cragside` | `Cragside` | 1.0000 | medium | the baseline |
| `Cragside (Large Print)` | `Cragside (Large Print)` | **0.5508** | low | the bracket is not a series bracket (`_SERIES_BRACKET` needs `Book`/`Vol`), so it stays in the search string, is sent literally to both sources, and the marker is then scored against the record's bare title |
| `Cragside [Large Print]` | `Cragside [Large Print]` | **0.5508** | low | same, and the brackets are not even stripped for the query |
| `Cragside - Large Print` | `Cragside - Large Print` | **0.5508** | low | same |
| `Cragside: Large Print Edition` | `Cragside: Large Print Edition` | **1.0000** | medium | the colon makes it a subtitle; no candidate carries one, so §3.3 compares **heads** and the marker is invisible to the score |
| `Cragside (Ulverscroft Large Print)` | `Cragside (Ulverscroft Large Print)` | 0.4667 | low | same as the bracket form |

Two failure modes, and the second is the one to document:

* **The bracket form is scored and costs real evidence** (1.0000 → 0.5508), but it
  fails earlier than that: both sources filter literally (`books.title: {_in: …}`
  on Hardcover, `intitle:"…"` on Google), so a marker the source does not spell is
  a **query that returns nothing**, and the book is graded with an empty pool. The
  score above is what a pool that did come back would be worth.
* **The colon form is silently ignored by the scorer** (1.0000, because the head
  is compared) and still sent literally, so it fails at the query with no signal
  anywhere that the marker was the reason.

**And the D3 rule points the opposite way from a filename marker.** A user whose
file says *Large Print* is asking for the Ulverscroft printing
(`2021-03`, `Ulverscroft Special Collection`); `earliest` selects the original
(`2017-07-07`). Recorded in the fixture: for `Cragside` the leader is the
`Independently Published` 2017 record, not the large print. D6 asks for the filename
case to be **documented rather than built**, and this is the thing to document: the
standard-edition rule is deliberately indifferent to the user's request, and [CBO-71](https://linear.app/cbow/issue/CBO-71/filename-edition-markers-let-the-user-disambiguate-which-edition-they)
is where the two would have to be reconciled.

## 7. The pass bar (D8)

**D8's 20% is met before the change and cannot distinguish the change from doing**
**nothing**, on the fixtures, in the shipped configuration:

* ~~shipped order: **11% medium** before, **11%** after any collapse variant;~~
* `~~google_books~~`~~ only: **33%** before, **11%** (exact-author key) or **0%**~~
  ~~(file-author-gated key) after.~~

*Dead figures (§2.2). D10 has since replaced the rate bar with determinism; §0.3*
*and §0.4 report by book.*

So the bar is **trivially met** in the configuration that is supposed to be the
problem case, and **not met** in the one where the ticket's complaint actually
lives. Both halves are true at once because the medium rate is a function of
whether Hardcover answers first; the number needs a stated population before it can
be a pass bar. **Per D8 this is brought back rather than retargeted: no number is**
**changed in this note.**

Two further things the bar cannot currently be evaluated against, both already
stated: §4.4's tuning set does not exist, and the Google-only configuration has
**one** distinct popular title behind its three medium rows.

---

## Decisions taken in this session (routine, for review)

| \# | Call | Why |
| -- | -- | -- |
| 1 | Branch `dsh/cbo-68-standard-edition-rule` off `main` at `e5ea994`, `--no-track` | The standing rule; Linear's suggested name is longer and the shorter one is the convention. |
| 2 | Read `docs/research-cbo-59.md` from `dsh/cbo-59-pooled-walk` via `git show` into `.tmp/` rather than switching branches | The note is not on `main`, and the deliverable is one file on a branch off `main`. |
| 3 | Present bands from `dedupe`/`rank`/`band_of` with [CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk)'s `_gather` transcribed, not from running `correction.py` | `main` has no band caller, so there is no other way to state a current band. |
| 4 | Group D6's file-title forms under "bracket", "colon", "dash" rather than listing every variant | They are three behaviours, not six, and the table shows which is which. |
| 5 | Reuse F2's 1071-row basis verbatim, including its 70-value window count | Comparability was the instruction, and the basis reproduces exactly. |
| 6 | Report the field-state sweep and the fixture population as two separate tables that are never averaged | One is a reachability enumeration, the other is a book rate; averaging them would be a fabricated number. |
| 7 | Sketch three collapse keys and one refused variant (§4) | D2's effect is not estimable without naming a key, and the key turns out to decide the answer. |
| 8 | Take the ISBN path as out of scope without deciding anything | The ticket settles it: an ISBN identifies one edition, so the question does not arise. |
| 9 | Probes in `scratch/cbo68-*.py`, gitignored, no engine of their own beyond `matching`'s pure functions | `scratch/` is excluded and [CBO-58](https://linear.app/cbow/issue/CBO-58/model-the-matcher-on-beets-distance-scoring-and-confidence-grading)/[CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk) set the precedent; the numbers stay re-runnable. |

## What I need decided

1. **D8's population.** "Title-path books" is two different rates — 11% (shipped
   order) and 33% (Google only). Which one is the bar about? *This is the revision*
   *D8 explicitly invites, and it is the only number I am not changing myself.*
2. **§4.4's tuning set does not exist, and this ticket's headline measurement**
   **depends on it.** Nine fixture rows over eight file fixtures cannot support a
   rate. Do we build the labelled set first (blocking session 2), or ship the rule
   and record the limitation? My recommendation is to build it, because D8's bar and
   D4's key decision both want it and neither can be judged without it.
3. **The collapse key's author component.** Exact (Poe stays medium), fuzzy at
   `AUTHOR_AGREES` (Poe strong, but merges `L. J. Ross` with `L. K. Ross`), or gated
   on the file's own author (Poe strong, no cross-author merging). **I recommend**
   **the third**, and the head-only variant must not ship. This is a behaviour
   decision with a false-accept edge, so it is yours rather than mine.
4. **Hardcover's dates.** The committed title recordings carry none, so D3's
   primary key for Hardcover is unverified and, if the field really is empty,
   degenerates to a tiebreak that ties. Confirming it needs a live title recording
   with the widened query (a token — I had none). Confirm, or accept arrival order
   on the Hardcover side and say so.
5. **Hardcover's missing** `order_by`**.** Adding one to the title query (or routing
   `_candidates` through the D3 rule) is what makes the Hardcover side
   deterministic, and it changes which edition's ISBN/publisher/cover is written.
   In session 2, or a follow-up?
6. **D6's premise is false as written.** The filename rides in nothing but the LLM
   prompt. Does session 2 document *that* (with the `dc:title` bracket/colon
   findings above), or does D6 get restated first?

## Recommendation for session 2's scope

**Build the rule, and treat the measurement as the session's other half.**

1. `collapse(candidates, file_book)` **in** `matching.py`, pure like everything
   else there: group candidates by the work, choose the standard edition, and run
   it **before** `dedupe` and `rank` (D2). Key: the title head plus the file-author
   gate; survivor: earliest ISO date, then payload completeness over the ten fields
   in §3.2, then a total-order fallback that does not depend on reply order.
2. **Hard-code** `earliest`**. No new config key** (§5). Add nothing to
   `config.example.toml` that a user cannot reach.
3. **Close the Hardcover determinism hole** (§1.2, §3.3) — an `order_by` on the
   title query's editions, or the same rule applied to Hardcover's per-work
   collapse. Pending decision 5.
4. **The acceptance test the ticket names**: a multi-edition reply resolves the same
   way every run, tested by shuffling the recorded reply and asserting the same
   survivor, the same pool and the same band. That test is what pins D2's ordering
   and is worth more than any of the unit cases.
5. **Re-measure and report the before/after medium rate on the fixture population,**
   **per source configuration**, because §7 shows the aggregate number is the wrong
   instrument.
6. **Document the D6 findings** (§6) wherever the edition-marker behaviour belongs —
   at minimum: the filename is read by the LLM only, a bracket marker reaches the
   query verbatim, and a colon marker is invisible to the score. Building the
   grammar stays [CBO-71](https://linear.app/cbow/issue/CBO-71/filename-edition-markers-let-the-user-disambiguate-which-edition-they)'s.
7. **Do not touch the scoring weights,** `BAND_GAP` **or the thresholds.** §4's estimate
   holds weights fixed, and F2's follow-up already covers why moving them is a
   re-derivation rather than a config edit.

## Session 2: the Hardcover numbers, re-taken (2026-09-23, [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re))

[CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re) re-recorded every source fixture against the shipped queries, so the
fixtures this note measured are gone. What follows is measured against the
replacement. Two things this note said are now known to be wrong, and both are
corrected here rather than in the body: it is a record of what was measured on
2026-09-22.

### §3.1 and decision 4: Hardcover's dates are populated

**13 of 13 Hardcover title-path editions are dated**, and every Hardcover fixture
in the corpus is dated 1/1. §3's table row for Hardcover ("8 editions across 4
pre-[CBO-38](https://linear.app/cbow/issue/CBO-38/05-configurable-field-rules-and-covers) title recordings — **0**") and §3.1's "Hardcover: unproven" are both
superseded: the 0 was a recording-era gap, exactly as §1.3 suspected, and the
field is populated.

| Fixture | Editions | Dated | Dates |
| -- | -- | -- | -- |
| `by-title-cragside.json` | 1 | 1 | `2017-07-07` |
| `by-title-cragside-other-fields.json` | 1 | 1 | `2017-07-07` |
| `by-title-berwick.json` | 2 | 2 | `2026-02-26` (both) |
| `by-title-belsay.json` | 1 | 1 | `2025-01-31` |
| `by-title-the-infirmary.json` | 4 | 4 | `2019-02-10`, `2019-02-10`, `2019-01-01`, `2025-10-09` |
| `by-title-the-infirmary-other-fields.json` | 4 | 4 | the same four |

[CBO-68](https://linear.app/cbow/issue/CBO-68/title-search-returns-editions-not-works-the-medium-band-is-the-normal)**'s decision 4 is answered in the affirmative**: Hardcover populates
`release_date` on title replies, so D3's primary key is not degenerate on
Hardcover and the Infirmary's three L.J. Ross editions can be ordered by it.

One thing the re-record makes visible that the old fixtures could not: **the**
**Infirmary's four editions are two works, not one.** The reply carries two distinct
`book.id`s — work 1198266 for the three L.J. Ross editions and work 2284109 for
the fourth — which is the collapse §1 and [CBO-65](https://linear.app/cbow/issue/CBO-65/dedupe-collapses-editions-differing-only-in-series-position-silently) describe, now shown by the
fixture as well as argued from it.

**A caveat on the tiebreak.** §3.1's first consequence ("if Hardcover's editions
carry no date in practice, D3's primary key degenerates to its tiebreak") no
longer holds, but the tiebreak is not idle either: `by-title-berwick.json`'s two
editions carry the **same** date, `2026-02-26`. Two editions of one work agreeing
on the date is the case the tiebreak exists for, and it is now visible in a
committed fixture.

### The band distribution: §2.2's table no longer stands, and the reason is not the fixtures

§2.2's numbers cannot be re-taken as they were measured, because the walk has
changed underneath them. **§2.1's closing note says** `main` **has no production**
**caller of** `rank()` — that was true at [CBO-68](https://linear.app/cbow/issue/CBO-68/title-search-returns-editions-not-works-the-medium-band-is-the-normal)'s branch point and is not true
now: [CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk) is merged, and `correction.py`'s `_gather` does `dedupe` → `rank` →
`band_of` with the early exit. §2.2's table is therefore a hybrid: [CBO-59](https://linear.app/cbow/issue/CBO-59/wire-the-pooled-gather-then-grade-flow-through-the-walk)'s pooled
walk, but with the *old* source-racing behaviour for the question of what gets
read.

Re-run over the re-recorded fixtures with the shipped `_gather` behaviour, one
row does not reproduce:

| Book | §2.2 said | Re-measured | Why |
| -- | -- | -- | -- |
| Berwick | `low (1)` | `strong (1)` | the reply's single candidate scores 1.0 against the file book and clears `singleton` (0.95), so the walk exits strong. The old fixture's candidate did not. |
| The Masque of the Red Death | `medium (10)` | `medium (20)` | the re-record returned 20 volumes where the old file held 10 |
| The Infirmary (Carly Reagon) | `strong (1)` | `~~low (1)~~` `strong` *(session 1b, §0.1 item 1)* | ~~the candidate scores 0.7, capped by ~~`~~NO_AGREEMENT_CEILING~~`~~; whether that reaches ~~`~~strong~~`~~ depends on the same ~~`~~_gather~~`~~ difference~~ |

The other six rows are unchanged. **The band distribution is re-takeable but the**
**re-take is** [CBO-68](https://linear.app/cbow/issue/CBO-68/title-search-returns-editions-not-works-the-medium-band-is-the-normal)**'s to do, not** [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re)**'s**: it needs the population's file books
and the decision about which walk §2.2 means. What [CBO-74](https://linear.app/cbow/issue/CBO-74/source-fixtures-have-drifted-from-the-queries-that-produced-them-re) can say is that §2.2's
table was measured against fixtures that no longer exist and a walk that has since
been replaced, so its 11% / 0% / 33% headline should not be quoted until [CBO-68](https://linear.app/cbow/issue/CBO-68/title-search-returns-editions-not-works-the-medium-band-is-the-normal)
re-runs it.

### What did not change

§1's structural finding is intact and is now better supported: Hardcover's exact
title query returns works rather than printings, one work from one title is a
singleton pool, and the walk exits early. The re-record shows that more clearly
than before — `by-title-berwick.json` is now two editions of **one** work, and
`by-title-the-infirmary.json` is four editions of two.
