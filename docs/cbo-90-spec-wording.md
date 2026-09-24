# CBO-90 — proposed design-spec wording

Goes into the design spec (CBO-33) directly after CBO-68's **The Standard Edition
(title path)** rule and its limits (`cbo-68-build-brief.md` §1), and replaces that
brief's third limit ("Every format is an Edition… Tracked as CBO-90"). Vocabulary
as in `context-additions-cbo-68.md` and `cbo-90-context-draft.md`.

---

> **Audio Editions are never written into an ebook.** Every format is an Edition
> of its Work, but a file Colophon corrects is never an audiobook, so an Edition
> the source states is audio is not offered as a candidate on either path. Only
> Hardcover states an Edition's Reading Format. Its client drops every Edition whose
> Reading Format is Audio before the pool is formed, so the Standard Edition is
> chosen from the Editions that remain, in the same order as before, and no Audio
> Edition's ISBN, publisher, date or cover can be written. On the ISBN path, an
> ISBN that Hardcover lists as an Audio Edition is treated as an ISBN Hardcover
> does not have: the walk moves on to the next source, and then to the title
> fallback, which keeps the file's own ISBN.
>
> Only a stated Audio format excludes an Edition. An Edition stated as physical,
> ebook or both, or with no Reading Format, stays eligible, so a print Edition's
> ISBN can still be written. That is the same allowance the ISBN path already
> makes, where print ISBNs in ebooks are common.

These limits also go into the spec:

* **A Work Hardcover lists only as audio offers nothing.** It is dropped with its
  Editions, so the walk asks the next source, or the book ends
  `colophon:unverified`. A missed match, never a wrong write.
* **Google Books states no Reading Format.** Its volumes are not filtered. Google's
  volumes API is not an audiobook catalogue, and this is accepted.
* **"Both" is not excluded.** An Edition Hardcover states is both physical and
  audio stays eligible until a real Work shows it causing a wrong write.
* **Excluding is not preferring.** The Standard Edition is still the earliest
  listed of the remaining Editions. Nothing Colophon writes or logs may call it the
  ebook edition.

---

## Where each clause comes from

| Clause | Grilling decision |
| -- | -- |
| Exclude, not reorder or suppress | Q3 |
| "Only Hardcover states…", its client drops | Q2, Q8 |
| ISBN path, direct hit | Q10 |
| Title fallback keeps the file's ISBN | Q10, and `_edits`' `fill` (the `overwrite` case is CBO-92) |
| Only stated Audio; 3 eligible; not-stated eligible | Q2, Q11 |
| Audio-only Work dropped | Q9 |
| Google not filtered | Q5 |

The spec should not name `reading_format_id` or `_candidates`: the implementation
detail is in `research-cbo-90.md` and belongs in the code comments. The gate in
`research-cbo-90.md` §5 must pass before this text is applied: it assumes Hardcover
states Audio for `9781799729945`.
