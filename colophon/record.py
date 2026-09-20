"""Colophon's own record: the spellings a library has settled on.

The sources disagree about how an author's name is spelt — Hardcover writes
`L.J. Ross` and Google Books writes `L. J. Ross` for the same person — and a
library that takes whichever it heard last ends up with both. So the first
source to match an author fixes the spelling, and every later book by that author
is given the same one, whatever the source that matched it wrote.

What is kept is a match, not a book: who recognised it, how sure they were, and
the identity they recognised it under. Nothing here is ever read to supply a
metadata value — the design spec's rule is that every written value comes from
the matched source's record — and there is deliberately **no series number
anywhere**, because a number worked out from a record rather than read from the
source is the one thing this record must never do.

A name is filed under two keys, because a source's own id is the strongest
identity available but is only meaningful to the source that issued it: Google
Books has no author ids, so a Google Books match has to be able to find a
standard Hardcover set. One key is the source's id, the other is the name
itself, and both point at the same standard.

The record is never cleared automatically. `reset()` is the only thing that
empties it, and it exists because a user may want to start the standards again —
not because anything in this program ever would.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from colophon.matching import normalise

# What the file's layout is, so a build meeting a file it does not understand
# stops rather than reading it. Bump this when the schema changes and add the
# step that carries an older file forward; refusing a *newer* file is the part
# that matters, because an old build writing a new table is how a column
# somebody else added gets dropped.
SCHEMA_VERSION = 1

# The two kinds of name the record keeps. They are one table because they are
# one question — has this been seen, and how is it spelt — and the kind is the
# only thing that tells them apart.
AUTHOR = "author"
SERIES = "series"

# What `names.source` holds for a row keyed by the name itself rather than by a
# source's id. A source is never the empty string, so the two cannot collide.
BY_NAME = ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS names (
    kind     TEXT NOT NULL,
    source   TEXT NOT NULL,
    key      TEXT NOT NULL,
    standard TEXT NOT NULL,
    seen     TEXT NOT NULL,
    PRIMARY KEY (kind, source, key)
);

CREATE TABLE IF NOT EXISTS matches (
    book_key   TEXT PRIMARY KEY,
    source     TEXT NOT NULL,
    confidence REAL NOT NULL,
    matched_at TEXT NOT NULL,
    matched_as TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS genres (
    genre TEXT PRIMARY KEY
);
"""


class RecordError(Exception):
    """The record cannot be used: a file from a newer Colophon, or a bad folder."""


@dataclass(frozen=True)
class Resolved:
    """One name as the record decided to write it.

    `spelling` is what the book gets. `seen` is what the source actually wrote,
    which is the same thing for a new name and differs whenever a standard or an
    override is being followed — that difference is the only record of which
    spellings a source produces, and it is what a person looks at when they
    wonder why their library says `L.J. Ross`.

    `identity` is the source's own id for the name, when it gave one, and it is
    what the record files the standard under as well as the spelling. `by_id` is
    whether the decision came from that id rather than from the spelling, which
    is what says the name is already anchored and must not be anchored again.
    """

    kind: str
    source: str
    spelling: str
    seen: str
    identity: int | str | None = None
    by_id: bool = False


@dataclass(frozen=True)
class Match:
    """A book a source recognised, and how sure it was."""

    book_key: str
    source: str
    confidence: float
    matched_as: str = ""


class Record:
    """The SQLite file holding the spellings, the matches and the genres."""

    def __init__(self, connection, path):
        self.connection = connection
        self.path = Path(path)

    @classmethod
    def open(cls, path):
        """The record at this path, creating the file and its schema if needed.

        A missing parent folder is made, because the default lives in a folder
        the relay is already expected to create. An unusable one is a real
        problem and is raised as a `RecordError` rather than as an `OSError`,
        so a caller has one kind of failure to handle.
        """
        path = Path(path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise RecordError(f"could not make {path.parent}: {error}") from error
        try:
            connection = sqlite3.connect(path)
        except sqlite3.Error as error:
            raise RecordError(f"could not open the record at {path}: {error}") from error
        connection.row_factory = sqlite3.Row
        record = cls(connection, path)
        try:
            record._prepare()
        except RecordError:
            # A file from a newer Colophon is refused without being written to,
            # and the handle to it is let go of on the way out rather than left
            # open for a caller that has no record to close.
            connection.close()
            raise
        return record

    def close(self):
        self.connection.close()

    def _prepare(self):
        """Check the layout, then make sure it is there."""
        found = self.connection.execute("PRAGMA user_version").fetchone()[0]
        if found > SCHEMA_VERSION:
            raise RecordError(
                f"the record at {self.path} was written by a newer Colophon "
                f"(version {found}, this build understands {SCHEMA_VERSION}); "
                "nothing was changed"
            )
        # Steps that carry an older file forward go here, guarded by `found`, so
        # the next ticket to change the schema adds one rather than a rebuild.
        self.connection.executescript(SCHEMA)
        self.connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        self.connection.commit()

    # Reading -----------------------------------------------------------------

    def resolve(self, kind, names, source, identities=(), overrides=None):
        """How each of these names should be written, and under which key.

        The order is the whole design, and each step is here for a reason:

        * **The user's overrides win**, always and first. They exist because a
          person correcting a spelling in their library app should not have to
          argue with a database.
        * **The source's own id** answers "this is a row I recorded before",
          which is the only thing that catches one source spelling a name two
          ways.
        * **The name itself** is what carries a standard from one source to
          another, and it is all a source with no ids has.
        * **Nothing** means this is a new name, and the source's spelling —
          from the source the user trusts most, because that is the one that
          matched the book — becomes the standard when the correction lands.

        `overrides` is keyed by the normalised name, and its keys are normalised
        again here: the config does that at load time, and this makes sure a
        caller that builds the mapping itself cannot quietly end up with a table
        that never matches.
        """
        overrides = {normalise(key): value for key, value in (overrides or {}).items()}
        resolved = []
        for position, name in enumerate(names):
            key = normalise(name)
            if not key:
                continue
            identity = _identity(identities, position)
            override = overrides.get(key)
            if override:
                resolved.append(
                    Resolved(
                        kind,
                        source,
                        override,
                        name,
                        identity,
                        by_id=identity is not None,
                    )
                )
                continue
            if identity is not None:
                found = self._standard(kind, source, str(identity))
                if found is not None:
                    resolved.append(
                        Resolved(kind, source, found, name, identity, by_id=True)
                    )
                    continue
            found = self._standard(kind, BY_NAME, key)
            if found is not None:
                resolved.append(Resolved(kind, source, found, name, identity))
                continue
            resolved.append(Resolved(kind, source, name, name, identity))
        return tuple(resolved)

    def _standard(self, kind, source, key):
        """The standard filed under this exact key, or None if nothing is."""
        row = self.connection.execute(
            "SELECT standard FROM names WHERE kind = ? AND source = ? AND key = ?",
            (kind, source, key),
        ).fetchone()
        return row["standard"] if row is not None else None

    # Writing -----------------------------------------------------------------

    def save(self, resolutions, match=None, when="", priority=()):
        """Write what was decided, once the book it was decided for has landed.

        Called after the file is in place rather than when the decision was made,
        so a crash part-way through a correction cannot teach a standard for a
        book that never arrived. A name whose standard the record already holds
        is left as it is: a standard does not move because a later book spelt the
        name differently.

        `when` is when the match happened, written down but never compared: two
        hosts in two time zones must not disagree about the order books arrived
        in, so the caller passes a UTC stamp and this does not invent one.

        `priority` is the user's source order, and it is the tie-break when a
        book is looked up again and the new match is exactly as confident as the
        one already recorded. Confidence itself is comparable across sources —
        the title score is computed from the file and the candidate record and
        never from which source offered it — so a strictly better match wins on
        its own and the order only decides a draw.
        """
        for resolution in resolutions:
            self._write_name(resolution)
            if resolution.by_id:
                continue
            self._write_id_row(resolution)
        if match is not None:
            self._write_match(match, when, priority)
        self.connection.commit()

    def _write_name(self, resolution):
        """File the standard under the name, unless this name already has one."""
        key = normalise(resolution.spelling)
        if not key:
            return
        self.connection.execute(
            "INSERT INTO names (kind, source, key, standard, seen) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (kind, source, key) DO NOTHING",
            (
                resolution.kind,
                BY_NAME,
                key,
                resolution.spelling,
                resolution.seen,
            ),
        )

    def _write_id_row(self, resolution):
        """Anchor this source row to the standard, so the id resolves next time.

        Written only when the name lookup is what found the standard. A name
        resolved by its id was anchored the first time it was seen, and writing
        it again would only give the row a second chance to disagree.
        """
        if resolution.identity is None:
            return
        self.connection.execute(
            "INSERT INTO names (kind, source, key, standard, seen) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (kind, source, key) DO NOTHING",
            (
                resolution.kind,
                resolution.source,
                str(resolution.identity),
                resolution.spelling,
                resolution.seen,
            ),
        )

    def _write_match(self, match, when, priority):
        """Record this match, unless the book is recorded from somewhere better.

        "Better" is a higher confidence, and on a draw the source the user
        trusts more. A book already recorded from the same source is simply
        updated: there is no ordering between a source and itself.
        """
        held = self.connection.execute(
            "SELECT source, confidence FROM matches WHERE book_key = ?",
            (match.book_key,),
        ).fetchone()
        if held is not None and not _beats(match, held, priority):
            return
        self.connection.execute(
            "INSERT INTO matches (book_key, source, confidence, matched_at, matched_as) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (book_key) DO UPDATE SET "
            "source = excluded.source, confidence = excluded.confidence, "
            "matched_at = excluded.matched_at, matched_as = excluded.matched_as",
            (match.book_key, match.source, match.confidence, when, match.matched_as),
        )

    # The rest ----------------------------------------------------------------

    def names(self):
        """Every name the record holds, as `(kind, source, key, standard, seen)`.

        Ordered, so two records built the same way read the same, and public
        because a caller with a record in its hand should not have to know the
        table names to ask what is in it.
        """
        return tuple(
            (row["kind"], row["source"], row["key"], row["standard"], row["seen"])
            for row in self.connection.execute(
                "SELECT kind, source, key, standard, seen FROM names "
                "ORDER BY kind, source, key"
            )
        )

    def standard(self, kind, source, key):
        """The one standard filed under this exact key, or None."""
        return self._standard(kind, source, key)

    def match(self, book_key):
        """What the record holds for this book, or None if it has never seen it."""
        row = self.connection.execute(
            "SELECT book_key, source, confidence, matched_at, matched_as "
            "FROM matches WHERE book_key = ?",
            (book_key,),
        ).fetchone()
        if row is None:
            return None
        return Match(
            book_key=row["book_key"],
            source=row["source"],
            confidence=row["confidence"],
            matched_as=row["matched_as"],
        )

    def genres(self):
        """The allowed genres, which CBO-42 fills in and this ticket only makes room for."""
        return tuple(
            row["genre"]
            for row in self.connection.execute("SELECT genre FROM genres ORDER BY genre")
        )

    def reset(self):
        """Empty the record. The only thing that ever does, and never automatic."""
        self.connection.executescript(
            "DELETE FROM names; DELETE FROM matches; DELETE FROM genres;"
        )
        self.connection.commit()


def book_key(isbn, title):
    """What a book is recognised by when it is looked up again.

    The ISBN when there is one, and the normalised title when there is not. The
    title is the weaker key and is used only because the alternative is worse:
    keying every ISBN-less book on a blank would make them all one book, so the
    second one recorded would overwrite the first's match.

    Two editions of one book carry different ISBNs and key separately, which is
    accepted for v1 — the consequence is that each can settle a spelling — and
    a paperback and a hardback of one title under one spelling key together.
    """
    isbn = str(isbn or "").strip()
    if isbn:
        return isbn
    return normalise(title)


def _beats(match, held, priority):
    """Whether this match should replace the one the record already has.

    A higher confidence wins outright. A draw goes to the source the user ranked
    higher, which is the same rule the walk itself follows — the first source
    that can answer is the one trusted — and a source that is not in the list at
    all sorts after every source that is.
    """
    if match.confidence != held["confidence"]:
        return match.confidence > held["confidence"]
    return _rank(priority, match.source) < _rank(priority, held["source"])


def _rank(priority, source):
    order = list(priority)
    return order.index(source) if source in order else len(order)


def _identity(identities, position):
    """The source's own id for the name at this position, if it gave one."""
    if position < len(identities):
        return identities[position]
    return None
