# CBO-90 — amendment to the Standard Edition ADR draft

Not a new ADR (Q15): excluding Audio Editions is easy to reverse, which fails the
first of the three ADR tests. It is an amendment to
`adr-draft-standard-edition.md` (CBO-68), made in the same commit that numbers that
ADR. Two edits.

## 1. Replace the third Consequences bullet

Current:

> - Every format is an Edition, so the Standard Edition can be an audiobook or a
>   hardback, and its ISBN, publisher and date are written to an EPUB when the file
>   has none. This is CBO-90.

Replace with:

> - Every format is an Edition, but Audio Editions are dropped by the source client
>   before the Standard Edition is chosen, on the title path and the ISBN path
>   alike (CBO-90). The Standard Edition can still be a hardback or paperback, and
>   its ISBN is written to an ebook that has none, as the ISBN path has always
>   allowed. A Work listed only as audio offers no candidate at all.

## 2. Add to Considered Options

> - **Prefer ebook Editions in the Standard Edition order** (CBO-90). Rejected. It
>   would put format ahead of date in D15 and make "standard" mean "the ebook", which
>   no source states reliably. Excluding the one format that is never right for an
>   ebook closes the risk and leaves D15's order alone.
> - **Keep the Standard Edition but do not write a non-ebook Edition's ISBN**
>   (CBO-90). Rejected, because the same Edition's publisher, date and cover would
>   still be written, and a hardback's ISBN is the allowance the ISBN path already
>   makes.
