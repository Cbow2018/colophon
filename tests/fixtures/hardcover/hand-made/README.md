# Hand-made fixtures: the cases a ticket rests on

> A **live** recording is re-recordable at will; nothing asserts its values, only
> its shape. A **hand-made** fixture exists to freeze one case a ticket rests on;
> it is never re-recorded, and it says which ticket and which case in the
> directory README.

This is the rule for both `fixtures/hardcover/hand-made/` and
`fixtures/googlebooks/hand-made/`. A directory rather than a filename suffix,
because the distinction is a different *reason to exist* and a directory is the
only form that cannot be forgotten when someone adds the next one.

Both files below were named `hand-made-*.json` and sat among the live recordings
until CBO-74, which is exactly the ambiguity the directory removes: the only
signal was a word in the filename, and nothing said what it obliged anyone to do.

| File | Was | Reads it | The case, and why a live recording cannot carry it |
| --- | --- | --- | --- |
| `work-without-title.json` | `hand-made-work-without-title.json` | `test_hardcover.ItTakesTheWorkTitleTests.test_it_falls_back_to_the_edition_title_when_the_work_has_none` | An edition whose work has **no `title` at all**. `books.title` is nullable in Hardcover's schema, and no real book has turned up to show the shape, so the reply is hand-made: `_candidate` has to fall back to the edition's own title, and a live recording cannot be relied on to contain a work with no title. |
| `wider-than-the-question.json` | `hand-made-wider-than-the-question.json` | `test_hardcover.ItTakesTheWorkTitleTests.test_it_takes_authors_and_leaves_the_translator_behind` | A reply **wider than the question**: it carries a translator and a narrator where the query asked only for authors. `_author_rows` filters again on `contribution == "Author"` in case the source ever returns one, and this is the only evidence that the second filter is doing anything. |

Both are CBO-35's and CBO-36's, and the two ISBNs they carry
(`9780000000003`, `9780000000004`) are Colophon's own inventions rather than
numbers any book has — as hand-made as the bodies are.

**What is not here.** The re-recordable ISBN and title recordings stay in the
parent directory, even the ones that have drifted, because a ticket does not rest
on a drifted reply — it rests on a reply that was true when it was taken and that
nothing may now overwrite. `by-isbn-two-series.json` is the one to watch: it is a
*deliberate* off-spec recording rather than a drifted one, kept because its whole
point is the natural order Hardcover returns, which the shipped query's `order_by`
destroys. It is called out at `README.md:199-202` and is exempted by name in the
fixture↔query guard. It stays live because re-recording it is a decision nobody
has taken, not because it is evidence CBO-74 froze.
