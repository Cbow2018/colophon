"""Tests for the correction pass: what it changes, when it backs up, and dry run."""

import shutil
import unittest
from pathlib import Path

from colophon.backups import Backups
from colophon.config import Config
from colophon.correction import Corrector
from colophon.epub import read
from colophon.hardcover import SourceError
from tests.opf import calibre_series, entries_of, epub3_series
from tests.samplebooks import (
    AS_DOWNLOADED,
    CHAPTER,
    DRM,
    GUTENBERG_DIR,
    ISBN,
    KEPUB_CHAPTER,
    SIMPLE,
    add_isbn,
    write_epub,
)
from tests.sources import FakeSource
from tests.tempdir import TemporaryDirectory

# A book that already says everything the source says, in both series formats,
# so there is genuinely nothing left to change.
ALREADY_MATCHES = f"""    <dc:title>Cragside</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
    <meta name="calibre:series" content="DCI Ryan Mysteries"/>
    <meta name="calibre:series_index" content="6"/>
    <meta property="belongs-to-collection" id="colophon-series">DCI Ryan Mysteries</meta>
    <meta property="collection-type" refines="#colophon-series">series</meta>
    <meta property="group-position" refines="#colophon-series">6</meta>
"""


class RefusingBackups:
    def keep(self, path):
        raise OSError("no space left on device")


class CorrectionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.backups = Backups(self.folder / "backups")
        self.source = FakeSource()
        self.addCleanup(self._tmp.cleanup)

    def book(self, name="Cragside.epub", content=CHAPTER):
        return write_epub(self.folder / name, AS_DOWNLOADED, version="2.0", content=content)

    def corrector(self, **kwargs):
        settings = {"source": self.source, "backups": self.backups}
        settings.update(kwargs)
        return Corrector(**settings)

    def kept(self):
        folder = self.folder / "backups"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


class MatchingTests(CorrectionTestCase):
    def test_a_matched_book_is_rewritten_with_what_the_source_says(self):
        path = self.book()

        outcome = self.corrector().correct(path)

        self.assertTrue(outcome.matched)
        book = read(path)
        self.assertEqual(book.title, "Cragside")
        self.assertEqual(book.authors, ("L.J. Ross",))

    def test_it_writes_the_series_in_both_formats(self):
        path = self.book()

        self.corrector().correct(path)

        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))
        self.assertEqual(epub3_series(path), ("DCI Ryan Mysteries", "series", "6"))

    def test_the_isbn_from_the_file_is_the_one_it_asks_about(self):
        self.corrector().correct(self.book())

        self.assertEqual(self.source.asked, [ISBN])

    def test_the_original_is_backed_up_before_it_is_changed(self):
        path = self.book()
        before = path.read_bytes()

        self.corrector().correct(path)

        self.assertEqual(self.kept(), ["Cragside.epub"])
        self.assertEqual((self.folder / "backups" / "Cragside.epub").read_bytes(), before)
        self.assertNotEqual(path.read_bytes(), before)

    def test_a_kepub_is_corrected_the_same_way(self):
        path = self.book(name="Cragside.kepub.epub", content=KEPUB_CHAPTER)

        outcome = self.corrector().correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Cragside")
        self.assertIn('class="koboSpan"', entries_of(path)["OEBPS/chapter.xhtml"].decode())

    def test_a_bare_kepub_is_corrected_too(self):
        """Kobo's own extension, without an .epub on the end."""
        path = self.book(name="Cragside.kepub", content=KEPUB_CHAPTER)

        outcome = self.corrector().correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Cragside")
    def test_the_outcome_lists_the_fields_and_where_each_value_came_from(self):
        path = self.book()

        outcome = self.corrector().correct(path)

        self.assertEqual(
            [(change.field, change.value, change.source) for change in outcome.changed],
            [
                ("title", "Cragside", "hardcover"),
                ("authors", "L.J. Ross", "hardcover"),
                ("series", "DCI Ryan Mysteries", "hardcover"),
                ("series_number", "6", "hardcover"),
            ],
        )


class FromConfigTests(unittest.TestCase):
    """Building the pass the configuration asks for."""

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def config(self, **extra):
        settings = {"hardcover_token_file": self.folder / "hardcover_token"}
        settings.update(extra)
        return Config(**settings)

    def test_no_token_file_means_no_source(self):
        corrector = Corrector.from_config(self.config(), Backups(self.folder / "backups"))

        self.assertIsNone(corrector.source)

    def test_it_says_so_when_there_is_no_token_file(self):
        with self.assertLogs("colophon", level="INFO") as captured:
            Corrector.from_config(self.config(), Backups(self.folder / "backups"))

        self.assertIn("no Hardcover token", captured.output[0])

    def test_a_token_file_gives_it_a_source(self):
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")

        corrector = Corrector.from_config(self.config(), Backups(self.folder / "backups"))

        self.assertIsNotNone(corrector.source)

    def test_the_dry_run_setting_comes_from_the_config(self):
        corrector = Corrector.from_config(
            self.config(dry_run=True), Backups(self.folder / "backups")
        )

        self.assertTrue(corrector.dry_run)


class AGutenbergBookTests(CorrectionTestCase):
    """A real book, from a real publisher of EPUBs, corrected end to end.

    Gutenberg's books carry no ISBN, so one is put in first, by hand: the point
    is to run a real EPUB 2 and a real EPUB 3 package document all the way
    through, licence and all.
    """

    def a_real_book(self, name="the-masque-of-the-red-death-epub3.epub"):
        path = self.folder / name
        shutil.copy(GUTENBERG_DIR / name, path)
        return add_isbn(path, ISBN)

    def test_a_real_epub_3_is_corrected_and_its_original_is_kept(self):
        path = self.a_real_book()
        original = path.read_bytes()

        outcome = self.corrector().correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Cragside")
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))
        self.assertEqual(epub3_series(path), ("DCI Ryan Mysteries", "series", "6"))
        self.assertEqual(self.kept(), [path.name])
        self.assertEqual((self.folder / "backups" / path.name).read_bytes(), original)

    def test_a_real_epub_2_is_corrected_too(self):
        path = self.a_real_book("the-masque-of-the-red-death-epub2.epub")

        outcome = self.corrector().correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))
        self.assertEqual(epub3_series(path), ("DCI Ryan Mysteries", "series", "6"))

    def test_the_gutenberg_licence_is_still_in_the_book_after_it_is_corrected(self):
        path = self.a_real_book()

        self.corrector().correct(path)

        whole_book = b"".join(entries_of(path).values()).decode("utf-8", "replace")
        self.assertIn("Section 1. General Terms of Use", whole_book)
        self.assertIn("Project Gutenberg License", whole_book)


class WhenThereIsNothingToChangeTests(CorrectionTestCase):
    def test_a_book_that_already_matches_is_not_backed_up_or_written(self):
        path = write_epub(self.folder / "Cragside.epub", ALREADY_MATCHES, version="2.0")
        before = path.read_bytes()

        outcome = self.corrector().correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.changed, ())
        self.assertEqual(self.kept(), [])
        self.assertEqual(path.read_bytes(), before)

    def test_a_book_with_no_isbn_is_left_alone_and_the_source_is_not_asked(self):
        path = write_epub(self.folder / "Cragside.epub", SIMPLE, version="2.0")

        outcome = self.corrector().correct(path)

        self.assertFalse(outcome.matched)
        self.assertEqual(self.source.asked, [])
        self.assertEqual(self.kept(), [])
        self.assertIn("no ISBN", outcome.fragment())

    def test_a_book_the_source_does_not_know_is_left_alone(self):
        source = FakeSource(found=None)
        path = self.book()

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertEqual(self.kept(), [])
        self.assertIn("no edition", outcome.fragment())
        self.assertIn(ISBN, outcome.fragment())

    def test_a_file_that_is_not_an_epub_is_not_even_read(self):
        path = self.folder / "Scan.pdf"
        path.write_bytes(b"%PDF-1.4 not a book")

        outcome = self.corrector().correct(path)

        self.assertEqual(self.source.asked, [])
        self.assertEqual(outcome.fragment(), "")

    def test_an_unreadable_epub_is_reported_rather_than_raised(self):
        path = self.folder / "Cragside.epub"
        path.write_bytes(b"not a zip at all")

        outcome = self.corrector().correct(path)

        self.assertEqual(self.source.asked, [])
        self.assertIn("metadata not read", outcome.fragment())

    def test_a_drm_locked_book_is_reported_rather_than_raised(self):
        path = write_epub(
            self.folder / "Cragside.epub",
            SIMPLE + f'\n    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>',
            version="2.0",
            extra_entries=[("META-INF/encryption.xml", DRM)],
        )

        outcome = self.corrector().correct(path)

        self.assertIn("encrypted", outcome.fragment())

    def test_with_no_source_configured_it_says_so(self):
        path = self.book()

        outcome = self.corrector(source=None).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("no Hardcover token", outcome.fragment())


class WhenTheSourceFailsTests(CorrectionTestCase):
    def test_a_source_that_cannot_answer_leaves_the_book_alone(self):
        source = FakeSource(error=SourceError("Hardcover rejected the token (HTTP 401)"))
        path = self.book()
        before = path.read_bytes()

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("Hardcover could not be asked", outcome.fragment())
        self.assertIn("rejected the token", outcome.fragment())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.kept(), [])

    def test_a_backup_that_fails_stops_the_change(self):
        path = self.book()
        before = path.read_bytes()

        outcome = self.corrector(backups=RefusingBackups()).correct(path)

        self.assertEqual(path.read_bytes(), before, "the book must not change unbacked-up")
        self.assertIn("nothing written", outcome.fragment())


class DryRunTests(CorrectionTestCase):
    def test_it_reports_what_it_would_change_without_touching_anything(self):
        path = self.book()
        before = path.read_bytes()

        outcome = self.corrector(dry_run=True).correct(path)

        self.assertTrue(outcome.matched)
        self.assertNotEqual(outcome.changed, ())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.kept(), [], "a dry run backs nothing up")
        self.assertIn("would change", outcome.fragment())

    def test_it_still_says_when_there_would_be_nothing_to_change(self):
        path = write_epub(self.folder / "Cragside.epub", ALREADY_MATCHES, version="2.0")

        outcome = self.corrector(dry_run=True).correct(path)

        self.assertIn("nothing to change", outcome.fragment())


class FragmentsTests(CorrectionTestCase):
    def test_the_fragment_names_the_match_the_confidence_the_fields_and_their_source(self):
        outcome = self.corrector().correct(self.book())

        fragment = outcome.fragment()

        self.assertIn("hardcover matched ISBN 9781521748831", fragment)
        self.assertIn("confidence 1.00", fragment)
        self.assertIn('title="Cragside"<-hardcover', fragment)
        self.assertIn('authors="L.J. Ross"<-hardcover', fragment)
        self.assertIn('series="DCI Ryan Mysteries"<-hardcover', fragment)
        self.assertIn('series_number="6"<-hardcover', fragment)

    def test_a_corrected_book_says_so_rather_than_saying_it_would(self):
        fragment = self.corrector().correct(self.book()).fragment()

        self.assertIn("changed", fragment)
        self.assertNotIn("would change", fragment)


if __name__ == "__main__":
    unittest.main()
