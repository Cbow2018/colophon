"""Tests for reading and correcting the metadata inside an EPUB or KEPUB."""

import re
import shutil
import unittest
import zipfile
from pathlib import Path

from colophon.epub import (
    UNVERIFIED_NOTE,
    UNVERIFIED_TAG,
    Edits,
    EpubError,
    correct,
    read,
)
from tests.opf import (
    calibre_series,
    collections,
    cover_meta,
    entries_of,
    epub3_series,
    manifest_items,
    refining_metas,
    subjects,
    text_of,
)
from tests.samplebooks import (
    A_BOXED_SET,
    CONTAINER,
    DRM,
    EXISTING_SERIES_COLLECTION,
    GUTENBERG_DIR,
    JPEG,
    KEPUB_CHAPTER,
    OBFUSCATED_FONT,
    PNG,
    SIMPLE,
    TWO_CREATORS,
    WITH_THE_OTHER_FIELDS,
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


class CoverTests(EpubTestCase):
    """Adding a cover, which is the only thing here that writes a new file into the zip."""

    def test_it_adds_a_cover_image_and_declares_it_for_epub_3(self):
        path = self.gutenberg("the-masque-of-the-red-death-epub3.epub")
        # A book that has none: the declaration is taken out first, so the test
        # is not also a test of the book it was copied from.
        _without_its_cover(path)

        changed = correct(path, Edits(), cover=PNG)

        self.assertEqual(changed, ("cover",))
        items = manifest_items(path)
        declared = [item for item in items.values() if item.get("properties") == "cover-image"]
        self.assertEqual(len(declared), 1)
        self.assertEqual(declared[0]["media-type"], "image/png")
        self.assertEqual(entries_of(path)[f"OEBPS/{declared[0]['href']}"], PNG)

    def test_it_declares_the_cover_the_way_epub_2_readers_look_for_it(self):
        path = write_epub(self.folder / "Cragside.epub", SIMPLE, version="2.0")

        correct(path, Edits(), cover=PNG)

        identifier = cover_meta(path)
        self.assertIsNotNone(identifier, "EPUB 2 knows a cover by its meta tag")
        self.assertEqual(manifest_items(path)[identifier]["media-type"], "image/png")

    def test_the_media_type_is_read_off_the_image_itself(self):
        """Both sources serve JPEGs, and a book may have had nothing to go on."""
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)

        correct(path, Edits(), cover=JPEG)

        declared = next(
            item
            for item in manifest_items(path).values()
            if (item.get("properties") or "").startswith("cover-image")
        )
        self.assertEqual(declared["media-type"], "image/jpeg")
        self.assertTrue(declared["href"].endswith(".jpg"))

    def test_it_leaves_the_cover_the_book_already_has(self):
        path = self.gutenberg("the-masque-of-the-red-death-epub3.epub")
        before = path.read_bytes()
        existing = next(
            name
            for name, item in manifest_items(path).items()
            if item.get("properties") == "cover-image"
        )

        changed = correct(path, Edits(), cover=PNG)

        self.assertEqual(changed, ())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(manifest_items(path)[existing]["properties"], "cover-image")

    def test_no_cover_bytes_means_no_cover_is_added(self):
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)
        before = path.read_bytes()

        changed = correct(path, Edits(), cover=None)

        self.assertEqual(changed, ())
        self.assertEqual(path.read_bytes(), before)

    def test_a_cover_is_added_alongside_the_metadata_in_one_write(self):
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)

        changed = correct(path, Edits(title="Cragside: A DCI Ryan Mystery"), cover=JPEG)

        self.assertEqual(changed, ("title", "cover"))
        self.assertEqual(read(path).title, "Cragside: A DCI Ryan Mystery")
        self.assertTrue(
            any(
                (item.get("properties") or "") == "cover-image"
                for item in manifest_items(path).values()
            )
        )

    def test_the_text_of_the_book_is_untouched_by_adding_a_cover(self):
        path = self.gutenberg("the-masque-of-the-red-death-epub3.epub")
        _without_its_cover(path)
        before = entries_of(path)

        correct(path, Edits(), cover=PNG)

        after = entries_of(path)
        for name, body in before.items():
            if not name.endswith(".opf"):
                self.assertEqual(after[name], body, f"{name} was rewritten")

    def test_a_written_cover_is_declared_once_however_the_book_is_read(self):
        """EPUB 2's meta tag and EPUB 3's property are both written, as the
        series is: any library app reads at least one of them."""
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)

        correct(path, Edits(), cover=PNG)

        items = manifest_items(path)
        self.assertIsNotNone(cover_meta(path))
        self.assertIn("cover-image", [item.get("properties") for item in items.values()])
        self.assertEqual(len([i for i in items.values() if i["media-type"] == "image/png"]), 1)


def _without_its_cover(path):
    """Take the cover declaration and image out of a real book, by hand.

    Gutenberg's EPUB 3 declares one twice over - the manifest item and EPUB 2's
    legacy meta tag - and both go, so the book really does arrive with none. The
    image is removed by name, so the book's other files are left where they are.
    """
    declared = next(
        item
        for item in manifest_items(path).values()
        if item.get("properties") == "cover-image"
    )
    cover_names = {
        f"OEBPS/{declared['href']}",
        f"OEBPS/{declared['href']}".replace("OEBPS/", ""),
    }

    with zipfile.ZipFile(path) as book:
        entries = [(entry, book.read(entry.filename)) for entry in book.infolist()]
    with zipfile.ZipFile(path, "w") as book:
        for entry, body in entries:
            if entry.filename in cover_names:
                continue
            if entry.filename.endswith(".opf"):
                text = body.decode("utf-8")
                text = text.replace(' properties="cover-image"', "")
                text = re.sub(
                    r'[ \t]*<meta name="cover" content="[^"]*"/>[ \t]*\n?', "", text
                )
                # The manifest item pointing at the image that was just removed.
                text = "\n".join(
                    line for line in text.splitlines() if declared["href"] not in line
                )
                body = text.encode("utf-8")
            written = zipfile.ZipInfo(entry.filename, entry.date_time)
            written.compress_type = entry.compress_type
            book.writestr(written, body)
    return path


class OtherFieldTests(EpubTestCase):
    """The three fields CBO-38 adds: read, written, and left alone."""

    def test_it_reads_the_description_the_publisher_and_the_date(self):
        path = write_epub(self.folder / "Cragside.epub", WITH_THE_OTHER_FIELDS)

        book = read(path)

        self.assertEqual(book.description, "A house full of secrets.")
        self.assertEqual(book.publisher, "Ulverscroft")
        self.assertEqual(book.date, "2019-01-01")

    def test_a_book_without_them_says_nothing_rather_than_an_empty_string(self):
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)

        book = read(path)

        self.assertIsNone(book.description)
        self.assertIsNone(book.publisher)
        self.assertIsNone(book.date)

    def test_it_reads_a_series_a_book_declares_the_epub_3_way(self):
        """`fill` judges the file, so the file's series has to be read both ways.

        Calibre's tags are the pair the writing side keeps together, but a book
        that says what series it is in through EPUB 3's collection has said so
        just as much - and a rule that overwrote it would be overwriting a field
        that was not empty.
        """
        path = write_epub(self.folder / "Cragside.epub", EXISTING_SERIES_COLLECTION)

        book = read(path)

        self.assertEqual(book.series, "Old Series")
        self.assertEqual(book.series_number, "1")

    def test_the_calibre_tags_win_when_a_book_declares_both(self):
        path = write_epub(
            self.folder / "Cragside.epub",
            """
    <dc:title>Cragside</dc:title>
    <meta name="calibre:series" content="Calibre's Series"/>
    <meta name="calibre:series_index" content="2"/>
    <meta property="belongs-to-collection" id="series-1">The Other One</meta>
    <meta property="collection-type" refines="#series-1">series</meta>
    <meta property="group-position" refines="#series-1">9</meta>
""",
        )

        book = read(path)

        self.assertEqual(book.series, "Calibre's Series")
        self.assertEqual(book.series_number, "2")

    def test_a_collection_that_is_not_a_series_is_not_a_series(self):
        path = write_epub(self.folder / "Cragside.epub", A_BOXED_SET)

        self.assertIsNone(read(path).series)

    def test_it_writes_them_onto_a_book_that_had_none(self):
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)

        changed = correct(
            path,
            Edits(
                description="A house full of secrets.",
                publisher="Ulverscroft",
                date="2017-07-07",
            ),
        )

        self.assertEqual(set(changed), {"description", "publisher", "date"})
        self.assertEqual(text_of(path, "description"), "A house full of secrets.")
        self.assertEqual(text_of(path, "publisher"), "Ulverscroft")
        self.assertEqual(text_of(path, "date"), "2017-07-07")

    def test_it_overwrites_what_the_book_already_had(self):
        path = write_epub(self.folder / "Cragside.epub", WITH_THE_OTHER_FIELDS)

        changed = correct(path, Edits(description="A different blurb.", publisher="Independently Published"))

        self.assertEqual(set(changed), {"description", "publisher"})
        self.assertEqual(text_of(path, "description"), "A different blurb.")
        self.assertEqual(text_of(path, "publisher"), "Independently Published")

    def test_a_value_the_book_already_carries_is_not_a_change(self):
        path = write_epub(self.folder / "Cragside.epub", WITH_THE_OTHER_FIELDS)
        before = path.read_bytes()

        changed = correct(path, Edits(description="A house full of secrets."))

        self.assertEqual(changed, ())
        self.assertEqual(path.read_bytes(), before)

    def test_the_isbn_and_the_language_can_be_written_too(self):
        path = write_epub(self.folder / "Cragside.epub", "    <dc:title>Cragside</dc:title>")

        changed = correct(
            path, Edits(isbn="9781521748831", language="en")
        )

        self.assertEqual(set(changed), {"isbn", "language"})
        self.assertEqual(read(path).isbn, "9781521748831")
        self.assertEqual(read(path).language, "en")

    def test_an_isbn_is_written_in_the_epub_3_urn_form(self):
        """The form a reader that checks the identifier understands."""
        path = write_epub(self.folder / "Cragside.epub", SIMPLE)

        correct(path, Edits(isbn="9781521748831"))

        self.assertEqual(text_of(path, "identifier"), "urn:isbn:9781521748831")

    def test_the_same_isbn_in_another_form_is_not_a_change(self):
        """`urn:isbn:…`, a hyphenated ISBN and a bare one are one number.

        The comparison is of the digits, so a book already carrying this ISBN -
        however it is spelt - is not rewritten, and the pass does not report a
        change it did not make.
        """
        for carried in (
            "urn:isbn:9781521748831",
            "978-1-5217-4883-1",
            "9781521748831",
            "ISBN:9781521748831",
        ):
            with self.subTest(carried=carried):
                path = write_epub(
                    self.folder / "Cragside.epub",
                    f'    <dc:title>Cragside</dc:title>\n'
                    f'    <dc:identifier opf:scheme="ISBN">{carried}</dc:identifier>',
                    version="2.0",
                )
                before = path.read_bytes()

                changed = correct(path, Edits(isbn="9781521748831"))

                self.assertEqual(changed, (), "the same ISBN, spell it how you like")
                self.assertEqual(path.read_bytes(), before)

    def test_a_different_isbn_is_rewritten_in_place(self):
        path = write_epub(
            self.folder / "Cragside.epub",
            '    <dc:title>Cragside</dc:title>\n'
            '    <dc:identifier opf:scheme="ISBN">1786813895</dc:identifier>',
            version="2.0",
        )

        changed = correct(path, Edits(isbn="9781521748831"))

        self.assertEqual(changed, ("isbn",))
        self.assertEqual(read(path).isbn, "9781521748831")


class TheUnverifiedMarkTests(EpubTestCase):
    """The mark itself: the tag and the note, on and off, at the file layer.

    `Corrector` decides that a book is unverified; what that looks like inside a
    book is decided here, so these are the tests for the tag, the two forms the
    note takes and the idempotence of both - the rules the pipeline relies on but
    does not own.
    """

    def a_book(self, metadata=SIMPLE):
        return write_epub(self.folder / "Cragside.epub", metadata)

    def test_marking_adds_the_tag_and_the_note(self):
        path = self.a_book()

        changed = correct(path, Edits(unverified=True))

        self.assertEqual(changed, ("description", "tag"))
        self.assertEqual(text_of(path, "description"), UNVERIFIED_NOTE)
        self.assertIn(UNVERIFIED_TAG, subjects(path))
        self.assertTrue(read(path).unverified, "and the file says so on the way back")

    def test_marking_keeps_the_blurb_and_puts_the_note_after_it(self):
        path = self.a_book(WITH_THE_OTHER_FIELDS)

        correct(path, Edits(unverified=True, description="A house full of secrets."))

        self.assertEqual(
            text_of(path, "description"),
            f"A house full of secrets.\n\n{UNVERIFIED_NOTE}",
        )

    def test_marking_twice_is_a_no_op_the_second_time(self):
        path = self.a_book()
        correct(path, Edits(unverified=True))
        marked = path.read_bytes()

        changed = correct(path, Edits(unverified=True, description=UNVERIFIED_NOTE))

        self.assertEqual(changed, (), "nothing left to write")
        self.assertEqual(path.read_bytes(), marked)
        self.assertEqual(subjects(path).count(UNVERIFIED_TAG), 1)

    def test_unmarking_takes_both_halves_off(self):
        """The pipeline hands the marked description back, and both halves go.

        A corrector unmarking a book has nothing of its own to say about the
        description - the source had no blurb - so what it passes on is the
        description the file already carries, note and all, and the mark coming
        off is what shortens it.
        """
        marked = f"A house full of secrets.\n\n{UNVERIFIED_NOTE}"
        path = self.a_book(WITH_THE_OTHER_FIELDS)
        correct(path, Edits(unverified=True, description="A house full of secrets."))

        changed = correct(path, Edits(unverified=False, description=marked))

        self.assertEqual(sorted(changed), ["description", "tag"])
        self.assertNotIn(UNVERIFIED_TAG, subjects(path))
        self.assertEqual(text_of(path, "description"), "A house full of secrets.")

    def test_dropping_the_description_leaves_the_book_without_one(self):
        """`description=None` means "leave it", so emptiness needs its own word.

        A marked book whose blurb was only ever the note has to come out with no
        description at all, which is not the same as a description left alone -
        and it is why `drop_description` exists beside an honest `description`.
        """
        path = self.a_book()
        correct(path, Edits(unverified=True))

        changed = correct(path, Edits(unverified=False, drop_description=True))

        self.assertEqual(sorted(changed), ["description", "tag"])
        self.assertIsNone(read(path).description)
        self.assertIsNone(text_of(path, "description"))

    def test_a_book_with_a_description_of_its_own_keeps_it(self):
        """Taking a note off is not a reason to lose a blurb that was there first."""
        marked = f"A house full of secrets.\n\n{UNVERIFIED_NOTE}"
        path = self.a_book(WITH_THE_OTHER_FIELDS)
        correct(path, Edits(unverified=True, description="A house full of secrets."))

        correct(path, Edits(unverified=False, description=marked))

        self.assertEqual(text_of(path, "description"), "A house full of secrets.")

    def test_unmarking_takes_every_copy_of_the_tag_off(self):
        """A book another tool left two tags on comes out with none.

        The mark is written once, but a book may have been through something that
        duplicated it, and taking one off while another stays would leave the book
        still marked while the log said the mark had gone.
        """
        path = self.a_book(
            f"    <dc:title>Cragside</dc:title>\n"
            f"    <dc:subject>{UNVERIFIED_TAG}</dc:subject>\n"
            f"    <dc:subject>{UNVERIFIED_TAG}</dc:subject>"
        )

        correct(path, Edits(unverified=False, drop_description=True))

        self.assertEqual(subjects(path), [], "both of them, not the first one found")

    def test_the_tag_goes_beside_the_book_s_own_subjects(self):
        path = self.a_book(
            '    <dc:title>Cragside</dc:title>\n'
            "    <dc:subject>Detective and mystery stories</dc:subject>"
        )

        correct(path, Edits(unverified=True))

        self.assertEqual(
            subjects(path), ["Detective and mystery stories", UNVERIFIED_TAG]
        )


if __name__ == "__main__":
    unittest.main()
