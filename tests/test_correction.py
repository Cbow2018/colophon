"""Tests for the correction pass: what it changes, when it backs up, and dry run."""

import shutil
import unittest
from pathlib import Path

from colophon.backups import Backups
from colophon.config import Config
from colophon.correction import Corrector
from colophon.epub import read
from colophon.hardcover import SourceError
from colophon.matching import Candidate
from tests.opf import calibre_series, entries_of, epub3_series
from tests.samplebooks import (
    AS_DOWNLOADED,
    BELSAY,
    BERWICK,
    CHAPTER,
    CRAGSIDE,
    DRM,
    GUTENBERG_DIR,
    INITIALS_WITHOUT_STOPS,
    ISBN,
    KEPUB_CHAPTER,
    SAPIENS,
    SIMPLE,
    WITHOUT_AUTHOR,
    WITHOUT_AUTHOR_OR_LANGUAGE,
    add_isbn,
    write_epub,
)
from tests.sources import (
    ANOTHER_INFIRMARY,
    BELSAY_CANDIDATE,
    BERWICK_CANDIDATE,
    CRAGSIDE_CANDIDATE,
    SAPIENS_CANDIDATE,
    THE_INFIRMARY_CANDIDATE,
    FakeSource,
)
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


class BooksWithoutAnIsbnTests(CorrectionTestCase):
    """The books CBO-36 exists for: no ISBN, so the title and author carry it.

    Each of the three real books was recorded from Hardcover with the query the
    client ships. The lookalike is `The Infirmary` - the same author's other
    book, whose work title matches none of the three - so it is only ever
    rejected by the title half of the comparison. A source is free to offer
    whatever it likes, which is what these fixtures do.
    """

    def book(self, name, metadata):
        return write_epub(self.folder / name, metadata, version="2.0")

    def a_book_the_source_has(self, name, metadata, candidate):
        return self.book(name, metadata), FakeSource(found=None, candidates=[candidate])

    def test_cragside_is_matched_by_its_cleaned_title(self):
        path, source = self.a_book_the_source_has(
            "Cragside.epub", CRAGSIDE, CRAGSIDE_CANDIDATE
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        book = read(path)
        self.assertEqual(book.title, "Cragside")
        self.assertEqual(book.authors, ("L.J. Ross",))
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))

    def test_berwick_is_matched_too(self):
        path, source = self.a_book_the_source_has("Berwick.epub", BERWICK, BERWICK_CANDIDATE)

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Berwick")
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "24"))

    def test_belsay_is_matched_and_gets_the_number_its_title_never_had(self):
        """Belsay is #23 on the record, and the file's title does not say so."""
        path, source = self.a_book_the_source_has("Belsay.epub", BELSAY, BELSAY_CANDIDATE)

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Belsay")
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "23"))

    def test_the_cleaned_title_is_what_the_source_is_asked_about(self):
        path, source = self.a_book_the_source_has(
            "Cragside.epub", CRAGSIDE, CRAGSIDE_CANDIDATE
        )

        self.corrector(source=source).correct(path)

        self.assertEqual(source.asked_titles, [["Cragside"]])
        self.assertEqual(source.asked_languages, ["en"])
        self.assertEqual(source.asked, [], "there was no ISBN to ask about")

    def test_the_book_is_searched_in_its_own_language(self):
        path, source = self.a_book_the_source_has(
            "Cragside.epub", CRAGSIDE, CRAGSIDE_CANDIDATE
        )

        self.corrector(source=source).correct(path)

        self.assertEqual(source.asked_languages, ["en"])

    def test_initials_run_together_in_the_file_still_match(self):
        """The file says `LJ Ross`; the record says `L.J. Ross`."""
        path, source = self.a_book_the_source_has(
            "Cragside.epub", INITIALS_WITHOUT_STOPS, CRAGSIDE_CANDIDATE
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).authors, ("L.J. Ross",))
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))

    def test_a_book_with_no_language_is_searched_without_one(self):
        path = self.book("Cragside.epub", WITHOUT_AUTHOR_OR_LANGUAGE)
        source = FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE])

        self.corrector(source=source).correct(path)

        self.assertEqual(source.asked_languages, [None])

    def test_a_book_is_searched_by_the_primary_part_of_its_language(self):
        """`en-GB` is asked about as `en`, or the editions are never found.

        The three-letter tag is asked about on `code3` instead, checked against
        the live API: `code3: {_eq: "eng"}` returns the editions a `code2`
        filter returns. What comes back then says `code2: en`, so the file and
        the record only agree on the comparison because `en` reduces to itself
        - a file that says `eng` against a record that says `en` is a mismatch
        the comparison refuses, and that is stated in the PR rather than
        papered over here.
        """
        for written, expected in (
            ("en-GB", "en"),
            ("en-US", "en"),
            ("EN", "en"),
            ("eng", "eng"),
            ("ger", "ger"),
        ):
            with self.subTest(language=written):
                metadata = CRAGSIDE.replace(
                    "<dc:language>en</dc:language>", f"<dc:language>{written}</dc:language>"
                )
                path, source = self.a_book_the_source_has(
                    f"{written}.epub", metadata, CRAGSIDE_CANDIDATE
                )

                outcome = self.corrector(source=source).correct(path)

                self.assertEqual(source.asked_languages, [expected])
                if expected != "eng" and expected != "ger":
                    self.assertTrue(outcome.matched, "`en` and `en-GB` are one language")

    def test_a_regional_language_still_matches_a_record_that_says_en(self):
        """The usual case: the file says `en-GB`, the record says `en`."""
        metadata = CRAGSIDE.replace(
            "<dc:language>en</dc:language>", "<dc:language>en-GB</dc:language>"
        )
        path, source = self.a_book_the_source_has(
            "Cragside-en-GB.epub", metadata, CRAGSIDE_CANDIDATE
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertEqual(source.asked_languages, ["en"])
        self.assertTrue(outcome.matched)

    def test_a_named_subtitle_is_asked_about_both_ways(self):
        """A record may keep the subtitle, so both forms go in the one request."""
        path = self.book("Sapiens.epub", SAPIENS)
        source = FakeSource(found=None, candidates=[SAPIENS_CANDIDATE])

        outcome = self.corrector(source=source).correct(path)

        self.assertEqual(
            source.asked_titles, [["Sapiens", "Sapiens: A Brief History of Humankind"]]
        )
        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Sapiens: A Brief History of Humankind")

    def test_a_subtitle_the_record_kept_is_still_matched(self):
        """The short form finds nothing; the long one, in the same request, does."""
        path = self.book("Sapiens.epub", SAPIENS)
        source = FakeSource(found=None, candidates=[SAPIENS_CANDIDATE])

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertIn("hardcover matched Sapiens", outcome.fragment())

    def test_a_title_with_no_subtitle_is_asked_about_once(self):
        path, source = self.a_book_the_source_has(
            "Cragside.epub", CRAGSIDE, CRAGSIDE_CANDIDATE
        )

        self.corrector(source=source).correct(path)

        self.assertEqual(source.asked_titles, [["Cragside"]])

    def test_the_lookalike_is_not_accepted_for_any_of_them(self):
        for name, metadata in (
            ("Cragside.epub", CRAGSIDE),
            ("Berwick.epub", BERWICK),
            ("Belsay.epub", BELSAY),
        ):
            with self.subTest(book=name):
                path = self.book(name, metadata)
                source = FakeSource(
                    found=None,
                    candidates=[THE_INFIRMARY_CANDIDATE, ANOTHER_INFIRMARY],
                )
                before = path.read_bytes()

                outcome = self.corrector(source=source).correct(path)

                self.assertFalse(outcome.matched)
                self.assertEqual(self.kept(), [])
                self.assertEqual(path.read_bytes(), before)

    def test_a_book_with_no_author_is_not_matched_on_its_title_alone(self):
        """A title match alone never reaches the threshold."""
        path = self.book("Cragside.epub", WITHOUT_AUTHOR)
        source = FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE])

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertEqual(self.kept(), [])

    def test_the_best_of_several_candidates_is_the_one_accepted(self):
        """The author's other book is offered first, and the right one wins."""
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(
            found=None,
            candidates=[THE_INFIRMARY_CANDIDATE, ANOTHER_INFIRMARY, CRAGSIDE_CANDIDATE],
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Cragside")
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))

    def test_a_confident_match_is_backed_up_before_it_is_written(self):
        path, source = self.a_book_the_source_has(
            "Cragside.epub", CRAGSIDE, CRAGSIDE_CANDIDATE
        )
        before = path.read_bytes()

        self.corrector(source=source).correct(path)

        self.assertEqual(self.kept(), ["Cragside.epub"])
        self.assertEqual((self.folder / "backups" / "Cragside.epub").read_bytes(), before)

    def test_the_outcome_says_which_title_the_match_was_made_on(self):
        path, source = self.a_book_the_source_has(
            "Cragside.epub", CRAGSIDE, CRAGSIDE_CANDIDATE
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertIn("hardcover matched Cragside by title and author", outcome.fragment())
        self.assertIn("confidence 1.00", outcome.fragment())

    def test_a_near_miss_says_which_book_it_was_and_what_was_wrong_with_it(self):
        """A book that was found, trusted less, but still named.

        The Infirmary is the same author's other book: the title is nothing
        like this file's, so it is not close enough to name, but its position
        in the series is what a file's own bracket is there to catch.
        """
        path = self.book("Cragside.epub", CRAGSIDE)
        wrong_position = Candidate(
            source="hardcover",
            title="Cragside",
            authors=("L.J. Ross",),
            series_number="11",
            language="en",
        )

        outcome = self.corrector(
            source=FakeSource(found=None, candidates=[wrong_position])
        ).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("Cragside", outcome.fragment())
        self.assertIn("confidence 0.80", outcome.fragment())
        self.assertIn("same title", outcome.fragment())

    def test_a_book_the_source_has_nothing_like_is_not_named_at_all(self):
        """Nothing in the reply agrees on title or author, so there is no near miss."""
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None, candidates=[ANOTHER_INFIRMARY])

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("no edition is called Cragside", outcome.fragment())
        self.assertNotIn("The Infirmary", outcome.fragment())

    def test_a_dry_run_reports_the_match_without_writing_it(self):
        path, source = self.a_book_the_source_has(
            "Cragside.epub", CRAGSIDE, CRAGSIDE_CANDIDATE
        )
        before = path.read_bytes()

        outcome = self.corrector(source=source, dry_run=True).correct(path)

        self.assertTrue(outcome.matched)
        self.assertNotEqual(outcome.changed, ())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.kept(), [])

    def test_a_title_the_source_does_not_know_is_not_a_match(self):
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None)

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("Cragside", outcome.fragment())

    def test_a_book_with_no_title_is_not_asked_about(self):
        path = self.book("Cragside.epub", "    <dc:creator>L. J. Ross</dc:creator>")
        source = FakeSource(found=None)

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertEqual(source.asked_titles, [])
        self.assertIn("no title", outcome.fragment())

    def test_a_source_that_cannot_answer_leaves_the_book_alone(self):
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(title_error=SourceError("Hardcover is rate limiting (HTTP 429)"))
        before = path.read_bytes()

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("Hardcover could not be asked", outcome.fragment())
        self.assertIn("rate limiting", outcome.fragment())
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.kept(), [])

    def test_a_book_that_already_says_what_the_source_says_is_not_rewritten(self):
        """A source with nothing but a title and an author has nothing to write."""
        path = self.book(
            "Already.epub",
            """    <dc:title>Cragside</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
""",
        )
        source = FakeSource(
            found=None,
            candidates=[Candidate(title="Cragside", authors=("L.J. Ross",), language="en")],
        )
        before = path.read_bytes()

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.changed, ())
        self.assertEqual(self.kept(), [])
        self.assertEqual(path.read_bytes(), before)


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
