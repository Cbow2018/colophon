"""The relay: ingest -> output, one file at a time.

Every file that has finished arriving is handed to the correction pass, which
may rewrite a book's metadata, and is then put where the library app will find
it - without ever overwriting anything, and without losing a file it could not
finish with.
"""

import hashlib
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from colophon.backups import Backups, free_name
from colophon.correction import Corrector
from colophon.files import READ_SIZE, copy_into_place

LOG = logging.getLogger("colophon")


class RelayError(Exception):
    """The relay cannot run at all (usually a folder it cannot use)."""


class Relay:
    def __init__(self, config, corrector=None, record=None):
        self.config = config
        self.backups = Backups(config.backup_dir, config.backup_retention_days)
        # Colophon's own record, or None when there is none. It is held here and
        # handed to the correction pass, because one connection to one SQLite
        # file is what this object owns and a second opener is how
        # `database is locked` starts.
        self.record = record
        self.correction = corrector or Corrector.from_config(
            config, self.backups, record=record
        )
        # path -> ((size, mtime), how many scans it has looked like that)
        self._seen = {}
        # files already reported in dry-run mode, so each is logged once
        self._announced = set()
        # path -> the (size, mtime) it had when it could not be removed from
        # the ingest folder, so it is left alone until it changes
        self._stuck = {}

    def prepare(self):
        """Make sure the folders exist before the first scan."""
        for folder in (self.config.ingest_dir, self.config.output_dir):
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise RelayError(f"cannot use {folder}: {error}") from error
        try:
            self.backups.prepare()
        except OSError as error:
            raise RelayError(f"cannot use {self.config.backup_dir}: {error}") from error

        self._sweep_genres()

        # The original is deleted once it has been copied out, so read-only
        # access to the ingest folder would leave every book to arrive twice.
        if not os.access(self.config.ingest_dir, os.W_OK):
            raise RelayError(
                f"cannot write to {self.config.ingest_dir}; the ingest folder must "
                "not be mounted read-only"
            )

    def _sweep_genres(self):
        """Forget the genres that did not fit, if the allowed list has changed.

        Done once, at startup, rather than by `Record.open`: deleting rows is a
        write, and a dry run must make none at all. So a dry run skips it
        entirely and the fingerprint is simply not rewritten - the next real run
        does the sweep. A record that cannot be swept is logged rather than
        raised: the worst it does is ask a question the record already has an
        answer to.
        """
        if self.record is None or self.config.dry_run:
            return
        try:
            self.record.sweep_genres(self.config.allowed_genres)
        except sqlite3.Error as error:
            LOG.error("could not sweep the genre cache: %s", error)

    def scan_once(self):
        """Look at the ingest folder once and deliver whatever has settled."""
        self._clear_out_old_backups()
        still_settling = {}
        present = set()
        for path in self._candidates():
            mark = self._mark(path)
            if mark is None:
                continue
            present.add(path)
            if self._stuck.get(path) == mark:
                continue
            self._stuck.pop(path, None)
            previous_mark, count = self._seen.get(path, (None, 0))
            count = count + 1 if previous_mark == mark else 1
            if count >= self.config.stable_checks:
                self._deliver(path, mark)
            else:
                still_settling[path] = (mark, count)
        self._seen = still_settling
        self._stuck = {
            path: mark for path, mark in self._stuck.items() if path in present
        }

    def _candidates(self):
        """Every file in the ingest folder, including subfolders, worth looking at."""
        skip_suffixes = self.config.skip_suffixes
        for folder, subfolders, names in os.walk(self.config.ingest_dir):
            subfolders[:] = [name for name in subfolders if not name.startswith(".")]
            for name in sorted(names):
                lowered = name.lower()
                if name.startswith(".") or lowered.endswith(skip_suffixes):
                    continue
                yield Path(folder) / name

    @staticmethod
    def _mark(path):
        """What the file looks like right now, or None if it is not a readable file."""
        try:
            details = path.stat()
        except OSError:
            return None
        return (details.st_size, details.st_mtime_ns)

    def _clear_out_old_backups(self):
        """Originals are kept for a while, then cleared out without being asked."""
        deleted = self.backups.expire()
        if deleted:
            LOG.info(
                "deleted %d backup%s older than %d days: %s",
                len(deleted),
                "" if len(deleted) == 1 else "s",
                self.backups.retention_days,
                ", ".join(path.name for path in deleted),
            )

    def _deliver(self, path, mark):
        if self.config.dry_run and (str(path), mark) in self._announced:
            # This exact version of the book has been reported already, and a
            # dry run leaves it where it is: asking the source again on every
            # scan would say the same thing, and be rude about it.
            return

        outcome = self.correction.correct(path)
        if outcome.waiting:
            # The pass did not finish with the book - the LLM could not be
            # asked, or a source the user configured could not be - so it stays
            # exactly where it is for the next UTC day: rewriting it would
            # change its hash, and delivering it would hand the library a book
            # Colophon knows it has not finished. The correction already said
            # why, once, so nothing is logged here.
            return
        correction = outcome.fragment()
        # Correcting a book rewrites it, so what it looked like a moment ago
        # is not what is about to be copied out.
        mark = self._mark(path) or mark

        destination, kind, note = self._destination_for(path)
        if destination is None:
            return

        # A book we have just corrected is already backed up, so a duplicate of
        # it does not need filing in the backups folder a second time.
        already_kept = kind == "duplicate" and outcome.kept is not None
        if already_kept:
            destination = Path(outcome.kept)
            note = f"{note}; the original was already kept as a backup"

        if self.config.dry_run:
            self._announced.add((str(path), mark))
            LOG.info(
                'dry run: would move "%s" -> %s (%s)%s',
                path.name,
                destination,
                note,
                _attached(correction),
            )
            return

        if not already_kept:
            try:
                copy_into_place(path, destination)
            except OSError as error:
                LOG.error('could not move "%s": %s', path.name, error)
                return
        # The book has arrived, so what was decided about it can be remembered.
        # Done here rather than when the decision was made, because a correction
        # that never reached the output folder is not one the library has: a
        # standard learnt from it would be a spelling nothing on the shelf has.
        self._remember(outcome)
        LOG.info(
            '%s "%s" -> %s (%s)%s',
            kind,
            path.name,
            destination,
            note,
            _attached(correction),
        )

        try:
            path.unlink()
        except OSError as error:
            # The copy is safely in place, so the book itself is fine. What
            # matters is not delivering it again on every scan from here on.
            self._stuck[path] = mark
            LOG.error(
                'delivered "%s" but could not remove it from %s: %s; leaving it '
                "there until it changes",
                path.name,
                path.parent,
                error,
            )

    def _remember(self, outcome):
        """Tell the record what this delivered book settled on.

        A failure here is logged rather than raised: the book itself is safely
        in the output folder, and losing one standard is worth far less than
        losing the scan. The next book by that author simply sets the spelling
        instead of following it.
        """
        if self.record is None or outcome.decision is None:
            return
        try:
            self.record.save(
                outcome.decision.resolutions,
                match=outcome.decision.match,
                when=_utc_now(),
                priority=self.config.sources,
                genres=outcome.decision.genres,
            )
        except sqlite3.Error as error:
            LOG.error("could not write to the record: %s", error)

    def _destination_for(self, path):
        """Where the file should go, what to call that, and why."""
        try:
            taken = self.config.output_dir / path.name
            if not taken.exists():
                return taken, "moved", _human_size(path.stat().st_size)

            if _same_contents(path, taken):
                return (
                    self.backups.free_name(path.name),
                    "duplicate",
                    f"identical to {taken}",
                )
            return (
                free_name(self.config.output_dir, path.name),
                "collision",
                f"a different file is already at {taken}",
            )
        except OSError as error:
            LOG.error('could not check "%s": %s', path.name, error)
            return None, None, None


def _utc_now():
    """When a match was recorded, in UTC and in a form a log reader can sort.

    The record is compared and shown, never scheduled against, so the format is
    ISO 8601 with a `Z` rather than anything local: two hosts in two time zones
    writing one record must not disagree about the order books arrived in.
    """
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _attached(fragment):
    """The metadata note for the end of a log line, space and all."""
    return f" {fragment}" if fragment else ""


def _same_contents(one, other):
    if one.stat().st_size != other.stat().st_size:
        return False
    return _digest(one) == _digest(other)


def _digest(path):
    running = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(READ_SIZE):
            running.update(chunk)
    return running.digest()


def _human_size(count):
    size = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
