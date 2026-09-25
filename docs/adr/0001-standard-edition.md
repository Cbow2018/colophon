---
status: accepted
---

# A title search resolves to one Standard Edition per Work, chosen by date

A title search returns Editions, not Works, so a popular title produced several
Editions that scored the same and gave a medium band, which leaves the book
`colophon:unverified` on an install with no LLM. We chose to keep one Standard
Edition per Work before ranking: the rule is `matching.standard_editions`. Two
candidates are grouped as one Work when their title heads are the same head, as
the scorer normalises it, their authors are the same letters after the scorer's
name normalisation, and their Series Placements do not conflict. The Standard
Edition is the one with the earliest date - dates compare as ISO prefixes, so
`2019` is earlier than `2019-02`, and a candidate with no date comes after every
dated one - then the source highest in the user's source list, then the one
carrying more of the ten payload fields, and last the payload compared field by
field. We chose this because it gives the same answer whatever order a source
lists its reply in, and it only needs fields the sources already send: a Google
candidate states no Series Placement, which the key takes as unstated rather than
as a placement to match (CBO-68, decisions D1–D3, D11–D24, and D22 as amended in
review).

The grouping key reads Series Placement because the glossary says a differing
placement is what tells two Works apart, and a key that ignored it merged two
Works that share a title and an author. Two placements conflict when the series,
as the scorer normalises it, or the position differs. A candidate that states no
placement joins a group only when exactly one placement is stated in it; when two
or more are, the unplaced candidates are a Work of their own. Both halves are
decided from the set of placements in the group rather than from the order the
candidates arrived in. What the key still does not read is the year, and
everything else a pairing of two Editions might need to be told apart is CBO-65's,
scoped against this key.

## Considered Options

- **Build one Work-level candidate per group** (CBO-68 option 2). Rejected because
  Google has no Work layer, so the Work would have no date and the year check would
  vanish. The same file then graded differently depending on source order, and the
  Work's title spelling depended on reply order, which is CBO-69's bug brought
  forward.
- **Keep `unverified` and require an LLM for title-path libraries** (option 3).
  Rejected because it also leaves Hardcover's arrival-order choice in place, and
  that writes a different Edition's ISBN from one run to the next on books that
  grade strong.
- **Most complete payload first** (`most_complete`). Rejected because completeness
  ties where dates don't, and it lets whichever source fills more fields decide the
  match.
- **Most popular by ratings or count.** Rejected because the signal differs between
  sources and isn't stable from run to run.
- **The file's own `dc:date` year first.** Not adopted, because a file's `dc:date`
  is often a production date rather than an Edition's, as Gutenberg's is. The
  evidence was handed to CBO-71.
- **Group by Hardcover's `book.id`.** Not used, because Google has no equivalent.
  The synthesized key matched `book.id` on every Hardcover fixture.
- **Leave Series Placement out of the key** (the first build of this rule).
  Rejected on review: a source's record of one Edition and another source's record
  of a different one were grouped as one Work, when the glossary says two
  placements that conflict are two Works. The Edition it kept was chosen before
  anything was scored, so the pool lost the record that agreed with the file.
  `test_the_pool_is_what_picks_the_record_that_gets_written` is the case.
- **Prefer ebook Editions in the Standard Edition order** (CBO-90). Rejected. It
  would put format ahead of date in the order above and make "standard" mean "the
  ebook", which no source states reliably: asked live, Hardcover labelled 41
  Editions in the re-recorded fixtures and only 9 of them ebook, one of which was
  a recording of an audiobook. Leaving the order alone and never writing an ISBN
  from a title match closes the risk without a rule that reads a field the source
  gets wrong.
- **Do not write a non-ebook Edition's ISBN, and keep the rest of its values**
  (CBO-90). Rejected, because the same Edition's publisher, date and cover would
  still be written, and a hardback's ISBN is the allowance the ISBN path already
  makes - so the rule would have to name which formats count and would still
  write from an Edition the source had mislabelled.

## Consequences

- "Earliest" means earliest *listed*. For a long-reprinted Work that is a modern
  printing, and nothing Colophon writes or logs may call it the first edition.
- A Work becomes a pool of one, graded against `singleton_score`. A dated file
  whose Edition isn't the earliest therefore stays medium without an LLM. This is
  accepted, and the figures are on CBO-76.
- Every format is an Edition, but the title path writes no ISBN, so the Standard
  Edition's ISBN cannot reach an ebook that has none (CBO-90). Its publisher,
  date and cover are still filled, and the ISBN path keeps the allowance it has
  always made, where an ISBN identifies one Edition and is written only when it
  is what recognised the book. An Edition the source states has an audio Reading
  Format is dropped by the source client before this rule sees it, on the title
  path and the ISBN path alike, so a Work listed only as audio offers no
  candidate at all. The Standard Edition can still be a hardback or a paperback.
- Source Priority decides between two Editions of one Work that share a date, so
  the trust order now reaches a value that gets written. That is deliberate: it
  is the one tiebreak a user can see and change.
- Two Works whose titles, authors and placements all agree are one Work here, as
  they already were to the scorer. CBO-65 is scoped against what is left of the
  key.
- `dedupe` runs after this rule and identifies a record by ISBN-13, then by
  title, first author and year, never by Series Placement. Two Works this key has
  just separated are therefore re-merged whenever those agree and neither carries
  an ISBN-13, and the one that arrived first stands, so for that pair the answer
  follows arrival order after all. Nothing in the corpus reaches it: every
  recorded pair carries an ISBN-13. That limit is CBO-65's.
