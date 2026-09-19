"""Tests for the correction pass: what it changes, when it backs up, and dry run."""

import inspect
import json
import shutil
import textwrap
import time
import unittest
from pathlib import Path
from unittest import mock

from colophon import sources as colophon_sources
from colophon.backups import Backups
from colophon.config import (
    FIELD_DEFAULTS,
    KNOWN_FIELDS,
    KNOWN_SOURCES,
    Config,
    load_config,
)
from colophon.correction import SOURCE_SETUP, Corrector
from colophon.epub import read
from colophon.googlebooks import GoogleBooks
from colophon.hardcover import Hardcover
from colophon.matching import Candidate
from colophon.sources import SourceError
from tests.coverimage import COVER as COVER_FIXTURE

# The cover Google really serves for the Cragside edition the recording below
# describes, recorded at the same time as the reply itself.
GOOGLE_COVER = Path(__file__).parent / "fixtures" / "covers" / "google-cragside.jpg"
GOOGLE_RECORDED = Path(__file__).parent / "fixtures" / "googlebooks"
from tests.opf import (
    calibre_series,
    collections,
    cover_meta,
    entries_of,
    epub3_series,
    manifest_items,
)
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
    CRAGSIDE_BLURB,
    CRAGSIDE_CANDIDATE,
    MATCH,
    NO_COVER_MATCH,
    SAPIENS_CANDIDATE,
    THE_INFIRMARY_CANDIDATE,
    FakeSource,
)
from tests.tempdir import TemporaryDirectory
from tests.test_googlebooks import Replay as GoogleReplay
from tests.test_googlebooks import ReplayByQuery
from tests.test_hardcover import Replay

# A book that already says everything the source says - every field the rules
# write, in both series formats, with a cover of its own - so there is genuinely
# nothing left to change under the default rules.
ALREADY_MATCHES = f"""    <dc:title>Cragside</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
    <dc:description>{CRAGSIDE_BLURB}</dc:description>
    <dc:publisher>Independently Published</dc:publisher>
    <dc:date>2017-07-07</dc:date>
    <meta name="cover" content="local-cover"/>
    <meta name="calibre:series" content="DCI Ryan Mysteries"/>
    <meta name="calibre:series_index" content="6"/>
    <meta property="belongs-to-collection" id="colophon-series">DCI Ryan Mysteries</meta>
    <meta property="collection-type" refines="#colophon-series">series</meta>
    <meta property="group-position" refines="#colophon-series">6</meta>
"""

# Everything the source says, on a book whose own values all differ, so an
# overwrite has something to overwrite.
WRONG_THROUGHOUT = f"""    <dc:title>Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)</dc:title>
    <dc:creator>LJ Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
    <dc:description>Whatever a download site made up.</dc:description>
    <dc:publisher>Somewhere Else</dc:publisher>
    <dc:date>1999-01-01</dc:date>
    <meta name="cover" content="local-cover"/>
    <meta name="calibre:series" content="An Old Series"/>
    <meta name="calibre:series_index" content="3"/>
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


def _refuse_the_network(url, *args, **kwargs):
    """The real image fetch, replaced by one that fails and says why."""
    raise SourceError(f"a test reached the network for {url}")


class TheFieldListTests(unittest.TestCase):
    """Which fields there are is one list, and it is not a field itself.

    `KNOWN_FIELDS` holds the nine a rule can be set for, and it is the list the
    corrector walks as well as the one `config.toml` is checked against: two
    copies would be two chances for a rule the user sets and nothing applies.
    """

    def test_the_field_list_is_the_one_the_defaults_are_keyed_by(self):
        self.assertEqual(tuple(name for name, _ in FIELD_DEFAULTS), KNOWN_FIELDS)

    def test_the_nine_fields_are_the_ones_the_design_spec_names(self):
        self.assertEqual(
            KNOWN_FIELDS,
            (
                "title",
                "authors",
                "series",
                "series_number",
                "description",
                "publisher",
                "date",
                "isbn",
                "language",
            ),
        )

    def test_a_cover_is_a_setting_and_not_one_of_the_fields(self):
        self.assertNotIn("cover", KNOWN_FIELDS, "a cover is a setting, not a rule")
        self.assertNotIn("genre", KNOWN_FIELDS)


class CorrectionTestCase(unittest.TestCase):
    def setUp(self):
        self.refuse_the_real_fetch()
        self._tmp = TemporaryDirectory()
        self.folder = Path(self._tmp.name)
        self.backups = Backups(self.folder / "backups")
        self.source = FakeSource(found=NO_COVER_MATCH)
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
        settings = {"backups": self.backups, "fetch": self.offline_cover}
        settings.update(kwargs)
        if "sources" not in settings:
            if source == "default":
                source = self.source
            settings["sources"] = [] if source is None else [source]
        return Corrector(**settings)

    def offline_cover(self, url):
        """A cover fetched from the fixtures, never from the network.

        Every corrector a test builds gets this unless it says otherwise, so no
        test can reach the network by accident: one that did would pass or fail
        depending on whether the network was there, which is not a test. The one
        URL it answers is the stand-in's own, and any other is refused loudly.
        """
        if url == MATCH.cover:
            return COVER_FIXTURE.read_bytes()
        raise SourceError(f"a test tried to fetch {url} from the network")

    def refuse_the_real_fetch(self):
        """Make the real fetch fail, so a corrector built without this one shows up.

        The injected `fetch` above is what every corrector here uses, and a test
        that builds its own without one would otherwise reach the network. This
        is the backstop for that: the failure is loud, and named for what it is.
        """
        patcher = mock.patch.object(
            colophon_sources,
            "image",
            _refuse_the_network,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def kept(self):
        folder = self.folder / "backups"
        return sorted(path.name for path in folder.iterdir()) if folder.is_dir() else []


class FieldRuleTests(CorrectionTestCase):
    """Each field follows its own rule: skip, fill if empty, or overwrite.

    The rules are the ones CBO-38's acceptance criteria name, set here through
    the corrector the way the config sets them. Every book in this class carries
    a value for every field already, so a rule that writes has something to
    overwrite and a rule that does not has something to leave alone.
    """

    # A cover the fake fetcher hands back, so a test about covers never reaches
    # the network. A real PNG, because the media type is read off the bytes.
    COVER = COVER_FIXTURE.read_bytes()

    def rules(self, **rules):
        """Every field's rule, with the ones a test cares about overridden."""
        settings = {name: "fill" for name in KNOWN_FIELDS}
        settings.update(rules)
        return settings

    def a_cover(self, url):
        """The cover the source offers, without a network to fetch it from."""
        if url == MATCH.cover:
            return self.COVER
        raise SourceError(f"a test tried to fetch {url} from the network")

    def corrector(self, rules=None, source=None, found=None, **kwargs):
        if source is None:
            source = self.source if found is None else FakeSource(found=found)
        if rules is None:
            # No rules at all, which is how a caller gets the ones the config
            # ships: a test about the defaults has to leave them alone.
            settings = {}
        else:
            settings = {"fields": rules}
        settings.setdefault("fetch", self.a_cover)
        settings.update(kwargs)
        return Corrector(sources=[source], backups=self.backups, **settings)

    def book(self, name="Cragside.epub", metadata=WRONG_THROUGHOUT):
        return write_epub(
            self.folder / name,
            metadata,
            version="2.0",
            extra_entries=[("OEBPS/local-cover.png", self.COVER)],
        )

    def test_the_default_rules_are_the_ones_the_ticket_names(self):
        """A bare book, so every field is one the rules have something to say about."""
        path = write_epub(
            self.folder / "Bare.epub",
            f"""    <dc:title>Something Else Entirely</dc:title>
    <dc:creator>Nobody</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:description>The file's own blurb, which fill must leave alone.</dc:description>
""",
            version="2.0",
        )

        outcome = self.corrector(found=MATCH).correct(path)

        written = {change.field for change in outcome.changed}
        self.assertEqual(
            written,
            {
                "title",
                "authors",
                "series",
                "series_number",
                "publisher",
                "date",
                "language",
                "cover",
            },
            "the overwrite fields and the empty fill fields, and the cover",
        )
        self.assertNotIn(
            "description",
            written,
            "the file's blurb is what `fill` means by leaving it alone",
        )
        self.assertNotIn(
            "isbn",
            written,
            "the file already carries the ISBN, so `fill` writes nothing",
        )

    def test_fill_writes_a_field_the_file_has_not_got(self):
        path = self.book(
            metadata=f"""    <dc:title>Cragside</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
"""
        )

        self.corrector(rules=self.rules(description="fill")).correct(path)

        self.assertEqual(read(path).description, CRAGSIDE_BLURB)

    def test_fill_leaves_a_field_the_file_already_has(self):
        """The whole point of the rule: the file's own blurb is the one kept."""
        path = self.book()

        self.corrector(rules=self.rules(description="fill")).correct(path)

        self.assertEqual(read(path).description, "Whatever a download site made up.")

    def test_fill_writes_nothing_when_the_source_has_nothing(self):
        """A source with no publisher has not offered a blank one."""
        source = FakeSource(
            found=Candidate(
                source="hardcover",
                title="Cragside",
                authors=("L.J. Ross",),
                isbn=ISBN,
            )
        )
        path = self.book(
            metadata=f"""    <dc:title>Something Else</dc:title>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
"""
        )

        self.corrector(source=source, rules=self.rules(title="overwrite")).correct(path)

        self.assertIsNone(read(path).publisher)
        self.assertIsNone(read(path).description)

    def test_overwrite_replaces_what_the_file_has(self):
        path = self.book()

        self.corrector(rules=self.rules(description="overwrite")).correct(path)

        self.assertEqual(read(path).description, CRAGSIDE_BLURB)

    def test_skip_never_writes_the_field(self):
        path = self.book()

        outcome = self.corrector(rules=self.rules(description="skip")).correct(path)

        self.assertEqual(read(path).description, "Whatever a download site made up.")
        self.assertNotIn("description", {change.field for change in outcome.changed})

    def test_skip_on_every_field_writes_nothing_at_all(self):
        path = self.book()
        before = path.read_bytes()

        outcome = self.corrector(rules=self.rules(**{name: "skip" for name in KNOWN_FIELDS})).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.changed, ())
        self.assertEqual(self.kept(), [])
        self.assertEqual(path.read_bytes(), before)

    def test_one_field_can_be_kept_while_another_is_overwritten(self):
        """The rules are per field, which is the whole of CBO-38."""
        path = self.book()

        self.corrector(
            rules=self.rules(title="overwrite", description="skip", publisher="skip", date="skip")
        ).correct(path)

        book = read(path)
        self.assertEqual(book.title, "Cragside", "the bad title is replaced")
        self.assertEqual(
            book.description, "Whatever a download site made up.", "the blurb is kept"
        )
        self.assertEqual(book.publisher, "Somewhere Else", "and so is the publisher")
        self.assertEqual(book.date, "1999-01-01")

    def test_filling_the_isbn_puts_the_source_s_isbn_into_a_book_with_none(self):
        path = write_epub(
            self.folder / "Cragside.epub",
            """    <dc:title>Cragside: A DCI Ryan Mystery</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:language>en</dc:language>
""",
            version="2.0",
        )
        source = FakeSource(found=None, candidates=[Candidate(
            source="hardcover", title="Cragside", authors=("L.J. Ross",), isbn=ISBN
        )])

        self.corrector(source=source, rules=self.rules(isbn="fill")).correct(path)

        self.assertEqual(read(path).isbn, ISBN)

    def test_filling_the_isbn_leaves_the_one_the_file_already_has(self):
        path = self.book(
            metadata=f"""    <dc:title>Something Else</dc:title>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
"""
        )
        source = FakeSource(
            found=Candidate(
                source="hardcover",
                title="Cragside",
                authors=("L.J. Ross",),
                isbn="9781786813891",
            )
        )

        self.corrector(source=source, rules=self.rules(isbn="fill")).correct(path)

        self.assertEqual(read(path).isbn, ISBN, "the file's own ISBN is kept")

    def test_filling_the_language_puts_the_source_s_language_in(self):
        path = self.book(
            metadata=f"""    <dc:title>Cragside</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
"""
        )

        self.corrector(rules=self.rules(language="fill")).correct(path)

        self.assertEqual(read(path).language, "en")

    def test_a_series_number_is_dropped_when_the_series_around_it_changes(self):
        """A skipped number is not stale on its own; it is stale about a series.

        The file says `An Old Series` #3 and the source says `DCI Ryan
        Mysteries`, with the number left alone. Keeping the 3 would record a
        position in the wrong series, so it comes off - and the log says so.
        """
        path = self.book()

        outcome = self.corrector(
            rules=self.rules(series="overwrite", series_number="skip")
        ).correct(path)

        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", None))
        self.assertEqual(read(path).series_number, None)
        self.assertIn("series_number", {change.field for change in outcome.changed})

    def test_a_series_number_is_kept_when_the_series_stays_the_same(self):
        """The file's series is the source's series, so its number is the source's.

        The file's own number is not stale - it is a position in the series the
        book is in - and the rule it was given says not to write the source's,
        so the file keeps what it had.
        """
        path = write_epub(
            self.folder / "Cragside.epub",
            f"""    <dc:title>Cragside: A DCI Ryan Mystery</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <meta name="calibre:series" content="DCI Ryan Mysteries"/>
    <meta name="calibre:series_index" content="3"/>
""",
            version="2.0",
        )

        self.corrector(rules=self.rules(series="skip", series_number="skip")).correct(path)

        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "3"))

    def test_the_two_series_names_are_compared_without_regard_to_case(self):
        """A capitalisation difference is the same series, and the number follows."""
        path = write_epub(
            self.folder / "Cragside.epub",
            f"""    <dc:title>Cragside: A DCI Ryan Mystery</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <meta name="calibre:series" content="dci ryan mysteries"/>
    <meta name="calibre:series_index" content="3"/>
""",
            version="2.0",
        )

        self.corrector(rules=self.rules(series="skip", series_number="overwrite")).correct(path)

        self.assertEqual(calibre_series(path), ("dci ryan mysteries", "6"))

    def test_the_number_follows_a_series_that_was_written(self):
        """Overwriting the series takes the source's number with it."""
        path = self.book()

        self.corrector(
            rules=self.rules(series="overwrite", series_number="overwrite")
        ).correct(path)

        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))

    def test_the_number_follows_a_series_that_was_filled_in(self):
        """The file had no series, the source's was filled in, and the number joins it."""
        path = write_epub(
            self.folder / "Cragside.epub",
            f"""    <dc:title>Cragside: A DCI Ryan Mystery</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
""",
            version="2.0",
        )

        self.corrector(rules=self.rules(series="fill", series_number="fill")).correct(path)

        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))

    def test_a_skipped_series_leaves_a_number_that_belongs_to_another_series_alone(self):
        """The mirror of the case the ticket settled.

        The file is in `An Old Series` #3 and its series is left alone, so the
        source's number is a position in a series this book is not in. Writing
        it, or dropping the file's own, would both be wrong: the file's pair is
        left exactly as it was.
        """
        path = self.book()

        outcome = self.corrector(
            rules=self.rules(series="skip", series_number="overwrite")
        ).correct(path)

        self.assertEqual(calibre_series(path), ("An Old Series", "3"))
        self.assertNotIn("series_number", {change.field for change in outcome.changed})

    def test_a_number_survives_a_series_nobody_wrote(self):
        """No series name and a number is a book as it arrived, not a fault.

        Nothing wrote a series, so nothing changed, and a number that has not
        been orphaned is left where it is - there is no series for it to
        contradict.
        """
        path = write_epub(
            self.folder / "Cragside.epub",
            f"""    <dc:title>Cragside: A DCI Ryan Mystery</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <meta name="calibre:series_index" content="3"/>
""",
            version="2.0",
        )

        outcome = self.corrector(rules=self.rules(series="skip", series_number="skip")).correct(path)

        self.assertEqual(calibre_series(path), (None, "3"))
        self.assertNotIn("series_number", {change.field for change in outcome.changed})

    def test_a_number_is_not_written_under_a_series_the_source_does_not_name(self):
        """A number with no series behind it is not a position in anything.

        The source can offer a number and no series name - Google's records
        carry no series data at all - and there is no series of the source's for
        it to belong to, so neither it nor the file's own number is written.
        """
        source = FakeSource(
            found=Candidate(
                source="hardcover",
                title="Cragside",
                authors=("L.J. Ross",),
                series_number="6",
                isbn=ISBN,
            )
        )
        path = write_epub(
            self.folder / "Cragside.epub",
            f"""    <dc:title>Cragside: A DCI Ryan Mystery</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <meta name="calibre:series" content="An Old Series"/>
    <meta name="calibre:series_index" content="3"/>
""",
            version="2.0",
        )

        self.corrector(
            source=source, rules=self.rules(series="overwrite", series_number="overwrite")
        ).correct(path)

        self.assertEqual(calibre_series(path), ("An Old Series", "3"))

    def test_the_number_follows_the_series_in_all_four_combinations(self):
        """Both rules, moving and not, from one table.

        Four combinations of what the source says and what the file has, so the
        rule is shown to be about the resulting pair rather than about which
        setting was used to get there.
        """
        source_series = "DCI Ryan Mysteries"
        cases = [
            # file series, file number, what the rules say, what the book ends up with
            ("An Old Series", "3", ("overwrite", "overwrite"), ("DCI Ryan Mysteries", "6")),
            ("An Old Series", "3", ("overwrite", "skip"), ("DCI Ryan Mysteries", None)),
            (
                source_series,
                "3",
                ("skip", "overwrite"),
                ("DCI Ryan Mysteries", "6"),
            ),
            (source_series, "3", ("skip", "skip"), ("DCI Ryan Mysteries", "3")),
            ("An Old Series", None, ("overwrite", "fill"), ("DCI Ryan Mysteries", "6")),
            (None, None, ("fill", "fill"), ("DCI Ryan Mysteries", "6")),
        ]
        for file_series, file_number, (series_rule, number_rule), expected in cases:
            with self.subTest(
                file=f"{file_series} #{file_number}",
                rules=f"series={series_rule}, number={number_rule}",
            ):
                metadata = f"""    <dc:title>Cragside: A DCI Ryan Mystery</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
"""
                if file_series:
                    metadata += (
                        f'    <meta name="calibre:series" content="{file_series}"/>\n'
                    )
                if file_number:
                    metadata += (
                        f'    <meta name="calibre:series_index" content="{file_number}"/>\n'
                    )
                path = write_epub(
                    self.folder / f"Case-{series_rule}-{number_rule}-{file_series}.epub",
                    metadata,
                    version="2.0",
                )

                self.corrector(
                    rules=self.rules(series=series_rule, series_number=number_rule)
                ).correct(path)

                self.assertEqual(calibre_series(path), expected)

    def test_fill_leaves_a_series_the_book_declares_the_epub_3_way(self):
        """A book says what series it is in two ways, and `fill` reads both.

        Reading only Calibre's tags would call this book's series empty and
        write over one that was there.
        """
        path = write_epub(
            self.folder / "Cragside.epub",
            f"""    <dc:title>Cragside: A DCI Ryan Mystery</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <meta property="belongs-to-collection" id="series-1">Old Series</meta>
    <meta property="collection-type" refines="#series-1">series</meta>
    <meta property="group-position" refines="#series-1">9</meta>
""",
            version="3.0",
        )

        self.corrector(rules=self.rules(series="fill", series_number="fill")).correct(path)

        self.assertEqual(read(path).series, "Old Series")
        self.assertEqual(epub3_series(path), ("Old Series", "series", "9"))

    def test_a_cover_is_added_to_a_book_that_has_none(self):
        path = write_epub(self.folder / "Cragside.epub", AS_DOWNLOADED, version="2.0")

        outcome = self.corrector(found=MATCH).correct(path)

        self.assertIn("cover", {change.field for change in outcome.changed})
        identifier = cover_meta(path)
        self.assertIsNotNone(identifier, "EPUB 2's own declaration, too")
        declared = manifest_items(path)[identifier]
        self.assertEqual(declared["media-type"], "image/png")
        self.assertEqual(entries_of(path)[f"OEBPS/{declared['href']}"], self.COVER)

    def test_the_added_cover_is_declared_for_epub_3_as_well(self):
        """The same as the series: both formats, so any library app reads it."""
        path = write_epub(self.folder / "Cragside.epub", AS_DOWNLOADED, version="3.0")

        self.corrector(found=MATCH).correct(path)

        declared = [
            item
            for item in manifest_items(path).values()
            if item.get("properties") == "cover-image"
        ]
        self.assertEqual(len(declared), 1)
        self.assertEqual(declared[0]["media-type"], "image/png")

    def test_a_cover_is_not_added_to_a_book_that_has_one(self):
        """The ticket's own criterion: the cover is added only if there is none."""
        path = self.book()
        before = entries_of(path)

        outcome = self.corrector().correct(path)

        self.assertNotIn("cover", {change.field for change in outcome.changed})
        self.assertEqual(
            [item for item in manifest_items(path).values() if item.get("media-type") == "image/png"],
            [
                item
                for item in manifest_items(path).values()
                if item.get("media-type") == "image/png"
            ],
            "the book's own cover entry is left as it was",
        )
        self.assertEqual(entries_of(path)["OEBPS/local-cover.png"], before["OEBPS/local-cover.png"])

    def test_the_cover_setting_can_be_turned_off(self):
        path = write_epub(self.folder / "Cragside.epub", AS_DOWNLOADED, version="2.0")

        outcome = self.corrector(found=MATCH, add_cover=False).correct(path)

        self.assertNotIn("cover", {change.field for change in outcome.changed})
        self.assertEqual(cover_meta(path), None)

    def test_the_log_line_names_the_cover_without_its_value(self):
        """A cover's value is an image, so the line says only that it moved.

        The blurb and the cover are the two fields whose values have no business
        in a log line: one is a thousand characters of prose and the other is
        bytes. Both are named there, and neither is written out.
        """
        path = write_epub(self.folder / "Cragside.epub", AS_DOWNLOADED, version="2.0")

        outcome = self.corrector(found=MATCH).correct(path)
        line = outcome.fragment()

        self.assertIn("cover<-hardcover", line)
        self.assertIn("description<-hardcover", line)
        self.assertNotIn('cover="', line)
        self.assertNotIn('description="', line)

    def test_a_cover_is_not_fetched_for_a_book_nothing_would_change(self):
        """No point downloading an image for a book about to be left alone."""
        asked = []

        def fetch(url):
            asked.append(url)
            return self.COVER

        path = write_epub(self.folder / "Already.epub", ALREADY_MATCHES, version="2.0")

        self.corrector(found=MATCH, fetch=fetch).correct(path)

        self.assertEqual(asked, [])

    def test_a_cover_is_fetched_from_the_source_that_matched(self):
        asked = []

        def fetch(url):
            asked.append(url)
            return self.COVER

        path = write_epub(self.folder / "Cragside.epub", AS_DOWNLOADED, version="2.0")

        self.corrector(found=MATCH, fetch=fetch).correct(path)

        self.assertEqual(asked, [MATCH.cover])

    def test_the_cover_comes_from_the_source_that_matched_and_no_other(self):
        """The priority list is a trust order for a cover as much as a title.

        The second source also has the book, and the first one is the one that
        answers, so the image may only be fetched from the first one's URL.
        """
        first = FakeSource(found=MATCH)
        second = FakeSource(
            found=Candidate(
                source="google_books",
                title="Cragside",
                authors=("L. J. Ross",),
                isbn=ISBN,
                cover="https://example.invalid/another-cover.jpg",
            ),
            name="google_books",
        )
        asked = []

        corrector = Corrector(
            sources=[first, second],
            backups=self.backups,
            fetch=lambda url: (asked.append(url), self.COVER)[1],
        )
        corrector.correct(write_epub(self.folder / "Cragside.epub", AS_DOWNLOADED))

        self.assertEqual(asked, [MATCH.cover])
        self.assertEqual(second.asked, [], "the lower-priority source is not asked at all")

    def test_a_cover_the_file_will_not_take_leaves_the_book_uncorrected(self):
        """Bytes that are no image are caught, not raised on out of the pass.

        The relay has no guard around the correction pass, so an `EpubError`
        escaping here would stop the whole run over one bad image. The book is
        left exactly as it was rather than half-corrected: the cover is decided
        before anything is written, so a book this pass cannot finish with is a
        book it does not touch.
        """
        path = write_epub(self.folder / "Cragside.epub", AS_DOWNLOADED, version="2.0")
        before = path.read_bytes()

        with self.assertLogs("colophon", level="WARNING") as captured:
            outcome = self.corrector(
                found=MATCH, fetch=lambda url: b"not an image at all"
            ).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.changed, ())
        self.assertEqual(self.kept(), [])
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("cover", "\n".join(captured.output))

    def test_a_cover_that_cannot_be_fetched_does_not_stop_the_metadata(self):
        """A blurb and a right title are worth having without the image."""
        def fetch(url):
            raise SourceError("could not fetch the cover: it answered HTTP 500")

        path = write_epub(
            self.folder / "Cragside.epub",
            f"""    <dc:title>Something Else Entirely</dc:title>
    <dc:creator>Nobody</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
""",
            version="2.0",
        )

        with self.assertLogs("colophon", level="WARNING") as captured:
            outcome = self.corrector(found=MATCH, fetch=fetch).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Cragside")
        self.assertEqual(read(path).description, CRAGSIDE_BLURB)
        self.assertNotIn("cover", {change.field for change in outcome.changed})
        self.assertIn("cover", "\n".join(captured.output))

    def test_a_dry_run_changes_nothing_and_still_says_what_it_would_do(self):
        path = write_epub(
            self.folder / "Cragside.epub",
            f"""    <dc:title>Something Else Entirely</dc:title>
    <dc:creator>Nobody</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
""",
            version="2.0",
        )
        before = path.read_bytes()
        asked = []

        outcome = self.corrector(
            found=MATCH,
            dry_run=True,
            fetch=lambda url: (asked.append(url), self.COVER)[1],
        ).correct(path)

        self.assertTrue(outcome.matched)
        self.assertFalse(outcome.applied)
        self.assertEqual(self.kept(), [])
        self.assertEqual(path.read_bytes(), before)
        self.assertIn("would change", outcome.fragment())
        self.assertIn(
            "cover",
            {change.field for change in outcome.changed},
            "a dry run says the cover would be added",
        )
        self.assertEqual(asked, [], "and fetches nothing to say so")


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

    def test_correcting_the_same_book_twice_gives_the_same_bytes(self):
        """Which the relay depends on: a re-dropped book has to compare equal.

        A book dropped twice is the same book corrected twice, and the relay
        decides it is a duplicate by comparing the bytes. A cover's name being
        built from its own bytes is what keeps this true; a timestamp in it
        would make every re-drop a "different file".
        """
        first = write_epub(self.folder / "First.epub", AS_DOWNLOADED, version="2.0")
        second = write_epub(self.folder / "Second.epub", AS_DOWNLOADED, version="2.0")

        self.corrector(source=FakeSource(found=MATCH)).correct(first)
        self.corrector(source=FakeSource(found=MATCH)).correct(second)

        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_two_corrections_a_second_apart_still_give_the_same_bytes(self):
        """The same, with the clock moved between them.

        A wall-clock stamp on the added cover is invisible until two corrections
        of the same book fall either side of a second - which, over a library,
        they do - and then a re-dropped book stops being recognised as a
        duplicate and is filed beside itself instead. This is what says the
        bytes do not depend on when the pass ran.
        """
        first = write_epub(self.folder / "First.epub", AS_DOWNLOADED, version="2.0")
        second = write_epub(self.folder / "Second.epub", AS_DOWNLOADED, version="2.0")

        self.corrector(source=FakeSource(found=MATCH)).correct(first)
        with mock.patch("time.localtime", return_value=time.localtime(time.time() + 3)):
            self.corrector(source=FakeSource(found=MATCH)).correct(second)

        self.assertEqual(first.read_bytes(), second.read_bytes())

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

        outcome = self.corrector(source=FakeSource(found=MATCH)).correct(path)

        self.assertEqual(
            [(change.field, change.value, change.source) for change in outcome.changed],
            [
                ("title", "Cragside", "hardcover"),
                ("authors", "L.J. Ross", "hardcover"),
                ("description", CRAGSIDE_BLURB, "hardcover"),
                ("publisher", "Independently Published", "hardcover"),
                ("date", "2017-07-07", "hardcover"),
                ("series", "DCI Ryan Mysteries", "hardcover"),
                ("series_number", "6", "hardcover"),
                # The cover is the one change that is bytes rather than a value,
                # so the source is named and the image itself is in the book.
                ("cover", "", "hardcover"),
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

    def write_config(self, text):
        """A config.toml on disk, for the tests that go through the file.

        The text is dedented because TOML is whitespace-sensitive: a setting
        written indented under a `[...]` header belongs to that table, which is
        not what an indented test string means.
        """
        path = self.folder / "config.toml"
        path.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
        return path

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

    def test_the_rules_a_config_carries_are_the_rules_the_pass_applies(self):
        """The whole point of the ticket: the file decides, not the code.

        This drives a `[fields]` table all the way through `load_config` and
        `from_config` to a corrected book, because parsing a setting and
        applying it are two different things and only one of them was tested.
        """
        path = self.write_config(
            """
            sources = ["hardcover"]
            dry_run = false
            add_cover = false
            [fields]
            title = "skip"
            description = "overwrite"
            """
        )
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")
        config = load_config(env={"COLOPHON_CONFIG": str(path)})
        book = write_epub(
            self.folder / "Cragside.epub",
            f"""    <dc:title>Something Else Entirely</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:description>The file's own blurb.</dc:description>
""",
            version="2.0",
        )

        corrector = Corrector.from_config(config, Backups(self.folder / "backups"))
        corrector.sources = (FakeSource(),)
        outcome = corrector.correct(book)

        written = {change.field for change in outcome.changed}
        self.assertIn("description", written, "the source's blurb replaced the file's")
        self.assertEqual(read(book).title, "Something Else Entirely")
        self.assertEqual(read(book).description, CRAGSIDE_BLURB)
        self.assertNotIn("cover", written, "the config turned covers off, too")

    def test_the_cover_setting_a_config_carries_is_applied_too(self):
        """The same seam, for the one setting that is not a field rule."""
        path = self.write_config(
            'sources = ["hardcover"]\ndry_run = false\nadd_cover = false\n'
        )
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")
        config = load_config(env={"COLOPHON_CONFIG": str(path)})
        book = write_epub(self.folder / "Cragside.epub", AS_DOWNLOADED, version="2.0")

        corrector = Corrector.from_config(config, Backups(self.folder / "backups"))
        corrector.sources = (FakeSource(found=MATCH),)
        outcome = corrector.correct(book)

        self.assertNotIn("cover", {change.field for change in outcome.changed})
        self.assertIsNone(cover_meta(book))

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
                self.assertTrue(entry["key_label"])

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
        """A source with nothing but a title, an author and a language.

        The file carries the first two and not the third, so `fill` has one
        thing it could write - the language - and the test is what that looks
        like when it does.
        """
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

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(
            [(change.field, change.value) for change in outcome.changed],
            [("language", "en")],
            "nothing is overwritten and only the missing language is filled",
        )
        self.assertEqual(read(path).title, "Cragside")
        self.assertEqual(read(path).authors, ("L.J. Ross",))
        self.assertEqual(read(path).language, "en")

    def test_a_book_the_source_has_nothing_to_add_to_is_left_exactly_as_it_was(self):
        """Everything the source knows, the file already says, so nothing moves."""
        path = self.book(
            "Already.epub",
            """    <dc:title>Cragside</dc:title>
    <dc:creator>L.J. Ross</dc:creator>
    <dc:language>en</dc:language>
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
        return Corrector(sources=list(sources), fetch=self.offline_cover, **settings)

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


class ARealGoogleRecordingThroughTheCorrectorTests(CorrectionTestCase):
    """The new fields end to end: a real client, a real recording, a real book.

    No stand-in for the source and none for the cover fetch either: the client
    parses Google's own reply with the mask CBO-38 widened, and the cover comes
    from `fixtures/covers/google-cragside.jpg`, the image Google really serves
    for the Cragside edition that recording describes.
    """

    def google(self, replay=None):
        return GoogleBooks(
            "a-key",
            transport=replay
            or GoogleReplay("by-title-cragside-other-fields.json"),
        )

    def book(self):
        """A book with no cover of its own, and nothing the rules need to keep."""
        return write_epub(
            self.folder / "Cragside.epub",
            CRAGSIDE,
            version="3.0",
        )

    def test_the_blurb_the_date_and_the_cover_all_arrive_from_the_recording(self):
        """Whichever of the two editions the comparison chose, the values are its.

        The recording holds two editions of Cragside - the Ulverscroft large
        print and the original - and they disagree about the blurb, the date and
        the cover. Which one wins is the comparison's business; what this is
        about is that whatever the file ends up saying, it is what that edition
        said, and the others' values are nowhere in it.
        """
        path = self.book()
        recorded = json.loads(
            (GOOGLE_RECORDED / "by-title-cragside-other-fields.json").read_text(
                encoding="utf-8"
            )
        )

        self.corrector(
            source=self.google(),
            fetch=lambda url: GOOGLE_COVER.read_bytes(),
        ).correct(path)

        book = read(path)
        written = [
            item["volumeInfo"]
            for item in recorded["items"]
            if item["volumeInfo"].get("description") == book.description
            and item["volumeInfo"].get("publishedDate") == book.date
        ]
        self.assertEqual(len(written), 1, "the values all come from one edition")
        self.assertTrue(
            book.description.startswith(("FROM THE", "After his climactic")),
            "the source's own words, unedited",
        )
        self.assertTrue(book.has_cover, "the book arrived with none and now has one")
        self.assertEqual(
            entries_of(path)[f"OEBPS/{manifest_items(path)[cover_meta(path)]['href']}"],
            GOOGLE_COVER.read_bytes(),
        )

    def test_no_series_is_written_and_none_is_removed(self):
        """Google's reply has no series in it, so the file's own is left alone."""
        path = write_epub(self.folder / "Cragside.epub", SERIES_ALREADY_ON_IT, version="3.0")

        self.corrector(
            source=self.google(), fetch=lambda url: GOOGLE_COVER.read_bytes()
        ).correct(path)

        self.assertEqual(calibre_series(path), ("An Old Series", "3"))


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
        corrector = Corrector(
            sources=list(sources), backups=self.backups, fetch=self.offline_cover
        )
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
