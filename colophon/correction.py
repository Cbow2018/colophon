"""The correction pass: read the book, ask a source, back it up, rewrite it.

The relay hands every incoming file to this. It decides whether the file is a
book worth correcting, reads the ISBN out of it, asks Hardcover, and writes
whatever the source is sure of. It writes nothing when there is nothing to
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

LOG = logging.getLogger("colophon")

# An exact ISBN match is as certain as metadata matching gets.
CONFIDENCE = 1.0
MATCHED_BY = "exact ISBN"

# The formats whose metadata Colophon understands. Everything else - PDFs,
# comics, MOBI - passes straight through, untouched and unread.
BOOK_SUFFIX = ".epub"


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
    matched: bool = False
    confidence: float | None = None
    source: str | None = None
    changed: tuple = ()
    applied: bool = False
    problem: str | None = None
    silent: bool = False
    # Where the original was kept before it was changed, if it was.
    kept: str | None = None

    def fragment(self):
        """The bracketed part of the log line, or nothing when there is nothing to say."""
        if self.silent:
            return ""
        if not self.matched:
            if self.problem is not None:
                return f"[{self.problem}]"
            return f"[no edition carries ISBN {self.isbn}]"

        head = (
            f"{self.source} matched ISBN {self.isbn} by {MATCHED_BY}, "
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
        if path.suffix.lower() != BOOK_SUFFIX:
            return Outcome(silent=True)

        try:
            book = epub.read(path)
        except EpubError as error:
            return Outcome(problem=f"metadata not read: {error}")
        if not book.isbn:
            return Outcome(problem="no ISBN in the file, so no source was asked")
        if self.source is None:
            return Outcome(problem="no Hardcover token, so the ISBN was not looked up")

        try:
            found = self.source.by_isbn(book.isbn)
        except SourceError as error:
            return Outcome(problem=f"Hardcover could not be asked: {error}")
        if found is None:
            return Outcome(isbn=book.isbn)
        return self._write(path, found)

    def _write(self, path, found):
        """Back the original up, then write what the source is sure of."""
        edits = _edits(found)
        matched = {
            "isbn": found.isbn,
            "matched": True,
            "confidence": CONFIDENCE,
            "source": found.source,
        }

        # Ask the file what would move before touching it: a book that already
        # matches is not backed up, and not rewritten either.
        planned = epub.correct(path, edits, write=False)
        if not planned:
            return Outcome(**matched)
        if self.dry_run:
            return Outcome(**matched, changed=_changes(planned, edits, found))

        try:
            kept = self.backups.keep(path)
        except OSError as error:
            return Outcome(
                **matched,
                changed=_changes(planned, edits, found),
                problem=f"could not back the original up: {error}",
            )

        written = epub.correct(path, edits)
        return Outcome(
            **matched,
            changed=_changes(written, edits, found),
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


def _changes(fields, edits, found):
    return tuple(Change(field, _value(edits, field), found.source) for field in fields)


def _value(edits, field):
    value = getattr(edits, field)
    return ", ".join(value) if field == "authors" else str(value)
