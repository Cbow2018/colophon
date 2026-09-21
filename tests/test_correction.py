"""Tests for the correction pass: what it changes, when it backs up, and dry run."""

import inspect
import json
import re
import shutil
import textwrap
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock

from colophon import epub as colophon_epub
from colophon import matching as colophon_matching
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
from colophon.epub import EpubError, read
from colophon.googlebooks import GoogleBooks
from colophon.hardcover import Hardcover
from colophon.llm import Llm
from colophon.matching import Bands, Candidate
from colophon.record import AUTHOR, BY_NAME, Record
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
    subjects,
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
    THE_INFIRMARY,
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
from tests.test_llm import Replay as LlmReplay
from tests.test_llm import today

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

# What the unverified marker is made of, as the design spec spells it. Held here
# rather than imported, so a test cannot agree with the code by sharing its
# constant: the value is the spec's, not the implementation's.
UNVERIFIED_TAG = "colophon:unverified"
UNVERIFIED_SENTENCE = "Metadata could not be verified by Colophon."

# A candidate that agrees on both halves and still falls short of the threshold.
# Its title is the file's own with the bracket taken off, so §3.3 scores the two
# full titles as identical (1.0000) and L.J. Ross is the file's author (1.0000);
# the record claims position 11 where the file's title claims 6, which §2 weighs
# at 0.20 over a 2.00 denominator, leaving 0.9070. That is the shape of a near
# miss - which is why a source cannot be asked for one, since Hardcover answers
# only titles it spells exactly.
A_NEAR_MISS = Candidate(
    source="hardcover",
    title="Cragside: A DCI Ryan Mystery",
    authors=("L.J. Ross",),
    series_number="11",
    language="en",
)

# The same near miss with §2's year in play as well: the file below carries a
# date and so does the record, so the denominator is the full 2.15 and the score
# is §2.1 row 4's own 0.9070 rather than the 0.90 a file with no date gets.
A_NEAR_MISS_WITH_A_YEAR = Candidate(
    source="hardcover",
    title="Cragside: A DCI Ryan Mystery",
    authors=("L.J. Ross",),
    series_number="11",
    date="2017-07-07",
    language="en",
)

# The no-ISBN Cragside with its date on it, which is what puts the year into the
# comparison: §4.1's singleton bar is about a pool of one, and 0.9070 is what a
# near miss scores when the file states everything the record does but the
# series position.
CRAGSIDE_DATED = """    <dc:title>Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)</dc:title>
    <dc:creator>L. J. Ross</dc:creator>
    <dc:date>2017-07-07</dc:date>
    <dc:language>en</dc:language>
"""


def same_book_with(blurb):
    """The no-ISBN Cragside, with this blurb on it and its markup escaped.

    A real `dc:description` holding an HTML blurb has that blurb's own angle
    brackets escaped in the file, so a fixture that wrote them raw would be an
    unreadable package document rather than a book with an HTML blurb.
    """
    held = blurb.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return CRAGSIDE.replace(
        "<dc:language>en</dc:language>",
        f"<dc:language>en</dc:language>\n    <dc:description>{held}</dc:description>",
    )


def unmarked_entries(path):
    """The book's entries with Colophon's unverified mark taken off it.

    A marked book is not the book it arrived as, so a test that means "nothing
    else about this file changed" has to say what "else" excludes - and it is
    exactly the mark: the tag, the sentence, and nothing more.

    The package document comes back as text with the mark cut out; every other
    entry is returned byte for byte. Read out of the zip by hand rather than
    through the code under test, so a failure here is a failure of the write and
    not of a reader that agrees with it.
    """
    entries = entries_of(path)
    opf = next(name for name in entries if name.endswith(".opf"))

    # The mark, in each of the shapes it takes. The description goes entirely
    # when the sentence was all of it, which is what the writer does for a book
    # with no blurb of its own.
    text = entries[opf].decode("utf-8")
    text = re.sub(rf"\s*<dc:subject>{re.escape(UNVERIFIED_TAG)}</dc:subject>", "", text)
    text = text.replace(f"\n\n{UNVERIFIED_SENTENCE}", "")
    text = re.sub(
        rf"\s*<dc:description>{re.escape(UNVERIFIED_SENTENCE)}</dc:description>",
        "",
        text,
    )
    text = text.replace(f"<p>{UNVERIFIED_SENTENCE}</p>", "")

    found = dict(entries)
    found[opf] = text.encode("utf-8")
    return found


def same_book(one, other):
    """Whether two sets of entries are the same book, the package document aside.

    Every entry but the package document is compared byte for byte. The package
    document is compared as a tree, because a book anything is written to has it
    re-serialised - ElementTree's declaration, its element order, its self-closing
    tags - and that happens for every correction. Failing a test about the mark on
    a difference the writer makes to every book would be testing the wrong thing.
    """
    if set(one) != set(other):
        return False
    for name in one:
        if not name.endswith(".opf") and one[name] != other[name]:
            return False
    return _as_tree(one) == _as_tree(other)


def _as_tree(entries):
    """The package document as a tree, insensitive to how it is spelt.

    The prefixes are made uniform, and the whitespace *between* elements is
    dropped: a document that had an element taken out of it is left with the
    blank line that element sat on, and that is not a difference in what the book
    says. Text inside an element is kept, because that is the metadata.
    """
    opf = next(name for name in entries if name.endswith(".opf"))
    body = entries[opf]
    colophon_epub._keep_namespace_prefixes(body)
    root = ET.fromstring(body)
    for element in root.iter():
        if not (element.text or "").strip():
            element.text = None
        if not (element.tail or "").strip():
            element.tail = None
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


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
        return write_epub(
            self.folder / name, AS_DOWNLOADED, version="2.0", content=content
        )

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

        outcome = self.corrector(
            rules=self.rules(**{name: "skip" for name in KNOWN_FIELDS})
        ).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.changed, ())
        self.assertEqual(self.kept(), [])
        self.assertEqual(path.read_bytes(), before)

    def test_one_field_can_be_kept_while_another_is_overwritten(self):
        """The rules are per field, which is the whole of CBO-38."""
        path = self.book()

        self.corrector(
            rules=self.rules(
                title="overwrite", description="skip", publisher="skip", date="skip"
            )
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
        source = FakeSource(
            found=None,
            candidates=[
                Candidate(
                    source="hardcover",
                    title="Cragside",
                    authors=("L.J. Ross",),
                    isbn=ISBN,
                )
            ],
        )

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

        self.corrector(rules=self.rules(series="skip", series_number="skip")).correct(
            path
        )

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

        self.corrector(
            rules=self.rules(series="skip", series_number="overwrite")
        ).correct(path)

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

        self.corrector(rules=self.rules(series="fill", series_number="fill")).correct(
            path
        )

        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))

    def test_a_skipped_series_leaves_a_number_that_belongs_to_another_series_alone(
        self,
    ):
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

        outcome = self.corrector(
            rules=self.rules(series="skip", series_number="skip")
        ).correct(path)

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
            source=source,
            rules=self.rules(series="overwrite", series_number="overwrite"),
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
            (
                "An Old Series",
                "3",
                ("overwrite", "overwrite"),
                ("DCI Ryan Mysteries", "6"),
            ),
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
                    metadata += f'    <meta name="calibre:series_index" content="{file_number}"/>\n'
                path = write_epub(
                    self.folder
                    / f"Case-{series_rule}-{number_rule}-{file_series}.epub",
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

        self.corrector(rules=self.rules(series="fill", series_number="fill")).correct(
            path
        )

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
            [
                item
                for item in manifest_items(path).values()
                if item.get("media-type") == "image/png"
            ],
            [
                item
                for item in manifest_items(path).values()
                if item.get("media-type") == "image/png"
            ],
            "the book's own cover entry is left as it was",
        )
        self.assertEqual(
            entries_of(path)["OEBPS/local-cover.png"], before["OEBPS/local-cover.png"]
        )

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
        self.assertEqual(
            second.asked, [], "the lower-priority source is not asked at all"
        )

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
        self.assertEqual(
            (self.folder / "backups" / "Cragside.epub").read_bytes(), before
        )
        self.assertNotEqual(path.read_bytes(), before)

    def test_a_kepub_is_corrected_the_same_way(self):
        path = self.book(name="Cragside.kepub.epub", content=KEPUB_CHAPTER)

        outcome = self.corrector().correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Cragside")
        self.assertIn(
            'class="koboSpan"', entries_of(path)["OEBPS/chapter.xhtml"].decode()
        )

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
        # a test about the other one's key being absent. The LLM's key file is
        # pointed at a path under the temporary folder for the same reason: it is
        # absent either way, but not at the real `/run/secrets` path.
        settings = {
            "hardcover_token_file": self.folder / "hardcover_token",
            "google_books_key_file": self.folder / "google_books_key",
            "llm_key_file": self.folder / "llm_key",
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

        self.assertEqual(
            [source.name for source in corrector.sources], ["google_books"]
        )

    def test_a_custom_endpoint_with_no_key_is_not_reported_as_no_llm(self):
        """ "No LLM key at …" is about a preset that needed one. A custom endpoint
        is used without a key, so saying the LLM is not set up would be a lie."""
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")

        with self.assertLogs("colophon", level="INFO") as captured:
            corrector = Corrector.from_config(
                self.config(
                    sources=("hardcover", "google_books"),
                    llm_provider="llamacpp",
                    llm_base_url="http://localhost:8080/v1",
                    llm_model="qwen2.5",
                ),
                Backups(self.folder / "backups"),
            )

        self.assertIsNotNone(corrector.llm, "it is set up, and no key file is needed")
        said = "\n".join(captured.output)
        self.assertIn("Google Books key", said, "the source with no key is still named")
        self.assertNotIn("no LLM key", said)

    def test_a_source_with_no_key_file_is_skipped_once_then_left_out(self):
        """Hardcover's token is there; Google Books' key is not set up at all.

        Said once each, not once per book: the source that is set up, and the
        LLM that is not.
        """
        (self.folder / "hardcover_token").write_text("a-token\n", encoding="utf-8")

        with self.assertLogs("colophon", level="INFO") as captured:
            corrector = Corrector.from_config(
                self.config(sources=("hardcover", "google_books")),
                Backups(self.folder / "backups"),
            )

        self.assertEqual([source.name for source in corrector.sources], ["hardcover"])
        said = "\n".join(captured.output)
        self.assertEqual(len(captured.output), 2, "said once, not once per book")
        self.assertIn("Google Books key", said)
        self.assertIn("no LLM key", said)

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
        corrector = Corrector.from_config(
            self.config(), Backups(self.folder / "backups")
        )

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

    def test_the_bands_a_config_carries_are_the_bands_the_pass_applies(self):
        """§4.5: the two thresholds are settings, so the pass is built with them.

        `strong_score` already reached the walk; this is the same seam for the
        two that did not, and it is the one that makes `singleton_score` a knob
        rather than a number the code keeps to itself.
        """
        config = self.config(
            sources=(), strong_score=0.7, singleton_score=0.9, medium_score=0.6
        )

        corrector = Corrector.from_config(config, Backups(self.folder / "backups"))

        self.assertEqual(corrector.bands, Bands(strong=0.7, singleton=0.9, medium=0.6))

    def test_a_pass_with_no_thresholds_bands_on_the_designed_ones(self):
        """§4.1 and §4.4: the numbers a caller that says nothing about them gets.

        The defaults are written out here rather than imported, so the pass and
        `config.py` cannot drift apart by both being read off one constant.
        """
        corrector = Corrector(backups=Backups(self.folder / "backups"))

        self.assertEqual(
            corrector.bands, Bands(strong=0.89, singleton=0.95, medium=0.80)
        )

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

        corrector = Corrector.from_config(
            self.config(), Backups(self.folder / "backups")
        )

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

    def test_a_book_the_source_does_not_know_is_marked_and_otherwise_left_alone(self):
        """No ISBN, no title match: the book is marked, and nothing else moves.

        The mark is a write, so the original is backed up - and the file is then
        the one that arrived apart from the tag and the sentence.
        """
        source = FakeSource(found=None)
        path = self.book("Cragside.epub", CRAGSIDE)
        original_entries = entries_of(path)

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertIn("no source", outcome.fragment())
        self.assertIn("Cragside", outcome.fragment())
        self.assertIn("hardcover", outcome.fragment(), "the source asked is named")
        self.assertTrue(same_book(unmarked_entries(path), original_entries))
        self.assertEqual(self.kept(), ["Cragside.epub"])

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
        path, source = self.a_book_the_source_has(
            "Berwick.epub", BERWICK, BERWICK_CANDIDATE
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(read(path).title, "Berwick")
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "24"))

    def test_belsay_is_matched_and_gets_the_number_its_title_never_had(self):
        """Belsay is #23 on the record, and the file's title does not say so."""
        path, source = self.a_book_the_source_has(
            "Belsay.epub", BELSAY, BELSAY_CANDIDATE
        )

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
        self.assertEqual(
            source.asked_titles, [["Cragside", "Cragside: A DCI Ryan Mystery"]]
        )
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
                    "<dc:language>en</dc:language>",
                    f"<dc:language>{written}</dc:language>",
                )
                path, source = self.a_book_the_source_has(
                    f"{written}.epub", metadata, CRAGSIDE_CANDIDATE
                )

                outcome = self.corrector(source=source).correct(path)

                self.assertEqual(source.asked_languages, [expected])
                self.assertTrue(
                    outcome.matched, f"`{written}` and `en` are one language"
                )

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
        self.assertEqual(
            source.asked_titles[0], ["Cragside", "Cragside: A DCI Ryan Mystery"]
        )

    def test_the_lookalike_is_not_accepted_for_any_of_them(self):
        """A different book by the same author is rejected - and the book is marked.

        Rejected, not accepted: none of the lookalike's values are written. But
        the book is no longer left completely alone, which is CBO-39: a book
        nothing matched confidently is marked unverified, and marking it means
        backing the original up first. So what this test holds is that the file
        is the one it arrived as apart from the mark, byte for byte.
        """
        for name, metadata in (
            ("Cragside.epub", CRAGSIDE),
            ("Berwick.epub", BERWICK),
            ("Belsay.epub", BELSAY),
        ):
            with self.subTest(book=name):
                path = self.book(name, metadata)
                original_entries = entries_of(path)
                source = FakeSource(
                    found=None,
                    candidates=[THE_INFIRMARY_CANDIDATE, ANOTHER_INFIRMARY],
                )

                outcome = self.corrector(source=source).correct(path)

                self.assertFalse(outcome.matched)
                self.assertTrue(outcome.unverified)
                self.assertTrue(
                    same_book(unmarked_entries(path), original_entries),
                    "the mark is the only thing about this file that changed",
                )

    def test_a_book_with_no_author_is_not_matched_on_its_title_alone(self):
        """A title match alone never reaches the threshold, so the book is marked."""
        path = self.book("Cragside.epub", WITHOUT_AUTHOR)
        original_entries = entries_of(path)
        source = FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE])

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertTrue(
            same_book(unmarked_entries(path), original_entries),
            "and nothing of the record was written",
        )

    def test_the_threshold_is_adjustable_and_below_it_a_near_miss_is_accepted(self):
        """At 0.85 the 0.90 candidate is good enough; at 0.95 it is not.

        The comparison grades a candidate rather than answering yes or no, so a
        threshold is a setting with a range to sit in rather than a wall. The
        candidate is a pool of one, so the bar that decides it is
        `singleton_score`; both bars move together here, because a singleton bar
        below the strong one is refused rather than merely unwise.
        """
        for threshold, expected in ((0.85, True), (0.95, False)):
            with self.subTest(strong_score=threshold):
                path = self.book("Cragside.epub", CRAGSIDE)
                source = FakeSource(found=None, candidates=[A_NEAR_MISS])

                outcome = self.corrector(
                    source=source,
                    strong_score=threshold,
                    singleton_score=threshold,
                ).correct(path)

                self.assertEqual(outcome.matched, expected)
                self.assertEqual(outcome.unverified, not expected)
                self.assertEqual(
                    read(path).title,
                    "Cragside: A DCI Ryan Mystery"
                    if expected
                    else "Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)",
                    "accepted means the record's values are written",
                )

    def test_a_lowered_threshold_does_not_let_a_record_that_agrees_on_nothing_through(
        self,
    ):
        """The threshold is the number; `agrees` is the floor under it.

        `Another Infirmary` is a real book of this one's name by someone else, so
        the title agrees exactly, the author does not, and §1.3's cap holds the
        number at 0.7 - which the default threshold refuses and a lowered 0.5
        would accept on the arithmetic alone. It is not an explanation of this
        file whatever the number says, so the rules must not write it, and the
        author left on the file is what shows they did not.
        """
        path = self.book("The Infirmary.epub", THE_INFIRMARY)
        source = FakeSource(found=None, candidates=[ANOTHER_INFIRMARY])

        outcome = self.corrector(source=source, strong_score=0.5).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertEqual(
            read(path).authors, ("L. J. Ross",), "the other author was not written"
        )

    def test_the_top_of_the_range_is_one_and_one_is_a_usable_setting(self):
        """1.0 accepts an exact match and nothing else - and it is not "the ISBN path only".

        It is a setting rather than a wall because a title and an author that both
        agree exactly score exactly 1.0, which is what makes `(0, 1]` the range
        instead of `(0, 1)`. What it refuses is everything under that: a record
        whose title and author both agree exactly and whose series position
        disagrees scores 0.90 (§2.1 row 4), so 1.0 refuses it. So the line 1.0
        draws is *certainty*, not *route* - an ISBN match always clears it, and
        so does an exact title-and-author match.
        """
        # Reachable, and reached by title.
        perfect = self.book("Perfect.epub", CRAGSIDE)
        perfect_source = FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE])

        outcome = self.corrector(
            source=perfect_source, strong_score=1.0, singleton_score=1.0
        ).correct(perfect)

        self.assertTrue(outcome.matched, "an exact title and author is exactly 1.0")
        self.assertFalse(outcome.unverified)
        self.assertIsNone(outcome.isbn, "and it is a title match, not an ISBN one")
        self.assertEqual(outcome.sought, "Cragside", "found by its title")

        # The best a near miss can do: the title and the author both agree
        # exactly and the series position does not. 0.90, and 1.0 refuses it.
        best_near_miss = Candidate(
            source="hardcover",
            title="Cragside: A DCI Ryan Mystery",
            authors=("L.J. Ross",),
            series="DCI Ryan Mysteries",
            series_number="11",
            language="en",
        )
        for threshold, expected in ((1.0, False), (0.85, True)):
            with self.subTest(strong_score=threshold):
                path = self.book(f"Contained-{threshold}.epub", CRAGSIDE)

                outcome = self.corrector(
                    source=FakeSource(found=None, candidates=[best_near_miss]),
                    strong_score=threshold,
                    # Both bars at the threshold, because a singleton bar below
                    # the strong one is refused and this candidate is a pool of
                    # one.
                    singleton_score=threshold,
                ).correct(path)

                self.assertEqual(
                    outcome.matched,
                    expected,
                    f"0.90 {'clears' if expected else 'does not clear'} {threshold}",
                )
                self.assertEqual(outcome.unverified, not expected)
                self.assertEqual(
                    read(path).title,
                    "Cragside: A DCI Ryan Mystery"
                    if expected
                    else "Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)",
                    "marked means nothing of the record was written",
                )

    def test_an_exact_match_whose_series_position_disagrees_scores_below_a_perfect_one(
        self,
    ):
        """The one exact match that is not a 1.0, and the line it sits under.

        A title and an author can both agree exactly and the comparison still not
        be certain: when the file's title carries a series position and the record
        carries a different one, §2.1 row 4 says the score is 0.9070. So at a
        threshold of 0.95 this book is marked unverified - which is the intended
        reading of that setting, not a gap in it. It is also the case that shows
        what a high threshold does *not* exclude: the same book with the position
        agreeing, or with no position on one side, is a 1.0 and is written.
        """
        file_title = "Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)"

        for position, expected_score in (
            ("11", 0.90),
            ("6", 1.0),
            (None, 1.0),
        ):
            with self.subTest(position=position):
                path = self.book(f"Series-{position}.epub", CRAGSIDE)
                candidate = Candidate(
                    source="hardcover",
                    title="Cragside",
                    authors=("L.J. Ross",),
                    series_number=position,
                    language="en",
                )

                outcome = self.corrector(
                    source=FakeSource(found=None, candidates=[candidate]),
                    strong_score=0.95,
                ).correct(path)

                self.assertEqual(
                    outcome.confidence,
                    expected_score,
                    "an exact title and author weigh 1.0, and §2's series "
                    "weight takes 0.20 off a 2.00 denominator",
                )
                self.assertEqual(
                    outcome.matched,
                    expected_score >= 0.95,
                    f"a {position} position against the file's 6 "
                    f"{'clears' if expected_score >= 0.95 else 'does not clear'} 0.95",
                )
                self.assertEqual(
                    read(path).title,
                    "Cragside" if expected_score >= 0.95 else file_title,
                    "a 0.90 is marked, so nothing of the record is written",
                )

    def test_a_threshold_of_one_refuses_a_near_miss_too(self):
        """The 0.9070 near miss is nowhere near the top of the range."""
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None, candidates=[A_NEAR_MISS])

        outcome = self.corrector(
            source=source, strong_score=1.0, singleton_score=1.0
        ).correct(path)

        self.assertFalse(outcome.matched, "0.9070 does not clear 1.0")
        self.assertTrue(outcome.unverified)

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
        self.assertEqual(
            (self.folder / "backups" / "Cragside.epub").read_bytes(), before
        )

    def test_the_outcome_says_which_title_the_match_was_made_on(self):
        path, source = self.a_book_the_source_has(
            "Cragside.epub", CRAGSIDE, CRAGSIDE_CANDIDATE
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertIn(
            "hardcover matched Cragside by title and author", outcome.fragment()
        )
        self.assertIn("confidence 1.00", outcome.fragment())

    def test_a_near_miss_says_which_book_it_was_and_what_was_wrong_with_it(self):
        """A book that was found, trusted less, but still named.

        The candidate is the right author and the file's own title with the
        bracket taken off, so the title and the author both agree exactly and
        only the series position disagrees: 0.90, under the 0.95 threshold this
        pass applies, and named rather than silently dropped.
        """
        path = self.book("Cragside.epub", CRAGSIDE)

        outcome = self.corrector(
            source=FakeSource(found=None, candidates=[A_NEAR_MISS]), strong_score=0.95
        ).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn(
            "no source among hardcover has an edition called Cragside",
            outcome.fragment(),
        )
        self.assertIn("confidence 0.90", outcome.fragment())
        self.assertIn("the full titles agree", outcome.fragment())

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

    def test_a_dry_run_says_what_the_mark_would_change_and_writes_none_of_it(self):
        """Dry run is on in the example config, so this is what a new user sees."""
        path = self.book("Cragside.epub", CRAGSIDE)
        before = path.read_bytes()

        outcome = self.corrector(source=FakeSource(found=None), dry_run=True).correct(
            path
        )

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertEqual(
            sorted(change.field for change in outcome.changed), ["description", "tag"]
        )
        self.assertEqual(path.read_bytes(), before, "nothing is written")
        self.assertEqual(self.kept(), [])
        self.assertIn(
            "would mark", outcome.fragment(), "a dry run says it would, not that it did"
        )

    def test_the_line_says_the_book_was_marked(self):
        path = self.book("Cragside.epub", CRAGSIDE)

        outcome = self.corrector(source=FakeSource(found=None)).correct(path)

        line = outcome.fragment()
        self.assertIn("no source among hardcover has an edition called Cragside", line)
        self.assertIn(f"marked {UNVERIFIED_TAG}", line)

    def test_a_book_already_marked_says_so_without_naming_fields(self):
        """A second pass over a marked book changes nothing, and the line is shorter.

        The mark is not written again and no rule runs, so there is no field list
        to append - and a line claiming changes that were not made would be worse
        than one that just says what the book is.
        """
        path = self.book("Cragside.epub", CRAGSIDE)

        self.corrector(source=FakeSource(found=None)).correct(path)
        again = self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertEqual(again.changed, ())
        self.assertTrue(again.unverified, "still a book nobody could vouch for")
        self.assertIn(f"marked {UNVERIFIED_TAG}", again.fragment())
        self.assertNotIn("description<-", again.fragment(), "nothing moved to report")

    def test_an_isbn_no_source_has_with_no_title_is_marked_not_called_untitled(self):
        """A book the sources were asked about is not a book nobody asked about.

        The fallback needs a title, and this file has none - but its ISBN was
        asked about and no source had it, so the honest line is the ISBN one and
        the honest outcome is the mark. Reporting the title path's "no title in
        the file, so no source was asked" would be false here, and it left the
        book unmarked as well.
        """
        path = write_epub(
            self.folder / "NoTitle.epub",
            f"""    <dc:creator>L. J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">{ISBN}</dc:identifier>
    <dc:language>en</dc:language>
""",
            version="2.0",
        )
        source = FakeSource(found=None)

        outcome = self.corrector(source=source).correct(path)

        self.assertEqual(source.asked, [ISBN], "the ISBN is what it was asked about")
        self.assertEqual(
            source.asked_titles, [], "and there is no title to fall back to"
        )
        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified, "so the book is marked like any other")
        self.assertIn(UNVERIFIED_TAG, subjects(path))
        self.assertIn(ISBN, outcome.fragment())
        self.assertIn("marked colophon:unverified", outcome.fragment())
        self.assertNotIn(
            "no title", outcome.fragment(), "it was asked about, by its ISBN"
        )

    def test_the_near_miss_line_says_the_book_was_marked_too(self):
        """A near miss is still a miss, so the book is marked and the line says so."""
        path = self.book("Cragside.epub", CRAGSIDE)
        nearly = Candidate(
            source="hardcover",
            title="Cragside: A DCI Ryan Mystery",
            authors=("L.J. Ross",),
            series_number="11",
            language="en",
        )

        outcome = self.corrector(
            source=FakeSource(found=None, candidates=[nearly]), strong_score=0.95
        ).correct(path)

        line = outcome.fragment()
        self.assertIn("confidence 0.90", line)
        self.assertIn(f"marked {UNVERIFIED_TAG}", line)

    def test_a_title_the_source_does_not_know_is_not_a_match(self):
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None)

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("Cragside", outcome.fragment())

    def test_a_book_no_source_can_match_is_marked_as_unverified(self):
        """The unverified path: not matched, but not left unmarked either."""
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None)

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertIn(UNVERIFIED_TAG, subjects(path))

    def test_a_book_the_source_offers_nothing_like_gets_the_marker_too(self):
        """Nothing agreed on title or author, so nothing can be named - still unverified."""
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None, candidates=[ANOTHER_INFIRMARY])

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertIn(UNVERIFIED_TAG, subjects(path))

    def test_a_book_is_told_it_is_unverified_in_its_own_description(self):
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None)

        self.corrector(source=source).correct(path)

        self.assertEqual(
            read(path).description,
            UNVERIFIED_SENTENCE,
            "the file had no blurb, so the note is the whole description",
        )

    def test_an_html_blurb_gets_the_note_as_its_own_paragraph(self):
        """A description carrying markup takes the note as a <p>, not a bare line.

        Appended plain, the note would sit outside the last element and some
        readers would drop it - which is the one thing it may not do, since it is
        there to be read.
        """
        path = self.book(
            "Cragside.epub", same_book_with("<p>A house full of secrets.</p>")
        )

        self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertEqual(
            read(path).description,
            f"<p>A house full of secrets.</p><p>{UNVERIFIED_SENTENCE}</p>",
        )

    def test_a_stray_angle_bracket_is_not_html(self):
        """`5 < 6` in a blurb is not markup, so the note goes on after a blank line.

        The test is whether a name follows the bracket, not whether one appears
        anywhere in the text: a blurb is prose, and prose uses `<`.
        """
        blurb = "Two brothers, and 5 < 6 of them left."
        path = self.book("Cragside.epub", same_book_with(blurb))

        self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertEqual(read(path).description, f"{blurb}\n\n{UNVERIFIED_SENTENCE}")

    def test_a_url_left_in_a_blurb_is_not_html_either(self):
        """`<https://example.com>` is a link somebody typed, not an element.

        An element name is letters, digits and hyphens; a scheme's colon is not
        one, and treating the link as markup would wrap the note in a paragraph
        for a blurb that has none - leaving the other one bare.
        """
        blurb = "Out now: <https://example.com/cragside>"
        path = self.book("Cragside.epub", same_book_with(blurb))

        self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertEqual(read(path).description, f"{blurb}\n\n{UNVERIFIED_SENTENCE}")

    def test_an_empty_description_counts_as_having_none(self):
        """A `<dc:description></dc:description>` is not a blurb to append after."""
        path = self.book("Cragside.epub", same_book_with(""))

        self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertEqual(read(path).description, UNVERIFIED_SENTENCE)

    def test_the_blurb_the_file_came_with_is_left_at_the_top(self):
        """A file's own blurb is not replaced - the note goes after it."""
        path = self.book(
            "Cragside.epub",
            same_book_with("A house full of secrets."),
        )
        source = FakeSource(found=None)

        self.corrector(source=source).correct(path)

        self.assertEqual(
            read(path).description,
            f"A house full of secrets.\n\n{UNVERIFIED_SENTENCE}",
        )

    def test_the_unverified_book_is_backed_up_before_it_is_marked(self):
        path = self.book("Cragside.epub", CRAGSIDE)
        before = path.read_bytes()

        self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertEqual(self.kept(), ["Cragside.epub"])
        self.assertEqual(
            (self.folder / "backups" / "Cragside.epub").read_bytes(), before
        )

    def test_marking_an_unverified_book_twice_changes_nothing_the_second_time(self):
        """A re-drop is looked up again, so the marker must not stack up."""
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(found=None)

        self.corrector(source=source).correct(path)
        marked = path.read_bytes()
        second = self.corrector(source=source).correct(path)

        self.assertEqual(subjects(path).count(UNVERIFIED_TAG), 1, "one tag, not two")
        self.assertEqual(
            read(path).description.count(UNVERIFIED_SENTENCE),
            1,
            "one sentence, not two",
        )
        self.assertEqual(second.changed, ())
        self.assertEqual(path.read_bytes(), marked, "nothing left to change")

    def test_a_book_with_no_title_is_not_asked_about(self):
        path = self.book("Cragside.epub", "    <dc:creator>L. J. Ross</dc:creator>")
        source = FakeSource(found=None)

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched)
        self.assertEqual(source.asked_titles, [])
        self.assertIn("no title", outcome.fragment())

    def test_the_mark_is_added_after_the_book_s_own_subjects(self):
        """A tag says what a book is about as well as what became of it.

        The book's own subjects are what a person put there or a source
        supplied, and Colophon's mark goes alongside them rather than replacing
        anything - which is also what makes a library's tag list readable.
        """
        path = self.book(
            "Cragside.epub",
            CRAGSIDE.replace(
                "<dc:language>en</dc:language>",
                "<dc:language>en</dc:language>\n"
                "    <dc:subject>Detective and mystery stories</dc:subject>",
            ),
        )

        self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertEqual(
            subjects(path),
            ["Detective and mystery stories", UNVERIFIED_TAG],
            "the book's own tag first, Colophon's after it",
        )

    def test_a_book_with_no_title_is_not_marked_unverified(self):
        """Nothing was asked, so nothing could fail to be confident.

        A file with no title is not a book nobody could verify - it is a file
        Colophon cannot look up at all, which is a problem with the file. It is
        reported and left exactly as it is, tag and all.
        """
        path = self.book("Cragside.epub", "    <dc:creator>L. J. Ross</dc:creator>")
        before = path.read_bytes()

        outcome = self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertFalse(outcome.unverified)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(subjects(path), [])

    def test_an_isbn_no_source_has_is_marked_unverified_when_the_title_fails_too(self):
        """Both ways of recognising the book came up empty, so it is marked.

        The ISBN path is tried first, so a book that says which edition it is does
        not have its title consulted first - but an ISBN no source has is not an
        answer either, and once the title path has also found nothing there is
        nothing left that could vouch for the file.
        """
        path = self.book("Cragside.epub", AS_DOWNLOADED)

        outcome = self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertIn(UNVERIFIED_TAG, subjects(path))
        self.assertEqual(
            read(path).title,
            "Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)",
        )

    def test_a_source_that_cannot_answer_leaves_the_book_alone(self):
        path = self.book("Cragside.epub", CRAGSIDE)
        source = FakeSource(
            title_error=SourceError("Hardcover is rate limiting (HTTP 429)")
        )
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
            candidates=[
                Candidate(title="Cragside", authors=("L.J. Ross",), language="en")
            ],
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
            candidates=[
                Candidate(title="Cragside", authors=("L.J. Ross",), language="en")
            ],
        )
        before = path.read_bytes()

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.changed, ())
        self.assertEqual(self.kept(), [])
        self.assertEqual(path.read_bytes(), before)


class TheMarkComingOffAgainTests(CorrectionTestCase):
    """A marked book that is matched later comes out clean.

    The mark is a statement about a book nobody could vouch for, so it is a
    statement about the last pass rather than a fact about the book. A re-dropped
    file is looked up again, and when a source has it after all the mark goes -
    otherwise a corrected book would go on telling the reader it was unverified.
    Both halves come off: the tag, and the note at the end of the description.
    """

    def an_unverified_book(self, blurb=None):
        """A book marked the way the unverified path marks one.

        Written straight from the no-ISBN fixture rather than through `book()`,
        which builds the ISBN-carrying one: a book with an ISBN takes the ISBN
        path, and the unverified path is the title path's.
        """
        path = write_epub(
            self.folder / "Cragside.epub",
            CRAGSIDE if blurb is None else same_book_with(blurb),
            version="2.0",
        )
        outcome = self.corrector(source=FakeSource(found=None)).correct(path)
        self.assertTrue(outcome.unverified, "the fixture starts out marked")
        self.assertIn(UNVERIFIED_TAG, subjects(path))
        return path

    def test_a_matched_book_has_the_tag_and_the_note_taken_off(self):
        path = self.an_unverified_book()
        source = FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE])

        outcome = self.corrector(source=source).correct(path)

        self.assertTrue(outcome.matched)
        self.assertFalse(outcome.unverified)
        self.assertNotIn(UNVERIFIED_TAG, subjects(path))
        self.assertIsNone(
            read(path).description,
            "the note was the whole description, so the whole of it goes",
        )
        self.assertEqual(read(path).title, "Cragside", "and the book is corrected")

    def test_the_blurb_a_marked_book_came_with_is_left_behind_the_note(self):
        """Only the note comes off; the file's own blurb is not Colophon's to lose."""
        path = self.an_unverified_book("A house full of secrets.")
        source = FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE])

        self.corrector(source=source).correct(path)

        self.assertNotIn(UNVERIFIED_TAG, subjects(path))
        self.assertEqual(
            read(path).description,
            "A house full of secrets.",
            "the note went, the blurb it was appended to stayed",
        )

    def test_a_matched_blurb_replaces_a_marked_description_whole(self):
        """`overwrite` on the description wins, and takes the stale note with it."""
        path = self.an_unverified_book("A house full of secrets.")
        # A candidate carrying the recorded blurb, because whether a source's
        # blurb replaces a marked description is the whole question here.
        source = FakeSource(found=None, candidates=[NO_COVER_MATCH])

        outcome = self.corrector(
            source=source, fields=self.rules(description="overwrite")
        ).correct(path)

        self.assertTrue(outcome.matched)
        self.assertNotIn(UNVERIFIED_TAG, subjects(path))
        self.assertEqual(read(path).description, CRAGSIDE_BLURB, "the source's blurb")
        self.assertNotIn(UNVERIFIED_SENTENCE, read(path).description)

    def test_an_html_note_comes_off_an_html_blurb(self):
        path = self.an_unverified_book("<p>A house full of secrets.</p>")
        source = FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE])

        self.corrector(source=source).correct(path)

        self.assertEqual(read(path).description, "<p>A house full of secrets.</p>")

    def test_the_source_that_matched_is_not_credited_with_removing_the_mark(self):
        """The tag is Colophon's, so the line that says it went says so.

        Crediting `hardcover` with taking off a tag it never saw would be the
        same lie as crediting it with writing one - and a removal has no value to
        show, so the tag is named the way a blurb is: without one.
        """
        path = self.an_unverified_book()
        source = FakeSource(found=None, candidates=[NO_COVER_MATCH])

        outcome = self.corrector(source=source).correct(path)

        tagged = [change for change in outcome.changed if change.field == "tag"]
        self.assertEqual(len(tagged), 1)
        self.assertEqual(tagged[0].source, "colophon")
        self.assertEqual(tagged[0].value, "", "taken off, not written")
        self.assertIn("tag<-colophon", outcome.fragment())

    def test_a_blurb_the_source_supplied_is_still_credited_to_the_source(self):
        path = self.an_unverified_book()
        source = FakeSource(found=None, candidates=[NO_COVER_MATCH])

        outcome = self.corrector(source=source).correct(path)

        blurb = [change for change in outcome.changed if change.field == "description"]
        self.assertEqual(
            [(change.source, change.value) for change in blurb],
            [("hardcover", CRAGSIDE_BLURB)],
            "the note came off and a source's blurb is what went on",
        )

    def test_the_file_s_own_blurb_is_not_credited_to_the_source(self):
        """A source that has no blurb has not supplied the one left behind.

        The text is the file's own with the note taken off, and a source silent
        about the description cannot be said to have supplied it - which is the
        case the log line would get wrong if it went by whether a rule wrote
        something rather than by who wrote the text.
        """
        path = self.an_unverified_book("A house full of secrets.")
        # The candidate says nothing about the description, so `fill` leaves the
        # file's alone and removing the note is all that happens to it.
        source = FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE])

        outcome = self.corrector(source=source).correct(path)

        blurb = [change for change in outcome.changed if change.field == "description"]
        self.assertEqual(
            [(change.source, change.value) for change in blurb],
            [("colophon", "A house full of secrets.")],
        )
        self.assertEqual(read(path).description, "A house full of secrets.")

    def rules(self, **rules):
        """Every field's rule, with the ones a test cares about overridden."""
        settings = {name: "fill" for name in KNOWN_FIELDS}
        settings.update(rules)
        return settings


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
        self.assertIn(ISBN, outcome.fragment(), "the ISBN tried is named as well")
        self.assertIn("Cragside", outcome.fragment())

    def test_an_isbn_miss_falls_back_to_the_title_path(self):
        """An ISBN no source has does not end the walk; the title path answers.

        An ISBN can be one nobody lists - a self-published edition, or simply a
        wrong one - and the book is still recognisable by its title and its
        author. So the same list is searched again by title, and the second source
        is the one that finds it.
        """
        path = self.book()
        first = FakeSource(found=None)
        second = self.a_second_source()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertEqual(
            first.asked_titles,
            [["Cragside", "Cragside: A DCI Ryan Mystery"]],
            "the source that had no ISBN is asked about the title instead",
        )
        self.assertEqual(
            second.asked_titles,
            [["Cragside", "Cragside: A DCI Ryan Mystery"]],
            "and so is the next one, in the order the user set",
        )
        self.assertTrue(outcome.matched)
        self.assertEqual(outcome.source, "google_books")
        self.assertEqual(
            read(path).isbn,
            ISBN,
            "the file keeps the ISBN it came with, which is not the record's",
        )

    def test_an_isbn_whose_title_path_also_fails_is_marked_unverified(self):
        """Both answers were "no", so nobody could vouch for the book."""
        path = self.book()

        outcome = self.corrector_over(
            FakeSource(found=None), FakeSource(found=None, name="google_books")
        ).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified)
        self.assertIn(UNVERIFIED_TAG, subjects(path))
        self.assertIn("marked colophon:unverified", outcome.fragment())
        self.assertIn(
            ISBN, outcome.fragment(), "and the line says which ISBN was tried"
        )

    # --- the title path ----------------------------------------------------

    def test_a_book_with_no_isbn_is_walked_down_the_list_too(self):
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        first = FakeSource(found=None)
        second = self.a_second_source()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(
            second.asked_titles, [["Cragside", "Cragside: A DCI Ryan Mystery"]]
        )
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

        The right author and the file's own title with the bracket taken off, so
        the title and the author both agree exactly and only the series position
        disagrees: 0.90, under the 0.95 threshold this pass applies, and named
        rather than silently dropped.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        original_entries = entries_of(path)
        nearly = Candidate(
            source="google_books",
            title="Cragside: A DCI Ryan Mystery",
            authors=("L. J. Ross",),
            series_number="11",
        )

        outcome = self.corrector_over(
            FakeSource(found=None, candidates=[nearly]),
            self.a_second_source(candidate=nearly),
            strong_score=0.95,
        ).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn(
            "no source among hardcover, google_books has an edition called Cragside",
            outcome.fragment(),
        )
        self.assertIn("confidence 0.90", outcome.fragment())
        # A near miss is still a miss: none of the candidate's values are written,
        # and the book is marked rather than corrected - which is what CBO-39 adds
        # to this case. Take the mark off and the file is the one that arrived,
        # byte for byte, so the mark is the whole of what happened to it.
        self.assertIn("marked colophon:unverified", outcome.fragment())
        self.assertTrue(
            same_book(unmarked_entries(path), original_entries),
            "take the mark off and the file is the one that arrived",
        )
        self.assertEqual(
            self.kept(), ["Cragside.epub"], "backed up before it was marked"
        )

    def test_a_source_that_offers_nothing_at_all_does_not_name_a_book(self):
        """A reply that agrees on neither title nor author is not an explanation."""
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")

        outcome = self.corrector_over(
            FakeSource(found=None),
            self.a_second_source(candidate=THE_INFIRMARY_CANDIDATE),
        ).correct(path)

        self.assertFalse(outcome.matched)
        self.assertIn("no source", outcome.fragment())
        self.assertIn("Cragside", outcome.fragment())
        self.assertIn("hardcover, google_books", outcome.fragment())
        self.assertNotIn("The Infirmary", outcome.fragment())

    # --- the pooled walk ---------------------------------------------------

    def test_two_sources_returning_the_same_edition_are_one_candidate_and_grade_strong(
        self,
    ):
        """The ticket's headline case: one record, one grading, a strong grade.

        Both sources have the edition the file is - the same ISBN, the same
        title, the same author - so the pool holds it once, and the walk stops
        at the source that answered rather than letting a second copy of the
        same record in as a runner-up at a gap of 0.0. A pool of two identical
        scores is a saturated metric and grades medium; a pool of one that
        agrees on everything is strong, and this is the second.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        edition = {
            "title": "Cragside",
            "authors": ("L. J. Ross",),
            "isbn": ISBN,
            "language": "en",
        }
        first = FakeSource(
            found=None, candidates=[Candidate(source="hardcover", **edition)]
        )
        second = FakeSource(
            found=None,
            candidates=[Candidate(source="google_books", **edition)],
            name="google_books",
        )

        outcome = self.corrector_over(first, second).correct(path)

        self.assertTrue(outcome.matched, outcome.fragment())
        self.assertEqual(outcome.confidence, 1.0, "one record, agreeing on everything")
        self.assertEqual(outcome.source, "hardcover", "the higher-priority source's")
        self.assertEqual(
            second.asked_titles, [], "and the walk stopped on a strong pool"
        )
        self.assertEqual(read(path).title, "Cragside")

    def test_two_genuinely_different_editions_are_not_merged(self):
        """Two records of one work are two candidates, and the gap says so.

        The same title, the same author, nothing else for the file to tell them
        apart with, and two different ISBNs: every field the comparison reads
        agrees, so both score 1.0 and the gap between them is 0.0. §1.2's answer
        to a saturated metric is the medium band, not a coin flip, so the book is
        not written from whichever of the two the source happened to list first.
        Being merged would have made it a singleton at 1.0 - strong, and written.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        source = FakeSource(
            found=None,
            candidates=[
                Candidate(
                    source="hardcover",
                    title="Cragside",
                    authors=("L. J. Ross",),
                    isbn=ISBN,
                    language="en",
                ),
                Candidate(
                    source="hardcover",
                    title="Cragside",
                    authors=("L. J. Ross",),
                    isbn="9781999761009",
                    language="en",
                ),
            ],
        )

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched, "neither edition is written from")
        self.assertTrue(outcome.unverified)
        self.assertEqual(outcome.confidence, 1.0, "and the tie is what stopped it")
        self.assertEqual(len(source.asked_titles), 1, "one request, one pool")

    def test_the_pool_is_what_corrects_the_book_the_first_source_got_wrong(self):
        """Gathered, the pool sees an edition the first source alone did not.

        Source one offers a different printing of the work - the same title and
        author a year out, which is §2.1 row 4's 0.9070 and what the shipped
        walk writes from. Source two has the edition the file is, and the pool
        grades the two together: the file's own edition leads by 0.09, so it is
        that record, not source one's, that is written.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE_DATED, version="2.0")
        first = FakeSource(
            found=None,
            candidates=[
                Candidate(
                    source="hardcover",
                    title="Cragside: A DCI Ryan Mystery",
                    authors=("L.J. Ross",),
                    series="DCI Ryan Mysteries",
                    series_number="11",
                    date="2018-03-01",
                    language="en",
                )
            ],
        )
        second = self.a_second_source(
            candidate=Candidate(
                source="google_books",
                title="Cragside: A DCI Ryan Mystery",
                authors=("L. J. Ross",),
                series="DCI Ryan Mysteries",
                series_number="6",
                date="2017-07-07",
                language="en",
            )
        )

        outcome = self.corrector_over(first, second).correct(path)

        self.assertTrue(outcome.matched, outcome.fragment())
        self.assertEqual(outcome.source, "google_books", "the edition the file is")
        self.assertEqual(calibre_series(path), ("DCI Ryan Mysteries", "6"))

    def test_a_pooled_singleton_in_the_medium_band_is_not_written(self):
        """§4.1: a pool of one needs 0.95, and the shipped walk writes at 0.89.

        The file's own title and author, exactly, with the record's series
        position disagreeing and a year on both sides: §2.1 row 4's 0.9070. That
        clears `strong_score`, and it is a pool of one, so nothing corroborates
        it - a medium-band book is a question for the model or a mark, and not a
        write, which is the whole point of the singleton bar.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE_DATED, version="2.0")

        outcome = self.corrector(
            source=FakeSource(found=None, candidates=[A_NEAR_MISS_WITH_A_YEAR])
        ).correct(path)

        self.assertEqual(outcome.confidence, 0.907)
        self.assertFalse(outcome.matched, "a singleton under 0.95 is not written from")
        self.assertTrue(outcome.unverified)
        self.assertEqual(
            read(path).title,
            "Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)",
            "marked means nothing of the record was written",
        )

    def test_the_singleton_bar_is_the_setting_that_writes_that_book(self):
        """§4.5: the same book and the same pool, one threshold lower."""
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE_DATED, version="2.0")

        outcome = self.corrector(
            source=FakeSource(found=None, candidates=[A_NEAR_MISS_WITH_A_YEAR]),
            singleton_score=0.90,
        ).correct(path)

        self.assertTrue(outcome.matched, outcome.fragment())
        self.assertEqual(outcome.confidence, 0.907)
        self.assertEqual(
            read(path).title,
            "Cragside: A DCI Ryan Mystery",
            "written, so the record's own title is on the book",
        )

    def test_a_pool_that_grades_strong_stops_the_walk_before_the_next_source(self):
        """§1.2: the sources below a decided book were never going to be asked."""
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        first = FakeSource(found=None, candidates=[CRAGSIDE_CANDIDATE])
        second = self.a_second_source()
        before = path.read_bytes()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertTrue(outcome.matched)
        self.assertEqual(second.asked_titles, [], "the walk stopped on the strong pool")
        self.assertNotEqual(path.read_bytes(), before, "and the book was written")

    def test_a_source_s_reply_is_scored_once_rather_than_twice(self):
        """§5: one ranking per reply, and everything downstream reads it.

        The reply used to be measured twice - once to decide the match and once
        again inside `top_candidates` to build the prompt - which on a reply of
        three was six `SequenceMatcher` runs where three would do. The pool is
        ranked once now, and the cap and the prompt both read that one ranking.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        source = FakeSource(
            found=None,
            candidates=[THE_INFIRMARY_CANDIDATE, ANOTHER_INFIRMARY, BERWICK_CANDIDATE],
        )

        with mock.patch.object(
            colophon_matching,
            "score_candidate",
            wraps=colophon_matching.score_candidate,
        ) as scored:
            self.corrector(source=source).correct(path)

        self.assertEqual(scored.call_count, 3, "one scoring pass over the reply")

    # --- a source that is down ---------------------------------------------

    def test_a_walk_that_could_not_be_finished_holds_the_book(self):
        """No lower-priority source quietly stands in for one that is down.

        The ISBN path is not pooled - an ISBN identifies one edition, so the
        first source to know it is as good as any other - and a source that
        cannot answer still stops it. What changed is what happens to the book:
        it is held for tomorrow rather than delivered, because a book whose
        sources were not all asked is not a book the library has finished with.
        """
        first = FakeSource(error=SourceError("Hardcover is rate limiting (HTTP 429)"))
        second = self.a_second_source()
        path = self.book()
        before = path.read_bytes()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.waiting, "held, not delivered")
        self.assertFalse(outcome.unverified, "and not marked: nothing was refused")
        self.assertEqual(second.asked, [], "the ISBN path stopped at the failure")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.kept(), [])

    def test_a_title_lookup_that_is_down_does_not_stop_the_walk(self):
        """The error is recorded, the next source is asked, and the book waits.

        The sources are pooled, so a reply from below the one that is down is
        still evidence about this book - and a book graded against a pool that
        is missing a configured source is not a book the rules refused (§4.2).
        The pool here grades medium, so it is the missing source and not the
        band that holds the book.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        first = FakeSource(
            found=None, title_error=SourceError("Hardcover answered HTTP 503")
        )
        second = self.a_second_source(candidate=A_NEAR_MISS)
        before = path.read_bytes()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertEqual(
            second.asked_titles,
            [["Cragside", "Cragside: A DCI Ryan Mystery"]],
            "the source below one that is down is still asked",
        )
        self.assertTrue(outcome.waiting)
        self.assertFalse(outcome.unverified, "held is not the same as marked")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.kept(), [])

    def test_a_completed_walk_with_an_errored_source_does_not_write_whatever_the_band(
        self,
    ):
        """§4.2's half-asked rule, at the band it would otherwise have written.

        The second source has the book exactly, so the pool grades strong and
        the walk would have written it - but the walk *completed*, and a source
        the user configured was never asked, so the pool is not the pool the
        user asked for. A walk that exited early is the other case, and is not
        half-asked: there the later source was never going to be asked.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        first = FakeSource(
            found=None, title_error=SourceError("Hardcover answered HTTP 503")
        )
        second = self.a_second_source()
        before = path.read_bytes()

        outcome = self.corrector_over(first, second).correct(path)

        self.assertTrue(
            second.asked_titles, "the pool was strong, so it was graded against it"
        )
        self.assertFalse(outcome.matched, "and it is not written from")
        self.assertTrue(outcome.waiting, "the book waits for the source to come back")
        self.assertFalse(outcome.unverified)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.kept(), [])

    def test_the_outcome_says_which_source_could_not_be_asked(self):
        first = FakeSource(error=SourceError("Hardcover rejected the token (HTTP 401)"))

        outcome = self.corrector_over(first, self.a_second_source()).correct(
            self.book()
        )

        self.assertTrue(outcome.waiting)
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

        self.assertEqual(
            len(captured.output), 1, "one warning, not one per source tried"
        )
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
            self.corrector_over(self.a_second_source_holding_the_isbn()).correct(
                self.book()
            )

    # --- the log line ------------------------------------------------------

    def test_each_written_value_is_attributed_to_the_source_that_supplied_it(self):
        second = self.a_second_source_holding_the_isbn()

        outcome = self.corrector_over(FakeSource(found=None), second).correct(
            self.book()
        )

        for change in outcome.changed:
            self.assertEqual(change.source, "google_books")
        self.assertIn('title="Cragside"<-google_books', outcome.fragment())

    def test_the_match_says_which_source_made_it(self):
        second = self.a_second_source_holding_the_isbn()

        outcome = self.corrector_over(FakeSource(found=None), second).correct(
            self.book()
        )

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
            transport=replay or GoogleReplay("by-title-cragside-other-fields.json"),
        )

    def book(self):
        """A book with no cover of its own, and nothing the rules need to keep."""
        return write_epub(
            self.folder / "Cragside.epub",
            CRAGSIDE,
            version="3.0",
        )

    def test_the_blurb_the_date_and_the_cover_all_arrive_from_the_recording(self):
        """The edition the file says it is, and no other: the values are its.

        The recording holds two editions of Cragside - the Ulverscroft large
        print and the original - and they disagree about the blurb, the date and
        the cover. The file carries the large print's ISBN, which is what an ISBN
        is for: the two are told apart exactly, and what the book ends up saying
        is what that edition said, with the other's values nowhere in it.
        """
        path = write_epub(
            self.folder / "Cragside.epub",
            """    <dc:title>Cragside: A DCI Ryan Mystery (The DCI Ryan Mysteries Book 6)</dc:title>
    <dc:creator>L. J. Ross</dc:creator>
    <dc:identifier opf:scheme="ISBN">9781444846577</dc:identifier>
    <dc:language>en</dc:language>
""",
            version="3.0",
        )
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
        path = write_epub(
            self.folder / "Cragside.epub", SERIES_ALREADY_ON_IT, version="3.0"
        )

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
        path = write_epub(
            self.folder / "Cragside.epub", SERIES_ALREADY_ON_IT, version="2.0"
        )

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

    def test_a_real_book_is_not_written_from_a_reply_full_of_editions(self):
        """No stand-in at all: the real client, a real recording, a real EPUB.

        The Gutenberg book carries no ISBN, so it goes down the title path, asks
        Google the question `colophon/googlebooks.py` builds, and is graded
        against what Google actually returned - which is ten volumes of the same
        story, five of them agreeing with the file on everything it states.
        Every one of those five scores 1.0, so the gap is 0.0 and §1.2 calls
        that saturated: the reply is read and scored, and the book is marked
        rather than written from a printing picked by nothing but list order.
        This is the recording in `fixtures/googlebooks/by-title-poe.json`, and
        nothing here is hand-written - which is the point, because a hand-made
        candidate can only ever agree with whatever the client was written to
        produce.
        """
        path = self.a_real_book()
        replay = ReplayByQuery(**{TITLE_ASKED: "by-title-poe.json"})
        source = GoogleBooks("a-key", transport=replay)

        outcome = self.corrector(source=source).correct(path)

        self.assertEqual(replay.asked, TITLE_ASKED)
        self.assertFalse(
            outcome.matched, "five editions at a gap of 0.0 is not a match"
        )
        self.assertTrue(outcome.unverified)
        self.assertIn("no source among google_books", outcome.fragment())
        self.assertIsNotNone(outcome.passed_over, "the reply was read and scored")
        self.assertGreater(outcome.confidence, 0.9, "and what it scored was high")
        # Nothing was written from it, so the book is the one that arrived.
        self.assertEqual(read(path).title, "The Masque of the Red Death")

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
        """Google's own recording, replayed to the real client - and it is medium.

        The reply holds two editions of *Cragside* - the Ulverscroft large print
        and the original - which agree with the file on everything it states, so
        both score 1.0 and the gap between them is 0.0. That is §1.2's saturated
        metric: the reply was read and scored, which is what this test is about,
        and a file that cannot tell two editions apart is not written from
        whichever one Google happened to list first. The ISBN path, below, is
        where an edition is recognised exactly.
        """
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        source = GoogleBooks("a-key", transport=GoogleReplay("by-title-cragside.json"))

        outcome = self.corrector(source=source).correct(path)

        self.assertFalse(outcome.matched, "two editions at a gap of 0.0 is not a match")
        self.assertTrue(outcome.unverified)
        self.assertEqual(outcome.confidence, 1.0, "the reply was read and scored")
        self.assertIn("google_books", outcome.fragment())

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
        source = FakeSource(
            error=SourceError("Hardcover rejected the token (HTTP 401)")
        )
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

        self.assertEqual(
            path.read_bytes(), before, "the book must not change unbacked-up"
        )
        self.assertIn("nothing written", outcome.fragment())

    def test_an_epub_error_while_marking_a_book_is_handled_not_raised(self):
        """The one thing a source is not: an error handler that cannot cope.

        A book can change between being read and being planned - another process
        may be rewriting it - and then `epub.correct` raises. The handler says so
        and leaves the book alone. It used to name the source that refused the
        cover, which does not exist on the unverified path, and an AttributeError
        there would take the whole relay scan down rather than one book.
        """
        # Written straight, because `book()` builds the ISBN-carrying fixture and
        # the unverified path is the title path's.
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        before = path.read_bytes()
        real = colophon_epub.correct
        calls = []

        def refuse_the_first_plan(*args, **kwargs):
            calls.append(kwargs.get("write"))
            if len(calls) == 1:
                raise EpubError("the file changed underneath us")
            return real(*args, **kwargs)

        with mock.patch.object(colophon_epub, "correct", refuse_the_first_plan):
            outcome = self.corrector(source=FakeSource(found=None)).correct(path)

        self.assertEqual(calls, [False], "the planning call is the one that raised")

        self.assertFalse(outcome.matched)
        self.assertTrue(outcome.unverified, "the book is still the book it was")
        self.assertEqual(outcome.changed, ())
        self.assertEqual(path.read_bytes(), before)


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
    def test_the_fragment_names_the_match_the_confidence_the_fields_and_their_source(
        self,
    ):
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


class RecordTests(CorrectionTestCase):
    """What the record does to a correction, and what a correction does to it.

    The ticket's consistency criterion, driven through the pass that writes the
    files rather than through the record alone: a library is only consistent if
    the books on the shelf are.
    """

    def record(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        opened = Record.open(f"{folder.name}/.colophon.db")
        self.addCleanup(opened.close)
        return opened

    def standard(self, record, kind, source, key):
        """The standard the record filed under one key, read from the table."""
        row = record.connection.execute(
            "SELECT standard FROM names WHERE kind = ? AND source = ? AND key = ?",
            (kind, source, key),
        ).fetchone()
        return row["standard"] if row is not None else None

    def deliver(self, path, record, **kwargs):
        """Correct a book the way the relay does, record write and all.

        The corrector decides and the relay persists, so a test that wants the
        record to have learnt something has to do both halves. Doing the second
        half here is what makes these the same assertions the running program
        makes, rather than a shortcut through an interface nothing calls.
        """
        outcome = self.corrector(record=record, **kwargs).correct(path)
        if outcome.decision is not None:
            record.save(
                outcome.decision.resolutions,
                match=outcome.decision.match,
            )
        return outcome

    def source_saying(self, authors, author_ids=(), series="DCI Ryan Mysteries"):
        return FakeSource(
            found=Candidate(
                source="hardcover",
                title="Cragside",
                authors=authors,
                author_ids=author_ids,
                series=series,
                series_number="6",
                language="en",
                isbn=ISBN,
            )
        )

    def test_a_matched_book_is_recorded_under_the_standard_it_was_given(self):
        record = self.record()

        self.deliver(
            self.book(), record, source=self.source_saying(("L.J. Ross",), (318638,))
        )

        self.assertEqual(self.standard(record, AUTHOR, BY_NAME, "lj ross"), "L.J. Ross")

    def test_the_second_book_by_that_author_gets_the_same_spelling(self):
        """The file says `L. J. Ross`; the shelf has already settled on `L.J. Ross`."""
        record = self.record()
        self.deliver(
            self.book("First.epub"),
            record,
            source=self.source_saying(("L.J. Ross",), (318638,)),
        )

        self.deliver(
            self.book("Second.epub"),
            record,
            source=self.source_saying(("L. J. Ross",), (350233,)),
        )

        self.assertEqual(read(self.folder / "Second.epub").authors, ("L.J. Ross",))

    def test_a_new_row_is_anchored_to_the_standard_it_resolved_to(self):
        """So the next book from that row is recognised by its id alone."""
        record = self.record()
        self.deliver(
            self.book("First.epub"),
            record,
            source=self.source_saying(("L.J. Ross",), (318638,)),
        )

        self.deliver(
            self.book("Second.epub"),
            record,
            source=self.source_saying(("L. J. Ross",), (350233,)),
        )

        self.assertEqual(
            self.standard(record, AUTHOR, "hardcover", "350233"), "L.J. Ross"
        )

    def test_an_override_beats_the_recorded_standard(self):
        record = self.record()
        self.deliver(
            self.book("First.epub"),
            record,
            source=self.source_saying(("L.J. Ross",), (318638,)),
        )

        self.deliver(
            self.book("Second.epub"),
            record,
            source=self.source_saying(("L.J. Ross",), (318638,)),
            overrides={"lj ross": "L J Ross"},
        )

        self.assertEqual(read(self.folder / "Second.epub").authors, ("L J Ross",))
        self.assertEqual(
            self.standard(record, AUTHOR, BY_NAME, "lj ross"),
            "L.J. Ross",
            "and the record is left as it was",
        )

    def test_a_dry_run_records_nothing(self):
        """It writes nothing to a book, so it must not write a standard either."""
        record = self.record()

        self.deliver(
            self.book(),
            record,
            source=self.source_saying(("L.J. Ross",), (318638,)),
            dry_run=True,
        )

        self.assertEqual(record.names(), ())

    def test_a_corrector_with_no_record_still_corrects(self):
        """The record is optional: a pass without one behaves as it always did."""
        outcome = self.corrector(
            source=self.source_saying(("L.J. Ross",), (318638,))
        ).correct(self.book())

        self.assertTrue(outcome.applied)
        self.assertEqual(read(self.folder / "Cragside.epub").authors, ("L.J. Ross",))

    def test_a_book_nothing_matched_records_nothing(self):
        record = self.record()

        self.deliver(self.book(), record, source=FakeSource(found=None, candidates=[]))

        self.assertEqual(record.names(), ())

    def test_a_rewrite_the_file_refused_records_nothing(self):
        """The book that reaches the library is the one it arrived as.

        `epub.correct` decides everything before it writes anything, so a book
        whose rewrite is refused is untouched - and a standard learnt from the
        spelling this pass chose would be one nothing on the shelf has. The
        rewrite is the only call that fails: answering the "what would move"
        question still works, which is what puts the pass on the writing branch.
        """
        record = self.record()
        real = colophon_epub.correct

        def refuse_the_write(path, edits, write=True, **kwargs):
            if write:
                raise EpubError("the file will not take it")
            return real(path, edits, write=False, **kwargs)

        with mock.patch.object(colophon_epub, "correct", side_effect=refuse_the_write):
            self.deliver(
                self.book(),
                record,
                source=self.source_saying(("L.J. Ross",), (318638,)),
            )

        self.assertEqual(record.names(), ())

    def test_the_series_is_standardised_the_same_way_an_author_is(self):
        record = self.record()
        self.deliver(
            self.book("First.epub"),
            record,
            source=self.source_saying(
                ("L.J. Ross",), (318638,), series="DCI Ryan Mysteries"
            ),
        )

        self.deliver(
            self.book("Second.epub"),
            record,
            source=self.source_saying(
                ("L.J. Ross",), (318638,), series="DCI RYAN MYSTERIES"
            ),
        )

        self.assertEqual(read(self.folder / "Second.epub").series, "DCI Ryan Mysteries")

    def test_an_author_override_does_not_reach_the_series(self):
        """`[authors]` is a table of author spellings; a series is not an author.

        A key only collides with a series name because both are resolved through
        the same normaliser, so a user writing an author's name twice cannot be
        taken to have asked for the series to be renamed with it.
        """
        record = self.record()

        self.deliver(
            self.book(),
            record,
            source=self.source_saying(("L.J. Ross",), (318638,)),
            overrides={"dci ryan mysteries": "L J Ross"},
        )

        self.assertEqual(
            read(self.folder / "Cragside.epub").series,
            "DCI Ryan Mysteries",
            "the series as the source spelt it",
        )


class GenreMappingTests(CorrectionTestCase):
    """CBO-42: a source's genres are mapped onto the user's own list, or dropped.

    Every reply here is a recording from `tests/fixtures/llm`, replayed through a
    real `Llm`, and the source replies are the real Hardcover recordings. So the
    whole path is the shipped one: the reply's shape decides what a genre is, the
    config decides what may be written, and the record decides what is asked
    twice.
    """

    # The allowed list the recordings were made against, which holds `Murder` as
    # well as `Crime` - so a mapping is a judgement rather than an echo.
    ALLOWED = (
        "Crime",
        "Mystery",
        "Thriller",
        "Historical Fiction",
        "Science Fiction",
        "Fantasy",
    )

    CRAGSIDE_GENRES = "by-isbn-9781521748831-genres.json"
    PYRAMIDS = "by-isbn-9780575064843-packed-genres.json"

    def record(self):
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        opened = Record.open(f"{folder.name}/.colophon.db")
        self.addCleanup(opened.close)
        return opened

    def llm(self, *names, **kwargs):
        return Llm(
            provider="deepseek",
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            key="llm-secret-key-4242",
            counter=self.folder / "llm.json",
            transport=LlmReplay(*names),
            **kwargs,
        )

    def spent(self, *names):
        """The same client with the UTC day's only call already spent."""
        counter = self.folder / "llm-spent.json"
        counter.write_text(json.dumps({"date": today(), "calls": 1}), encoding="utf-8")
        return Llm(
            provider="deepseek",
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            key="llm-secret-key-4242",
            daily_limit=1,
            counter=counter,
            transport=LlmReplay(*names),
        )

    def source_saying(self, genres):
        """A source offering Cragside with these genres on its record."""
        return FakeSource(
            found=Candidate(
                source="hardcover",
                title="Cragside",
                authors=("L.J. Ross",),
                series="DCI Ryan Mysteries",
                series_number="6",
                language="en",
                isbn=ISBN,
                genres=genres,
            )
        )

    def hardcover_over(self, name):
        """A real Hardcover client, replaying a recorded reply."""
        return Hardcover("hardcover-token", transport=Replay(name))

    def deliver(self, path, corrector, record=None):
        """Correct a book the way the relay does, record write and all."""
        outcome = corrector.correct(path)
        if record is not None and outcome.decision is not None:
            record.save(
                outcome.decision.resolutions,
                match=outcome.decision.match,
                genres=outcome.decision.genres,
            )
        return outcome

    def asked(self, corrector):
        """The source genres the model was asked about, in order."""
        return [line.rsplit("Source genre: ", 1)[1] for line in self.prompts(corrector)]

    def prompts(self, corrector):
        return [
            sent["body"]["messages"][1]["content"]
            for sent in corrector.llm._transport.sent
        ]

    # The ticket's own two cases -------------------------------------------

    def test_messy_genres_map_onto_the_allowed_list_and_are_deduped(self):
        """Four Hardcover genres, three of them one shelf label.

        The recording behind the source reply really carries `Murder`, `Crime`,
        `Thriller` and `Mystery`, and one reply is replayed for each of the four:
        what the transport answers is what it answers, and the point here is what
        the corrector makes of four source genres arriving as one allowed genre.
        """
        corrector = self.corrector(
            source=self.hardcover_over(self.CRAGSIDE_GENRES),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-murder.json"),
        )

        outcome = self.deliver(self.book(), corrector)

        self.assertEqual(
            self.asked(corrector), ["Murder", "Crime", "Thriller", "Mystery"]
        )
        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ("Crime",))
        self.assertEqual(
            [change.value for change in outcome.changed if change.field == "genres"],
            ["Crime"],
            "one entry per allowed genre, not one per source genre",
        )

    def test_an_unmappable_genre_is_dropped(self):
        """A character heading is not a genre, and the model says so."""
        for name, genre in (
            (
                "genre-mapping-unmappable.json",
                "Finlay-Ryan, Maxwell (Fictitious character)",
            ),
            ("genre-mapping-synagogues.json", "Synagogues"),
        ):
            with self.subTest(name=name):
                corrector = self.corrector(
                    source=self.source_saying(((genre, genre),)),
                    genres=self.ALLOWED,
                    llm=self.llm(name),
                )

                self.deliver(self.book(), corrector)

                self.assertEqual(read(self.folder / "Cragside.epub").subjects, ())

    def test_a_genre_that_does_not_fit_leaves_the_book_with_none(self):
        corrector = self.corrector(
            source=self.source_saying((("Fiction", "Fiction"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-fiction.json"),
        )

        self.deliver(self.book(), corrector)

        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ())

    def test_a_truncated_reply_drops_rather_than_writes(self):
        for name in ("genre-mapping-batch.json", "genre-mapping-truncated.json"):
            with self.subTest(name=name):
                corrector = self.corrector(
                    source=self.source_saying((("Murder", "Murder"),)),
                    genres=self.ALLOWED,
                    llm=self.llm(name),
                )

                self.deliver(self.book(), corrector)

                self.assertEqual(read(self.folder / "Cragside.epub").subjects, ())

    # What is written, and how -------------------------------------------------

    def test_the_target_is_written_as_the_config_spells_it(self):
        """The model answers `Crime`; the match against the list is case-insensitive."""
        corrector = self.corrector(
            source=self.source_saying((("crime", "crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
        )

        self.deliver(self.book(), corrector)

        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ("Crime",))

    def test_an_off_list_target_is_dropped(self):
        """The allowed list is the only authority; the model is not trusted with it."""
        corrector = self.corrector(
            source=self.source_saying((("Murder", "Murder"),)),
            genres=("Fantasy",),
            llm=self.llm("genre-mapping-murder.json"),
        )

        self.deliver(self.book(), corrector)

        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ())

    def test_the_book_s_own_subjects_are_kept(self):
        path = write_epub(
            self.folder / "Cragside.epub",
            AS_DOWNLOADED + "    <dc:subject>Northumberland</dc:subject>",
            version="2.0",
        )
        corrector = self.corrector(
            source=self.source_saying((("Murder", "Murder"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-murder.json"),
        )

        self.deliver(path, corrector)

        self.assertEqual(read(path).subjects, ("Northumberland", "Crime"))

    def test_a_genre_the_book_already_carries_is_not_written_again(self):
        path = write_epub(
            self.folder / "Cragside.epub",
            AS_DOWNLOADED + "    <dc:subject>Crime</dc:subject>",
            version="2.0",
        )
        corrector = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
        )

        self.deliver(path, corrector)

        self.assertEqual(read(path).subjects, ("Crime",), "one tag, not two")

    # The list, and what it costs ---------------------------------------------

    def test_an_empty_allowed_list_costs_no_call(self):
        """No list means there is no question to ask, so none is asked."""
        corrector = self.corrector(
            source=self.source_saying((("Murder", "Murder"),)),
            genres=(),
            llm=self.llm("genre-mapping-murder.json"),
        )

        self.deliver(self.book(), corrector)

        self.assertEqual(corrector.llm._transport.sent, [])
        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ())

    def test_a_book_with_no_genres_asks_nothing(self):
        corrector = self.corrector(
            source=self.source_saying(()),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-murder.json"),
        )

        self.deliver(self.book(), corrector)

        self.assertEqual(corrector.llm._transport.sent, [])

    def test_a_recording_made_before_this_ticket_has_no_genres_to_ask_about(self):
        """A reply with no `cached_tags` is absent, not a bug."""
        corrector = self.corrector(
            source=self.hardcover_over("by-isbn-found.json"),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-murder.json"),
        )

        self.deliver(self.book(), corrector)

        self.assertEqual(corrector.llm._transport.sent, [])

    def test_no_llm_set_up_means_the_genres_are_dropped(self):
        corrector = self.corrector(
            source=self.source_saying((("Murder", "Murder"),)),
            genres=self.ALLOWED,
        )

        outcome = self.deliver(self.book(), corrector)

        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ())
        self.assertFalse(
            outcome.waiting, "a book is not held for a model nobody set up"
        )

    def test_a_genre_call_that_could_not_be_made_does_not_hold_the_book(self):
        """The wait belongs to a match the LLM was needed for, not to a tag.

        The day's calls are spent, so the question cannot be put. The book was
        resolved by its ISBN without the model, and it lands exactly as it would
        have with no genres configured - corrected, minus the tags.
        """
        corrector = self.corrector(
            source=self.source_saying((("Murder", "Murder"),)),
            genres=self.ALLOWED,
            llm=self.spent("genre-mapping-murder.json"),
        )

        with self.assertLogs("colophon", level="WARNING") as caught:
            outcome = self.deliver(self.book(), corrector)

        self.assertFalse(outcome.waiting, "the book is not held for a tag")
        self.assertTrue(outcome.applied, "and it is corrected and delivered")
        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ())
        line = "\n".join(caught.output)
        self.assertIn("Murder", line)
        self.assertIn("could not be asked", line)
        self.assertNotIn("does not fit", line, "not the model saying no")

    def test_a_genre_that_could_not_be_asked_is_not_recorded_and_is_asked_again(self):
        """Absent, not decided: nothing is cached, so the next run asks it again."""
        record = self.record()
        spent = self.corrector(
            source=self.source_saying((("Murder", "Murder"),)),
            genres=self.ALLOWED,
            llm=self.spent("genre-mapping-murder.json"),
            record=record,
        )

        self.deliver(self.book("First.epub"), spent, record=record)

        self.assertEqual(record.genres(), (), "no row, positive or null")

        later = self.corrector(
            source=self.source_saying((("Murder", "Murder"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-murder.json"),
            record=record,
        )
        self.deliver(self.book("Second.epub"), later, record=record)

        self.assertEqual(len(later.llm._transport.sent), 1, "asked again")
        self.assertEqual(read(self.folder / "Second.epub").subjects, ("Crime",))

    def test_a_book_that_needed_the_chooser_and_could_not_ask_it_still_waits(self):
        """The two paths are pinned apart: only the match's own wait survives."""
        path = write_epub(self.folder / "Cragside.epub", CRAGSIDE, version="2.0")
        corrector = self.corrector(
            source=FakeSource(found=None, candidates=[A_NEAR_MISS]),
            genres=self.ALLOWED,
            llm=self.spent("genre-mapping-murder.json"),
            strong_score=0.95,
        )

        outcome = self.deliver(path, corrector)

        self.assertTrue(outcome.waiting)
        self.assertIn("daily limit", outcome.note)

    # The packed forms ---------------------------------------------------------

    def test_a_packed_form_is_asked_about_as_its_parts(self):
        """`Fantasy:Humour` is two questions, and the packed string is never one."""
        corrector = self.corrector(
            source=self.hardcover_over(self.PYRAMIDS),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-packed.json", "genre-mapping-fiction.json"),
        )

        self.deliver(self.book(), corrector)

        asked = self.asked(corrector)
        self.assertIn("Fantasy", asked)
        self.assertIn("Humour", asked)
        for genre in asked:
            with self.subTest(genre=genre):
                self.assertNotIn(":", genre)

    def test_a_key_two_strings_collide_on_gets_one_row_and_the_first_wins(self):
        """`Fantasy` arrives alone and again inside `Fantasy:Humour`."""
        record = self.record()
        corrector = self.corrector(
            source=self.hardcover_over(self.PYRAMIDS),
            genres=("Fantasy", "Humour"),
            llm=self.llm("genre-mapping-packed.json", "genre-mapping-fiction.json"),
            record=record,
        )

        self.deliver(self.book(), corrector, record=record)

        rows = {(row[0], row[1]): row for row in record.genres()}
        self.assertEqual(
            set(rows),
            {
                ("hardcover", "Fantasy"),
                ("hardcover", "Adventure"),
                ("hardcover", "Science Fiction"),
                ("hardcover", "General"),
                ("hardcover", "Humor"),
                ("hardcover", "Humour"),
                ("hardcover", "Satire"),
                ("hardcover", "Science Fiction & Fantasy"),
                ("hardcover", "Comedy & Humor"),
            },
        )
        self.assertEqual(
            rows[("hardcover", "Fantasy")][2:],
            ("Fantasy", "Fantasy"),
            "one row, and the first string it came out of wins",
        )
        for row in record.genres():
            with self.subTest(seen=row[3]):
                self.assertNotIn(":", row[3], "the packed path is not recoverable")

    # The cache and the memo --------------------------------------------------

    def test_two_books_carrying_one_genre_spend_one_call(self):
        corrector = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
        )

        self.deliver(self.book("First.epub"), corrector)
        self.deliver(self.book("Second.epub"), corrector)

        self.assertEqual(len(corrector.llm._transport.sent), 1)

    def test_a_run_where_nothing_lands_still_asks_each_genre_once(self):
        """The memo is on the run, so a book that never arrives still teaches it."""
        record = self.record()
        corrector = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
            record=record,
        )

        self.deliver(self.book("First.epub"), corrector)
        self.deliver(self.book("Second.epub"), corrector)

        self.assertEqual(len(corrector.llm._transport.sent), 1)
        self.assertEqual(record.genres(), (), "and the record learnt nothing")

    def test_a_second_run_spends_nothing(self):
        record = self.record()
        first = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
            record=record,
        )
        self.deliver(self.book("First.epub"), first, record=record)

        second = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
            record=record,
        )
        self.deliver(self.book("Second.epub"), second, record=record)

        self.assertEqual(second.llm._transport.sent, [])
        self.assertEqual(read(self.folder / "Second.epub").subjects, ("Crime",))

    def test_a_positive_hit_that_is_still_allowed_is_not_asked_again(self):
        record = self.record()
        record.save_genres((("hardcover", "Crime", "Crime", "Crime"),))
        corrector = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
            record=record,
        )

        self.deliver(self.book(), corrector, record=record)

        self.assertEqual(corrector.llm._transport.sent, [])
        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ("Crime",))

    def test_a_positive_hit_that_is_no_longer_allowed_is_asked_again(self):
        record = self.record()
        record.save_genres((("hardcover", "Crime", "True Crime", "Crime"),))
        corrector = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
            record=record,
        )

        self.deliver(self.book(), corrector, record=record)

        self.assertEqual(len(corrector.llm._transport.sent), 1, "it was asked again")
        self.assertEqual(record.mapping("hardcover", "Crime"), "Crime")
        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ("Crime",))

    def test_the_re_ask_is_stored_and_the_next_book_pays_nothing(self):
        """A `DO NOTHING` upsert would leave the stale target and re-ask for ever."""
        record = self.record()
        record.save_genres((("hardcover", "Crime", "True Crime", "Crime"),))
        first = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
            record=record,
        )

        self.deliver(self.book("First.epub"), first, record=record)
        self.deliver(self.book("Second.epub"), first, record=record)

        self.assertEqual(len(first.llm._transport.sent), 1, "once for the run")
        rows = {row[1]: row for row in record.genres()}
        self.assertEqual(rows["Crime"][2], "Crime", "the new answer is stored")
        self.assertEqual(rows["Crime"][3], "Crime", "and the provenance is not")

    def test_a_stored_null_is_not_asked_again(self):
        """A null is an answer: the model has already said this genre does not fit."""
        record = self.record()
        record.save_genres((("hardcover", "Fiction", "", "Fiction"),))
        corrector = self.corrector(
            source=self.source_saying((("Fiction", "Fiction"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-fiction.json"),
            record=record,
        )

        self.deliver(self.book(), corrector, record=record)

        self.assertEqual(corrector.llm._transport.sent, [])
        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ())

    def test_the_mapping_is_not_written_down_for_a_book_that_never_landed(self):
        """The decision travels to the relay, and the relay persists it on arrival."""
        record = self.record()
        corrector = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
            record=record,
        )

        outcome = self.deliver(self.book(), corrector)

        self.assertIsNotNone(outcome.decision)
        self.assertEqual(record.genres(), (), "nothing was persisted")

    def test_a_book_that_needs_no_rewrite_still_teaches_the_record(self):
        """The mapping is about the source's vocabulary, not about this file.

        Nothing is planned for a book whose every field already matches and which
        already carries the genre it maps to, so there is no rewrite to hang a
        decision on - but the genre was asked about and answered, and the record
        is what stops the next book paying for the same question.
        """
        record = self.record()
        path = write_epub(
            self.folder / "Cragside.epub",
            AS_DOWNLOADED + "    <dc:subject>Crime</dc:subject>",
            version="2.0",
        )
        corrector = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
            record=record,
            fields={name: "skip" for name in KNOWN_FIELDS},
        )

        outcome = self.deliver(path, corrector, record=record)

        self.assertEqual(outcome.changed, (), "nothing was written")
        self.assertEqual(len(corrector.llm._transport.sent), 1, "the genre was asked")
        self.assertEqual(record.mapping("hardcover", "Crime"), "Crime")

    # A dry run ----------------------------------------------------------------

    def test_a_dry_run_asks_nothing_and_says_what_it_does_not_know(self):
        corrector = self.corrector(
            source=self.source_saying((("Murder", "Murder"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-murder.json"),
            dry_run=True,
        )

        with self.assertLogs("colophon", level="INFO") as caught:
            outcome = self.deliver(self.book(), corrector)

        self.assertEqual(corrector.llm._transport.sent, [])
        self.assertIn("Murder", "\n".join(caught.output))
        self.assertTrue(outcome.dry_run)
        self.assertEqual(read(self.folder / "Cragside.epub").subjects, ())

    def test_a_dry_run_uses_a_cached_answer_and_reports_the_genre_it_would_add(self):
        record = self.record()
        record.save_genres((("hardcover", "Crime", "Crime", "Crime"),))
        corrector = self.corrector(
            source=self.source_saying((("Crime", "Crime"),)),
            genres=self.ALLOWED,
            llm=self.llm("genre-mapping-case.json"),
            record=record,
            dry_run=True,
        )

        outcome = self.deliver(self.book(), corrector)

        self.assertEqual(corrector.llm._transport.sent, [])
        self.assertEqual(
            [
                (change.field, change.value)
                for change in outcome.changed
                if change.field == "genres"
            ],
            [("genres", "Crime")],
        )


if __name__ == "__main__":
    unittest.main()
