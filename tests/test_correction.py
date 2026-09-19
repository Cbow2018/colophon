"""Tests for the correction pass: what it changes, when it backs up, and dry run."""

import inspect
import shutil
import unittest
from pathlib import Path

from colophon.backups import Backups
from colophon.config import KNOWN_SOURCES, Config
from colophon.correction import SOURCE_SETUP, Corrector
from colophon.epub import read
from colophon.googlebooks import GoogleBooks
from colophon.hardcover import Hardcover
from colophon.matching import Candidate
from colophon.sources import SourceError
from tests.opf import calibre_series, collections, entries_of, epub3_series
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
from tests.test_googlebooks import Replay as GoogleReplay
from tests.test_googlebooks import ReplayByQuery
from tests.test_hardcover import Replay

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


# A real Gutenberg book that arrived already carrying a series, so a source with
# no series data of its own can be shown to leave it alone rather than clear it.
SERIES_ALREADY_ON_IT = """    <dc:title>The Masque of the Red Death</dc:title>
    <dc:creator>Edgar Allan Poe</dc:creator>
    <dc:language>en</dc:language>
    <meta name="calibre:series" content="An Old Series"/>
    <meta name="calibre:series_index" content="3"/>
"""

# The `q` Google is asked for the Gutenberg book, which is what its recording was
# made with and therefore what a replay has to match before handing it back.
TITLE_ASKED = 'intitle:"The Masque of the Red Death" inauthor:"Edgar Allan Poe"'


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

    def corrector(self, source="default", **kwargs):
        """A corrector over one source unless a test hands it a longer list.

        Most tests here are about one source and what it makes of a book, so a
        bare source is wrapped into the list of one the corrector actually
        takes; a test about the priority list passes `sources=` instead. A test
        that wants no source at all passes `source=None`.
        """
        settings = {"backups": self.backups}
        settings.update(kwargs)
        if "sources" not in settings:
            if source == "default":
                source = self.source
            settings["sources"] = [] if source is None else [source]
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
        # One source's file by default, so a test about that source is not also
        # a test about the other one's key being absent.
        settings = {
            "hardcover_token_file": self.folder / "hardcover_token",
            "google_books_key_file": self.folder / "google_books_key",
            "sources": ("hardcover",),
        }
        settings.update(extra)
        return Config(**settings)

    def test_the_built_sources_are_in_the_order_the_config_puts_them(self):
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")
        (self.folder / "google_books_key").write_text("a-key\n", encoding="utf-8")

        corrector = Corrector.from_config(
            self.config(sources=("google_books", "hardcover")),
            Backups(self.folder / "backups"),
        )

        self.assertEqual(
            [source.name for source in corrector.sources], ["google_books", "hardcover"]
        )

    def test_a_source_left_out_of_the_list_is_not_built(self):
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")
        (self.folder / "google_books_key").write_text("a-key\n", encoding="utf-8")

        corrector = Corrector.from_config(
            self.config(sources=("google_books",)), Backups(self.folder / "backups")
        )

        self.assertEqual([source.name for source in corrector.sources], ["google_books"])

    def test_a_source_with_no_key_file_is_skipped_once_then_left_out(self):
        """Hardcover's token is there; Google Books' key is not set up at all."""
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")

        with self.assertLogs("colophon", level="INFO") as captured:
            corrector = Corrector.from_config(
                self.config(sources=("hardcover", "google_books")),
                Backups(self.folder / "backups"),
            )

        self.assertEqual([source.name for source in corrector.sources], ["hardcover"])
        self.assertEqual(len(captured.output), 1, "said once, not once per book")
        self.assertIn("Google Books key", "\n".join(captured.output))

    def test_a_key_file_that_cannot_be_read_is_not_fatal(self):
        """A path that is not a readable key file is a real error, and said so.

        The key is pointed at something that cannot be read as a file. A
        directory is the portable way to say that, but a process running under a
        restricted token - the file sandbox these tests run in, for one - is
        refused a directory read with `PermissionError` rather than
        `IsADirectoryError`; either way it is an `OSError`, which is what the
        reader has to survive.
        """
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")
        where = self.folder / "google_books_key"
        where.mkdir()
        try:
            where.read_text(encoding="utf-8")
        except OSError:
            pass
        else:
            self.skipTest("this platform reads a directory as if it were a file")

        with self.assertLogs("colophon", level="ERROR") as captured:
            corrector = Corrector.from_config(
                self.config(sources=("hardcover", "google_books")),
                Backups(self.folder / "backups"),
            )

        self.assertEqual([source.name for source in corrector.sources], ["hardcover"])
        self.assertIn("Google Books key file", "\n".join(captured.output))

    def test_no_token_file_means_no_source(self):
        corrector = Corrector.from_config(self.config(), Backups(self.folder / "backups"))

        self.assertEqual(corrector.sources, ())

    def test_every_configured_source_has_a_label(self):
        """The corrector can only hold sources `config.py` allows, and every one
        of those has to be buildable and nameable.

        `_build` and `_blamed` both look a source up in `SOURCE_SETUP` by the
        name the config allows, so the two lists drifting apart would be a
        `KeyError` in production rather than a wrong answer. This is the test
        that makes adding a source to one list and not the other fail here
        instead.
        """
        self.assertEqual(set(SOURCE_SETUP), set(KNOWN_SOURCES))
        for name, entry in SOURCE_SETUP.items():
            with self.subTest(source=name):
                self.assertTrue(entry["label"], "a source needs something to be called")
                self.assertIn(entry["file"], Config.__dataclass_fields__)
                self.assertTrue(entry["secret_name"])

    def test_it_says_so_when_there_is_no_token_file(self):
        with self.assertLogs("colophon", level="INFO") as captured:
            Corrector.from_config(self.config(), Backups(self.folder / "backups"))

        self.assertIn("no Hardcover token", captured.output[0])

    def test_a_token_file_gives_it_a_source(self):
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")

        corrector = Corrector.from_config(self.config(), Backups(self.folder / "backups"))

        self.assertEqual([source.name for source in corrector.sources], ["hardcover"])

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
        self.assertIn("no source", outcome.fragment())
        self.assertIn(ISBN, outcome.fragment())
        self.assertIn("hardcover", outcome.fragment(), "the source asked is named")

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
        self.assertIn("no source is set up", outcome.fragment())


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

        # The cleaned title first, then the same title with the subtitle left on
        # for a source that kept it, both in the one request.
        self.assertEqual(source.asked_titles, [["Cragside", "Cragside: A DCI Ryan Mystery"]])
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
        filter returns. What comes back then says `code2: en`, and that is still
        this book - the query is what keeps other languages out, so the
        comparison does not re-check and reject the record the query found.
        """
        for written, expected in (
            ("en-GB", "en"),
            ("en-US", "en"),
            ("EN", "en"),
            ("eng", "eng"),
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
                self.assertTrue(outcome.matched, f"`{written}` and `en` are one language")

    def test_a_file_tagged_eng_matches_a_record_carrying_both_codes(self):
        """The case the client-side language check used to refuse.

        A file says `eng`. The lookup asks about `code3`, and the record comes
        back carrying `code2: en` and `code3: eng` - which the client reads as
        `en`. Both codes are the same language, so the book is matched.
        """
        metadata = CRAGSIDE.replace(
            "<dc:language>en</dc:language>", "<dc:language>eng</dc:language>"
        )
        path, source = self.a_book_the_source_has(
            "Cragside-eng.epub", metadata, CRAGSIDE_CANDIDATE
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertEqual(source.asked_languages, ["eng"], "asked about on code3")
        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Cragside")
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))

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
        """Nothing was taken off, so there is no second form to ask about."""
        path = self.book(
            "Normal People.epub",
            """    <dc:title>Normal People</dc:title>
    <dc:creator>Sally Rooney</dc:creator>
    <dc:language>en</dc:language>
""",
        )
        source = FakeSource(
            found=None,
            candidates=[
                Candidate(
                    source="hardcover",
                    title="Normal People",
                    authors=("Sally Rooney",),
                    language="en",
                )
            ],
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertEqual(source.asked_titles, [["Normal People"]])
        self.assertTrue(outcome.matched)

    def test_a_near_miss_is_named_from_the_same_single_pass(self):
        """Scoring happens once: the source is not asked again for the near miss."""
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None, candidates=[ANOTHER_INFIRMARY])

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertEqual(len(source.asked_titles), 1, "one request, one scoring pass")
        self.assertEqual(source.asked_titles[0], ["Cragside", "Cragside: A DCI Ryan Mystery"])

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

        The candidate is the right author and a title that only contains the
        file's, with the wrong position in the series on top: 0.84, under the
        threshold, and named rather than silently dropped.
        """
        path = self.book("Cragside.epub", CRAGSIDE)
        nearly = Candidate(
            source="hardcover",
            title="Cragside: A DCI Ryan Mystery",
            authors=("L.J. Ross",),
            series_number="11",
            language="en",
        )

        outcome = self.corrector(
            source=FakeSource(found=None, candidates=[nearly])
        ).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn(
            "no source among hardcover has an edition called Cragside", outcome.fragment()
        )
        self.assertIn("confidence 0.84", outcome.fragment())
        self.assertIn("contained", outcome.fragment())

    def test_a_book_the_source_has_nothing_like_is_not_named_at_all(self):
        """Nothing in the reply agrees on title or author, so there is no near miss."""
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None, candidates=[ANOTHER_INFIRMARY])

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("no source", outcome.fragment())
        self.assertIn("Cragside", outcome.fragment())
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


class TheSourcePriorityListTests(CorrectionTestCase):
    """Sources are tried in the order the user sets, and the first match wins.

    The list is a trust order, not a per-field preference: a book takes its
    values from the first source that matches it, and a source that is down
    stops the walk for that book rather than being stood in for by a
    lower-priority one. Both the ISBN path and the title path walk the same
    list.
    """

    def a_second_source(self, candidate=None, found=None):
        """A lower-priority source, offering Google's own record of the book.

        The recorded Cragside, as Google has it: the work's title, the author
        spaced the way Google spells it, and the ISBN. A candidate is labelled
        with the source that offered it, as a real one is. `found` is what the
        ISBN lookup answers with, which is None unless a test says otherwise,
        because a source is free not to have the edition.
        """
        if candidate is None:
            candidate = Candidate(
                source="google_books",
                title="Cragside",
                authors=("L. J. Ross",),
                isbn=ISBN,
            )
        return FakeSource(found=found, candidates=[candidate], name="google_books")

    def a_second_source_holding_the_isbn(self):
        """The same, for the ISBN path, where it is what recognised the book."""
        return self.a_second_source(
            found=Candidate(
                source="google_books",
                title="Cragside",
                authors=("L. J. Ross",),
                isbn=ISBN,
            )
        )

    def corrector_over(self, *sources, **kwargs):
        settings = {"backups": self.backups}
        settings.update(kwargs)
        return Corrector(sources=list(sources), **settings)

    # --- the ISBN path -----------------------------------------------------

    def test_the_first_source_that_has_the_isbn_is_the_one_used(self):
        first, second = FakeSource(), self.a_second_source()

        outcome = self.corrector_over(first, second).correct(self.book())

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.source, "hardcover")
        self.assertEqual(second.asked, [], "the second source is never reached")

    def test_the_next_source_is_tried_when_the_first_has_no_such_isbn(self):
        first = FakeSource(found=None)
        second = self.a_second_source_holding_the_isbn()
        path = self.book()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(first.asked, [ISBN])
        self.assertEqual(second.asked, [ISBN])
        self.assertEqual(outcome.source, "google_books")
        self.assertEqual(read(path).title, "Cragside")

    def test_a_book_no_source_has_is_reported_as_unmatched(self):
        outcome = self.corrector_over(
            FakeSource(found=None), FakeSource(found=None, name="google_books")
        ).correct(self.book())

        self.assertFalse(outcome.matched)
        self.assertIn("no source", outcome.fragment())
        self.assertIn(ISBN, outcome.fragment())

    def test_an_isbn_miss_does_not_fall_back_to_the_title_path(self):
        """A book with an ISBN stays on the ISBN path, as it does today."""
        first = FakeSource(found=None)
        second = self.a_second_source()

        self.corrector_over(first, second).correct(self.book())

        self.assertEqual(second.asked_titles, [], "no title search for a book with an ISBN")

    # --- the title path ----------------------------------------------------

    def test_a_book_with_no_isbn_is_walked_down_the_list_too(self):
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        first = FakeSource(found=None)
        second = self.a_second_source()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(second.asked_titles, [["Cragside", "Cragside: A DCI Ryan Mystery"]])
        self.assertEqual(read(path).title, "Cragside")

    def test_the_author_is_passed_to_a_source_that_filters_on_it(self):
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        source = self.a_second_source()

        self.corrector_over(source).correct(path)

        self.assertEqual(source.asked_authors, ["L. J. Ross"])

    def test_the_next_source_is_tried_when_the_first_offers_nothing_good_enough(self):
        """A near miss from a trusted source does not veto a lower one."""
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        first = FakeSource(found=None, candidates=[ANOTHER_INFIRMARY])
        second = self.a_second_source()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.source, "google_books")

    def test_no_source_offering_anything_good_enough_names_the_near_miss(self):
        """A near miss is named, and the book is left alone.

        The right author and a title that only contains the file's, with the
        wrong position in the series on top: 0.84, under the threshold, and
        named rather than silently dropped.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        before = path.read_bytes()
        nearly = Candidate(
            source="google_books",
            title="Cragside: A DCI Ryan Mystery",
            authors=("L. J. Ross",),
            series_number="11",
        )

        outcome = self.corrector_over(
            FakeSource(found=None, candidates=[nearly]),
            self.a_second_source(candidate=nearly),
        ).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn(
            "no source among hardcover, google_books has an edition called Cragside",
            outcome.fragment(),
        )
        self.assertIn("confidence 0.84", outcome.fragment())
        self.assertEqual(path.read_bytes(), before, "a book nothing matches is not touched")
        self.assertEqual(self.kept(), [])

    def test_a_source_that_offers_nothing_at_all_does_not_name_a_book(self):
        """A reply that agrees on neither title nor author is not an explanation."""
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")

        outcome = self.corrector_over(
            FakeSource(found=None), self.a_second_source(candidate=THE_INFIRMARY_CANDIDATE)
        ).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("no source", outcome.fragment())
        self.assertIn("Cragside", outcome.fragment())
        self.assertIn("hardcover, google_books", outcome.fragment())
        self.assertNotIn("The Infirmary", outcome.fragment())

    # --- a source that is down ---------------------------------------------

    def test_a_source_that_is_down_stops_the_walk_for_that_book(self):
        """No lower-priority source quietly stands in for one that is down."""
        first = FakeSource(error=SourceError("Hardcover is rate limiting (HTTP 429)"))
        second = self.a_second_source()
        path = self.book()
        before = path.read_bytes()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertFalse(outcome.matched)
        self.assertEqual(second.asked, [], "the walk stopped at the failure")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.kept(), [])

    def test_a_title_lookup_that_is_down_stops_the_walk_too(self):
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        first = FakeSource(found=None, title_error=SourceError("Hardcover answered HTTP 503"))
        second = self.a_second_source()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertFalse(outcome.matched)
        self.assertEqual(second.asked_titles, [])

    def test_the_outcome_says_which_source_could_not_be_asked(self):
        first = FakeSource(error=SourceError("Hardcover rejected the token (HTTP 401)"))

        outcome = self.corrector_over(first, self.a_second_source()).correct(self.book())

        self.assertIn("Hardcover could not be asked", outcome.fragment())
        self.assertIn("rejected the token", outcome.fragment())

    def test_a_source_that_is_down_is_a_warning_of_its_own(self):
        """A source being unreachable is a problem with the run, not one book.

        A user watching `docker logs` should not have to read every book's line
        to notice that a source has stopped answering, so the failure is logged
        at WARNING as well as appearing in that book's line.
        """
        first = FakeSource(error=SourceError("Hardcover is rate limiting (HTTP 429)"))

        with self.assertLogs("colophon", level="WARNING") as captured:
            self.corrector_over(first, self.a_second_source()).correct(self.book())

        self.assertEqual(len(captured.output), 1, "one warning, not one per source tried")
        self.assertIn("WARNING", captured.output[0])
        self.assertIn("Hardcover", captured.output[0])
        self.assertIn("rate limiting", captured.output[0])

    def test_the_warning_names_the_book_that_could_not_be_looked_up(self):
        first = FakeSource(error=SourceError("Hardcover answered HTTP 503"))

        with self.assertLogs("colophon", level="WARNING") as captured:
            self.corrector_over(first).correct(self.book())

        self.assertIn(ISBN, captured.output[0])

    def test_a_book_that_matches_warns_about_nothing(self):
        with self.assertNoLogs("colophon", level="WARNING"):
            self.corrector_over(self.a_second_source_holding_the_isbn()).correct(self.book())

    # --- the log line ------------------------------------------------------

    def test_each_written_value_is_attributed_to_the_source_that_supplied_it(self):
        second = self.a_second_source_holding_the_isbn()

        outcome = self.corrector_over(FakeSource(found=None), second).correct(self.book())

        for change in outcome.changed:
            self.assertEqual(change.source, "google_books")
        self.assertIn('title="Cragside"<-google_books', outcome.fragment())

    def test_the_match_says_which_source_made_it(self):
        second = self.a_second_source_holding_the_isbn()

        outcome = self.corrector_over(FakeSource(found=None), second).correct(self.book())

        self.assertIn("google_books matched ISBN", outcome.fragment())


class ABookMatchedFromGoogleBooksTests(CorrectionTestCase):
    """A real book corrected from Google Books, end to end.

    Google has no series data for a novel, so the point of these is what is
    *not* written: the title and the authors move, and the series does not,
    because there is nothing to put there. The Gutenberg book carries no ISBN,
    so it goes down the title path, which is the path a Google Books match
    usually takes.
    """

    def a_real_book(self, name="the-masque-of-the-red-death-epub3.epub"):
        path = self.folder / name
        shutil.copy(GUTENBERG_DIR / name, path)
        return path

    def google(self):
        """Google's record of the Gutenberg book: a title, an author, no series."""
        return FakeSource(
            found=None,
            candidates=[
                Candidate(
                    source="google_books",
                    title="The Masque of the Red Death",
                    authors=("Edgar Allan Poe",),
                    language="en",
                )
            ],
            name="google_books",
        )

    def test_a_real_book_is_corrected_from_google_books(self):
        path = self.a_real_book()

        outcome = self.corrector(source=self.google()).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.source, "google_books")
        self.assertEqual(read(path).title, "The Masque of the Red Death")
        self.assertEqual(read(path).authors, ("Edgar Allan Poe",))

    def test_no_series_is_written_from_a_source_that_has_none(self):
        path = self.a_real_book()

        self.corrector(source=self.google()).correct(path)

        self.assertEqual(calibre_series(path), (None, None))
        self.assertIsNone(epub3_series(path), "no collection is invented either")
        self.assertEqual(
            [name for name in collections(path).values()],
            [],
            "and nothing was added for the series' sake",
        )

    def test_a_series_the_file_already_had_is_left_alone(self):
        """Not writing a series is not the same as removing one.

        A book that arrived carrying Calibre's series tags keeps them: a source
        with no series data has nothing to say about them, so it says nothing.
        """
        path = write_epub(self.folder / "Cragside.epub", SERIES_ALREADY_ON_IT, version="2.0")

        self.corrector(source=self.google()).correct(path)

        self.assertEqual(calibre_series(path), ("An Old Series", "3"))

    def test_the_log_line_credits_google_books_for_every_value(self):
        path = self.a_real_book()

        outcome = self.corrector(source=self.google()).correct(path)

        self.assertIn("google_books matched", outcome.fragment())
        for change in outcome.changed:
            self.assertEqual(change.source, "google_books")

    def test_the_gutenberg_licence_survives_a_google_books_correction(self):
        path = self.a_real_book()

        self.corrector(source=self.google()).correct(path)

        whole_book = b"".join(entries_of(path).values()).decode("utf-8", "replace")
        self.assertIn("Section 1. General Terms of Use", whole_book)
        self.assertIn("Project Gutenberg License", whole_book)

    def test_a_real_book_is_corrected_from_a_recorded_google_books_reply(self):
        """No stand-in at all: the real client, a real recording, a real EPUB.

        The Gutenberg book carries no ISBN, so it goes down the title path, asks
        Google the question `colophon/googlebooks.py` builds, and takes its title
        and authors from the volume Google actually returned. This is the
        recording in `fixtures/googlebooks/by-title-poe.json`, and nothing here
        is hand-written - which is the point, because a hand-made candidate can
        only ever agree with whatever the client was written to produce.
        """
        path = self.a_real_book()
        replay = ReplayByQuery(**{TITLE_ASKED: "by-title-poe.json"})
        source = GoogleBooks("a-key", transport=replay)

        outcome = self.corrector(source=source).correct(path)

        self.assertEqual(replay.asked, TITLE_ASKED)
        self.assertTrue(outcome.matched, outcome.fragment())
        self.assertEqual(outcome.source, "google_books")
        self.assertEqual(read(path).title, "The Masque of the Red Death")
        self.assertEqual(read(path).authors, ("Edgar Allan Poe",))
        # Google has no series for it, so there is still no series on the book.
        self.assertEqual(calibre_series(path), (None, None))

    def test_the_original_is_kept_before_google_books_values_are_written(self):
        """A record spelling the author differently is a change, so it is backed up.

        The Gutenberg book already says the title Google does, so the author's
        spelling is what moves - and the copy in the backups folder has to be
        the book as it arrived, not as it came out.
        """
        path = self.a_real_book()
        original = path.read_bytes()
        source = FakeSource(
            found=None,
            candidates=[
                Candidate(
                    source="google_books",
                    title="The Masque of the Red Death",
                    authors=("Poe, Edgar Allan",),
                    language="en",
                )
            ],
            name="google_books",
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(self.kept(), [path.name])
        self.assertEqual((self.folder / "backups" / path.name).read_bytes(), original)
        self.assertEqual(read(path).authors, ("Poe, Edgar Allan",))
        self.assertNotEqual(path.read_bytes(), original)


class ARealSourceThroughTheCorrectorTests(CorrectionTestCase):
    """The real source classes, driven by the real corrector.

    Every other test here passes a stand-in, which is what makes them fast and
    readable - and also what let a source whose `by_title` did not accept the
    author go unnoticed until the sources were swapped by hand. A stand-in can
    only ever agree with the corrector about an interface that has already been
    written down; the real classes have to be asked directly.
    """

    def test_the_real_hardcover_answers_the_title_path(self):
        """Hardcover's own recording, replayed to the real client."""
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        source = Hardcover("a-token", transport=Replay("by-title-cragside.json"))

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched, outcome.fragment())
        self.assertEqual(read(path).title, "Cragside")

    def test_the_real_google_books_answers_the_title_path(self):
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        source = GoogleBooks("a-key", transport=GoogleReplay("by-title-cragside.json"))

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched, outcome.fragment())
        self.assertEqual(outcome.source, "google_books")
        self.assertEqual(read(path).title, "Cragside")

    def test_the_real_google_books_answers_the_isbn_path(self):
        """The recording carries the ISBN that was asked about, so it is a match."""
        path = self.book()
        source = GoogleBooks("a-key", transport=GoogleReplay("by-isbn-cragside.json"))

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched, outcome.fragment())
        self.assertEqual(outcome.source, "google_books")

    def test_the_two_real_sources_are_interchangeable_in_the_list(self):
        """Both classes have to satisfy the same interface, or only one works."""
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        sources = (
            Hardcover("a-token", transport=Replay("by-title-cragside.json")),
            GoogleBooks("a-key", transport=GoogleReplay("by-title-cragside.json")),
        )

        for source in sources:
            with self.subTest(source=source.name):
                self.assertTrue(hasattr(source, "name"))
                self.assertEqual(
                    list(inspect.signature(source.by_title).parameters),
                    ["titles", "language", "author"],
                    "the priority list calls every source the same way",
                )

        # The first source in the list answers, and the second is never asked.
        corrector = Corrector(sources=list(sources), backups=self.backups)
        outcome = corrector.correct(path)
        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.source, "hardcover")


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
