"""A throwaway folder for tests, made in a way every environment can write to.

`tempfile.TemporaryDirectory()` creates its folder with mode 0o700. On Windows
that becomes a private access-control list, so a process running under a
restricted token - the DSH file sandbox, for one - is refused write access and
every test that touches a temporary file dies with `PermissionError`. Making
the folder with `os.mkdir`'s default mode leaves the inherited permissions
alone. The folder is still unique, and still removed afterwards.
"""

import secrets
import shutil
import tempfile
from pathlib import Path

DEFAULT_PREFIX = "colophon-tests-"


class TemporaryDirectory:
    """Like `tempfile.TemporaryDirectory`, without the private permissions.

    Use `name` for the folder and hand `cleanup` to `addCleanup`.
    """

    def __init__(self, prefix=DEFAULT_PREFIX):
        self.name = str(_make(prefix))
        self._removed = False

    def cleanup(self):
        """Remove the folder and everything in it; safe to call more than once."""
        if not self._removed:
            self._removed = True
            shutil.rmtree(self.name, ignore_errors=True)


def _make(prefix):
    parent = Path(tempfile.gettempdir())
    while True:
        path = parent / f"{prefix}{secrets.token_hex(8)}"
        try:
            path.mkdir(parents=True)
        except FileExistsError:
            continue
        return path
