---
status: accepted
---

# An ISBN hit is trusted unless the title contradicts it

An exact ISBN hit used to short-circuit matching: `_by_isbn` returned at the
first source that had the ISBN and wrote that record whole, without reading a
word of the file's own title. Ebook ISBNs are frequently stale, absent or the
print edition's, so a file titled *Seahouses* carrying Cragside's ISBN was
silently rewritten as *Cragside* - another book's title, series, publisher and
date written into it, with nothing in the log to say a contradiction had been
seen. We chose to read the title before writing the hit: the record is written
as it always was when its title agrees with the file's, and when it does not the
hit is a **stale ISBN** and the book takes the fallback that a file whose ISBN
no source has already takes - the title path on the file's own title, with the
file's own ISBN kept. The author is not read on this path at all.

**A title agrees** when either of two things holds. The record's whole title,
through `comparison_text`, is contained in the file's through `comparison_text`
as whole words - `f" {record} " in f" {file} "`, which admits every messy title
measured (`Cragside - L J Ross`, `Cragside.epub`, `L. J. Ross - Cragside (DCI
Ryan 6)`) and refuses every sibling (`Seahouses`, `Angel`, `Holy Island`). Or
the calibrated title similarity - the file's head against the record's, one form
per side, exactly as the scorer compares them - reaches `TITLE_AGREES = 0.5`,
which is what catches a misspelling, because `Cragsde` does not contain
`cragside` and scores 0.8533. `TITLE_AGREES` is deliberately its own constant
rather than a reuse of `AUTHOR_AGREES`: the two happen to share a value today,
and tuning the author gate must not move what an ISBN path writes. A file with
no searchable title never contradicts - it has nothing to disagree with, and on
that path the ISBN is the only identity it has. A contradicted record is not
discarded: it joins the pool the LLM Chooser is offered, because a file whose
title is the wrong half (`Untitled`, `Microsoft Word - doc1`) can only be
matched to the book its ISBN names by a reader of both.

When the model picks that contradicted record, **the write is a title match, not
an ISBN match**. The file's ISBN did not identify this book - the reason the
book is here at all is that the record contradicts the identifier - so the ISBN
field keeps its own rule and the record's ISBN is not written over the file's.
CBO-90's rule, that an ISBN is only written when an ISBN identified the book,
therefore stays true rather than gaining an exception.

## Considered Options

- **Grade the hit through `score_candidate` and write it when the score is
  strong.** Rejected: it loses files with no author. The scorer caps a candidate
  at `NO_AGREEMENT_CEILING = 0.7` when the file names no creator or the names do
  not reach `AUTHOR_AGREES`, so every ISBN-bearing file with no author, or with
  `Unknown`, would grade low and be marked Unverified - where today it is
  written. That is a regression on a population that is not wrong about
  anything, and it is the case the whole rule exists to protect.
- **A floor on the raw title ratio.** Rejected: the two populations overlap. Measured
  on `_parts_of` heads, `The Shrine` against the file's own title scores 0.5217
  and `Angel` 0.4615, while the genuinely-messy `Cragside - a DCI Ryan mystery`
  scores 0.4571 - so no floor admits the real title without also admitting the
  siblings. A floor on the *calibrated* similarity cannot be drawn either: every
  raw ratio below `SIMILARITY_FLOOR = 0.35` returns a clean 1.0 penalty, so the
  messy title, `Untitled`, `Holy Island` and an empty title all come out at
  similarity 0.0000.
- **Character containment.** Rejected: `Angel` is in `Evangeline`, `Us` is in
  `Tempus Fugit`, `Emma` is in `Gemma and the Lighthouse` - each writes a
  different book over the file confidently.

## Consequences

Containment is one-directional, so a record whose title is the first word(s) of
the file's is still written: a *Dune Messiah* file carrying Dune's ISBN is
written as *Dune*, and `Cragside: It Begins` carrying the ISBN of *It* is
written as *It*. This is a known limit, accepted at the time of the decision and
never worse than the rule it replaces, which wrote every case including these.
It is marked with a `ponytail:` comment where containment is tested and pinned
by a test named as the limit so it cannot move silently.

The demoted rows are the price and they are the point. Seven stale sibling
cases and an `Untitled` file that used to be silently rewritten as another book
now land on the title path, which under a default install with no LLM ends
`colophon:unverified` with their own metadata. Pooling the title query into the
ISBN walk was considered and deferred: the two designs interact through
`dedupe`'s keep-first, which makes the written payload a function of Source
Priority until CBO-61 merges duplicates, so the conflict veto this rule implies
and the pooling both wait on CBO-61.
