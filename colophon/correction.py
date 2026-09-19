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
from dataclasses import dataclass
from pathlib import Path

from colophon import epub
from colophon.epub import Edits, EpubError
from colophon.hardcover import Hardcover, SourceError
from colophon.matching import (
    FileBook,
    best_candidate,
    nearest_candidate,
    primary_language,
    search_titles,
)

LOG = logging.getLogger("colophon")

# An exact ISBN match is as certain as metadata matching gets.
CONFIDENCE = 1.0
MATCHED_BY = "exact ISBN"
# A title and author match is never certain, so it has to clear this.
TITLE_CONFIDENCE = 0.85
TITLE_MATCHED_BY = "title and author"

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

    def fragment(self):
        """The bracketed part of the log line, or nothing when there is nothing to say."""
        if self.silent:
            return ""
        if not self.matched:
            if self.problem is not None:
                return f"[{self.problem}]"
            if self.passed_over is not None:
                # The best explanation of this file, and what was wrong with it.
                return (
                    f"[no edition is called {self.sought} confidently enough: "
                    f"{self.passed_over}, confidence {self.confidence:.2f}]"
                )
            if self.sought:
                return f"[no edition is called {self.sought}]"
            return f"[no edition carries ISBN {self.isbn}]"

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
            f'{change.field}="{change.value}"<-{change.source}' for change in self.changed
        )
        return f"[{head}; {'changed' if self.applied else 'would change'} {fields}]"


class Corrector:
    """Corrects the books the relay hands it, one file at a time.

    `source` is None when no Hardcover token was found, and `dry_run` decides
    whether a correction is actually written: in a dry run every answer is the
    same, except that nothing on disk moves, including the backup.
    """

    def __init__(self, source=None, backups=None, dry_run=False):
        self.source = source
        self.backups = backups
        self.dry_run = dry_run

    @classmethod
    def from_config(cls, config, backups):
        """The pass this configuration asks for, whose source may be missing."""
        try:
            source = Hardcover.from_secret_file(config.hardcover_token_file)
        except SourceError as error:
            LOG.error("%s; carrying on without metadata lookups", error)
            return cls(backups=backups, dry_run=config.dry_run)
        if source is None:
            LOG.info(
                "no Hardcover token at %s, so books pass through with the metadata "
                "they came with",
                config.hardcover_token_file,
            )
        return cls(source=source, backups=backups, dry_run=config.dry_run)

    def correct(self, path):
        path = Path(path)
        if path.suffix.lower() not in BOOK_SUFFIXES:
            return Outcome(silent=True)

        try:
            book = epub.read(path)
        except EpubError as error:
            return Outcome(problem=f"metadata not read: {error}")
        if self.source is None:
            return Outcome(problem="no Hardcover token, so nothing was looked up")
        if book.isbn:
            return self._by_isbn(path, book)
        return self._by_title(path, book)

    def _by_isbn(self, path, book):
        """The ISBN path: the file says which edition it is, so ask about that."""
        try:
            found = self.source.by_isbn(book.isbn)
        except SourceError as error:
            return Outcome(problem=f"Hardcover could not be asked: {error}")
        if found is None:
            return Outcome(isbn=book.isbn)
        return self._write(path, found, CONFIDENCE, book.isbn)

    def _by_title(self, path, book):
        """The title path, for a file that carries no ISBN.

        The title is cleaned first, because the file's title has the subtitle
        and the series on it and a source keeps neither. Every candidate that
        comes back is scored against the file, and only a confident match is
        written; a book whose title matches but whose author does not is not a
        match at all, so it is passed over.
        """
        titles = search_titles(book.title)
        if not titles:
            return Outcome(problem="no title in the file, so no source was asked")
        title = titles[0]

        # A `dc:language` may be regional (`en-GB`) or three-letter (`eng`); the
        # source indexes editions by the primary code, so that is what is asked.
        language = primary_language(book.language) or None
        try:
            # Every form in one request: the query filters with `_in`, which is
            # the only title operator the server permits.
            candidates = self.source.by_title(list(titles), language)
        except SourceError as error:
            return Outcome(problem=f"Hardcover could not be asked: {error}")

        file_book = FileBook(book.title, book.authors, language)
        found = best_candidate(file_book, candidates, TITLE_CONFIDENCE)
        if found is None:
            # Nothing was near enough to write. If anything was near at all,
            # say which book it was and what was wrong with it.
            nearest = nearest_candidate(file_book, candidates)
            if nearest is None or not nearest.agrees:
                return Outcome(sought=title)
            return Outcome(
                sought=nearest.candidate.title or title,
                confidence=nearest.confidence,
                passed_over=nearest.why,
            )
        return self._write(path, found.candidate, found.confidence)

    def _write(self, path, found, confidence, isbn=None):
        """Back the original up, then write what the source is sure of.

        `found` carries the source it came from, so nothing here has to be told
        where the values are from. `isbn` is set only when an ISBN is what
        recognised the book, because that is what the log line then reports.
        """
        edits = _edits(found)
        matched = {
            "isbn": isbn,
            "sought": None if isbn else found.title,
            "matched": True,
            "confidence": confidence,
            "source": found.source,
        }

        # Ask the file what would move before touching it: a book that already
        # matches is not backed up, and not rewritten either.
        planned = epub.correct(path, edits, write=False)
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

        written = epub.correct(path, edits)
        return Outcome(
            **matched,
            changed=_changes(written, edits, found.source),
            applied=True,
            kept=str(kept),
        )


def _edits(found):
    """Only the fields the source actually has: a field it lacks is not a blank."""
    return Edits(
        title=found.title,
        authors=found.authors or None,
        series=found.series,
        series_number=found.series_number,
    )


def _changes(fields, edits, source):
    return tuple(Change(field, _value(edits, field), source) for field in fields)


def _value(edits, field):
    value = getattr(edits, field)
    return ", ".join(value) if field == "authors" else str(value)
