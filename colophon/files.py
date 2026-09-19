"""Putting a copy of a file somewhere, without it being seen half-written.

Nothing here decides *where* a copy should go. It is the one place that knows
how to put one there safely, so the relay and the backups folder cannot drift
apart on what "safely" means.
"""

import os
import shutil

READ_SIZE = 1024 * 1024
TEMP_SUFFIX = ".colophon-tmp"


def temp_name(name):
    """The half-written name for a file.

    Hidden, and it never ends in the book's own extension, so a library app
    watching the output folder cannot import a file that is still copying.
    """
    return f".{name}{TEMP_SUFFIX}"


def copy_into_place(source, destination):
    """Copy under a hidden name, then rename it, leaving the original alone.

    Copying rather than renaming is deliberate: a rename keeps the original
    owner, while a copy is created by this process and so comes out owned by
    the user the container runs as. Removing the original is the caller's job,
    because it can fail on its own.
    """
    half_written = destination.parent / temp_name(destination.name)
    try:
        with open(source, "rb") as reading, open(half_written, "wb") as writing:
            shutil.copyfileobj(reading, writing, READ_SIZE)
            writing.flush()
            os.fsync(writing.fileno())
        os.replace(half_written, destination)
    except OSError:
        half_written.unlink(missing_ok=True)
        raise
