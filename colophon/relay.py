"""The pass-through relay: ingest -> output, one file at a time.

Nothing here reads or changes a book's metadata; that arrives in later work.
The job is only to notice a finished file and put it where the library app
will find it, without ever overwriting or losing anything.
"""

import hashlib
import logging
import os
import shutil
from pathlib import Path

LOG = logging.getLogger("colophon")

TEMP_SUFFIX = ".colophon-tmp"

_READ_SIZE = 1024 * 1024


class RelayError(Exception):
    """The relay cannot run at all (usually a folder it cannot use)."""


def temp_name(name):
    """The half-written name for a file.

    Hidden, and it never ends in the book's own extension, so a library app
    watching the output folder cannot import a file that is still copying.
    """
    return f".{name}{TEMP_SUFFIX}"


class Relay:
    def __init__(self, config):
        self.config = config
        # path -> ((size, mtime), how many scans it has looked like that)
        self._seen = {}
        # files already reported in dry-run mode, so each is logged once
        self._announced = set()

    def prepare(self):
        """Make sure the three folders exist before the first scan."""
        for folder in (
            self.config.ingest_dir,
            self.config.output_dir,
            self.config.backup_dir,
        ):
            try:
                folder.mkdir(parents=True, exist_ok=True)
            except OSError as error:
                raise RelayError(f"cannot use {folder}: {error}") from error

        # The original is deleted once it has been copied out, so read-only
        # access to the ingest folder would leave every book to arrive twice.
        if not os.access(self.config.ingest_dir, os.W_OK):
            raise RelayError(
                f"cannot write to {self.config.ingest_dir}; the ingest folder must "
                "not be mounted read-only"
            )

    def scan_once(self):
        """Look at the ingest folder once and deliver whatever has settled."""
        still_settling = {}
        for path in self._candidates():
            mark = self._mark(path)
            if mark is None:
                continue
            previous_mark, count = self._seen.get(path, (None, 0))
            count = count + 1 if previous_mark == mark else 1
            if count >= self.config.stable_checks:
                self._deliver(path, mark)
            else:
                still_settling[path] = (mark, count)
        self._seen = still_settling

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

    def _deliver(self, path, mark):
        destination, kind, note = self._destination_for(path)
        if destination is None:
            return

        if self.config.dry_run:
            announcement = (str(path), mark)
            if announcement not in self._announced:
                self._announced.add(announcement)
                LOG.info(
                    'dry run: would move "%s" -> %s (%s)', path.name, destination, note
                )
            return

        try:
            _transfer(path, destination)
        except OSError as error:
            LOG.error('could not move "%s": %s', path.name, error)
            return
        LOG.info('%s "%s" -> %s (%s)', kind, path.name, destination, note)

    def _destination_for(self, path):
        """Where the file should go, what to call that, and why."""
        try:
            taken = self.config.output_dir / path.name
            if not taken.exists():
                return taken, "moved", _human_size(path.stat().st_size)

            if _same_contents(path, taken):
                return (
                    _free_name(self.config.backup_dir, path.name),
                    "duplicate",
                    f"identical to {taken}",
                )
            return (
                _free_name(self.config.output_dir, path.name),
                "collision",
                f"a different file is already at {taken}",
            )
        except OSError as error:
            LOG.error('could not check "%s": %s', path.name, error)
            return None, None, None


def _transfer(source, destination):
    """Copy into place under a hidden name, then rename, then drop the original.

    Copying rather than renaming is deliberate: a rename keeps the original
    owner, while a copy is created by this process and so comes out owned by
    the user the container runs as.
    """
    half_written = destination.parent / temp_name(destination.name)
    try:
        with open(source, "rb") as reading, open(half_written, "wb") as writing:
            shutil.copyfileobj(reading, writing, _READ_SIZE)
            writing.flush()
            os.fsync(writing.fileno())
        os.replace(half_written, destination)
    except OSError:
        half_written.unlink(missing_ok=True)
        raise
    source.unlink()


def _same_contents(one, other):
    if one.stat().st_size != other.stat().st_size:
        return False
    return _digest(one) == _digest(other)


def _digest(path):
    running = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(_READ_SIZE):
            running.update(chunk)
    return running.digest()


def _free_name(folder, name):
    """folder/name, or folder/'name (2)', 'name (3)'... if that is taken."""
    candidate = folder / name
    if not candidate.exists():
        return candidate

    stem, dot, extension = name.rpartition(".")
    number = 2
    while True:
        numbered = f"{stem} ({number}).{extension}" if dot else f"{name} ({number})"
        candidate = folder / numbered
        if not candidate.exists():
            return candidate
        number += 1


def _human_size(count):
    size = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
