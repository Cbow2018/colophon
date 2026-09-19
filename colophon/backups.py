"""The backups folder: originals kept safe, never overwritten, not kept for ever.

Two things land here. A copy of the original goes in before Colophon changes
anything, and an identical duplicate the library already has goes in rather
than being deleted outright. Either way nothing already in the folder is ever
overwritten, and anything older than the retention is deleted on the next scan.
"""

import os
import time
from pathlib import Path

from colophon.files import copy_into_place

DEFAULT_RETENTION_DAYS = 30

SECONDS_A_DAY = 24 * 60 * 60


class Backups:
    def __init__(self, folder, retention_days=DEFAULT_RETENTION_DAYS):
        self.folder = Path(folder)
        self.retention_days = retention_days

    def prepare(self):
        self.folder.mkdir(parents=True, exist_ok=True)

    def free_name(self, name):
        """A name in this folder that nothing has taken yet."""
        return free_name(self.folder, name)

    def keep(self, path):
        """Copy a file in, without ever overwriting what is already here."""
        self.prepare()
        kept = self.free_name(Path(path).name)
        copy_into_place(Path(path), kept)
        return kept

    def expire(self):
        """Delete what is older than the retention, and say what went.

        Identical duplicates the relay filed here are ordinary files as far as
        this is concerned; a folder left empty is tidied away with them.

        A name starting with a dot is not an original and is never deleted: the
        LLM call counter lives in this folder, and a folder-clearing pass is
        exactly how it would otherwise disappear - which would hand a
        crash-looping container a fresh daily limit on every restart.
        """
        cutoff = time.time() - self.retention_days * SECONDS_A_DAY
        deleted = []
        for folder, subfolders, names in os.walk(self.folder, topdown=False):
            for name in names:
                if name.startswith("."):
                    continue
                path = Path(folder) / name
                if _older_than(path, cutoff) and _remove(path):
                    deleted.append(path)
            for name in subfolders:
                try:
                    (Path(folder) / name).rmdir()
                except OSError:
                    pass
        return tuple(deleted)


def free_name(folder, name):
    """folder/name, or folder/'name (2)', 'name (3)'... if that name is taken.

    The one place that decides what a name becomes when it is already in use,
    so the backups folder and the output folder cannot drift apart.
    """
    folder = Path(folder)
    if not (folder / name).exists():
        return folder / name

    stem, dot, extension = name.rpartition(".")
    number = 2
    while True:
        numbered = f"{stem} ({number}).{extension}" if dot else f"{name} ({number})"
        candidate = folder / numbered
        if not candidate.exists():
            return candidate
        number += 1


def _older_than(path, cutoff):
    try:
        return path.stat().st_mtime < cutoff
    except OSError:
        return False


def _remove(path):
    try:
        path.unlink()
    except OSError:
        return False
    return True
