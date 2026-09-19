"""Tests for reading and correcting the metadata inside an EPUB or KEPUB."""

import shutil
import unittest
import zipfile
from pathlib import Path

from colophon.epub import Edits, EpubError, correct, read
from tests.opf import (
    calibre_series,
    collections,
    entries_of,
    epub3_series,
    refining_metas,
)
from tests.samplebooks import (
    A_BOXED_SET,
    CONTAINER,
    DRM,
    EXISTING_SERIES_COLLECTION,
    GUTENBERG_DIR,
    KEPUB_CHAPTER,
    OBFUSCATED_FONT,
    SIMPLE,
    TWO_CREATORS,
    write_epub,
)
from tests.tempdir import TemporaryDirectory


class EpubTestCase(unittest.TestCase):
    """A throwaway folder to build books in, and a real book to copy from."""

    # Which Gutenberg layout `gutenberg()` copies, unless a test says otherwise.
    gutenberg_book = "the-masque-of-the-red-death-epub2.epub"

    def setUp(self):
        # Each test gets a folder of its own, removed when it finishes.
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def gutenberg(self, name=None):
        """A private copy, so no test can rewrite the file committed in the repo."""
        name = name or self.gutenberg_book
        path = self.folder / name
        shutil.copy(GUTENBERG_DIR / name, path)
        return path


class ReadingTests(unittest.TestCase):
    """One Gutenberg book, published in both layouts, so the two can be compared."""

    def test_it_reads_a_gutenberg_epub_2(self):
        book = read(GUTENBERG_DIR / "the-masque-of-the-red-death-epub2.epub")

        self.assertEqual(book.title, "The Masque of the Red Death")
        self.assertEqual(book.authors, ("Edgar Allan Poe",))
        self.assertEqual(book.language, "en")
        self.assertIsNone(book.isbn)

    def test_it_reads_a_gutenberg_epub_3(self):
        book = read(GUTENBERG_DIR / "the-masque-of-the-red-death-epub3.epub")

        self.assertEqual(book.title, "The Masque of the Red Death")
        self.assertEqual(book.authors, ("Edgar Allan Poe",))
        self.assertEqual(book.language, "en")


class IsbnTests(EpubTestCase):
    def book_with(self, identifiers, **kwargs):
        metadata = "\n".join(
            f'    <dc:identifier {attribute}>{text}</dc:identifier>'
            for attribute, text in identifiers
        )
        return write_epub(self.folder / "Cragside.epub", metadata, **kwargs)

    def test_it_reads_an_isbn_13_from_an_epub_2_identifier_scheme(self):
        path = self.book_with(
            [('opf:scheme="ISBN"', "9781786813891"), ('opf:scheme="URI"', "urn:uuid:1")],
            version="2.0",
        )

        self.assertEqual(read(path).isbn, "9781786813891")

    def test_it_reads_an_isbn_13_from_an_epub_3_urn(self):
        path = self.book_with([("", "urn:isbn:9781786813891")])

        self.assertEqual(read(path).isbn, "9781786813891")

    def test_it_strips_the_hyphens_so_a_source_can_be_asked_for_it(self):
        path = self.book_with([('opf:scheme="ISBN"', "978-1-78681-389-1")], version="2.0")

        self.assertEqual(read(path).isbn, "9781786813891")

    def test_it_prefers_the_isbn_13_when_the_file_carries_both(self):
        path = self.book_with(
            [('opf:scheme="ISBN"', "1786813895"), ('opf:scheme="ISBN"', "9781786813891")],
            version="2.0",
        )

        self.assertEqual(read(path).isbn, "9781786813891")

    def test_it_reads_an_isbn_10_when_that_is_all_there_is(self):
        path = self.book_with([('opf:scheme="ISBN"', "1786813895")], version="2.0")

        self.assertEqual(read(path).isbn, "1786813895")

    def test_an_identifier_that_is_not_an_isbn_is_ignored(self):
        path = self.book_with(
            [('opf:scheme="URI"', "urn:uuid:0d5f0d3a-1b1a-4c3a-9d3f-2a0f5b1c8e77")]
        )

        self.assertIsNone(read(path).isbn)

    def test_a_book_with_no_identifiers_at_all_has_no_isbn(self):
        path = write_epub(self.folder / "Cragside.epub", "    <dc:title>Cragside</dc:title>")

        self.assertIsNone(read(path).isbn)


class RefusingWhatItCannotHandleTests(EpubTestCase):
    def test_a_file_that_is_not_a_zip_is_refused(self):
        path = self.folder / "Cragside.epub"
        path.write_bytes(b"not a book at all")

        with self.assertRaises(EpubError):
            read(path)

    def test_a_zip_that_is_not_an_epub_is_refused(self):
        path = self.folder / "Cragside.epub"
        with zipfile.ZipFile(path, "w") as not_a_book:
            not_a_book.writestr("readme.txt", "not a book")

        with self.assertRaises(EpubError):
            read(path)

    def test_a_book_with_drm_is_refused(self):
        path = write_epub(
            self.folder / "Cragside.epub",
            SIMPLE,
            extra_entries=[("META-INF/encryption.xml", DRM)],
        )

        with self.assertRaises(EpubError):
            read(path)

    def test_a_book_with_obfuscated_fonts_is_still_read(self):
        """Font obfuscation is routine in retail books and is not DRM."""
        path = write_epub(
            self.folder / "Cragside.epub",
            SIMPLE,
            extra_entries=[("META-INF/encryption.xml", OBFUSCATED_FONT)],
        )

        self.assertEqual(read(path).title, "Cragside")

    def test_a_kepub_is_read_like_any_other_epub(self):
        path = write_epub(
            self.folder / "Cragside.kepub.epub",
            SIMPLE
            + '\n    <dc:identifier opf:scheme="ISBN">9781786813891</dc:identifier>',
            version="3.0",
        )

        book = read(path)

        self.assertEqual(book.title, "Cragside")
        self.assertEqual(book.isbn, "9781786813891")


class CorrectingTests(EpubTestCase):
    def test_it_overwrites_the_title(self):
        path = self.gutenberg()

        changed = correct(path, Edits(title="The Masque of the Red Death: A Story"))

        self.assertEqual(changed, ("title",))
        self.assertEqual(read(path).title, "The Masque of the Red Death: A Story")

    def test_it_writes_the_series_in_calibres_format_and_the_epub_3_format(self):
        path = self.gutenberg()

        changed = correct(path, Edits(series="The Red Death", series_number=6))

        self.assertEqual(set(changed), {"series", "series_number"})
        self.assertEqual(calibre_series(path), ("The Red Death", "6"))
        self.assertEqual(epub3_series(path), ("The Red Death", "series", "6"))

    def test_it_reports_only_the_fields_it_actually_changed(self):
        path = self.gutenberg()

        changed = correct(
            path,
            Edits(title="The Masque of the Red Death", series="The Red Death"),
        )

        self.assertEqual(changed, ("series",))

    def test_it_leaves_alone_the_fields_it_was_not_given(self):
        path = self.gutenberg()

        correct(path, Edits(series="The Red Death"))

        book = read(path)
        self.assertEqual(book.title, "The Masque of the Red Death")
        self.assertEqual(book.authors, ("Edgar Allan Poe",))
        self.assertEqual(book.language, "en")

    def test_it_writes_nothing_at_all_when_nothing_changed(self):
        path = self.gutenberg()
        before = path.read_bytes()

        changed = correct(path, Edits(title="The Masque of the Red Death"))

        self.assertEqual(changed, ())
        self.assertEqual(path.read_bytes(), before)

    def test_every_other_entry_survives_the_rewrite_byte_for_byte(self):
        path = self.gutenberg("the-masque-of-the-red-death-epub3.epub")
        before = entries_of(path)

        correct(path, Edits(title="A Different Title", series="The Red Death", series_number=6))

        after = entries_of(path)
        self.assertEqual(list(after), list(before))
        for name, body in before.items():
            if not name.endswith(".opf"):
                self.assertEqual(after[name], body, f"{name} was rewritten")

    def test_the_gutenberg_licence_is_still_in_the_book_afterwards(self):
        path = self.gutenberg("the-masque-of-the-red-death-epub3.epub")

        correct(path, Edits(title="A Different Title"))

        whole_book = entries_of(path)["OEBPS/8992904816723053170_1064-h-2.htm.xhtml"].decode(
            "utf-8", "replace"
        )
        self.assertIn("Section 1. General Terms of Use", whole_book)
        self.assertIn("Project Gutenberg License", whole_book)

    def test_the_rewritten_book_is_still_a_valid_epub(self):
        path = self.gutenberg()

        correct(path, Edits(title="A Different Title", series="The Red Death"))

        with zipfile.ZipFile(path) as book:
            self.assertIsNone(book.testzip())
            first = book.infolist()[0]
            self.assertEqual(first.filename, "mimetype")
            self.assertEqual(first.compress_type, zipfile.ZIP_STORED)
        self.assertEqual(read(path).title, "A Different Title")


class AuthorTests(EpubTestCase):
    gutenberg_book = "the-masque-of-the-red-death-epub3.epub"

    def test_it_overwrites_the_author(self):
        path = self.gutenberg()

        changed = correct(path, Edits(authors=("Edgar Allan Poe II",)))

        self.assertEqual(changed, ("authors",))
        self.assertEqual(read(path).authors, ("Edgar Allan Poe II",))

    def test_it_leaves_the_metas_that_refine_the_first_creator_alone(self):
        """EPUB 3 hangs `file-as` and `role` off the first creator by id."""
        path = self.gutenberg()

        correct(path, Edits(authors=("Edgar Allan Poe II",)))

        refines = {name for name, _ in refining_metas(path)}
        self.assertIn("file-as", refines)
        self.assertIn("role", refines)

    def test_it_drops_a_creator_the_source_does_not_have(self):
        path = write_epub(self.folder / "Cragside.epub", TWO_CREATORS)

        changed = correct(path, Edits(authors=("LJ Ross",)))

        self.assertEqual(changed, ("authors",))
        self.assertEqual(read(path).authors, ("LJ Ross",))

    def test_it_drops_the_metas_that_refined_the_creator_it_dropped(self):
        path = write_epub(self.folder / "Cragside.epub", TWO_CREATORS)

        correct(path, Edits(authors=("LJ Ross",)))

        dangling = [name for name, refines in refining_metas(path) if refines == "#author_1"]
        self.assertEqual(dangling, [])

    def test_it_adds_a_second_author(self):
        path = write_epub(self.folder / "Cragside.epub", TWO_CREATORS)

        changed = correct(path, Edits(authors=("LJ Ross", "LJ Ross's Friend")))

        self.assertEqual(changed, ("authors",))
        self.assertEqual(read(path).authors, ("LJ Ross", "LJ Ross's Friend"))

    def test_it_adds_an_author_to_a_book_that_had_none(self):
        path = write_epub(self.folder / "Cragside.epub", "    <dc:title>Cragside</dc:title>")

        correct(path, Edits(authors=("LJ Ross",)))

        self.assertEqual(read(path).authors, ("LJ Ross",))

    def test_an_empty_author_list_leaves_the_book_alone(self):
        path = write_epub(self.folder / "Cragside.epub", TWO_CREATORS)
        before = path.read_bytes()

        changed = correct(path, Edits(authors=()))

        self.assertEqual(changed, ())
        self.assertEqual(read(path).authors, ("LJ Ross", "Someone Else"))
        self.assertEqual(path.read_bytes(), before)


class SeriesEdgeCaseTests(EpubTestCase):
    def test_it_reuses_the_series_collection_the_book_already_has(self):
        path = write_epub(self.folder / "Cragside.epub", EXISTING_SERIES_COLLECTION)

        correct(path, Edits(series="DCI Ryan", series_number=6))

        self.assertEqual(epub3_series(path), ("DCI Ryan", "series", "6"))
        self.assertEqual(list(collections(path)), ["series-1"])
        self.assertEqual(calibre_series(path), ("DCI Ryan", "6"))

    def test_it_leaves_a_collection_that_is_not_a_series_alone(self):
        path = write_epub(self.folder / "Cragside.epub", A_BOXED_SET)

        correct(path, Edits(series="DCI Ryan", series_number=6))

        found = collections(path)
        self.assertEqual(found["set-1"], {"name": "The Complete DCI Ryan", "collection-type": "set"})
        self.assertIn(("DCI Ryan", "series", "6"), [tuple(v.values()) for v in found.values()])

    def test_a_series_number_between_two_books_is_kept_as_it_is(self):
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)

        correct(path, Edits(series="DCI Ryan", series_number=1.5))

        self.assertEqual(calibre_series(path), ("DCI Ryan", "1.5"))
        self.assertEqual(epub3_series(path), ("DCI Ryan", "series", "1.5"))

    def test_a_whole_number_is_not_written_with_a_decimal_point(self):
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)

        correct(path, Edits(series="DCI Ryan", series_number=6.0))

        self.assertEqual(calibre_series(path), ("DCI Ryan", "6"))
        self.assertEqual(epub3_series(path), ("DCI Ryan", "series", "6"))

    def test_a_series_number_with_a_source_that_gave_no_series_name(self):
        """Without a series name there is nothing for EPUB 3 to refine."""
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)

        changed = correct(path, Edits(series_number=6))

        self.assertEqual(changed, ("series_number",))
        self.assertEqual(calibre_series(path), (None, "6"))
        self.assertIsNone(epub3_series(path))


class KepubTests(EpubTestCase):
    def test_the_kobo_spans_survive_a_correction(self):
        path = write_epub(
            self.folder / "Cragside.kepub.epub",
            SIMPLE + '\n    <dc:identifier opf:scheme="ISBN">9781786813891</dc:identifier>',
            content=KEPUB_CHAPTER,
        )

        correct(path, Edits(title="Cragside: A DCI Ryan Mystery", series="DCI Ryan"))

        chapter = entries_of(path)["OEBPS/chapter.xhtml"].decode()
        self.assertIn('class="koboSpan"', chapter)
        self.assertIn('id="kobo.1.1"', chapter)
        self.assertEqual(read(path).title, "Cragside: A DCI Ryan Mystery")


class LeavingABookAloneTests(EpubTestCase):
    def test_a_drm_locked_book_is_left_exactly_as_it_was(self):
        path = write_epub(
            self.folder / "Cragside.epub",
            SIMPLE,
            extra_entries=[("META-INF/encryption.xml", DRM)],
        )
        before = path.read_bytes()

        with self.assertRaises(EpubError):
            correct(path, Edits(title="Something Else"))

        self.assertEqual(path.read_bytes(), before)

    def test_a_file_that_is_not_an_epub_is_left_exactly_as_it_was(self):
        path = self.folder / "Cragside.epub"
        path.write_bytes(b"not a book at all")

        with self.assertRaises(EpubError):
            correct(path, Edits(title="Something Else"))

        self.assertEqual(path.read_bytes(), b"not a book at all")

    def test_a_package_document_with_no_metadata_is_refused(self):
        path = self.folder / "Cragside.epub"
        with zipfile.ZipFile(path, "w") as book:
            book.writestr(zipfile.ZipInfo("mimetype"), "application/epub+zip")
            book.writestr("META-INF/container.xml", CONTAINER)
            book.writestr("OEBPS/content.opf", '<?xml version="1.0"?>\n<package xmlns="http://www.idpf.org/2007/opf" version="3.0"/>')
        before = path.read_bytes()

        with self.assertRaises(EpubError):
            correct(path, Edits(title="Something Else"))

        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
