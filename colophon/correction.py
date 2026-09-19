"""The correction pass: read the book, ask a source, back it up, rewrite it.

The relay hands every incoming file to this. It decides whether the file is a
book worth correcting, reads the ISBN out of it, asks Hardcover, and writes
whatever the source is sure of. A book with no ISBN is asked about by its
cleaned title and author instead, and whatever comes back is only written if
the comparison is confident enough. It writes nothing when there is nothing to
change, nothing when there is no match, and nothing at all in dry-run mode -
and it backs the original up before it changes a byte, so a correction can
always be undone.
"""

import logging
from dataclasses import dataclass, replace
from pathlib import Path

from colophon import epub
from colophon.config import FIELD_DEFAULTS, KNOWN_FIELDS
from colophon.epub import Edits, EpubError
from colophon.googlebooks import GoogleBooks
from colophon.hardcover import Hardcover
from colophon.matching import (
    FileBook,
    nearest_candidate,
    primary_language,
    search_titles,
)
from colophon.sources import SourceError
from colophon.sources import image as fetch_image

LOG = logging.getLogger("colophon")

# One entry per source Colophon knows: the setting naming its key file, what to
# call the source in a sentence, what to call that key file, and how to build the
# source from it. A name missing from here is a programming mistake rather than a
# user one - `config.py` refuses a name it does not know long before this is
# reached - which is why the sentences live here too, rather than in a second map
# keyed by the same names.
SOURCE_SETUP = {
    "hardcover": {
        "file": "hardcover_token_file",
        "label": "Hardcover",
        "key_label": "Hardcover token",
        "make": Hardcover.from_secret_file,
    },
    "google_books": {
        "file": "google_books_key_file",
        "label": "Google Books",
        "key_label": "Google Books key",
        "make": GoogleBooks.from_secret_file,
    },
}

# An exact ISBN match is as certain as metadata matching gets.
CONFIDENCE = 1.0
MATCHED_BY = "exact ISBN"
# A title and author match is never certain, so it has to clear this.
TITLE_CONFIDENCE = 0.85
TITLE_MATCHED_BY = "title and author"

# Fields whose values are not what belongs in a log line, so the line names them
# without it: the blurb is a thousand characters of prose that is in the book,
# and a cover's value is bytes. The line's job is which fields moved and who
# supplied them.
_NAME_ONLY = ("description", "cover")

# The formats whose metadata Colophon understands. Everything else - PDFs,
# comics, MOBI - passes straight through, untouched and unread. Kobo writes
# its own extension as well as the .kepub.epub one.
BOOK_SUFFIXES = (".epub", ".kepub")


@dataclass(frozen=True)
class Change:
    """One field that moved, and the source that supplied its new value."""

    field: str
    value: str
    source: str


@dataclass(frozen=True)
class Outcome:
    """What became of one book, in enough detail for the relay's one log line."""

    isbn: str | None = None
    # What the source was asked about, when that was not an ISBN: the cleaned
    # title a book without one was recognised by.
    sought: str | None = None
    matched: bool = False
    confidence: float | None = None
    source: str | None = None
    changed: tuple = ()
    applied: bool = False
    problem: str | None = None
    silent: bool = False
    # Where the original was kept before it was changed, if it was.
    kept: str | None = None
    # Why the best candidate was not good enough, when there was one and it
    # was not. Empty whenever a match was made or none was offered.
    passed_over: str | None = None
    # Which sources were asked, and did not have the book. Only filled in when
    # nothing matched, because that is the case where the reader of the log has
    # nothing else to go on about what was tried.
    tried: tuple = ()

    def fragment(self):
        """The bracketed part of the log line, or nothing when there is nothing to say."""
        if self.silent:
            return ""
        if not self.matched:
            if self.problem is not None:
                return f"[{self.problem}]"
            if self.passed_over is not None:
                # The best explanation of this file, and what was wrong with it.
                # The sources are named here for the same reason they are named
                # when nothing was found at all: the reader has no match to
                # anchor on, and "confidence 0.84 - against which source?" is
                # the next question they would have.
                return (
                    f"[no source{self._among()} has an edition called {self.sought} "
                    f"confidently enough: {self.passed_over}, "
                    f"confidence {self.confidence:.2f}]"
                )
            return f"[{self._nothing_found()}]"

        if self.isbn:
            head = (
                f"{self.source} matched ISBN {self.isbn} by {MATCHED_BY}, "
                f"confidence {self.confidence:.2f}"
            )
        else:
            head = (
                f"{self.source} matched {self.sought} by {TITLE_MATCHED_BY}, "
                f"confidence {self.confidence:.2f}"
            )
        if self.problem is not None:
            return f"[{head}; nothing written: {self.problem}]"
        if not self.changed:
            return f"[{head}; nothing to change]"

        fields = ", ".join(
            f"{change.field}<-{change.source}"
            if change.field in _NAME_ONLY
            else f'{change.field}="{change.value}"<-{change.source}'
            for change in self.changed
        )
        return f"[{head}; {'changed' if self.applied else 'would change'} {fields}]"

    def _among(self):
        """The sources that were tried, for the log lines that have no match.

        A book that was matched says which source matched it, and the sources
        that were passed over on the way are reconstructible from the config. A
        book that was not matched has no such anchor, so the sources that were
        actually asked are worth writing down - on both the near-miss line and
        the nothing-found line, which are the two that have no match to name.
        """
        return f" among {', '.join(self.tried)}" if self.tried else ""

    def _nothing_found(self):
        """The line for a book not one source had, naming every source asked."""
        if self.sought:
            return f"no source{self._among()} has an edition called {self.sought}"
        return f"no source{self._among()} carries ISBN {self.isbn}"


class Corrector:
    """Corrects the books the relay hands it, one file at a time.

    `sources` is the priority list, in the order the user set: the first source
    that matches a book is the one it takes its values from, and both the ISBN
    path and the title path walk the same list. An empty list - no source
    configured, or none of them usable - means every book passes through with
    the metadata it came with.

    A source that cannot answer stops the walk for that book rather than being
    passed over: the list is a trust order, so a lower-priority source must
    never quietly stand in for a higher-priority one that is down. What happens
    to the book after that belongs to the retry window (CBO-43).

    `dry_run` decides whether a correction is actually written: in a dry run
    every answer is the same, except that nothing on disk moves, including the
    backup.
    """

    def __init__(
        self,
        sources=None,
        backups=None,
        dry_run=False,
        fields=None,
        add_cover=True,
        fetch=None,
    ):
        self.sources = tuple(sources or ())
        self.backups = backups
        self.dry_run = dry_run
        # What to do with each field, as a mapping: `skip`, `fill` or
        # `overwrite`. A field the mapping leaves out is one nothing has an
        # opinion about, so it is simply not written.
        self.fields = dict(fields or FIELD_DEFAULTS)
        self.add_cover = add_cover
        # How a cover is fetched, injected so no test reaches the network.
        self.fetch = fetch or fetch_image

    @classmethod
    def from_config(cls, config, backups):
        """The pass this configuration asks for, minus any source it cannot build."""
        sources = []
        for name in config.sources:
            source = _build(name, config)
            if source is not None:
                sources.append(source)
        return cls(
            sources=sources,
            backups=backups,
            dry_run=config.dry_run,
            fields=config.fields,
            add_cover=config.add_cover,
        )

    def correct(self, path):
        path = Path(path)
        if path.suffix.lower() not in BOOK_SUFFIXES:
            return Outcome(silent=True)

        try:
            book = epub.read(path)
        except EpubError as error:
            return Outcome(problem=f"metadata not read: {error}")
        if not self.sources:
            return Outcome(problem="no source is set up, so nothing was looked up")
        if book.isbn:
            return self._by_isbn(path, book)
        return self._by_title(path, book)

    def _by_isbn(self, path, book):
        """The ISBN path: the file says which edition it is, so ask about that.

        The walk stops at the first source that has the edition. An ISBN
        identifies one, so the first source to know it is as good as any other,
        and the ISBN itself is only ever written by its own rule - usually
        nothing, since the file already carries it.
        """
        tried = []
        for source in self.sources:
            tried.append(source.name)
            try:
                found = source.by_isbn(book.isbn)
            except SourceError as error:
                return self._failed(source, error, f"ISBN {book.isbn}")
            if found is not None:
                return self._write(path, found, CONFIDENCE, isbn=book.isbn, book=book)
        return Outcome(isbn=book.isbn, tried=tuple(tried))

    def _by_title(self, path, book):
        """The title path, for a file that carries no ISBN.

        The title is cleaned first, because the file's title has the subtitle
        and the series on it and a source keeps neither. Each source is asked in
        turn, and the first to offer a candidate that clears the threshold is
        the match - a near miss from a trusted source does not stop a
        lower-priority one from being asked, but it is remembered, so a book no
        source can match still names the closest thing to it.
        """
        titles = search_titles(book.title)
        if not titles:
            return Outcome(problem="no title in the file, so no source was asked")
        title = titles[0]

        # A `dc:language` may be regional (`en-GB`) or three-letter (`eng`); the
        # source indexes editions by the primary code, so that is what is asked.
        language = primary_language(book.language) or None
        file_book = FileBook(book.title, book.authors, language)
        author = next((name for name in book.authors if str(name).strip()), None)

        nearest = None
        tried = []
        for source in self.sources:
            tried.append(source.name)
            try:
                # Every form in one request: a source filters its own way, and
                # the caller's language and author are the filters that keep the
                # reply to this book.
                candidates = source.by_title(list(titles), language, author)
            except SourceError as error:
                return self._failed(source, error, title)

            # One pass: the nearest candidate is measured once, and what was
            # measured is what gets written or named.
            match = nearest_candidate(file_book, candidates)
            if match is None or not match.agrees:
                # A reply that agrees on neither title nor author is not an
                # explanation of this book, and is not named as one.
                continue
            if match.confidence >= TITLE_CONFIDENCE:
                return self._write(path, match.candidate, match.confidence, book=book)
            # A near miss: remembered rather than written, so a book no source
            # can match still names the closest thing to it.
            if nearest is None or match.confidence > nearest.confidence:
                nearest = match

        if nearest is not None:
            return Outcome(
                sought=nearest.candidate.title or title,
                confidence=nearest.confidence,
                passed_over=nearest.why,
                tried=tuple(tried),
            )
        # Neither source offered anything that agrees on title and author, or
        # offered nothing at all. The book is named by the title the sources
        # were asked about, which is the file's own cleaned title.
        return Outcome(sought=title, tried=tuple(tried))

    def _failed(self, source, error, sought):
        """A source that could not answer stops the walk, and is said out loud.

        The walk does not carry on to a lower-priority source: the list is a
        trust order, so a book is never quietly corrected from a source the user
        ranked below one that is down. The book passes through untouched.

        This is logged at WARNING and not only in the book's own log line,
        because a source being unreachable is a problem with the run rather than
        a fact about one book, and a user watching `docker logs` should not have
        to read every book's line to notice it. What happens to the book next -
        the retry window, and the `colophon:source-unavailable` tag - is CBO-43's.
        """
        blamed = _blamed(source)
        LOG.warning(
            "%s could not be asked about %s, so the book is left alone: %s",
            blamed,
            sought,
            error,
        )
        return Outcome(problem=f"{blamed} could not be asked: {error}")

    def _write(self, path, found, confidence, isbn=None, book=None):
        """Back the original up, then write what the source is sure of.

        `found` carries the source it came from, so nothing here has to be told
        where the values are from. `isbn` is set only when an ISBN is what
        recognised the book, because that is what the log line then reports.

        `book` is the file as it was read, and it is never left out: each rule is
        judged against it, `fill` writes only a field the file is empty of, and
        whether the book already has a cover is a fact about the file.
        """
        edits = self._edits(found, book)
        matched = {
            "isbn": isbn,
            "sought": None if isbn else found.title,
            "matched": True,
            "confidence": confidence,
            "source": found.source,
        }

        # Ask the file what would move before touching it: a book that already
        # matches is not backed up, and not rewritten either. The cover is asked
        # for only once something is going to be written, because fetching an
        # image for a book about to be left alone is work done for nothing -
        # and a dry run fetches nothing either, for the same reason it writes
        # nothing. What it reports is that a cover would be added, not the image.
        cover = self._cover(path, found, book, would_add=self.dry_run)
        wanted = self._wants_cover(found, book)
        try:
            planned = epub.correct(
                path,
                edits,
                write=False,
                cover=cover,
                would_add_cover=self.dry_run and wanted,
            )
        except EpubError as error:
            # The cover is not an image the file will take. Nothing is written
            # on this pass whatever happens - it only says what would move - so
            # the book is left alone and the reason is said once, here.
            LOG.warning(
                "%s offered a cover for %s that the file would not take, so the "
                "book is corrected without it: %s",
                _label(found.source),
                path.name,
                error,
            )
            planned = ()
            cover = None
        if not planned:
            return Outcome(**matched)
        if self.dry_run:
            return Outcome(**matched, changed=_changes(planned, edits, found.source))

        try:
            kept = self.backups.keep(path)
        except OSError as error:
            return Outcome(
                **matched,
                changed=_changes(planned, edits, found.source),
                problem=f"could not back the original up: {error}",
            )

        try:
            written = epub.correct(path, edits, cover=cover)
        except EpubError:
            # The same cover, refused on the pass that writes. The book is left
            # exactly as it was - `epub.correct` decides everything before it
            # writes anything - so this is the same outcome as a cover that
            # could not be fetched, and the warning above was the saying.
            written = ()
        return Outcome(
            **matched,
            changed=_changes(written, edits, found.source),
            applied=True,
            kept=str(kept),
        )

    def _edits(self, found, book):
        """The fields this source's record is allowed to write, and no others.

        Each field is decided on its own, which is what the config is for: a book
        can take its title from the source and keep its description, and another
        the other way round. `fill` is judged against the file, so a field the
        file already carries is left as it is; `overwrite` writes the source's
        value whenever the source has one.

        A field the source said nothing about is written by no rule at all: `fill`
        on a field a source is silent about is not a blank, and a source with no
        publisher has not offered an empty one.
        """
        wanted = {}
        for name in KNOWN_FIELDS:
            rule = self.fields.get(name, "skip")
            value = getattr(found, name, None)
            if name == "authors":
                value = tuple(value or ()) or None
            if rule == "skip" or not value:
                continue
            current = getattr(book, name, None)
            if name == "authors":
                current = tuple(current or ())
            if rule == "fill" and current:
                continue
            wanted[name] = value

        return _series_consistent(Edits(**wanted), found, book)

    def _cover(self, path, found, book, would_add=False):
        """The cover to add to this book, or None when there is none to add.

        Only the source that matched is asked for one: the priority list is a
        trust order for every field alike, so a cover may not come from a source
        the user ranked below the one that recognised the book. A source with no
        cover for this book is the ordinary case rather than a failure.

        Fetching can fail, and a cover is the least important thing about a book:
        a blurb and a right title are worth having whether or not the image
        arrives. So a failure here is a line in the log rather than a reason to
        leave the metadata alone.

        `would_add` is a dry run asking whether a cover is on its way without
        wanting the bytes: none are fetched, and `None` is the answer that means
        "not to hand" rather than "none to add".
        """
        if not self._wants_cover(found, book):
            return None
        if would_add:
            return None
        try:
            return self.fetch(found.cover)
        except SourceError as error:
            LOG.warning(
                "%s offered a cover for %s that could not be fetched, so the book "
                "is corrected without it: %s",
                _label(found.source),
                path.name,
                error,
            )
            return None

    def _wants_cover(self, found, book):
        """Whether a cover is to be added to this book, setting and all.

        Three things decide it and nothing else does: the setting is on, the
        source offered one, and the book has none of its own. It is asked
        separately from fetching because a dry run has to answer it without
        fetching anything, and because "no cover to add" and "the bytes are not
        to hand" are different answers with different outcomes.
        """
        return bool(self.add_cover and found.cover and not book.has_cover)


def _series_consistent(edits, found, book):
    """Keep the number and the series it is a position in from disagreeing.

    A series number is a position in a named series, not a number on its own, so
    the number always follows its series:

    * If the book ends up in the source's series - because the series was
      overwritten, because it was filled in where the file had none, or because
      the file was already in it - the source's number is a position in the
      series the book is in, and its own rule decides whether to write it.
    * If the book ends up in some other series - because the series was skipped,
      or because the source does not name one at all - the source's number is a
      position in a series this book is not in. It is not written, and the
      number the file came with is left alone, unless the series around it has
      changed, in which case it is dropped: it would then be a claim about the
      wrong series rather than an old number.

    Both names are compared without regard to case, because a capitalisation
    difference between a file and a record is the same series.

    The question is what the book ends up saying, not which rules were set:
    `overwrite` for the series and `skip` for the number, and `skip` for the
    series and `overwrite` for the number, are the same question asked from
    opposite ends, and both are answered from the resulting pair.
    """
    resulting = edits.series if edits.series is not None else book.series
    if edits.series_number is not None:
        # The source's number, on its way in. It belongs to the source's series,
        # so it is written only if the book ends up in that series; otherwise it
        # is a position in a series this book is not in, and neither it nor the
        # file's own number is written.
        if _same_series(resulting, found.series):
            return edits
        return replace(edits, series_number=None)

    # The file's number, being left alone - which is right only while the series
    # around it is too. A number whose series has just been replaced is a claim
    # about the wrong series, so it goes.
    if book.series_number and not _same_series(resulting, book.series):
        return replace(edits, drop_series_number=True)
    return edits


def _same_series(one, other):
    """Whether two series names are the same series, capitalisation aside."""
    if not one or not other:
        return False
    return str(one).strip().casefold() == str(other).strip().casefold()


def _build(name, config):
    """The named source, or None if the user has not set its key up.

    A missing key file is not an error: the source is simply not available, and
    the user is told once, at startup, rather than once per book. A key file
    that is there but unreadable is a real problem and is said so.
    """
    entry = SOURCE_SETUP[name]
    where = getattr(config, entry["file"])
    try:
        source = entry["make"](where)
    except SourceError as error:
        LOG.error("%s; carrying on without %s", error, name)
        return None
    if source is None:
        LOG.info(
            "no %s at %s, so %s is not asked and the rest of the list carries on "
            "without it",
            entry["key_label"],
            where,
            name,
        )
    return source


def _blamed(source):
    """What to call a source in a sentence, as opposed to in a log field."""
    return _label(source.name)


def _label(name):
    """The label of a source, by name.

    A source names itself the way a log field wants it - `hardcover` - and a
    sentence wants it the way a person writes it, which is the label in
    `SOURCE_SETUP`. Every source the corrector can hold came from `from_config`,
    which built it from a name `config.py` had already checked against
    `KNOWN_SOURCES`, so a name that is not in the map is a bug in Colophon rather
    than something a user can cause: it is worth an exception, not a fallback.
    `test_every_configured_source_has_a_label` is what keeps that true.
    """
    return SOURCE_SETUP[name]["label"]


def _changes(fields, edits, source):
    return tuple(Change(field, _value(edits, field), source) for field in fields)


def _value(edits, field):
    """What a change's value is, for the log line and the outcome alike.

    A field the edits do not carry is one that was written by being taken off -
    a stale series number - or a cover, which is bytes rather than a value.
    """
    value = getattr(edits, field, None)
    if field == "authors":
        return ", ".join(value or ())
    return "" if value is None else str(value)
