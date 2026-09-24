---
status: accepted
---

# A title search resolves to one Standard Edition per Work, chosen by date

A title search returns Editions, not Works, so a popular title produced several
Editions that scored the same and gave a medium band, which leaves the book
`colophon:unverified` on an install with no LLM. We chose to keep one Standard
Edition per Work before ranking. Two candidates are grouped as one Work when
their title heads match, their authors are the same letters after name
normalisation, and their Series Placements do not conflict. The Standard Edition
is the one with the earliest date, then the source highest in the user's source
list, then the most complete payload, and last the payload compared field by
field. We chose this because it gives the same answer whatever order a source
lists its reply in, and it only needs fields every source already sends (CBO-68,
decisions D1–D3 and D11–D23).

The grouping key reads Series Placement because the glossary says a differing
placement is what tells two Works apart, and a key that ignored it merged two
Works that share a title and an author. Two placements conflict when the series
or the position differs. A candidate that states no placement joins a group only
when exactly one placement is stated in it; when two or more are, the unplaced
candidates are a Work of their own. Both halves are decided from the set of
placements in the group rather than from the order the candidates arrived in.
What the key still does not read is the year, and everything else a pairing of
two Editions might need to be told apart is CBO-65's, scoped against this key.

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
  Rejected on review: it made one Work of a source's record of an Edition and
  another source's record of a different one, and the Edition it kept was chosen
  before anything was scored, so the pool lost the record that agreed with the
  file. `test_the_pool_is_what_picks_the_record_that_gets_written` is the case.

## Consequences

- "Earliest" means earliest *listed*. For a long-reprinted Work that is a modern
  printing, and nothing Colophon writes or logs may call it the first edition.
- A Work becomes a pool of one, graded against `singleton_score`. A dated file
  whose Edition isn't the earliest therefore stays medium without an LLM. This is
  accepted, and the figures are on CBO-76.
- Every format is an Edition, so the Standard Edition can be an audiobook or a
  hardback, and its ISBN, publisher and date are written to an EPUB when the file
  has none. This is CBO-90.
- Source Priority decides between two Editions of one Work that share a date, so
  the trust order now reaches a value that gets written. That is deliberate: it
  is the one tiebreak a user can see and change.
- Two Works whose titles, authors and placements all agree are one Work here, as
  they already were to the scorer. CBO-65 is scoped against what is left of the
  key.
